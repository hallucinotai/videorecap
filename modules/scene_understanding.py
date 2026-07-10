"""GPT-4o vision scene understanding for recap (ported from scripts/describe_video.py).

Produces a scene timeline + narrative, and can inject compact fields into
narration_context for clip selection / narration prompts.

Boundary modes (SCENE_BOUNDARY_MODE):
  - fixed (default): sample at SCENE_SAMPLE_FPS, chunk by SCENE_BATCH_FRAMES
  - pyscenedetect: PySceneDetect shot cuts → merge short shots → sample frames per scene
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from modules.scene_boundaries import (
    boundary_mode_from_env,
    detect_merged_scenes,
    pyscenedetect_available,
    sample_timestamps_in_window,
)

logger = logging.getLogger(__name__)

METHOD = "scene_understanding_v1"

DEFAULT_SAMPLE_FPS = 0.5
DEFAULT_BATCH_FRAMES = 8
DEFAULT_MODEL = "gpt-4o"
DEFAULT_SUMMARY_MAX_CHARS = 4000
DEFAULT_SEGMENT_DESC_MAX_CHARS = 400

SEGMENT_SYSTEM_PROMPT = """You are an expert video analyst describing footage frame-by-frame.
Your job is to write a detailed, chronological account of everything visible and happening
in the provided frames — not a short summary.

Rules:
- Describe settings, people, objects, actions, expressions, camera movement, and transitions.
- Reference approximate timestamps when describing changes (frames are labeled with their time).
- Write in complete sentences and paragraphs; be thorough and observant.
- Do NOT invent dialogue or events that are not visible.
- If something is unclear, say so rather than guessing.
- Do NOT compress the scene into a one-line summary — expand on what you see."""

MERGE_SYSTEM_PROMPT = """You are an expert video analyst.
You will receive detailed descriptions of consecutive segments from the same video.
Combine them into one continuous, detailed narrative that preserves all observable detail.

