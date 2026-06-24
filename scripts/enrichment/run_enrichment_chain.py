#!/usr/bin/env python3
"""
Run L1→L4 enrichment in one go (same as backend pipeline, for local debugging).

Prerequisite: L0 transcription.json from scripts/enrichment/run_l0_transcribe.py

Usage:
  python scripts/enrichment/run_enrichment_chain.py
  python scripts/enrichment/run_enrichment_chain.py \\
    --raw-transcript output/transcriptions/transcription.json \\
    --video assets/input_trimmed.mp4
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ENRICHMENT_DIR = Path(__file__).resolve().parent
if str(_ENRICHMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_ENRICHMENT_DIR))

from common import (
    DEFAULT_RAW_TRANSCRIPT,
    default_layers_dir,
    load_env_file,
    repo_root,
    resolve_path,
    setup_import_paths,
)


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
    parser.add_argument(
        "--raw-transcript",
        default=str(resolve_path(DEFAULT_RAW_TRANSCRIPT, base=root)),
        help="L0 transcription.json",
    )
    parser.add_argument("--video", default=None, help="Video for L2 video reconcile")
    parser.add_argument("--job-id", default="local-debug")
    parser.add_argument("--working-dir", default=str(root))
    parser.add_argument(
        "--layers-dir",
        default=str(default_layers_dir(root)),
    )
    parser.add_argument(
        "--from-layer",
        choices=["L1", "L2", "L3", "L4"],
        default="L1",
        help="Start at this layer (uses default inputs for that layer)",
    )
    args = parser.parse_args()

    working_dir = Path(args.working_dir).expanduser().resolve()
    raw = resolve_path(args.raw_transcript, base=working_dir)
    layers_dir = resolve_path(args.layers_dir, base=working_dir)
    common = [
        "--job-id",
        args.job_id,
        "--working-dir",
        str(working_dir),
        "--layers-dir",
        str(layers_dir),
    ]

    steps: list[tuple[str, list[str]]] = [
        ("run_l1_normalize.py", ["--input", str(raw)] + common),
        (
            "run_l2_identity.py",
            ["--raw-transcript", str(raw)] + common + (
                ["--video", str(resolve_path(args.video, base=working_dir))]
                if args.video
                else []
            ),
        ),
        ("run_l3_gender.py", ["--raw-transcript", str(raw)] + common),
        ("run_l4_finalize.py", common),
    ]

    start_idx = {"L1": 0, "L2": 1, "L3": 2, "L4": 3}[args.from_layer]
    for script, extra in steps[start_idx:]:
        _run(script, extra)

    print(f"\nChain finished. Terminal output: {layers_dir / 'enrichment_L4.json'}")


if __name__ == "__main__":
    main()
