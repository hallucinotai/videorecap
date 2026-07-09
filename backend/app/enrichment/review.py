"""Apply human review decisions to terminal enrichment documents."""

from __future__ import annotations

import copy
from typing import Any

from modules.enrichment.document import get_review_queue
from modules.enrichment.l4_finalize import (
    _build_attribution_review_queue,
    _build_review_queue,
    _merge_gender_proposals,
    _pronoun_hints_from_profiles,
)

_PRONOUN_FOR_GENDER = {"male": "he", "female": "she"}


def apply_gender_review_decisions(
    doc: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Merge user decisions into speaker_profiles and sync L3_gender.

    Each decision: { speaker_id, action: confirm|override|reject, gender?: male|female|unknown }
    """
    doc = copy.deepcopy(doc)
    speaker_profiles = doc.get("speaker_profiles") or _merge_gender_proposals(doc)
    l3_gender = doc.get("L3_gender") or {}
    narration_context = doc.get("narration_context") or {}
    speakers_compat = doc.get("speakers") or {}

    for decision in decisions:
        speaker_id = decision.get("speaker_id")
        action = decision.get("action")
        profile = speaker_profiles.get(speaker_id)
        if not speaker_id or not profile:
            continue

        gender_block = profile.setdefault(
            "gender",
            {"value": "unknown", "confidence": 0.0, "status": "unknown", "sources": [], "evidence": []},
        )
        l3_entry = l3_gender.setdefault(speaker_id, {"speaker_id": speaker_id})

        if action == "reject":
            gender_block["value"] = "unknown"
            gender_block["confidence"] = 0.0
            gender_block["status"] = "rejected"
            l3_entry["gender"] = "unknown"
            l3_entry["gender_confidence"] = 0.0
            l3_entry["gender_status"] = "rejected"
            l3_entry["requires_review"] = False
            l3_entry["pronoun_hint"] = None
        elif action == "override":
            gender = decision.get("gender", "unknown")
            gender_block["value"] = gender
            gender_block["confidence"] = 1.0
            gender_block["status"] = "confirmed"
            gender_block["evidence"] = list(gender_block.get("evidence") or []) + ["user_override"]
            l3_entry["gender"] = gender
            l3_entry["gender_confidence"] = 1.0
            l3_entry["gender_status"] = "confirmed"
            l3_entry["requires_review"] = False
            l3_entry["pronoun_hint"] = _PRONOUN_FOR_GENDER.get(gender) if gender in _PRONOUN_FOR_GENDER else None
        elif action == "confirm":
            gender_block["status"] = "confirmed"
            gender_block["evidence"] = list(gender_block.get("evidence") or []) + ["user_confirmed"]
            l3_entry["gender_status"] = "confirmed"
            l3_entry["requires_review"] = False
            l3_entry["pronoun_hint"] = _PRONOUN_FOR_GENDER.get(gender_block.get("value", ""))

        if speaker_id in speakers_compat:
            value = gender_block.get("value")
            if value and value != "unknown":
                speakers_compat[speaker_id]["gender"] = value
                speakers_compat[speaker_id]["gender_confidence"] = gender_block.get("confidence", 0)
            elif action == "reject":
                speakers_compat[speaker_id].pop("gender", None)
                speakers_compat[speaker_id].pop("gender_confidence", None)

    review_queue = _build_review_queue(speaker_profiles)
    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
    review_queue.extend(_build_attribution_review_queue(utterances))
    pronoun_hints = _pronoun_hints_from_profiles(speaker_profiles)

    narration_context["pronoun_hints"] = pronoun_hints
    narration_context["review_queue"] = review_queue
    narration_context.pop("gender_review_queue", None)

    doc["speaker_profiles"] = speaker_profiles
    doc["L3_gender"] = l3_gender
    doc["narration_context"] = narration_context
    doc["speakers"] = speakers_compat
    return doc


def apply_attribution_review_decisions(
    doc: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Apply user attribution review decisions on utterances.

    Each decision: {
      utterance_id, action: confirm|reject|override,
      speaker_confirmed?: str (for override)
    }
    """
    doc = copy.deepcopy(doc)
    l1 = doc.setdefault("L1_transcript", {})
    utterances = list(l1.get("utterances") or [])
    by_id = {u.get("id"): u for u in utterances if u.get("id")}

    for decision in decisions:
        uid = decision.get("utterance_id")
        action = decision.get("action")
        row = by_id.get(uid)
        if not row:
            continue
        if action == "confirm":
            row["attribution_status"] = "confirmed"
            row["speaker_confirmed"] = row.get("speaker_predicted")
        elif action == "reject":
            row["attribution_status"] = "rejected"
            row["speaker_confirmed"] = row.get("speaker")
        elif action == "override":
            confirmed = decision.get("speaker_confirmed") or row.get("speaker_predicted")
            row["attribution_status"] = "confirmed"
            row["speaker_confirmed"] = confirmed

    l1["utterances"] = utterances
    doc["L1_transcript"] = l1

    narration_context = doc.get("narration_context") or {}
    review_queue = _build_review_queue(doc.get("speaker_profiles") or _merge_gender_proposals(doc))
    review_queue.extend(_build_attribution_review_queue(utterances))
    narration_context["review_queue"] = review_queue
    doc["narration_context"] = narration_context
    return doc


def review_required(doc: dict[str, Any]) -> bool:
    return len(get_review_queue(doc)) > 0
