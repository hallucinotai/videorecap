#!/usr/bin/env python3
"""
Sample video frames at a fixed rate and caption each with BLIP.

Local test utility — lives under scripts/ (gitignored). Not part of the app pipeline.

Pipeline:
  1. Extract frames at N fps (default 2 fps → one frame every 0.5s)
  2. Save each frame with timestamp in the filename
  3. Run BLIP (Bootstrapping Language-Image Pre-training) on each frame
  4. Write JSON + readable text summary with timestamp + description

Usage:
  pip install -r scripts/blip_requirements.txt

  python scripts/describe_video_blip.py \\
    --video assets/input_video.mp4 \\
    --output-dir video_descriptions

Dependencies:
  torch, torchvision, transformers, Pillow, opencv-python
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2


def format_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    mins, rem_ms = divmod(total_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{mins}:{secs:02d}.{ms:03d}"


def frame_filename(sample_index: int, timestamp_sec: float) -> str:
    return f"frame_{sample_index:05d}_{timestamp_sec:.3f}s.jpg"


@dataclass
class SampledFrame:
    sample_index: int
    source_frame_index: int
    timestamp_sec: float
    image_path: Path | None
    bgr: Any


class BLIPCaptioner:
    """BLIP image captioning via Hugging Face transformers."""

    def __init__(
        self,
        *,
        model_id: str = "Salesforce/blip-image-captioning-base",
        device: str = "cpu",
        max_new_tokens: int = 50,
    ):
        import torch
        from transformers import BlipForConditionalGeneration, BlipProcessor

        self.device = device
        self.max_new_tokens = max_new_tokens
        self._torch = torch
        self.processor = BlipProcessor.from_pretrained(model_id)
        self.model = BlipForConditionalGeneration.from_pretrained(model_id).to(device)
        self.model.eval()
        self.model_id = model_id

    def describe_bgr(self, frame_bgr) -> str:
        from PIL import Image

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        inputs = self.processor(images=pil, return_tensors="pt").to(self.device)
        with self._torch.inference_mode():
            output_ids = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)
        return self.processor.decode(output_ids[0], skip_special_tokens=True).strip()


def sample_frames(
    video_path: Path,
    *,
    sample_fps: float = 2.0,
    max_samples: int | None = None,
) -> tuple[list[SampledFrame], dict[str, Any]]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")

    video_fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    total_source_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_sec = total_source_frames / video_fps if video_fps > 0 and total_source_frames else 0.0

    interval = 1.0 / sample_fps
    samples: list[SampledFrame] = []
    t = 0.0
    sample_index = 0

    while t <= duration_sec + 1e-6:
        if max_samples is not None and sample_index >= max_samples:
            break

        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            break

        source_frame_index = int(round(t * video_fps))
        samples.append(
            SampledFrame(
                sample_index=sample_index,
                source_frame_index=source_frame_index,
                timestamp_sec=round(t, 3),
                image_path=None,
                bgr=frame,
            )
        )
        sample_index += 1
        t += interval

    cap.release()

    meta = {
        "video_fps": round(video_fps, 3),
        "total_source_frames": total_source_frames,
        "duration_sec": round(duration_sec, 3),
        "sample_fps": sample_fps,
        "sample_interval_sec": round(interval, 3),
        "sample_count": len(samples),
    }
    return samples, meta


def run_pipeline(
    *,
    video_path: Path,
    output_dir: Path,
    sample_fps: float,
    model_id: str,
    device: str,
    save_frames: bool,
    max_samples: int | None,
    max_new_tokens: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = output_dir / "frames"
    if save_frames:
        frames_dir.mkdir(parents=True, exist_ok=True)

    print(f"Video: {video_path}")
    samples, video_meta = sample_frames(
        video_path, sample_fps=sample_fps, max_samples=max_samples
    )
    print(
        f"  duration={video_meta['duration_sec']}s  "
        f"sample_fps={sample_fps}  samples={len(samples)}"
    )

    print(f"Loading BLIP: {model_id} ({device})")
    captioner = BLIPCaptioner(
        model_id=model_id, device=device, max_new_tokens=max_new_tokens
    )

    started = time.time()
    entries: list[dict[str, Any]] = []

    for i, sample in enumerate(samples):
        rel_image: str | None = None
        if save_frames:
            fname = frame_filename(sample.sample_index, sample.timestamp_sec)
            out_path = frames_dir / fname
            cv2.imwrite(str(out_path), sample.bgr)
            rel_image = str(Path("frames") / fname)
            sample.image_path = out_path

        description = captioner.describe_bgr(sample.bgr)
        entries.append(
            {
                "sample_index": sample.sample_index,
                "source_frame_index": sample.source_frame_index,
                "timestamp_sec": sample.timestamp_sec,
                "timestamp": format_timestamp(sample.timestamp_sec),
                "image_path": rel_image,
                "description": description,
            }
        )

        if (i + 1) % 10 == 0 or i + 1 == len(samples):
            print(
                f"  [{i + 1}/{len(samples)}] {format_timestamp(sample.timestamp_sec)}  "
                f"{description[:70]}{'…' if len(description) > 70 else ''}",
                flush=True,
            )

    elapsed = time.time() - started

    report = {
        "video": str(video_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "model": {
            "name": "BLIP",
            "checkpoint": model_id,
            "device": device,
        },
        **video_meta,
        "processing_sec": round(elapsed, 2),
        "descriptions": entries,
    }
    return report


def write_text_summary(report: dict[str, Any], path: Path) -> None:
    lines = [
        f"Video: {report['video']}",
        f"Samples: {report['sample_count']} @ {report['sample_fps']} fps",
        f"Model: {report['model']['checkpoint']}",
        "",
    ]
    for item in report["descriptions"]:
        lines.append(f"[{item['timestamp']} | {item['timestamp_sec']:.3f}s]")
        lines.append(item["description"])
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sample video frames and caption with BLIP."
    )
    parser.add_argument("--video", required=True, type=Path, help="Input video path")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("video_descriptions"),
        help="Output directory (default: video_descriptions)",
    )
    parser.add_argument(
        "--sample-fps",
        type=float,
        default=2.0,
        help="Frame sampling rate in fps (default: 2.0 → every 0.5s)",
    )
    parser.add_argument(
        "--model",
        default="Salesforce/blip-image-captioning-base",
        help="HF BLIP checkpoint (default: blip-image-captioning-base)",
    )
    parser.add_argument("--device", default="cpu", help="cpu | cuda | mps")
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Optional cap for quick tests",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=50,
        help="BLIP caption length limit (default: 50)",
    )
    parser.add_argument(
        "--no-save-frames",
        action="store_true",
        help="Skip writing JPG files; only output captions JSON/txt",
    )
    args = parser.parse_args(argv)

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1

    if args.sample_fps <= 0:
        print("--sample-fps must be > 0", file=sys.stderr)
        return 1

    missing: list[str] = []
    for pkg in ("torch", "torchvision", "transformers", "PIL"):
        try:
            __import__(pkg if pkg != "PIL" else "PIL")
        except ImportError:
            missing.append("pillow" if pkg == "PIL" else pkg)

    if missing:
        print(
            "Missing: " + ", ".join(missing) + "\n"
            "Install: pip install -r scripts/blip_requirements.txt",
            file=sys.stderr,
        )
        return 1

    try:
        report = run_pipeline(
            video_path=args.video,
            output_dir=args.output_dir,
            sample_fps=args.sample_fps,
            model_id=args.model,
            device=args.device,
            save_frames=not args.no_save_frames,
            max_samples=args.max_samples,
            max_new_tokens=args.max_new_tokens,
        )
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    json_path = args.output_dir / "descriptions.json"
    txt_path = args.output_dir / "descriptions.txt"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    write_text_summary(report, txt_path)

    print()
    print(f"Captions: {report['sample_count']}")
    print(f"JSON: {json_path.resolve()}")
    print(f"Text: {txt_path.resolve()}")
    if not args.no_save_frames:
        print(f"Frames: {(args.output_dir / 'frames').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
