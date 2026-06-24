#!/usr/bin/env python3
"""
L1: Normalize raw AssemblyAI transcript into stable utterance IDs.

Input:  L0 transcription.json (metadata + speakers + segments)
Output: enrichment_L1.json (L1_transcript.utterances with u1, u2, …)

Usage:
  python scripts/enrichment/run_l1_normalize.py
  python scripts/enrichment/run_l1_normalize.py \\
    --input output/transcriptions/transcription.json \\
    --output output/transcriptions/layers/enrichment_L1.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ENRICHMENT_DIR = Path(__file__).resolve().parent
if str(_ENRICHMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_ENRICHMENT_DIR))

from common import (
    add_common_args,
    build_run_context,
    load_env_file,
    parse_paths,
    print_chain_hint,
    run_enrichment_layer,
    setup_import_paths,
)


def main() -> None:
    setup_import_paths()
    load_env_file()

    parser = argparse.ArgumentParser(description="L1: Normalize AssemblyAI transcript")
    add_common_args(parser, layer_id="L1")
    args = parser.parse_args()

    working_dir, input_path, output_path, layers_dir = parse_paths(args)

    if not input_path.is_file():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    ctx = build_run_context(
        job_id=args.job_id,
        working_dir=working_dir,
        layers_output_dir=layers_dir,
        raw_transcript=None,
        video_path=None,
    )

    print(f"L1 Normalize")
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_path}")

    try:
        result = run_enrichment_layer(
            "L1",
            input_path=input_path,
            output_path=output_path,
            ctx=ctx,
        )
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    utterances = (result.get("L1_transcript") or {}).get("utterances") or []
    summary = (result.get("L1_transcript") or {}).get("diarization_summary") or {}
    print(f"\nDone. utterances={len(utterances)} speakers={summary.get('speaker_count', '?')}")
    print_chain_hint("L1", output_path)


if __name__ == "__main__":
    main()
