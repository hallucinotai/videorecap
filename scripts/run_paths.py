"""Per-video output paths for local scripts under scripts/."""

from __future__ import annotations

import re
from pathlib import Path

TRANSCRIPTIONS_ROOT = Path("output") / "transcriptions"
ASSETS_ROOT = Path("output") / "assets"


def sanitize_run_name(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "_", name.strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "untitled"


def run_name_from_video(video_path: Path) -> str:
    return sanitize_run_name(video_path.stem)


def infer_run_name(path: Path, *, working_dir: Path) -> str | None:
    """
    Infer run folder from paths like:
      output/transcriptions/<run>/transcription.json
      output/transcriptions/<run>/layers/enrichment_L1.json
      backend/output/transcriptions/<run>/transcription.json
    """
    resolved = path.resolve()

    transcriptions_root = (working_dir / TRANSCRIPTIONS_ROOT).resolve()
    try:
        rel = resolved.relative_to(transcriptions_root)
        parts = rel.parts
        if parts and parts[0] != "layers":
            return parts[0]
    except ValueError:
        pass

    parts = resolved.parts
    for index, part in enumerate(parts):
        if part != "transcriptions" or index + 1 >= len(parts):
            continue
        candidate = parts[index + 1]
        if candidate != "layers":
            return candidate
    return None


def resolve_run_name(
    *,
    run_name: str | None,
    video_path: Path | None,
    input_path: Path | None,
    working_dir: Path,
) -> str:
    if run_name:
        return sanitize_run_name(run_name)
    if video_path is not None:
        return run_name_from_video(video_path)
    if input_path is not None:
        inferred = infer_run_name(input_path, working_dir=working_dir)
        if inferred:
            return inferred
    raise ValueError(
        "Could not determine run name. Pass --run-name, provide --video, "
        "or use --input under output/transcriptions/<run_name>/..."
    )


def transcriptions_dir(working_dir: Path, run_name: str) -> Path:
    return working_dir / TRANSCRIPTIONS_ROOT / sanitize_run_name(run_name)


def layers_dir(working_dir: Path, run_name: str) -> Path:
    return transcriptions_dir(working_dir, run_name) / "layers"


def raw_transcript_path(working_dir: Path, run_name: str) -> Path:
    return transcriptions_dir(working_dir, run_name) / "transcription.json"


def assets_dir(working_dir: Path, run_name: str) -> Path:
    return working_dir / ASSETS_ROOT / sanitize_run_name(run_name)


def characters_dir(working_dir: Path, run_name: str) -> Path:
    return transcriptions_dir(working_dir, run_name) / "characters"
