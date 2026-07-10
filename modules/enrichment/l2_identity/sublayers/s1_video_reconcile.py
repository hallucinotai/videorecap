"""L2.S1: Observe on-screen characters (continuous tracking with sparse fallback).

SKIPPED — auto-correct "who spoke" from video (scorecard row 5):
  This sublayer must remain observe-only. Do not wire lip sync
  (``face_analysis.find_speaking_face``) or
  ``reconcile.apply_visual_utterance_corrections`` here. Relabeling diarization
  from whoever is on screen collapses speaker labels — on-screen presence is
  not the same as who spoke. Speaker identity stays on audio diarization;
  LP may propose ``speaker_predicted`` for review without overwriting
  ``utterance.speaker`` from vision alone.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from modules.enrichment.composite import SublayerSkipped
from modules.enrichment.document import build_s1_video_artifact, deep_copy_doc, slim_l2_reconciliation
from modules.enrichment.l2_identity.character_observation import (
    annotate_utterances_with_characters,
    build_video_faces_from_observations,
    dominant_character_per_speaker,
    l2_character_observation_summary,
    run_l2_character_observation,
)
from modules.enrichment.l2_identity.continuous_tracking import (
    continuous_tracking_available,
    run_l2_continuous_tracking,
    tracking_mode_from_env,
)

logger = logging.getLogger(__name__)


def _dependency_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "opencv": False,
        "insightface": False,
        "ultralytics": False,
        "supervision": False,
        "errors": {},
    }
    try:
        import cv2  # noqa: F401

        status["opencv"] = True
    except ImportError as exc:
        status["errors"]["opencv"] = str(exc)
    try:
        from insightface.app import FaceAnalysis  # noqa: F401

        status["insightface"] = True
    except ImportError as exc:
        status["errors"]["insightface"] = str(exc)

    continuous = continuous_tracking_available()
    status["ultralytics"] = continuous.get("ultralytics", False)
    status["supervision"] = continuous.get("supervision", False)
    for key, err in (continuous.get("errors") or {}).items():
        if key not in status["errors"]:
            status["errors"][key] = err
    status["continuous_ready"] = bool(continuous.get("ready"))
    return status


def _av_diagnostics(
    doc: dict[str, Any],
    ctx: Any,
    *,
    skip_reason: str | None = None,
    tracking_method: str | None = None,
) -> dict[str, Any]:
    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
    video_path = getattr(ctx, "video_path", None)
    words_count = sum(len(u.get("words") or []) for u in utterances)
    return {
        "status": "skipped" if skip_reason else "ok",
        "skip_reason": skip_reason,
        "tracking_method": tracking_method,
        "tracking_mode_env": tracking_mode_from_env(),
        "video_path": video_path,
        "video_exists": bool(video_path and os.path.isfile(video_path)),
        "video_size_bytes": os.path.getsize(video_path) if video_path and os.path.isfile(video_path) else None,
        "utterance_count": len(utterances),
        "utterances_with_word_timestamps": sum(1 for u in utterances if u.get("words")),
        "word_timestamp_count": words_count,
        "dependencies": _dependency_status(),
        "hint": _skip_hint(skip_reason),
    }


def _skip_hint(skip_reason: str | None) -> str | None:
    if not skip_reason:
        return None
    if skip_reason == "no_video":
        return "Video path was not passed to enrichment — rebuild worker and re-run the job."
    if skip_reason == "opencv_unavailable":
        return "Install opencv-python-headless in the Celery worker image, then restart the worker."
    if skip_reason and skip_reason.startswith("no_faces_detected"):
        return "No faces detected at transcript sample times — check lighting or install insightface for ArcFace."
    if skip_reason == "video_unreadable":
        return "OpenCV could not decode the video file."
    if skip_reason and "continuous_tracking" in skip_reason:
        return (
            "Continuous tracking unavailable — install ultralytics, supervision, insightface, "
            "onnxruntime or set L2_CHARACTER_TRACKING=sparse."
        )
    return "See worker logs for L2.S1 enrichment details."


def _run_sparse(doc: dict[str, Any], video_path: Path):
    return run_l2_character_observation(doc, video_path)


def _run_with_fallback(doc: dict[str, Any], video_path: Path) -> tuple[Any, list, str]:
    """
    Prefer continuous tracking when mode=continuous; fall back to sparse observation.
    Returns (report, face_observations, method_used).
    """
    mode = tracking_mode_from_env()
    if mode == "sparse":
        report, observations = _run_sparse(doc, video_path)
        return report, observations, report.method

    try:
        report, observations = run_l2_continuous_tracking(doc, video_path)
        if observations:
            return report, observations, report.method
        logger.warning("L2.S1 continuous tracking returned no observations; falling back to sparse")
    except Exception as exc:
        logger.warning(
            "L2.S1 continuous tracking failed (%s); falling back to character_observation_v1",
            exc,
        )

    report, observations = _run_sparse(doc, video_path)
    return report, observations, report.method


class S1VideoReconcileEnricher:
    sublayer_id = "S1"

    def on_skip(self, doc: dict[str, Any], ctx: Any, skip_reason: str) -> dict[str, Any]:
        diagnostics = _av_diagnostics(doc, ctx, skip_reason=skip_reason)
        output = deep_copy_doc(doc)
        output["L2_reconciliation"] = slim_l2_reconciliation(
            {
                "method": "character_observation_v1",
                "status": "skipped",
                "skip_reason": skip_reason,
                "diagnostics": diagnostics,
            }
        )
        output["L2_speaker_merge_map"] = {}
        output["L2_video_faces"] = {}
        output["L2_character_observation"] = {}
        logger.warning("L2.S1 character observation skipped: %s | %s", skip_reason, diagnostics.get("hint"))
        return output

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        deps = _dependency_status()
        if not deps["opencv"]:
            raise SublayerSkipped("opencv_unavailable")

        video_path = getattr(ctx, "video_path", None)
        if not video_path or not os.path.isfile(video_path):
            raise SublayerSkipped("no_video")

        utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
        if not utterances:
            raise SublayerSkipped("no_utterances")

        assets_dir = getattr(ctx, "assets_dir", None)
        if not assets_dir:
            raise SublayerSkipped("no_assets_dir")

        all_speaker_ids = sorted({u["speaker"] for u in utterances if u.get("speaker")})
        from modules.enrichment.l2_identity.sampling import sample_timestamps_for_utterance

        sample_points_total = sum(len(sample_timestamps_for_utterance(u)) for u in utterances)

        report, face_observations, method_used = _run_with_fallback(doc, Path(video_path))
        if not face_observations:
            raise SublayerSkipped(f"no_faces_detected:{sample_points_total}_sample_points")

        speaker_to_character = dominant_character_per_speaker(report.speaker_character_votes)
        video_faces = build_video_faces_from_observations(
            face_observations,
            speaker_to_character,
            assets_dir=assets_dir,
            job_id=ctx.job_id,
            ctx=ctx,
        )
        updated_utterances = annotate_utterances_with_characters(utterances, face_observations)

        reconciliation = {
            "method": method_used,
            "status": "ok",
            "diagnostics": _av_diagnostics(doc, ctx, tracking_method=method_used),
            "diarization_speaker_count": report.diarization_speaker_count,
            "character_count_visual": report.character_count_visual,
            "character_count_significant": report.character_count_significant,
            "count_mismatch": report.count_mismatch,
            "visual_cluster_count": report.character_count_visual,
            "canonical_speaker_count": len(all_speaker_ids),
            "sample_points": report.sample_points,
            "faces_sampled": report.faces_sampled,
            "embedding_method": report.embedding_method,
            "speaker_to_character": speaker_to_character,
            "utterances_relabeled": 0,
            "utterances_visual_corrected": 0,
            "utterances_merge_corrected": 0,
            "over_segmentation_corrected": False,
            "mismatch": report.count_mismatch,
        }

        output = deep_copy_doc(doc)
        l1 = dict(output.get("L1_transcript") or {})
        l1["utterances"] = updated_utterances
        output["L1_transcript"] = l1
        output["L2_speaker_merge_map"] = {}
        output["L2_video_faces"] = video_faces
        output["L2_reconciliation"] = reconciliation
        output["L2_character_observation"] = l2_character_observation_summary(report)

        logger.info(
            "L2.S1 %s: %d diarization speakers, %d visual characters, %d samples",
            method_used,
            report.diarization_speaker_count,
            report.character_count_visual,
            report.faces_sampled,
        )
        return output


def s1_artifact(
    doc: dict[str, Any],
    skip_reason: str | None = None,
    ctx: Any | None = None,
) -> dict[str, Any]:
    hint = None
    if skip_reason:
        diagnostics = _av_diagnostics(
            doc,
            ctx or type("C", (), {"video_path": None})(),
            skip_reason=skip_reason,
        )
        hint = diagnostics.get("hint")
    return build_s1_video_artifact(doc, skip_reason=skip_reason, hint=hint)