Rules:
- Keep the play-by-play level of detail — do not shorten or summarize away specifics.
- Maintain chronological order with clear time references where helpful.
- Smooth transitions between segments without repeating the same observations.
- Do NOT invent content that was not in the segment descriptions."""


def scene_understanding_enabled() -> bool:
    raw = (os.environ.get("ENABLE_SCENE_UNDERSTANDING") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _env_optional_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None
    return value if value > 0 else None


class FrameExtractor:
    def __init__(self, video_path: Path):
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("opencv_unavailable") from exc

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(str(video_path))
        if not self._cap.isOpened():
            raise FileNotFoundError(f"Cannot open video: {video_path}")

        self.fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 25.0)
        frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.duration_sec = frame_count / self.fps if self.fps > 0 and frame_count > 0 else None

    def read_at(self, timestamp_sec: float):
        self._cap.set(self._cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp_sec) * 1000.0)
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self) -> None:
        self._cap.release()


def sample_timestamps(
    *,
    duration_sec: float,
    sample_fps: float,
    max_duration: float | None,
) -> list[float]:
    if duration_sec is None or duration_sec <= 0:
        raise ValueError("Could not determine video duration.")
    if sample_fps <= 0:
        raise ValueError("sample_fps must be > 0")

    end = duration_sec
    if max_duration is not None:
        end = min(end, max_duration)

    interval = 1.0 / sample_fps
    timestamps: list[float] = []
    t = 0.0
    while t <= end + 1e-6:
        timestamps.append(round(t, 3))
        t += interval
    return timestamps


def extract_frames(
    *,
    video_path: Path,
    timestamps: list[float],
    output_dir: Path | None = None,
) -> list[dict[str, Any]]:
    import cv2

    extractor = FrameExtractor(video_path)
    frames: list[dict[str, Any]] = []

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    try:
        for idx, ts in enumerate(timestamps):
            frame = extractor.read_at(ts)
            entry: dict[str, Any] = {
                "index": idx,
                "timestamp_sec": ts,
                "saved": False,
                "path": None,
                "jpeg_base64": None,
            }

            if frame is None:
                entry["error"] = "frame read failed"
                frames.append(entry)
                continue

            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                entry["error"] = "jpeg encode failed"
                frames.append(entry)
                continue

            entry["jpeg_base64"] = base64.b64encode(encoded.tobytes()).decode("ascii")

            if output_dir is not None:
                filename = f"frame_{idx:05d}_{ts:.3f}s.jpg"
                out_path = output_dir / filename
                cv2.imwrite(str(out_path), frame)
                entry["saved"] = True
                entry["path"] = str(out_path)

            frames.append(entry)
    finally:
        extractor.close()

    return frames


def _chunk(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _vision_message_content(
    frames: list[dict[str, Any]],
    *,
    batch_index: int,
    batch_count: int,
    sample_fps: float,
) -> list[dict[str, Any]]:
    start_ts = frames[0]["timestamp_sec"]
    end_ts = frames[-1]["timestamp_sec"]
    text = (
        f"Video segment {batch_index + 1} of {batch_count}. "
        f"Frames sampled at {sample_fps:g} per second from {start_ts:.1f}s to {end_ts:.1f}s.\n"
        f"Each image is labeled with its timestamp. "
        f"Write a detailed description of everything happening in this segment."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]

    for frame in frames:
        if not frame.get("jpeg_base64"):
            continue
        ts = frame["timestamp_sec"]
        content.append({"type": "text", "text": f"[Frame at {ts:.2f}s]"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{frame['jpeg_base64']}",
                    "detail": "high",
                },
            }
        )
    return content


def _get_openai_client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai_unavailable") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("openai_api_key_missing")
    return OpenAI(api_key=api_key, max_retries=3)


def describe_batch(
    client,
    *,
    model: str,
    frames: list[dict[str, Any]],
    batch_index: int,
    batch_count: int,
    sample_fps: float,
) -> str:
    usable = [f for f in frames if f.get("jpeg_base64")]
    if not usable:
        return f"[Segment {batch_index + 1}: no readable frames]"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SEGMENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _vision_message_content(
                    usable,
                    batch_index=batch_index,
                    batch_count=batch_count,
                    sample_fps=sample_fps,
                ),
            },
        ],
        max_tokens=2500,
    )
    return (response.choices[0].message.content or "").strip()


def merge_descriptions(client, *, model: str, segments: list[dict[str, Any]]) -> str:
    if len(segments) == 1:
        return segments[0]["description"]

    lines = []
    for seg in segments:
        lines.append(
            f"--- Segment {seg['batch_index'] + 1} ({seg['start_sec']:.1f}s – {seg['end_sec']:.1f}s) ---\n"
            f"{seg['description']}"
        )
    joined = "\n\n".join(lines)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": MERGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Combine these consecutive segment descriptions into one detailed narrative:\n\n"
                    f"{joined}"
                ),
            },
        ],
        max_tokens=4000,
    )
    return (response.choices[0].message.content or "").strip()


def run_scene_understanding(
    video_path: str | Path,
    *,
    sample_fps: float | None = None,
    batch_frames: int | None = None,
    model: str | None = None,
    max_duration: float | None = None,
    skip_merge: bool = False,
    save_frames_dir: Path | None = None,
    boundary_mode: str | None = None,
) -> dict[str, Any]:
    """
    Sample video frames and describe scenes with a vision LLM.

    boundary_mode:
      - fixed: uniform sampling + SCENE_BATCH_FRAMES chunks
      - pyscenedetect: ContentDetector shots merged into scenes, then sample per scene

    Returns:
      {
        method, model, sample_fps, batch_frames, boundary_mode,
        video_duration_sec, analyzed_duration_sec, frame_count, batch_count,
        narrative, segments: [{start_sec, end_sec, description, ...}]
      }
    """
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Video not found: {path}")

    resolved_fps = sample_fps if sample_fps is not None else _env_float("SCENE_SAMPLE_FPS", DEFAULT_SAMPLE_FPS)
    resolved_batch = batch_frames if batch_frames is not None else _env_int("SCENE_BATCH_FRAMES", DEFAULT_BATCH_FRAMES)
    resolved_model = model or os.environ.get("SCENE_VISION_MODEL") or DEFAULT_MODEL
    resolved_max = max_duration if max_duration is not None else _env_optional_float("SCENE_MAX_DURATION")
    mode = boundary_mode_from_env(boundary_mode)

    extractor = FrameExtractor(path)
    duration = extractor.duration_sec
    extractor.close()

    if mode == "pyscenedetect":
        avail = pyscenedetect_available()
        if not avail.get("scenedetect"):
            logger.warning(
                "SCENE_BOUNDARY_MODE=pyscenedetect but scenedetect missing (%s); falling back to fixed",
                avail.get("error"),
            )
            mode = "fixed"

    if mode == "pyscenedetect":
        try:
            scene_windows = detect_merged_scenes(path, max_duration=resolved_max)
        except Exception as exc:
            logger.warning("PySceneDetect failed (%s); falling back to fixed", exc)
            mode = "fixed"
            scene_windows = []
    else:
        scene_windows = []

    if mode == "fixed":
        timestamps = sample_timestamps(
            duration_sec=duration or 0.0,
            sample_fps=resolved_fps,
            max_duration=resolved_max,
        )
        if not timestamps:
            raise ValueError("No timestamps to sample.")

        logger.info(
            "Scene understanding [fixed]: video=%s duration=%.1fs sample_fps=%s frames=%d model=%s",
            path.name,
            duration or 0.0,
            resolved_fps,
            len(timestamps),
            resolved_model,
        )

        frames = extract_frames(video_path=path, timestamps=timestamps, output_dir=save_frames_dir)
        usable_frames = [f for f in frames if f.get("jpeg_base64")]
        if not usable_frames:
            raise ValueError("No frames could be read from the video.")

        frame_batches = _chunk(usable_frames, resolved_batch)
        batch_specs: list[dict[str, Any]] = []
        for i, batch in enumerate(frame_batches):
            batch_specs.append(
                {
                    "batch_index": i,
                    "start_sec": batch[0]["timestamp_sec"],
                    "end_sec": batch[-1]["timestamp_sec"],
                    "frames": batch,
                    "boundary": "fixed",
                }
            )
        analyzed_end = timestamps[-1]
    else:
        if not scene_windows:
            raise ValueError("PySceneDetect produced no scene windows.")

        logger.info(
            "Scene understanding [pyscenedetect]: video=%s duration=%.1fs scenes=%d "
            "sample_fps=%s max_frames/scene=%d model=%s",
            path.name,
            duration or 0.0,
            len(scene_windows),
            resolved_fps,
            resolved_batch,
            resolved_model,
        )

        batch_specs = []
        all_timestamps: list[float] = []
        for i, (start_sec, end_sec) in enumerate(scene_windows):
            ts_list = sample_timestamps_in_window(
                start_sec,
                end_sec,
                sample_fps=resolved_fps,
                max_frames=resolved_batch,
            )
            all_timestamps.extend(ts_list)
            frames = extract_frames(video_path=path, timestamps=ts_list, output_dir=save_frames_dir)
            usable = [f for f in frames if f.get("jpeg_base64")]
            if not usable:
                logger.warning("Scene %d (%.1f–%.1fs): no readable frames; skipping", i, start_sec, end_sec)
                continue
            batch_specs.append(
                {
                    "batch_index": i,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "frames": usable,
                    "boundary": "pyscenedetect",
                }
            )
        if not batch_specs:
            raise ValueError("No frames could be read from PySceneDetect scenes.")
        analyzed_end = scene_windows[-1][1]

    client = _get_openai_client()

    segments: list[dict[str, Any]] = []
    total_frames = 0
    for spec in batch_specs:
        batch = spec["frames"]
        total_frames += len(batch)
        description = describe_batch(
            client,
            model=resolved_model,
            frames=batch,
            batch_index=spec["batch_index"],
            batch_count=len(batch_specs),
            sample_fps=resolved_fps,
        )
        segments.append(
            {
                "batch_index": spec["batch_index"],
                "start_sec": spec["start_sec"],
                "end_sec": spec["end_sec"],
                "frame_count": len(batch),
                "boundary": spec["boundary"],
                "description": description,
            }
        )
        logger.info(
            "Scene batch %d/%d (%.1f–%.1fs, %s) done",
            spec["batch_index"] + 1,
            len(batch_specs),
            spec["start_sec"],
            spec["end_sec"],
            spec["boundary"],
        )

    if skip_merge or len(segments) == 1:
        narrative = "\n\n".join(
            f"[{seg['start_sec']:.1f}s – {seg['end_sec']:.1f}s]\n{seg['description']}"
            for seg in segments
        )
        merge_skipped = skip_merge and len(segments) > 1
    else:
        narrative = merge_descriptions(client, model=resolved_model, segments=segments)
        merge_skipped = False

    return {
        "method": METHOD,
        "video": str(path.resolve()),
        "model": resolved_model,
        "boundary_mode": mode,
        "sample_fps": resolved_fps,
        "batch_frames": resolved_batch,
        "video_duration_sec": duration,
        "analyzed_duration_sec": analyzed_end,
        "frame_count": total_frames,
        "batch_count": len(batch_specs),
        "scene_window_count": len(scene_windows) if mode == "pyscenedetect" else None,
        "merge_skipped": merge_skipped,
        "narrative": narrative,
        "description": narrative,  # alias for lab script compatibility
        "segments": segments,
    }


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def build_narration_scene_fields(
    scene_result: dict[str, Any],
    *,
    summary_max_chars: int = DEFAULT_SUMMARY_MAX_CHARS,
    segment_desc_max_chars: int = DEFAULT_SEGMENT_DESC_MAX_CHARS,
) -> dict[str, Any]:
    """Compact fields for narration_context from a scene_understanding result."""
    narrative = scene_result.get("narrative") or scene_result.get("description") or ""
    segments_out: list[dict[str, Any]] = []
    for seg in scene_result.get("segments") or []:
        segments_out.append(
            {
                "start": float(seg.get("start_sec") or 0),
                "end": float(seg.get("end_sec") or 0),
                "description": _truncate(str(seg.get("description") or ""), segment_desc_max_chars),
            }
        )
    return {
        "scene_summary": _truncate(str(narrative), summary_max_chars),
        "scene_segments": segments_out,
        "scene_method": scene_result.get("method") or METHOD,
        "scene_model": scene_result.get("model"),
    }


def inject_scene_into_transcript_doc(
    doc: dict[str, Any],
    scene_result: dict[str, Any],
) -> dict[str, Any]:
    """Merge scene fields into narration_context on a transcript/enrichment document."""
    output = dict(doc)
    narration_context = dict(output.get("narration_context") or {})
    narration_context.update(build_narration_scene_fields(scene_result))
    output["narration_context"] = narration_context
    return output


def inject_scene_into_transcript_file(
    transcript_path: str | Path,
    scene_result: dict[str, Any],
    *,
    output_path: str | Path | None = None,
) -> Path:
    """Load transcript JSON, inject scene fields, write back (or to output_path)."""
    path = Path(transcript_path)
    with path.open(encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"Expected JSON object in {path}")

    updated = inject_scene_into_transcript_doc(doc, scene_result)
    dest = Path(output_path) if output_path else path
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)
    return dest


def write_scene_artifact(scene_result: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(scene_result, f, indent=2)
    return path
