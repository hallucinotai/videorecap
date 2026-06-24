#!/usr/bin/env python3
"""
Sample video frames at a fixed rate and describe each with GLM-4.5V (multimodal VLM).

Local test utility — lives under scripts/ (gitignored). Not part of the app pipeline.

Pipeline:
  1. Extract frames at N fps (default 2 fps → one frame every 0.5s)
  2. Save each frame with timestamp in the filename
  3. Run GLM-4.5V on each frame via Hugging Face transformers chat template
  4. Write JSON + readable text summary with timestamp + description

Usage:
  pip install -r scripts/glm45v_requirements.txt

  python scripts/describe_video_glm45v.py \\
    --video assets/output_clip.mp4 \\
    --output-dir video_descriptions_glm

Notes:
  - GLM-4.5V is a large MoE VLM (~12B active). Use GPU + ample VRAM.
  - For lower VRAM try: --model zai-org/GLM-4.5V-FP8
  - For local dev/smaller GPU: --model THUDM/GLM-4.1V-9B-Thinking
  - Requires transformers>=4.57.1 and huggingface-cli login if the checkpoint is gated.
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

DEFAULT_PROMPT = (
    "Describe this video frame in detail. Include people, actions, objects, "
    "setting, and mood. Be concise but specific."
)


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


class GLM45VDescriber:
    """GLM-4.5V multimodal description via Hugging Face transformers."""

    def __init__(
        self,
        *,
        model_id: str = "zai-org/GLM-4.5V-FP8",
        device: str = "cuda",
        max_new_tokens: int = 256,
        prompt: str = DEFAULT_PROMPT,
    ):
        import torch
        from transformers import AutoProcessor

        self.model_id = model_id
        self.max_new_tokens = max_new_tokens
        self.prompt = prompt
        self._torch = torch

        self.processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        self.model = self._load_model(model_id, device)
        self.model.eval()

    def _load_model(self, model_id: str, device: str):
        import torch

        kwargs: dict[str, Any] = {
            "torch_dtype": torch.float16 if device.startswith("cuda") else torch.float32,
            "trust_remote_code": True,
        }

        # Prefer MoE class for GLM-4.5V family; fall back to generic auto loader.
        try:
            from transformers import Glm4vMoeForConditionalGeneration

            if device == "cpu":
                kwargs["device_map"] = None
                model = Glm4vMoeForConditionalGeneration.from_pretrained(model_id, **kwargs)
                return model.to(device)
            kwargs["device_map"] = "auto" if device == "auto" else {"": device}
            return Glm4vMoeForConditionalGeneration.from_pretrained(model_id, **kwargs)
        except (ImportError, OSError, ValueError):
            from transformers import AutoModelForVision2Seq

            if device == "cpu":
                model = AutoModelForVision2Seq.from_pretrained(model_id, **kwargs)
                return model.to(device)
            kwargs["device_map"] = "auto" if device in ("auto", "cuda") else {"": device}
            return AutoModelForVision2Seq.from_pretrained(model_id, **kwargs)

    @property
    def device(self):
        return self.model.device

    def describe_bgr(self, frame_bgr) -> str:
        from PIL import Image

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil},
                    {"type": "text", "text": self.prompt},
                ],
            }
        ]

        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs.pop("token_type_ids", None)
        inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in inputs.items()}

        with self._torch.inference_mode():
            generated_ids = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)

        input_len = inputs["input_ids"].shape[1]
        new_tokens = generated_ids[0][input_len:]
        text = self.processor.decode(new_tokens, skip_special_tokens=True)
        return text.strip()


def run_pipeline(
    *,
    video_path: Path,
    output_dir: Path,
    sample_fps: float,
    model_id: str,
    device: str,
    prompt: str,
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

    print(f"Loading GLM-4.5V: {model_id} ({device})")
    if device == "cpu":
        print("  warning: GLM-4.5V on CPU is extremely slow and may OOM on full weights.")

    describer = GLM45VDescriber(
        model_id=model_id,
        device=device,
        max_new_tokens=max_new_tokens,
        prompt=prompt,
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

        description = describer.describe_bgr(sample.bgr)
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

        if (i + 1) % 5 == 0 or i + 1 == len(samples):
            preview = description.replace("\n", " ")[:80]
            print(
                f"  [{i + 1}/{len(samples)}] {format_timestamp(sample.timestamp_sec)}  "
                f"{preview}{'…' if len(description) > 80 else ''}",
                flush=True,
            )

    elapsed = time.time() - started

    return {
        "video": str(video_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "model": {
            "name": "GLM-4.5V",
            "checkpoint": model_id,
            "device": device,
            "prompt": prompt,
        },
        **video_meta,
        "processing_sec": round(elapsed, 2),
        "descriptions": entries,
    }


def write_text_summary(report: dict[str, Any], path: Path) -> None:
    lines = [
        f"Video: {report['video']}",
        f"Samples: {report['sample_count']} @ {report['sample_fps']} fps",
        f"Model: {report['model']['checkpoint']}",
        f"Prompt: {report['model']['prompt']}",
        "",
    ]
    for item in report["descriptions"]:
        lines.append(f"[{item['timestamp']} | {item['timestamp_sec']:.3f}s]")
        lines.append(item["description"])
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sample video frames and describe with GLM-4.5V multimodal model."
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("video_descriptions_glm"),
        help="Output directory (default: video_descriptions_glm)",
    )
    parser.add_argument("--sample-fps", type=float, default=2.0)
    parser.add_argument(
        "--model",
        default="zai-org/GLM-4.5V-FP8",
        help="HF checkpoint (default: GLM-4.5V-FP8; or zai-org/GLM-4.5V)",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        help="cuda | auto | cpu | mps (default: cuda)",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Text instruction sent with each frame",
    )
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--no-save-frames", action="store_true")
    args = parser.parse_args(argv)

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1
    if args.sample_fps <= 0:
        print("--sample-fps must be > 0", file=sys.stderr)
        return 1

    missing: list[str] = []
    for pkg, import_name in (
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("pillow", "PIL"),
        ("accelerate", "accelerate"),
    ):
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(
            "Missing: " + ", ".join(missing) + "\n"
            "Install: pip install -r scripts/glm45v_requirements.txt",
            file=sys.stderr,
        )
        return 1

    try:
        import transformers

        ver = tuple(int(x) for x in transformers.__version__.split(".")[:2])
        if ver < (4, 57):
            print(
                f"transformers>={transformers.__version__} may be too old for GLM-4.5V; "
                "need >=4.57.1. Upgrade: pip install -U 'transformers>=4.57.1'",
                file=sys.stderr,
            )
    except ImportError:
        pass

    try:
        report = run_pipeline(
            video_path=args.video,
            output_dir=args.output_dir,
            sample_fps=args.sample_fps,
            model_id=args.model,
            device=args.device,
            prompt=args.prompt,
            save_frames=not args.no_save_frames,
            max_samples=args.max_samples,
            max_new_tokens=args.max_new_tokens,
        )
    except (FileNotFoundError, RuntimeError, OSError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    json_path = args.output_dir / "descriptions.json"
    txt_path = args.output_dir / "descriptions.txt"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    write_text_summary(report, txt_path)

    print()
    print(f"Descriptions: {report['sample_count']}")
    print(f"JSON: {json_path.resolve()}")
    print(f"Text: {txt_path.resolve()}")
    if not args.no_save_frames:
        print(f"Frames: {(args.output_dir / 'frames').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
