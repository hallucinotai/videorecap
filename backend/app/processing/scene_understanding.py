"""Service wrapper for GPT-4o scene understanding (pre-recap)."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)


def run_scene_understanding_service(
    video_path: str,
    transcript_path: str,
    working_dir: str,
    *,
    progress_callback: Callable | None = None,
) -> dict[str, Any]:
    """
    Run scene understanding and inject fields into the transcript JSON.

    Returns:
      {
        skipped: bool,
        skip_reason?: str,
        scene_artifact_path?: str,
        transcript_path: str,  # possibly updated in place
        scene_result?: dict,
      }
    """
    from modules.scene_understanding import (
        inject_scene_into_transcript_file,
        run_scene_understanding,
        scene_understanding_enabled,
        write_scene_artifact,
    )

    if not scene_understanding_enabled():
        return {
            "skipped": True,
            "skip_reason": "disabled",
            "transcript_path": transcript_path,
        }

    if not video_path or not os.path.isfile(video_path):
        return {
            "skipped": True,
            "skip_reason": "no_video",
            "transcript_path": transcript_path,
        }

    if not transcript_path or not os.path.isfile(transcript_path):
        return {
            "skipped": True,
            "skip_reason": "no_transcript",
            "transcript_path": transcript_path,
        }

    if progress_callback:
        progress_callback(step=3, message="Analyzing visual scenes for recap…")

    try:
        scene_result = run_scene_understanding(video_path)
    except Exception as exc:
        logger.warning("Scene understanding failed (%s); continuing without scene context", exc)
        return {
            "skipped": True,
            "skip_reason": f"failed:{exc}",
            "transcript_path": transcript_path,
        }

    artifact_dir = os.path.join(working_dir, "output", "transcriptions")
    os.makedirs(artifact_dir, exist_ok=True)
    artifact_path = os.path.join(artifact_dir, "scene_understanding.json")
    write_scene_artifact(scene_result, artifact_path)

    updated_transcript = inject_scene_into_transcript_file(transcript_path, scene_result)

    if progress_callback:
        progress_callback(step=3, message="Scene understanding complete")

    logger.info(
        "Scene understanding: %d segments, narrative_chars=%d → %s",
        len(scene_result.get("segments") or []),
        len(scene_result.get("narrative") or ""),
        artifact_path,
    )

    return {
        "skipped": False,
        "scene_artifact_path": artifact_path,
        "transcript_path": str(updated_transcript),
        "scene_result": scene_result,
    }
