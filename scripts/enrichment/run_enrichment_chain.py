#!/usr/bin/env python3
"""
Run L1→L4 enrichment in one go (same as backend pipeline, for local debugging).

Prerequisite: L0 transcription.json from scripts/enrichment/run_l0_transcribe.py

Usage:
  python scripts/enrichment/run_enrichment_chain.py --video assets/input_video.mp4
  python scripts/enrichment/run_enrichment_chain.py \\
    --run-name input_video_1 \\
    --video assets/input_video.mp4
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ENRICHMENT_DIR = Path(__file__).resolve().parent
if str(_ENRICHMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_ENRICHMENT_DIR))

from common import add_run_name_arg, add_video_arg, load_env_file, repo_root, resolve_path, setup_import_paths
from run_paths import raw_transcript_path, resolve_run_name


def _run(script: str, extra_args: list[str]) -> None:
    path = _ENRICHMENT_DIR / script
    cmd = [sys.executable, str(path), *extra_args]
    print(f"\n{'=' * 72}\n$ {' '.join(cmd)}\n{'=' * 72}")
    subprocess.run(cmd, check=True)


def main() -> None:
    setup_import_paths()
    load_env_file()

    root = repo_root()
    parser = argparse.ArgumentParser(description="Run L1→L4 enrichment chain")
    add_run_name_arg(parser)
    add_video_arg(parser)
    parser.add_argument(
        "--raw-transcript",
        default=None,
        help="L0 transcription.json (default: output/transcriptions/<run-name>/transcription.json)",
    )
    parser.add_argument("--job-id", default="local-debug")
    parser.add_argument("--working-dir", default=str(root))
    parser.add_argument(
        "--from-layer",
        choices=["L1", "L2", "LP", "L3", "L4"],
        default="L1",
        help="Start at this layer (uses default inputs for that layer)",
    )
    args = parser.parse_args()

    working_dir = Path(args.working_dir).expanduser().resolve()
    video_path = (
        resolve_path(args.video, base=working_dir)
        if args.video
        else None
    )
    raw_arg = (
        resolve_path(args.raw_transcript, base=working_dir)
        if args.raw_transcript
        else None
    )

    try:
        run_name = resolve_run_name(
            run_name=args.run_name,
            video_path=video_path,
            input_path=raw_arg,
            working_dir=working_dir,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    raw = raw_arg or raw_transcript_path(working_dir, run_name)
    common = [
        "--run-name",
        run_name,
        "--job-id",
        args.job_id,
        "--working-dir",
        str(working_dir),
    ]

    steps: list[tuple[str, list[str]]] = [
        ("run_l1_normalize.py", common),
        (
            "run_l2_identity.py",
            common + (["--video", str(video_path)] if video_path else []),
        ),
        ("run_lp_attribution.py", common),
        (
            "run_l3_gender.py",
            common + (["--video", str(video_path)] if video_path else []),
        ),
        ("run_l4_finalize.py", common),
    ]

    # L1 needs explicit raw transcript input
    steps[0] = ("run_l1_normalize.py", ["--input", str(raw), *common])

    start_idx = {"L1": 0, "L2": 1, "LP": 2, "L3": 3, "L4": 4}[args.from_layer]
    for script, extra in steps[start_idx:]:
        _run(script, extra)

    print(
        f"\nChain finished. Terminal output: "
        f"{working_dir / 'output' / 'transcriptions' / run_name / 'layers' / 'enrichment_L4.json'}"
    )


if __name__ == "__main__":
    main()
