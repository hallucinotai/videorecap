#!/usr/bin/env python3
"""
L4: Finalize enrichment — merge gender proposals and build review queue.

Input:  enrichment_L3.json
Output: enrichment_L4.json (terminal layer with speaker_profiles + review_queue)

Usage:
  python scripts/enrichment/run_l4_finalize.py \\
    --input output/transcriptions/layers/enrichment_L3.json
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
    run_enrichment_layer,
    setup_import_paths,
)


def main() -> None:
    setup_import_paths()
    load_env_file()

    parser = argparse.ArgumentParser(description="L4: Finalize enrichment review")
    add_common_args(parser, layer_id="L4")
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

    print("L4 Finalize")
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_path}")

    try:
        result = run_enrichment_layer(
            "L4",
            input_path=input_path,
            output_path=output_path,
            ctx=ctx,
        )
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    from modules.enrichment.document import get_review_queue

    profiles = result.get("speaker_profiles") or {}
    queue = get_review_queue(result)
    print(f"\nDone. speaker_profiles={len(profiles)} review_items={len(queue)}")
    print("\nChain complete (terminal layer).")


if __name__ == "__main__":
    main()
