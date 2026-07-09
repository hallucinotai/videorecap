"""L3.S3: Per-utterance gender from video frames (Gender-Classifier-Mini)."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any

from modules.enrichment.composite import SublayerSkipped
from modules.enrichment.document import deep_copy_doc, is_real_speaker_id
from modules.enrichment.l3_gender.frame_extractor import extract_speaking_face_crops
from modules.enrichment.l3_gender.sublayers.s1_text_analysis import _aggregate_gender
from modules.enrichment.l3_gender import voice_classifier

logger = logging.getLogger(__name__)


def _resolve_video_path(doc: dict[str, Any], ctx: Any) -> str | None:
    video_path = getattr(ctx, "video_path", None)
    if video_path and os.path.isfile(video_path):
        return video_path

    working_dir = getattr(ctx, "working_dir", None)
    if not working_dir:
        return None

    metadata = doc.get("L0_metadata") or doc.get("metadata") or {}
    run_hint = metadata.get("run_name") or metadata.get("video_id")
    if run_hint:
        candidate = os.path.join(working_dir, "assets", f"{run_hint}.mp4")
        if os.path.isfile(candidate):
            return candidate

    assets_root = os.path.join(working_dir, "assets")
    if os.path.isdir(assets_root):
        for name in sorted(os.listdir(assets_root)):
            if name.endswith(".mp4"):
                return os.path.join(assets_root, name)
    return None


def _build_l3_audio(
    utterances: list[dict[str, Any]],
    votes: dict[str, list[tuple[str, float, str]]],
    utterance_counts: dict[str, int],
    classified_counts: dict[str, int],
) -> dict[str, Any]:
    l3_audio: dict[str, Any] = {}
    speaker_ids = sorted(
        set(votes.keys())
        | set(utterance_counts.keys())
        | {u.get("speaker") for u in utterances if u.get("speaker")}
    )
    for speaker_id in speaker_ids:
        if not speaker_id or str(speaker_id).startswith("_"):
            continue
        aggregated = _aggregate_gender(votes.get(speaker_id, []))
        l3_audio[speaker_id] = {
            "speaker_id": speaker_id,
            "gender": aggregated["gender"],
            "gender_confidence": aggregated["gender_confidence"],
            "gender_evidence": aggregated["gender_evidence"],
            "gender_source": "gender_classifier_mini",
            "gender_status": "proposed",
            "utterance_count": utterance_counts.get(speaker_id, 0),
            "classified_count": classified_counts.get(speaker_id, 0),
        }
    return l3_audio


class S3AudioVoiceEnricher:
    sublayer_id = "S3"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        l1 = doc.get("L1_transcript") or {}
        utterances = l1.get("utterances") or []
        if not utterances:
            raise SublayerSkipped("no_utterances")

        video_path = _resolve_video_path(doc, ctx)
        if not video_path:
            raise SublayerSkipped("no_video")

        if not voice_classifier.torch_available():
            raise SublayerSkipped("torch_unavailable")

        try:
            voice_classifier._get_model()
        except RuntimeError as exc:
            raise SublayerSkipped("model_load_failed") from exc

        assets_dir = getattr(ctx, "assets_dir", None)
        if not assets_dir:
            raise SublayerSkipped("no_assets_dir")

        crops = extract_speaking_face_crops(
            video_path,
            utterances,
            assets_dir=assets_dir,
            doc=doc,
            ctx=ctx,
        )

        votes: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        utterance_counts: dict[str, int] = defaultdict(int)
        classified_counts: dict[str, int] = defaultdict(int)

        enriched_utterances: list[dict[str, Any]] = []
        first_error: str | None = None
        for utterance in utterances:
            row = dict(utterance)
            speaker_id = row.get("speaker") or "Unknown"
            if not str(speaker_id).startswith("_"):
                utterance_counts[speaker_id] += 1

            uid = str(row.get("id") or "")
            frame_path = crops.get(uid)
            if frame_path:
                row["utterance_face_local_path"] = frame_path
                try:
                    gender, confidence = voice_classifier.classify_image(frame_path)
                    row["voice_gender"] = gender
                    row["voice_gender_confidence"] = confidence
                    if gender in ("male", "female") and not str(speaker_id).startswith("_"):
                        votes[speaker_id].append((gender, confidence, f"frame:{uid}"))
                        classified_counts[speaker_id] += 1
                except Exception as exc:
                    if first_error is None:
                        first_error = str(exc)
                    logger.warning("Gender classify failed for %s: %s", uid, exc)
                    row["voice_gender"] = "unknown"
                    row["voice_gender_confidence"] = 0.0
            else:
                row["voice_gender"] = "unknown"
                row["voice_gender_confidence"] = 0.0

            enriched_utterances.append(row)

        l3_audio = _build_l3_audio(
            enriched_utterances,
            votes,
            utterance_counts,
            classified_counts,
        )
        if not any(
            (profile.get("classified_count") or 0) > 0 for profile in l3_audio.values()
        ):
            if first_error:
                logger.error("L3.S3 no classified utterances; first error: %s", first_error)
            raise SublayerSkipped("no_classified_utterances")

        output = deep_copy_doc(doc)
        output["L1_transcript"] = {**(output.get("L1_transcript") or {}), "utterances": enriched_utterances}
        output["L3_audio"] = l3_audio
        return output


def s3_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
    utterance_frames = [
        {
            "id": u.get("id"),
            "speaker": u.get("speaker"),
            "voice_gender": u.get("voice_gender"),
            "voice_gender_confidence": u.get("voice_gender_confidence"),
        }
        for u in utterances
        if u.get("voice_gender") is not None
    ]
    return {
        "L3_audio": {
            speaker_id: profile
            for speaker_id, profile in (doc.get("L3_audio") or {}).items()
            if is_real_speaker_id(speaker_id)
        },
        "utterance_frames": utterance_frames,
    }
