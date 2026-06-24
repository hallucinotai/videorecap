#!/usr/bin/env python3
"""
Layer 1: Character tracking + pipeline scaffolding.

Local test utility — lives under scripts/ (gitignored).

Full pipeline (movie-scene use case)
------------------------------------
Video
 ├── Audio → Whisper → Pyannote → Speaker Timeline     [--phase audio]
 └── Video → YOLOv11 → ByteTrack → ArcFace → Character Timeline   [default]
              → LocateAnything (optional)              [--ground-locate]
              → Character Grounding

Audio + Video → Qwen2.5-VL → Event Extraction → Narration        [--phase events]

Layer 1 priority stack (implemented):
  YOLOv11 + ByteTrack + ArcFace identity merge

Primary output:
  {
    "person_1": {"frames": [1, 2, 3, ...]},
    "person_2": {"frames": [1, 2, 3, ...]}
  }

Validation (default min 2 persons for dialogue scenes):
  if person_count < min_persons:
      raise CharacterTrackingFailed(...)

Usage:
  pip install -r scripts/layer1_requirements.txt

  python scripts/layer1_character_tracking.py \\
    --video assets/output_clip.mp4 \\
    --output scripts/layer1_person_frames.json \\
    --min-persons 2
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class CharacterTrackingFailed(Exception):
    """Raised when Layer 1 cannot find enough characters to proceed."""


def validate_character_tracking(person_count: int, min_persons: int = 2) -> None:
    if person_count < min_persons:
        raise CharacterTrackingFailed(
            "Character tracking failed. Do not run action recognition."
        )


# ---------------------------------------------------------------------------
# YOLOv11 person detection
# ---------------------------------------------------------------------------


class YOLOv11PersonDetector:
    """COCO class-0 (person) detection via Ultralytics YOLOv11."""

    PERSON_CLASS_ID = 0

    def __init__(
        self,
        *,
        model_name: str = "yolo11n.pt",
        device: str = "cpu",
        conf: float = 0.25,
        iou: float = 0.45,
        min_box_area_ratio: float = 0.002,
    ):
        from ultralytics import YOLO

        self.model = YOLO(model_name)
        self.device = device
        self.conf = conf
        self.iou = iou
        self.min_box_area_ratio = min_box_area_ratio
        self.model_name = model_name

    def detect(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Return Nx5 float32: x1, y1, x2, y2, confidence."""
        h, w = frame_bgr.shape[:2]
        frame_area = float(h * w)
        min_area = frame_area * self.min_box_area_ratio

        results = self.model.predict(
            source=frame_bgr,
            conf=self.conf,
            iou=self.iou,
            classes=[self.PERSON_CLASS_ID],
            device=self.device,
            verbose=False,
        )

        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return np.empty((0, 5), dtype=np.float32)

        boxes = results[0].boxes
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()

        kept: list[list[float]] = []
        for (x1, y1, x2, y2), score in zip(xyxy, confs):
            area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            if area < min_area:
                continue
            kept.append([float(x1), float(y1), float(x2), float(y2), float(score)])

        if not kept:
            return np.empty((0, 5), dtype=np.float32)
        return np.array(kept, dtype=np.float32)


# ---------------------------------------------------------------------------
# ByteTrack
# ---------------------------------------------------------------------------


@dataclass
class RawTrack:
    track_id: int
    frames: list[int] = field(default_factory=list)
    embeddings: list[np.ndarray] = field(default_factory=list)
    bboxes: list[np.ndarray] = field(default_factory=list)


