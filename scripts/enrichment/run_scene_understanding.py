#!/usr/bin/env python3
"""
Scene understanding: GPT-4o vision describe → scene_understanding.json
(+ optional inject into enrichment/transcript JSON for recap).

Usage:
  python scripts/enrichment/run_scene_understanding.py \\
    --run-name input_video \\
    --video assets/input_video.mp4

  # Smoke test first 60s
  SCENE_MAX_DURATION=60 python scripts/enrichment/run_scene_understanding.py \\
    --run-name input_video \\
    --video assets/input_video.mp4

  # Inject into L4 (or any transcript JSON) for local recap testing
  python scripts/enrichment/run_scene_understanding.py \\
    --run-name input_video \\
    --video assets/input_video.mp4 \\
    --inject-into output/transcriptions/input_video/layers/enrichment_L4.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ENRICHMENT_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _ENRICHMENT_DIR.parent
_REPO_ROOT = _SCRIPTS_DIR.parent
for path in (_REPO_ROOT, _SCRIPTS_DIR, _ENRICHMENT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common import (  # noqa: E402
    add_run_name_arg,
    load_env_file,
    resolve_path,
    setup_import_paths,
)
from run_paths import layers_dir as run_layers_dir  # noqa: E402
from run_paths import resolve_run_name  # noqa: E402


def main() -> int:
    setup_import_paths()
    load_env_file()

    parser = argparse.ArgumentParser(description="Scene understanding (GPT-4o vision)")
    add_run_name_arg(parser)
    parser.add_argument("--video", required=True, help="Input video path")
    parser.add_argument(
        "--working-dir",
        default=str(_REPO_ROOT),
        help="Repo/working directory (default: repo root)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output scene_understanding.json (default: run layers dir)",
    )
    parser.add_argument(
        "--inject-into",
        default=None,
        help="Transcript/enrichment JSON to patch with narration_context.scene_*",
    )
    parser.add_argument(
        "--sample-fps",
        type=float,
        default=None,
        help="Override SCENE_SAMPLE_FPS (default from env or 0.5)",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=None,
        help="Only analyze first N seconds (overrides SCENE_MAX_DURATION)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Vision model (default SCENE_VISION_MODEL or gpt-4o)",
    )
    parser.add_argument(
        "--boundary-mode",
        choices=["fixed", "pyscenedetect"],
        default=None,
        help="Scene windows: fixed time batches or PySceneDetect+merge (default: SCENE_BOUNDARY_MODE / fixed)",
    )
    parser.add_argument(
        "--skip-merge",
        action="store_true",
        help="Keep segment descriptions separate instead of merging",
    )
    args = parser.parse_args()

    working_dir = Path(args.working_dir).expanduser().resolve()
    video_path = resolve_path(args.video, base=working_dir)
    if not video_path.is_file():
        print(f"Error: video not found: {video_path}", file=sys.stderr)
        return 1

    run_name = resolve_run_name(
        run_name=args.run_name,
        video_path=video_path,
        input_path=None,
        working_dir=working_dir,
    )
    layers = run_layers_dir(working_dir, run_name)
    layers.mkdir(parents=True, exist_ok=True)

    output_path = (
        resolve_path(args.output, base=working_dir)
        if args.output
        else layers / "scene_understanding.json"
    )

    from modules.scene_understanding import (
        inject_scene_into_transcript_file,
        run_scene_understanding,
        write_scene_artifact,
    )

    print("Scene Understanding")
    print(f"  Run:    {run_name}")
    print(f"  Video:  {video_path}")
    print(f"  Output: {output_path}")

    try:
        result = run_scene_understanding(
            video_path,
            sample_fps=args.sample_fps,
            max_duration=args.max_duration,
            model=args.model,
            skip_merge=args.skip_merge,
            boundary_mode=args.boundary_mode,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    write_scene_artifact(result, output_path)
    print(
        f"\nDone. method={result.get('method')} boundary={result.get('boundary_mode')} "
        f"segments={len(result.get('segments') or [])} "
        f"frames={result.get('frame_count')} narrative_chars={len(result.get('narrative') or '')}"
    )

    if args.inject_into:
        inject_path = resolve_path(args.inject_into, base=working_dir)
        if not inject_path.is_file():
            print(f"Error: inject target not found: {inject_path}", file=sys.stderr)
            return 1
        dest = inject_scene_into_transcript_file(inject_path, result)
        print(f"Injected scene fields into: {dest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
