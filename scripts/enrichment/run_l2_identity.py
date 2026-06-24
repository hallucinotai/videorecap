#!/usr/bin/env python3
"""
L2: Speaker identity — video reconcile (S1) + text names (S2).

Input:  enrichment_L1.json
Output: enrichment_L2.json (+ L2/sublayers/S1_video.json, S2_text.json)

Also requires L0 raw transcript for speaker metadata (--raw-transcript).
Pass --video to enable face/lip video reconcile; omitted video skips S1 gracefully.

Usage:
  python scripts/enrichment/run_l2_identity.py \\
    --input output/transcriptions/layers/enrichment_L1.json \\
    --raw-transcript output/transcriptions/transcription.json \\
    --video assets/input_trimmed.mp4
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
    add_raw_transcript_arg,
    add_video_arg,
    build_run_context,
    load_env_file,
    parse_paths,
    print_chain_hint,
    resolve_path,
    run_enrichment_layer,
    setup_import_paths,
)


def main() -> None:
    setup_import_paths()
    load_env_file()

    parser = argparse.ArgumentParser(description="L2: Speaker identity enrichment")
    add_common_args(parser, layer_id="L2")
    add_raw_transcript_arg(parser)
    add_video_arg(parser)
    args = parser.parse_args()

    working_dir, input_path, output_path, layers_dir = parse_paths(args)
    raw_path = resolve_path(args.raw_transcript, base=working_dir)
    video_path = resolve_path(args.video, base=working_dir) if args.video else None

    if not input_path.is_file():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    if not raw_path.is_file():
        print(f"Error: raw transcript not found: {raw_path}", file=sys.stderr)
        sys.exit(1)
    if video_path and not video_path.is_file():
        print(f"Error: video not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    ctx = build_run_context(
        job_id=args.job_id,
        working_dir=working_dir,
        layers_output_dir=layers_dir,
        raw_transcript=raw_path,
        video_path=video_path,
    )

    print("L2 Identity")
    print(f"  Input:  {input_path}")
    print(f"  Raw:    {raw_path}")
    print(f"  Video:  {video_path or '(none — S1 video reconcile will skip)'}")
    print(f"  Output: {output_path}")

    try:
        result = run_enrichment_layer(
            "L2",
            input_path=input_path,
            output_path=output_path,
            ctx=ctx,
        )
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    speakers = result.get("L2_speakers") or {}
    recon = (result.get("L2_reconciliation") or {}).get("status")
    print(f"\nDone. speakers={len(speakers)} video_reconcile={recon or 'n/a'}")
    print_chain_hint("L2", output_path)


if __name__ == "__main__":
    main()
