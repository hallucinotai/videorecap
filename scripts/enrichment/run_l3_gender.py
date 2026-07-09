#!/usr/bin/env python3
"""
L3: Gender enrichment — text analysis (S1) + visual hints (S2) + frame gender (S3).

Input:  enrichment_L2.json
Output: enrichment_L3.json (+ L3/sublayers/S1_text.json, S2_visual.json, S3_audio.json)

Usage:
  python scripts/enrichment/run_l3_gender.py --run-name input_video_1 \\
    --video assets/input_video.mp4
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

    parser = argparse.ArgumentParser(description="L3: Gender enrichment")
    add_common_args(parser, layer_id="L3")
    add_raw_transcript_arg(parser)
    add_video_arg(parser)
    args = parser.parse_args()

    working_dir, input_path, output_path, layers_dir, run_name = parse_paths(args, layer_id="L3")
    raw_path = resolve_raw_transcript_path(args, working_dir, run_name)
    video_path = resolve_path(args.video, base=working_dir) if args.video else None

    if not input_path.is_file():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    ctx = build_run_context(
        job_id=args.job_id,
        working_dir=working_dir,
        run_name=run_name,
        layers_output_dir=layers_dir,
        raw_transcript=raw_path if raw_path.is_file() else None,
        video_path=video_path,
        audio_path=None,
    )

    print("L3 Gender")
    print(f"  Run:    {run_name}")
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_path}")
    if ctx.video_path:
        print(f"  Video:  {ctx.video_path}")

    try:
        result = run_enrichment_layer(
            "L3",
            input_path=input_path,
            output_path=output_path,
            ctx=ctx,
        )
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    gender = result.get("L3_gender") or {}
    visual = result.get("L3_visual") or {}
    audio = result.get("L3_audio") or {}
    sub_status = (result.get("pipeline_meta") or {}).get("sublayer_status") or {}
    print(
        f"\nDone. gender_profiles={len(gender)} visual_hints={len(visual)} "
        f"frame_gender_profiles={len(audio)} S3={sub_status.get('L3.S3')}"
    )
    print_chain_hint("L3", output_path, working_dir=working_dir)


if __name__ == "__main__":
    main()