class ByteTrackRunner:
    """ByteTrack via supervision; records per-frame active track IDs."""

    def __init__(self, *, min_confidence: float = 0.25):
        import supervision as sv

        self._sv = sv
        self.tracker = sv.ByteTrack(track_activation_threshold=min_confidence)
        self._records: dict[int, RawTrack] = {}

    def update(
        self,
        frame_index_1based: int,
        frame_bgr: np.ndarray,
        detections_xyxy_conf: np.ndarray,
        arcface: ArcFaceEncoder | None = None,
    ) -> list[tuple[int, np.ndarray]]:
        sv = self._sv
        if detections_xyxy_conf.size == 0:
            dets = sv.Detections.empty()
        else:
            dets = sv.Detections(
                xyxy=detections_xyxy_conf[:, :4],
                confidence=detections_xyxy_conf[:, 4],
                class_id=np.zeros(len(detections_xyxy_conf), dtype=int),
            )

        tracked = self.tracker.update_with_detections(dets)
        active: list[tuple[int, np.ndarray]] = []

        if tracked.tracker_id is None:
            return active

        for i, tid in enumerate(tracked.tracker_id):
            if tid is None:
                continue
            tid_int = int(tid)
            bbox = tracked.xyxy[i].astype(np.float32)
            active.append((tid_int, bbox))

            rec = self._records.setdefault(tid_int, RawTrack(track_id=tid_int))
            if not rec.frames or rec.frames[-1] != frame_index_1based:
                rec.frames.append(frame_index_1based)
            rec.bboxes.append(bbox)
            if arcface is not None:
                emb_list = arcface.encode_detections(frame_bgr, np.array([bbox]))
                if emb_list and emb_list[0] is not None:
                    rec.embeddings.append(emb_list[0])

        return active

    def export(self) -> dict[int, RawTrack]:
        return self._records


# ---------------------------------------------------------------------------
# ArcFace identity embeddings
# ---------------------------------------------------------------------------


class ArcFaceEncoder:
    """Face appearance embeddings for cross-track identity consistency."""

    def __init__(self, *, device: str = "cpu", model_name: str = "buffalo_l"):
        try:
            from insightface.app import FaceAnalysis
        except ImportError as exc:
            raise RuntimeError(
                "insightface is required for ArcFace. Install with:\n"
                "  pip install insightface onnxruntime"
            ) from exc

        ctx_id = 0 if device.startswith("cuda") else -1
        self.app = FaceAnalysis(name=model_name, providers=["CPUExecutionProvider"])
        self.app.prepare(ctx_id=ctx_id, det_size=(640, 640))
        self.model_name = model_name
        self._embed_dim = 512

    @property
    def embed_dim(self) -> int:
        return self._embed_dim

    def encode_detections(
        self,
        frame_bgr: np.ndarray,
        boxes_xyxy: np.ndarray,
    ) -> list[np.ndarray | None]:
        """One ArcFace embedding per detection (None if no face in crop)."""
        if boxes_xyxy.size == 0:
            return []

        h, w = frame_bgr.shape[:2]
        out: list[np.ndarray | None] = []

        for box in boxes_xyxy:
            x1, y1, x2, y2 = (int(max(0, v)) for v in box[:4])
            x2 = min(w, max(x1 + 1, x2))
            y2 = min(h, max(y1 + 1, y2))
            crop = frame_bgr[y1:y2, x1:x2]
            if crop.size == 0:
                out.append(None)
                continue

            faces = self.app.get(crop)
            if not faces:
                # Try upper-body region (common face location in person box)
                face_h = max(1, int((y2 - y1) * 0.45))
                crop2 = frame_bgr[y1 : y1 + face_h, x1:x2]
                faces = self.app.get(crop2) if crop2.size else []

            if not faces:
                out.append(None)
                continue

            best = max(faces, key=lambda f: float(getattr(f, "det_score", 0.0)))
            emb = np.asarray(best.normed_embedding, dtype=np.float32)
            out.append(emb)

        return out


# ---------------------------------------------------------------------------
# ArcFace identity merge (fragmented ByteTrack IDs → stable characters)
# ---------------------------------------------------------------------------


