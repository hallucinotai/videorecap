#!/usr/bin/env python3
"""
Sample video frames at 2 fps and describe what is happening using a vision model.

Local test utility — lives under scripts/ (gitignored). Not part of the app pipeline.

Pipeline:
  1. OpenCV seeks to timestamps every 0.5s (2 frames per second)
  2. Frames are batched and sent to a vision-capable LLM (default: gpt-4o)
  3. Each batch produces a detailed, moment-by-moment description
  4. Batch descriptions are stitched into one continuous narrative

Usage:
  python scripts/describe_video.py \\
    --video assets/input_video.mp4 \\
    --output-dir scripts/video_descriptions

  # Limit to first 60 seconds (useful while testing)
  python scripts/describe_video.py --video assets/input_video.mp4 --max-duration 60

  # Save sampled frames alongside the description
  python scripts/describe_video.py --video assets/input_video.mp4 --save-frames

Dependencies (local test env):
  pip install opencv-python openai python-dotenv
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


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


class FrameExtractor:
    def __init__(self, video_path: Path):
        try:
            import cv2
        except ImportError as exc:
            raise SystemExit(
                "opencv-python is required. Install with: pip install opencv-python"
            ) from exc

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


def sample_timestamps(*, duration_sec: float, sample_fps: float, max_duration: float | None) -> list[float]:
    if duration_sec is None or duration_sec <= 0:
        raise ValueError("Could not determine video duration.")

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
    output_dir: Path | None,
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
                print(f"  ! miss  @ {ts:7.3f}s")
                continue

            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                entry["error"] = "jpeg encode failed"
                frames.append(entry)
                print(f"  ! encode fail @ {ts:7.3f}s")
                continue

            entry["jpeg_base64"] = base64.b64encode(encoded.tobytes()).decode("ascii")

            if output_dir is not None:
                filename = f"frame_{idx:05d}_{ts:.3f}s.jpg"
                out_path = output_dir / filename
                cv2.imwrite(str(out_path), frame)
                entry["saved"] = True
                entry["path"] = str(out_path)

            frames.append(entry)
            print(f"  ✓ frame {idx + 1}/{len(timestamps)} @ {ts:7.3f}s")
    finally:
        extractor.close()

    return frames


def _chunk(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _vision_message_content(frames: list[dict[str, Any]], *, batch_index: int, batch_count: int) -> list[dict[str, Any]]:
    start_ts = frames[0]["timestamp_sec"]
    end_ts = frames[-1]["timestamp_sec"]
    text = (
        f"Video segment {batch_index + 1} of {batch_count}. "
        f"Frames sampled at 2 per second from {start_ts:.1f}s to {end_ts:.1f}s.\n"
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
        raise SystemExit("openai is required. Install with: pip install openai") from exc

    try:
        import dotenv

        dotenv.load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set. Add it to .env or export it in your shell.")
    return OpenAI(api_key=api_key, max_retries=3)


def describe_batch(
    client,
    *,
    model: str,
    frames: list[dict[str, Any]],
    batch_index: int,
    batch_count: int,
) -> str:
    usable = [f for f in frames if f.get("jpeg_base64")]
    if not usable:
        return f"[Segment {batch_index + 1}: no readable frames]"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SEGMENT_SYSTEM_PROMPT},
            {"role": "user", "content": _vision_message_content(usable, batch_index=batch_index, batch_count=batch_count)},
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


def describe_video(
    *,
    video_path: Path,
    output_dir: Path,
    sample_fps: float = 2.0,
    batch_frames: int = 10,
    model: str = "gpt-4o",
    max_duration: float | None = None,
    save_frames: bool = False,
    skip_merge: bool = False,
) -> dict[str, Any]:
    print(f"Video: {video_path}")
    print(f"Sample rate: {sample_fps} fps  |  Batch size: {batch_frames} frames  |  Model: {model}")

    extractor = FrameExtractor(video_path)
    duration = extractor.duration_sec
    extractor.close()

    timestamps = sample_timestamps(
        duration_sec=duration or 0.0,
        sample_fps=sample_fps,
        max_duration=max_duration,
    )
    if not timestamps:
        raise ValueError("No timestamps to sample.")

    print(f"Duration: {duration:.1f}s  |  Frames to extract: {len(timestamps)}")

    frames_dir = output_dir / "frames" if save_frames else None
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nExtracting frames...")
    frames = extract_frames(video_path=video_path, timestamps=timestamps, output_dir=frames_dir)
    usable_frames = [f for f in frames if f.get("jpeg_base64")]
    if not usable_frames:
        raise ValueError("No frames could be read from the video.")

    batches = _chunk(usable_frames, batch_frames)
    client = _get_openai_client()

    print(f"\nAnalyzing {len(batches)} batch(es) with {model}...")
    segments: list[dict[str, Any]] = []
    for i, batch in enumerate(batches):
        t0 = time.perf_counter()
        print(f"  Batch {i + 1}/{len(batches)}  ({batch[0]['timestamp_sec']:.1f}s – {batch[-1]['timestamp_sec']:.1f}s)...")
        description = describe_batch(
            client,
            model=model,
            frames=batch,
            batch_index=i,
            batch_count=len(batches),
        )
        elapsed = time.perf_counter() - t0
        print(f"    done in {elapsed:.1f}s ({len(description.split())} words)")
        segments.append(
            {
                "batch_index": i,
                "start_sec": batch[0]["timestamp_sec"],
                "end_sec": batch[-1]["timestamp_sec"],
                "frame_count": len(batch),
                "description": description,
            }
        )

    if skip_merge or len(segments) == 1:
        full_description = "\n\n".join(
            f"[{seg['start_sec']:.1f}s – {seg['end_sec']:.1f}s]\n{seg['description']}"
            for seg in segments
        )
        merge_skipped = skip_merge and len(segments) > 1
    else:
        print("\nMerging segment descriptions...")
        full_description = merge_descriptions(client, model=model, segments=segments)
        merge_skipped = False

    result = {
        "video": str(video_path.resolve()),
        "model": model,
        "sample_fps": sample_fps,
        "batch_frames": batch_frames,
        "video_duration_sec": duration,
        "analyzed_duration_sec": timestamps[-1],
        "frame_count": len(usable_frames),
        "batch_count": len(batches),
        "merge_skipped": merge_skipped,
        "description": full_description,
        "segments": segments,
    }

    txt_path = output_dir / "description.txt"
    json_path = output_dir / "description.json"
    txt_path.write_text(full_description + "\n", encoding="utf-8")
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print()
    print(f"Description saved: {txt_path}")
    print(f"Metadata saved:    {json_path}")
    if frames_dir:
        print(f"Frames saved:      {frames_dir}")
    print()
    print("=" * 72)
    print(full_description)
    print("=" * 72)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sample video at 2 fps and produce a detailed vision-model description."
    )
    parser.add_argument("--video", required=True, type=Path, help="Path to input video")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./video_descriptions"),
        help="Directory for description.txt, description.json, and optional frames",
    )
    parser.add_argument(
        "--sample-fps",
        type=float,
        default=2.0,
        help="Frames per second to sample (default: 2.0)",
    )
    parser.add_argument(
        "--batch-frames",
        type=int,
        default=10,
        help="Frames per vision API call (default: 10 = 5s at 2fps)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", "gpt-4o"),
        help="Vision-capable OpenAI model (default: gpt-4o or OPENAI_MODEL env)",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=None,
        help="Only analyze the first N seconds (useful for testing)",
    )
    parser.add_argument(
        "--save-frames",
        action="store_true",
        help="Write sampled JPEG frames to output-dir/frames/",
    )
    parser.add_argument(
        "--skip-merge",
        action="store_true",
        help="Keep segment descriptions separate instead of merging into one narrative",
    )
    args = parser.parse_args(argv)

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1
    if args.sample_fps <= 0:
        print("--sample-fps must be > 0", file=sys.stderr)
        return 1
    if args.batch_frames < 1:
        print("--batch-frames must be >= 1", file=sys.stderr)
        return 1

    try:
        describe_video(
            video_path=args.video,
            output_dir=args.output_dir,
            sample_fps=args.sample_fps,
            batch_frames=args.batch_frames,
            model=args.model,
            max_duration=args.max_duration,
            save_frames=args.save_frames,
            skip_merge=args.skip_merge,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
