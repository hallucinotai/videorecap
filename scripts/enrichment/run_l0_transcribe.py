#!/usr/bin/env python3
"""
L0: Transcribe a video with AssemblyAI speaker diarization.

Local CLI utility — writes the same JSON structure as the backend pipeline:
  metadata, speakers, segments (with optional word-level timestamps).

Usage:
  export ASSEMBLYAI_API_KEY=aai_...
  python scripts/enrichment/run_l0_transcribe.py --video assets/input_video.mp4

  python scripts/enrichment/run_l0_transcribe.py \\
    --video assets/input_video.mp4 \\
    --output-dir output/transcriptions \\
    --language en

Output:
  <output-dir>/transcription.json   (AssemblyAI enhanced format — L0)
  <output-dir>/transcription.txt    (human-readable lines)
  output/original/extracted_audio.wav (preserved audio extract)

Next step (L1 normalize):
  python scripts/enrichment/run_l1_normalize.py

Full enrichment chain (L1→L4):
  python scripts/enrichment/run_enrichment_chain.py --video assets/input_trimmed.mp4

Dependencies:
  pip install assemblyai moviepy
  Supports moviepy 1.x (moviepy.editor) and 2.x (moviepy).
  Backend Docker uses moviepy==1.0.3; local venv may use moviepy 2.x.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ENRICHMENT_DIR = Path(__file__).resolve().parent
if str(_ENRICHMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_ENRICHMENT_DIR))

from common import load_env_file, print_chain_hint, setup_import_paths


def main() -> None:
    setup_import_paths()
    load_env_file()

    parser = argparse.ArgumentParser(
        description="L0: Transcribe video with AssemblyAI speaker diarization",
    )
    parser.add_argument(
        "--video",
        required=True,
        help="Path to input video file",
    )
    parser.add_argument(
        "--output-dir",
        default="output/transcriptions",
        help="Directory for transcription.json and transcription.txt (default: output/transcriptions)",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="AssemblyAI language code (default: en)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="AssemblyAI API key (default: ASSEMBLYAI_API_KEY env var)",
    )
    args = parser.parse_args()

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.is_file():
        print(f"Error: video not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    api_key = (args.api_key or os.environ.get("ASSEMBLYAI_API_KEY") or "").strip()
    if not api_key:
        print(
            "Error: AssemblyAI API key required.\n"
            "  Set ASSEMBLYAI_API_KEY in .env or pass --api-key",
            file=sys.stderr,
        )
        sys.exit(1)

    from modules.transcription import transcribe_video_with_assemblyai

    print("L0 Transcribe (AssemblyAI)")
    print(f"  Video: {video_path}")
    print(f"  Output dir: {args.output_dir}")
    print(f"  Language: {args.language}")

    try:
        json_path = transcribe_video_with_assemblyai(
            str(video_path),
            output_dir=args.output_dir,
            api_key=api_key,
            language_code=args.language,
        )
    except ImportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Install with: pip install assemblyai moviepy", file=sys.stderr)
        sys.exit(1)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        doc = json.load(f)

    segment_count = len(doc.get("segments") or {})
    speaker_count = len(doc.get("speakers") or {})
    json_file = Path(json_path)

    print("\nDone.")
    print(f"  JSON: {json_path}")
    print(f"  Text: {json_file.with_name('transcription.txt')}")
    print(f"  Segments: {segment_count}")
    print(f"  Speakers: {speaker_count}")
    print_chain_hint("L0", json_file)


if __name__ == "__main__":
    main()