def _track_mean_embedding(track: RawTrack) -> np.ndarray | None:
    if not track.embeddings:
        return None
    mean = np.mean(np.stack(track.embeddings, axis=0), axis=0)
    norm = np.linalg.norm(mean)
    return (mean / norm) if norm > 1e-6 else mean


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6))


def merge_tracks_by_arcface(
    raw_tracks: dict[int, RawTrack],
    *,
    similarity_threshold: float = 0.45,
    min_track_frames: int = 5,
) -> dict[int, list[int]]:
    """
    Merge ByteTrack IDs into stable character IDs using ArcFace similarity.
    Returns {character_id: sorted unique frame list}.
    """
    eligible = {
        tid: t
        for tid, t in raw_tracks.items()
        if len(set(t.frames)) >= min_track_frames
    }
    if not eligible:
        return {}

    ids = list(eligible.keys())
    parent = list(range(len(ids)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    embs = [_track_mean_embedding(eligible[i]) for i in ids]

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ei, ej = embs[i], embs[j]
            if ei is not None and ej is not None:
                if _cosine(ei, ej) >= similarity_threshold:
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for idx, tid in enumerate(ids):
        groups.setdefault(find(idx), []).append(tid)

    merged: dict[int, list[int]] = {}
    for char_idx, (_, member_tids) in enumerate(sorted(groups.items()), start=1):
        frames: set[int] = set()
        for tid in member_tids:
            frames.update(eligible[tid].frames)
        merged[char_idx] = sorted(frames)

    return merged


# ---------------------------------------------------------------------------
# Optional stubs — later pipeline phases
# ---------------------------------------------------------------------------


def run_audio_branch(
    video_path: Path,
    *,
    device: str = "cpu",
    hf_token: str | None = None,
) -> dict[str, Any]:
    """
    Audio → Whisper → Pyannote → Speaker timeline.
    Returns placeholder structure; full diarization requires HF pyannote access.
    """
    del device, hf_token
    return {
        "status": "stub",
        "message": "Whisper + Pyannote branch not fully wired in Layer 1 script yet.",
        "speaker_timeline": [],
        "source_video": str(video_path),
    }


def run_locate_anything(
    video_path: Path,
    character_timeline: dict[str, Any],
) -> dict[str, Any]:
    """Optional spatial grounding stub (LocateAnything)."""
    return {
        "status": "stub",
        "message": "LocateAnything grounding not implemented in this test script.",
        "video": str(video_path),
        "characters": list(character_timeline.keys()),
        "groundings": [],
    }


def run_event_extraction(
    video_path: Path,
    *,
    character_timeline: dict[str, Any],
    speaker_timeline: dict[str, Any] | None,
    model: str = "Qwen2.5-VL",
) -> dict[str, Any]:
    """Qwen2.5-VL / Video-LLaMA3 event extraction stub."""
    return {
        "status": "stub",
        "message": f"{model} event extraction not implemented in this test script.",
        "video": str(video_path),
        "events": [],
        "narration": None,
        "inputs": {
            "characters": character_timeline,
            "speakers": speaker_timeline,
        },
    }


def _extract_wav_from_video(video_path: Path, wav_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(wav_path),
        ],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Layer 1 video pipeline
# ---------------------------------------------------------------------------


@dataclass
class Layer1Config:
    video_path: Path
    output_path: Path
    device: str = "cpu"
    yolo_model: str = "yolo11n.pt"
    conf: float = 0.25
    frame_stride: int = 1
    max_frames: int | None = None
    min_track_frames: int = 5
    min_persons: int = 2
    arcface_similarity: float = 0.45
    arcface_model: str = "buffalo_l"
    skip_validation: bool = False
    run_audio: bool = False
    run_locate: bool = False
    run_events: bool = False


class Layer1Pipeline:
    def __init__(self, config: Layer1Config):
        self.config = config
        self.detector = YOLOv11PersonDetector(
            model_name=config.yolo_model,
            device=config.device,
            conf=config.conf,
        )
        self.tracker = ByteTrackRunner(min_confidence=config.conf)
        self.arcface = ArcFaceEncoder(device=config.device, model_name=config.arcface_model)

    def run_video_tracking(self) -> tuple[dict[str, Any], dict[str, Any]]:
        cap = cv2.VideoCapture(str(self.config.video_path))
        if not cap.isOpened():
            raise FileNotFoundError(f"Cannot open video: {self.config.video_path}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        started = time.time()
        frame_idx = 0
        processed = 0
        timeline_sample: list[dict[str, Any]] = []

        print("Layer 1 — Video branch")
        print(f"  YOLOv11 ({self.config.yolo_model}) → ByteTrack → ArcFace")
        print(f"  {self.config.video_path}")
        print(f"  {frame_w}x{frame_h} @ {fps:.2f} fps | device={self.config.device} | stride={self.config.frame_stride}")
        print()

        while True:
            if self.config.max_frames is not None and frame_idx >= self.config.max_frames:
                break

            ok, frame = cap.read()
            if not ok:
                break

            frame_idx += 1
            if (frame_idx - 1) % self.config.frame_stride != 0:
                continue

            processed += 1
            frame_1 = frame_idx

            dets = self.detector.detect(frame)
            active = self.tracker.update(frame_1, frame, dets, self.arcface)

            if processed % 50 == 0:
                print(
                    f"  frame {frame_1}/{total_frames}  persons={len(dets)}  tracks={len(active)}",
                    flush=True,
                )

            if processed <= 5 or processed % 100 == 0:
                timeline_sample.append(
                    {
                        "frame": frame_1,
                        "detections": len(dets),
                        "active_track_ids": [tid for tid, _ in active],
                    }
                )

        cap.release()
        elapsed = time.time() - started

        raw = self.tracker.export()
        merged = merge_tracks_by_arcface(
            raw,
            similarity_threshold=self.config.arcface_similarity,
            min_track_frames=self.config.min_track_frames,
        )

        # Order characters by first frame appearance
        ordered = sorted(merged.items(), key=lambda kv: kv[1][0] if kv[1] else 10**9)
        primary: dict[str, Any] = {}
        id_remap: dict[int, str] = {}
        for i, (char_id, frames) in enumerate(ordered, start=1):
            key = f"person_{i}"
            primary[key] = {"frames": frames}
            id_remap[char_id] = key

        meta = {
            "pipeline": {
                "layer": 1,
                "video_branch": "YOLOv11 → ByteTrack → ArcFace → Character Timeline",
                "audio_branch": "Whisper → Pyannote (optional --phase audio)",
                "fusion": "Qwen2.5-VL event extraction (optional --phase events)",
            },
            "video": str(self.config.video_path.resolve()),
            "fps": round(fps, 3),
            "total_frames": frame_idx,
            "processed_frames": processed,
            "duration_sec": round(frame_idx / fps, 3) if fps else None,
            "processing_sec": round(elapsed, 2),
            "models": {
                "detection": "YOLOv11",
                "detection_checkpoint": self.config.yolo_model,
                "tracker": "ByteTrack",
                "appearance": "ArcFace",
                "appearance_checkpoint": self.config.arcface_model,
            },
            "person_count": len(primary),
            "raw_bytetrack_ids": len(raw),
            "merged_character_ids": len(merged),
            "track_id_to_person": {str(k): v for k, v in id_remap.items()},
            "settings": {
                "conf": self.config.conf,
                "frame_stride": self.config.frame_stride,
                "min_track_frames": self.config.min_track_frames,
                "min_persons": self.config.min_persons,
                "arcface_similarity": self.config.arcface_similarity,
                "device": self.config.device,
            },
            "character_timeline": primary,
            "timeline_sample": timeline_sample[-30:],
        }

        return primary, meta


def _write_outputs(
    output_path: Path,
    primary: dict[str, Any],
    meta: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(primary, f, indent=2)
    meta_path = output_path.with_name(output_path.stem + "_meta.json")
    payload = meta if extra is None else {**meta, "optional_phases": extra}
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return meta_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Layer 1: YOLOv11 + ByteTrack + ArcFace character tracking.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Pipeline phases (future / optional):
  --phase audio   Whisper → Pyannote speaker timeline (stub)
  --phase events  Qwen2.5-VL event extraction (stub)
  --ground-locate LocateAnything character grounding (stub)
        """,
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scripts/layer1_person_frames.json"),
    )
    parser.add_argument("--device", default="cpu", help="cpu | cuda | mps | 0 for GPU")
    parser.add_argument("--yolo-model", default="yolo11n.pt", help="Ultralytics YOLOv11 weights")
    parser.add_argument("--conf", type=float, default=0.25, help="Person detection confidence")
    parser.add_argument("--frame-stride", type=int, default=1, help="Process every Nth frame")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--min-track-frames", type=int, default=5)
    parser.add_argument(
        "--min-persons",
        type=int,
        default=2,
        help="Minimum characters required or validation fails (default: 2)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Do not abort when person_count < min-persons",
    )
    parser.add_argument("--arcface-similarity", type=float, default=0.45)
    parser.add_argument("--phase", action="append", choices=("audio", "events"), default=[])
    parser.add_argument("--ground-locate", action="store_true")
    args = parser.parse_args(argv)

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1

    missing: list[str] = []
    for pkg in ("ultralytics", "supervision", "insightface", "onnxruntime"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(
            "Missing: " + ", ".join(missing) + "\n"
            "Install: pip install -r scripts/layer1_requirements.txt",
            file=sys.stderr,
        )
        return 1

    config = Layer1Config(
        video_path=args.video,
        output_path=args.output,
        device=args.device,
        yolo_model=args.yolo_model,
        conf=args.conf,
        frame_stride=max(1, args.frame_stride),
        max_frames=args.max_frames,
        min_track_frames=args.min_track_frames,
        min_persons=args.min_persons,
        arcface_similarity=args.arcface_similarity,
        skip_validation=args.skip_validation,
        run_audio="audio" in args.phase,
        run_locate=args.ground_locate,
        run_events="events" in args.phase,
    )

    try:
        pipeline = Layer1Pipeline(config)
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    primary, meta = pipeline.run_video_tracking()

    try:
        if not config.skip_validation:
            validate_character_tracking(meta["person_count"], config.min_persons)
    except CharacterTrackingFailed as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        meta["validation_error"] = str(exc)
        meta_path = _write_outputs(args.output, primary, meta)
        print(f"Partial output written: {args.output.resolve()}", file=sys.stderr)
        return 2

    extra: dict[str, Any] = {"validation": {
        "passed": True,
        "person_count": meta["person_count"],
        "min_persons": config.min_persons,
    }}

    if config.run_audio:
        print("\nLayer 1 — Audio branch (stub)")
        extra["speaker_timeline"] = run_audio_branch(config.video_path)
    if config.run_locate:
        print("\nLayer 1 — LocateAnything (stub)")
        extra["character_grounding"] = run_locate_anything(config.video_path, primary)
    if config.run_events:
        print("\nFusion — Event extraction (stub)")
        extra["events"] = run_event_extraction(
            config.video_path,
            character_timeline=primary,
            speaker_timeline=extra.get("speaker_timeline"),
        )

    meta_path = _write_outputs(args.output, primary, meta, extra=extra)

    print()
    print(f"Persons tracked: {meta['person_count']} (required >= {config.min_persons})")
    for key, val in primary.items():
        frames = val["frames"]
        print(f"  {key}: {len(frames)} frames  ({frames[0]}–{frames[-1]})")
    print(f"Output: {args.output.resolve()}")
    print(f"Meta:   {meta_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
