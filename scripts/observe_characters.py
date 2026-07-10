#!/usr/bin/env python3
"""
Observe distinct video characters from L1 utterance samples (prototype for new L2.S1).

SKIPPED — auto-correct "who spoke" from video (scorecard row 5):
  Lab scripts must not rewrite diarization from on-screen faces or lip motion.
  Whoever appears on screen is not necessarily the speaker; doing so collapses
  speaker diarization. This tool stays observe-only (characters vs labels).

Does NOT merge/collapse AssemblyAI speakers. Samples frames using the same logic as
enrichment L2 (word-chunk timestamps), clusters faces into char_1, char_2, …, optionally
describes appearance via OpenAI vision, and reports count mismatch vs diarization.

Usage:
  # Face portraits saved automatically under output/transcriptions/<run-name>/characters/
  python scripts/observe_characters.py \\
    --video assets/input_video.mp4

  # Optional: save every sample crop for debugging
  python scripts/observe_characters.py ... --save-crops output/character_crops/input_video_1

  # Skip portrait JPEG output
  python scripts/observe_characters.py ... --no-portraits

Dependencies:
  opencv-python
  Optional: insightface onnxruntime (ArcFace character counting)
  Optional: openai + OPENAI_API_KEY for --describe
  Optional: mediapipe (histogram fallback only when insightface is unavailable)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
for path in (_REPO_ROOT, _SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from character_observation.core import (
    load_l1_document,
    observe_characters,
    report_to_dict,
)
from run_paths import characters_dir, resolve_run_name, transcriptions_dir


def _load_dotenv() -> None:
    env_path = _REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path)


def main() -> int:
    _load_dotenv()

    parser = argparse.ArgumentParser(
        description="Observe video characters from L1 utterance samples (no speaker merge)"
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help=(
            "Output folder name under output/transcriptions/<run-name>/ "
            "(default: video filename stem, or inferred from --input)"
        ),
    )
    parser.add_argument(
        "--input",
        default=None,
        help="L1 enrichment JSON (default: output/transcriptions/<run-name>/layers/enrichment_L1.json)",
    )
    parser.add_argument(
        "--video",
        required=True,
        help="Source video file",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON report (default: output/transcriptions/<run-name>/character_observation.json)",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Run OpenAI vision to fill appearance fields per character (needs OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--appearance-model",
        default="gpt-4o-mini",
        help="Vision model for --describe (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--save-crops",
        default=None,
        help="Optional directory to save every sample crop as JPEG (debug/review)",
    )
    parser.add_argument(
        "--characters-dir",
        default=None,
        help=(
            "Directory for per-character face portraits "
            "(default: output/transcriptions/<run-name>/characters/)"
        ),
    )
    parser.add_argument(
        "--no-portraits",
        action="store_true",
        help="Do not write per-character face.jpg files or portrait paths in JSON",
    )
    parser.add_argument(
        "--min-cluster-samples",
        type=int,
        default=3,
        help="Minimum face samples to count a character as significant (default: 3)",
    )
    args = parser.parse_args()

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.is_file():
        print(f"Error: video not found: {video_path}", file=sys.stderr)
        return 1

    try:
        run_name = resolve_run_name(
            run_name=args.run_name,
            video_path=video_path,
            input_path=Path(args.input).expanduser().resolve() if args.input else None,
            working_dir=_REPO_ROOT,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    input_path = (
        Path(args.input).expanduser().resolve()
        if args.input
        else transcriptions_dir(_REPO_ROOT, run_name) / "layers" / "enrichment_L1.json"
    )
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else transcriptions_dir(_REPO_ROOT, run_name) / "character_observation.json"
    )
    crops_dir = Path(args.save_crops).expanduser().resolve() if args.save_crops else None
    portrait_dir = None
    if not args.no_portraits:
        portrait_dir = (
            Path(args.characters_dir).expanduser().resolve()
            if args.characters_dir
            else characters_dir(_REPO_ROOT, run_name)
        )

    if not input_path.is_file():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        return 1

    print("Character observation (prototype)")
    print(f"  Run:    {run_name}")
    print(f"  Input:  {input_path}")
    print(f"  Video:  {video_path}")
    print(f"  Output: {output_path}")
    print(f"  Describe: {args.describe}")
    if portrait_dir:
        print(f"  Portraits: {portrait_dir}")
    if crops_dir:
        print(f"  Sample crops: {crops_dir}")

    l1_doc = load_l1_document(input_path)
    report = observe_characters(
        video_path=video_path,
        l1_doc=l1_doc,
        describe=args.describe,
        appearance_model=args.appearance_model,
        save_crops_dir=crops_dir,
        characters_dir=portrait_dir,
        working_dir=_REPO_ROOT,
        min_cluster_samples=args.min_cluster_samples,
    )
    payload = report_to_dict(report)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print()
    print(f"  Diarization speakers: {report.diarization_speaker_count} {report.diarization_speaker_ids}")
    print(f"  Visual characters (raw): {report.character_count_visual} ({report.embedding_method})")
    print(f"  Significant (≥{report.min_cluster_samples} samples): {report.character_count_significant}")
    print(f"  Faces sampled:        {report.faces_sampled} / {report.sample_points} sample points")
    print(f"  Count mismatch:       {report.count_mismatch}")
    if report.characters:
        print("  Significant characters:")
        for cid, meta in sorted(report.characters.items()):
            if int(meta.get("sample_count") or 0) < report.min_cluster_samples:
                continue
            co = meta.get("aai_speaker_cooccurrence") or {}
            portrait = meta.get("portrait") or {}
            path_hint = portrait.get("face_relative_path") or portrait.get("face_local_path") or "—"
            print(f"    {cid}: {meta['sample_count']} samples, AAI co-occur {co}, face={path_hint}")
    print(f"\nWrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
