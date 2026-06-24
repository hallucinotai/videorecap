"""L3.S2: Visual hints from speaker portraits (low-weight, no face-gender ML in v1)."""

from __future__ import annotations

from typing import Any

from modules.enrichment.composite import SublayerSkipped
from modules.enrichment.document import GENDER_NAME_HINT_CONFIDENCE, deep_copy_doc


class S2VisualHintsEnricher:
    sublayer_id = "S2"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        l2_identity = doc.get("L2_identity") or {}
        l3_gender = doc.get("L3_gender") or {}
        if not l2_identity:
            raise SublayerSkipped("no_l2_identity")

        l3_visual: dict[str, Any] = {}
        for speaker_id, profile in l2_identity.items():
            if speaker_id.startswith("_"):
                continue
            face = profile.get("face") or {}
            if not face.get("portrait_s3_key") and not face.get("portrait_local_path"):
                continue

            text_gender = (l3_gender.get(speaker_id) or {}).get("gender")
            text_conf = float((l3_gender.get(speaker_id) or {}).get("gender_confidence") or 0.0)

            entry: dict[str, Any] = {
                "speaker_id": speaker_id,
                "portrait_s3_key": face.get("portrait_s3_key"),
                "portrait_local_path": face.get("portrait_local_path"),
                "alignment_confidence": face.get("alignment_confidence"),
                "gender": "unknown",
                "gender_confidence": 0.0,
                "gender_evidence": [],
                "gender_source": "visual_v1",
            }

            # v1: only propagate existing text proposals as weak visual alignment, never infer from pixels alone
            if text_gender in ("male", "female") and face.get("alignment_confidence", 0) >= 0.5:
                boost = round(min(text_conf, GENDER_NAME_HINT_CONFIDENCE + 0.1), 2)
                entry["gender"] = text_gender
                entry["gender_confidence"] = boost
                entry["gender_evidence"] = [f"portrait_alignment:{boost:.2f}"]
                entry["thumbnail_s3_key"] = face.get("portrait_s3_key")

            l3_visual[speaker_id] = entry

        if not l3_visual:
            raise SublayerSkipped("no_portraits")

        output = deep_copy_doc(doc)
        output["L3_visual"] = l3_visual
        return output


def s1_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    return {"L3_gender": doc.get("L3_gender") or {}}


def s2_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    return {"L3_visual": doc.get("L3_visual") or {}}
