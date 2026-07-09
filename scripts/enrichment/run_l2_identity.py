#!/usr/bin/env python3
"""
L2: Speaker identity — character observation (S1) + text names (S2).

Input:  enrichment_L1.json
Output: enrichment_L2.json (chain-compatible with L3/L4)

Usage:
  python scripts/enrichment/run_l2_identity.py \\
    --run-name input_video_1 \\
    --video assets/input_video.mp4

  python scripts/enrichment/run_l2_identity.py \\
    --run-name input_video_1 \\
    --video assets/input_video.mp4 \\
    --output output/transcriptions/input_video_1/layers/enrichment_L2.json
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
    resolve_raw_transcript_path,
    run_enrichment_layer,
    setup_import_paths,
)


def main() -> None:
    setup_import_paths()
    load_env_file()

    parser = argparse.ArgumentParser(description="L2: Character observation + speaker names")
    add_common_args(parser, layer_id="L2")
    add_raw_transcript_arg(parser)
    add_video_arg(parser)
    args = parser.parse_args()

    working_dir, input_path, output_path, layers_dir, run_name = parse_paths(args, layer_id="L2")
    raw_transcript = resolve_raw_transcript_path(args, working_dir, run_name)
    video_path = resolve_path(args.video, base=working_dir) if args.video else None

    if not input_path.is_file():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    ctx = build_run_context(
        job_id=args.job_id,
        working_dir=working_dir,
        run_name=run_name,
        layers_output_dir=layers_dir,
        raw_transcript=raw_transcript if raw_transcript.is_file() else None,
        video_path=video_path if video_path and video_path.is_file() else None,
    )

    print("L2 Identity")
    print(f"  Run:    {run_name}")
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_path}")
    print(f"  Video:  {ctx.video_path or '(none — S1 will skip)'}")

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

    obs = result.get("L2_character_observation") or {}
    recon = result.get("L2_reconciliation") or {}
    print(
        f"\nDone. visual_characters={obs.get('character_count_visual', '?')} "
        f"diarization={obs.get('diarization_speaker_count', '?')} "
        f"S1={recon.get('status', '?')}"
    )
    print_chain_hint("L2", output_path, working_dir=working_dir)


if __name__ == "__main__":
    main()
