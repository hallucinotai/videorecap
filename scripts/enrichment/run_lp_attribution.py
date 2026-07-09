#!/usr/bin/env python3
"""
LP: Speaker attribution — text context (S1) + visual fusion (S2) + fuse (S3).

Input:  enrichment_L2.json
Output: enrichment_LP.json

Usage:
  python scripts/enrichment/run_lp_attribution.py --run-name one-miniute-time-machine
"""

from __future__ import annotations

import sys
from pathlib import Path

_ENRICHMENT_DIR = Path(__file__).resolve().parent
if str(_ENRICHMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_ENRICHMENT_DIR))

from common import (
    add_common_args,
    add_raw_transcript_arg,
    build_run_context,
    load_env_file,
    parse_paths,
    print_chain_hint,
    resolve_raw_transcript_path,
    run_enrichment_layer,
    setup_import_paths,
)


def main() -> None:
    setup_import_paths()
    load_env_file()

    import argparse

    parser = argparse.ArgumentParser(description="LP: Speaker attribution")
    add_common_args(parser, layer_id="LP")
    add_raw_transcript_arg(parser)
    args = parser.parse_args()

    working_dir, input_path, output_path, layers_dir, run_name = parse_paths(args, layer_id="LP")
    raw_path = resolve_raw_transcript_path(args, working_dir, run_name)

    if not input_path.is_file():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    ctx = build_run_context(
        job_id=args.job_id,
        working_dir=working_dir,
        run_name=run_name,
        layers_output_dir=layers_dir,
        raw_transcript=raw_path if raw_path.is_file() else None,
        video_path=None,
        audio_path=None,
    )

    print("LP Speaker Attribution")
    print(f"  Run:    {run_name}")
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_path}")

    try:
        result = run_enrichment_layer(
            "LP",
            input_path=input_path,
            output_path=output_path,
            ctx=ctx,
        )
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    attr = result.get("LP_attribution") or {}
    sub_status = (result.get("pipeline_meta") or {}).get("sublayer_status") or {}
    print(
        f"\nDone. pending_review={attr.get('pending_review_count', 0)} "
        f"S1={sub_status.get('LP.S1')} S2={sub_status.get('LP.S2')} S3={sub_status.get('LP.S3')}"
    )
    print_chain_hint("LP", output_path, working_dir=working_dir)


if __name__ == "__main__":
    main()
