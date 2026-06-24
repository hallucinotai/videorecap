#!/usr/bin/env python3
"""
Sample 2 video frames per word (start + end) for a single AssemblyAI utterance.

Local test utility — lives under scripts/ (gitignored). Not part of the app pipeline.

Usage:
  python scripts/sample_word_frames.py \\
    --video /path/to/video.mp4 \\
    --json /path/to/transcription.json \\
    --utterance 1 \\
    --output-dir ./word_frame_samples

Expects AssemblyAI-style JSON with word-level timestamps, e.g.:
  { "segments": { "0": { "text": "...", "start": 4.2, "end": 7.1, "speaker": "A",
      "words": [ {"text": "Hey", "start": 4.2, "end": 4.45}, ... ] } } }

Also accepts raw AssemblyAI API export with top-level "utterances" and ms timestamps.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _slug(text: str, max_len: int = 24) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "word").strip()).strip("_")
    return (slug or "word")[:max_len]


def _normalize_time(value: float, *, times_in_ms: bool) -> float:
    return value / 1000.0 if times_in_ms else value


def _detect_ms_timestamps(words: list[dict]) -> bool:
    """Heuristic: values > 500 are almost certainly milliseconds."""
    for word in words[:5]:
        for key in ("start", "end"):
            val = word.get(key)
            if val is not None and float(val) > 500:
                return True
    return False


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _ordered_utterances(doc: dict) -> list[dict]:
    """Return utterances/segments sorted by start time."""
    if isinstance(doc.get("utterances"), list):
        items = list(doc["utterances"])
    elif isinstance(doc.get("segments"), dict):
        items = list(doc["segments"].values())
    elif isinstance(doc.get("segments"), list):
        items = list(doc["segments"])
    else:
        raise ValueError(
            "JSON must contain 'utterances' (list) or 'segments' (dict/list) "
            "with AssemblyAI diarization output."
        )

    if not items:
        raise ValueError("No utterances/segments found in JSON.")

    return sorted(items, key=lambda u: float(u.get("start", 0)))


def _words_for_utterance(utterance: dict) -> list[dict]:
    words = utterance.get("words") or []
    if not words:
        raise ValueError(
            f"Utterance has no word-level timestamps. Text: {utterance.get('text', '')!r}\n"
            "Re-run transcription with AssemblyAI word timestamps enabled."
        )

    times_in_ms = _detect_ms_timestamps(words)
    normalized: list[dict] = []
    for idx, word in enumerate(words):
        text = str(word.get("text") or word.get("word") or "").strip()
        if not text:
            continue
        start = _normalize_time(float(word["start"]), times_in_ms=times_in_ms)
        end = _normalize_time(float(word["end"]), times_in_ms=times_in_ms)
        normalized.append({"index": idx, "text": text, "start": start, "end": end})

    if not normalized:
        raise ValueError("Utterance words list is empty after filtering.")
    return normalized


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


def sample_utterance_word_frames(
    *,
    video_path: Path,
    json_path: Path,
    utterance_number: int = 1,
    output_dir: Path,
) -> list[dict]:
    doc = _load_json(json_path)
    utterances = _ordered_utterances(doc)

    if utterance_number < 1 or utterance_number > len(utterances):
        raise ValueError(
            f"--utterance must be between 1 and {len(utterances)} (got {utterance_number})"
        )

    utterance = utterances[utterance_number - 1]
    words = _words_for_utterance(utterance)
    output_dir.mkdir(parents=True, exist_ok=True)

    u_tag = f"u{utterance_number:02d}"
    speaker = utterance.get("speaker") or utterance.get("speaker_id") or "?"
    utterance_text = utterance.get("text", "")

    extractor = FrameExtractor(video_path)
    manifest: list[dict] = []

    try:
        import cv2

        for word in words:
            w_tag = f"w{word['index'] + 1:02d}"
            word_slug = _slug(word["text"])

            for edge, ts in (("start", word["start"]), ("end", word["end"])):
                frame = extractor.read_at(ts)
                filename = f"{u_tag}_{w_tag}_{word_slug}_{edge}_{ts:.3f}s.png"
                out_path = output_dir / filename

                if frame is None:
                    manifest.append(
                        {
                            "utterance": utterance_number,
                            "word_index": word["index"],
                            "word": word["text"],
                            "edge": edge,
                            "timestamp_sec": ts,
                            "saved": False,
                            "path": None,
                            "error": "frame read failed",
                        }
                    )
                    print(f"  ! miss  {edge:5s} @ {ts:7.3f}s  '{word['text']}'")
                    continue

                cv2.imwrite(str(out_path), frame)
                manifest.append(
                    {
                        "utterance": utterance_number,
                        "word_index": word["index"],
                        "word": word["text"],
                        "edge": edge,
                        "timestamp_sec": round(ts, 3),
                        "saved": True,
                        "path": str(out_path),
                    }
                )
                print(f"  ✓ saved {edge:5s} @ {ts:7.3f}s  '{word['text']}'  →  {out_path.name}")
    finally:
        extractor.close()

    summary = {
        "video": str(video_path.resolve()),
        "json": str(json_path.resolve()),
        "utterance_number": utterance_number,
        "speaker": speaker,
        "utterance_text": utterance_text,
        "utterance_start_sec": float(utterance.get("start", words[0]["start"])),
        "utterance_end_sec": float(utterance.get("end", words[-1]["end"])),
        "word_count": len(words),
        "frames_requested": len(words) * 2,
        "frames_saved": sum(1 for m in manifest if m["saved"]),
        "video_fps": extractor.fps,
        "video_duration_sec": extractor.duration_sec,
        "frames": manifest,
    }

    manifest_path = output_dir / f"{u_tag}_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print()
    print(f"Utterance {utterance_number} [{speaker}]: {utterance_text}")
    print(f"Words: {len(words)}  |  Frames saved: {summary['frames_saved']}/{summary['frames_requested']}")
    print(f"Output: {output_dir.resolve()}")
    print(f"Manifest: {manifest_path}")

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract 2 frames per word (start/end) from utterance N using AssemblyAI timestamps."
    )
    parser.add_argument("--video", required=True, type=Path, help="Path to source video (.mp4, etc.)")
    parser.add_argument("--json", required=True, type=Path, dest="json_path", help="AssemblyAI transcription JSON")
    parser.add_argument(
        "--utterance",
        type=int,
        default=1,
        help="1-based utterance index after sorting by start time (default: 1)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./word_frame_samples"),
        help="Directory for PNG frames + manifest (default: ./word_frame_samples)",
    )
    args = parser.parse_args(argv)

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1
    if not args.json_path.is_file():
        print(f"JSON not found: {args.json_path}", file=sys.stderr)
        return 1

    try:
        sample_utterance_word_frames(
            video_path=args.video,
            json_path=args.json_path,
            utterance_number=args.utterance,
            output_dir=args.output_dir,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
