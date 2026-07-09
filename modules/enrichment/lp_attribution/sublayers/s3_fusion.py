"""LP.S3: Fuse text + visual signals into final speaker/character predictions."""

from __future__ import annotations

from typing import Any

from modules.enrichment.composite import SublayerSkipped
from modules.enrichment.document import build_utterance_speaker_correction, deep_copy_doc
from modules.enrichment.lp_attribution.fusion import (
    build_speaker_merge_suggestions,
    character_for_speaker,
    fuse_speaker_prediction,
)


class S3FusionEnricher:
    sublayer_id = "S3"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
        if not utterances:
            raise SublayerSkipped("no_utterances")

        lp_text = doc.get("LP_text") or {}
        lp_visual = doc.get("LP_visual") or {}
        l2_obs = doc.get("L2_character_observation") or {}
        l2_identity = doc.get("L2_identity") or {}
        speaker_character_votes = l2_obs.get("speaker_character_votes") or {}
        count_mismatch = bool(
            lp_visual.get("count_mismatch") or l2_obs.get("count_mismatch")
        )

        text_by_id = lp_text.get("utterances") or {}
        visual_by_id = lp_visual.get("utterances") or {}

        pending_count = 0
        enriched_utterances: list[dict[str, Any]] = []
        fusion_rows: dict[str, Any] = {}

        for utterance in utterances:
            row = dict(utterance)
            uid = str(row.get("id") or "")
            diarization = str(row.get("speaker") or "")

            text_row = text_by_id.get(uid) or {}
            visual_row = visual_by_id.get(uid) or {}
            llm_speaker = text_row.get("speaker_hint")
            visual_speaker = visual_row.get("speaker_visual")

            predicted, confidence, evidence = fuse_speaker_prediction(
                diarization_speaker=diarization,
                llm_speaker=llm_speaker,
                visual_speaker=visual_speaker,
                count_mismatch=count_mismatch,
            )

            character_predicted = character_for_speaker(
                predicted, l2_identity, speaker_character_votes
            )
            if not character_predicted:
                character_predicted = visual_row.get("character_visual")

            if text_row.get("text_evidence"):
                evidence.append(f"llm:{text_row['text_evidence'][:60]}")
            for item in visual_row.get("visual_evidence") or []:
                evidence.append(f"visual:{item}")

            if predicted != diarization:
                status = "pending_review"
                pending_count += 1
                row["attribution_correction"] = build_utterance_speaker_correction(
                    from_speaker=diarization,
                    to_speaker=predicted,
                    method="multimodal_fusion",
                    layer="LP",
                    sublayer="S3",
                    confidence=confidence,
                )
            else:
                status = "proposed"

            row["speaker_predicted"] = predicted
            if character_predicted:
                row["character_predicted"] = character_predicted
            row["attribution_confidence"] = confidence
            row["attribution_status"] = status
            row["attribution_evidence"] = evidence

            fusion_rows[uid] = {
                "speaker_predicted": predicted,
                "character_predicted": character_predicted,
                "attribution_confidence": confidence,
                "attribution_status": status,
            }
            enriched_utterances.append(row)

        merge_suggestions = build_speaker_merge_suggestions(
            l2_identity, speaker_character_votes
        )

        lp_character_profiles: dict[str, Any] = {}
        for speaker_id, profile in (lp_text.get("speakers") or {}).items():
            char_id = character_for_speaker(
                speaker_id, l2_identity, speaker_character_votes
            )
            key = char_id or speaker_id
            lp_character_profiles[key] = {
                **profile,
                "speaker_id": speaker_id,
                "character_id": char_id,
            }

        output = deep_copy_doc(doc)
        output["L1_transcript"] = {
            **(output.get("L1_transcript") or {}),
            "utterances": enriched_utterances,
        }
        output["LP_attribution"] = {
            "method": "multimodal_fusion_v1",
            "count_mismatch": count_mismatch,
            "pending_review_count": pending_count,
            "speaker_merge_suggestions": merge_suggestions,
            "utterances": fusion_rows,
        }
        output["LP_character_profiles"] = lp_character_profiles
        return output


def s3_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "LP_attribution": doc.get("LP_attribution") or {},
        "LP_character_profiles": doc.get("LP_character_profiles") or {},
    }
