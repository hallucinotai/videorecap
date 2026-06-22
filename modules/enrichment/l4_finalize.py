"""L4: Terminal enrichment layer — merge proposals, build review queue with presentation."""

from __future__ import annotations

from typing import Any

from modules.enrichment.document import (
    GENDER_NARRATION_MIN,
    deep_copy_doc,
    format_timestamp_sec,
    get_review_queue,
    mark_layer_ok,
    truncate_quote,
    utterances_to_segment_refs,
)

_PRONOUN_FOR_GENDER = {"male": "he", "female": "she"}


def _best_utterance_for_speaker(
    utterances: list[dict[str, Any]], speaker_id: str
) -> dict[str, Any] | None:
    speaker_utts = [u for u in utterances if u.get("speaker") == speaker_id and u.get("text")]
    if not speaker_utts:
        return None
    return max(speaker_utts, key=lambda u: len(u.get("text", "")))


def _build_display_label(
    speaker_id: str,
    l2_info: dict[str, Any] | None,
    utterance: dict[str, Any] | None,
) -> str:
    name = (l2_info or {}).get("name")
    if name:
        return str(name)
    if utterance:
        quote = truncate_quote(utterance.get("text", ""))
        ts = format_timestamp_sec(float(utterance.get("start", 0)))
        return f'Person at {ts} — "{quote}"'
    return f"Speaker {speaker_id}"


def _merge_gender_proposals(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Merge L3 (and future visual) proposals into per-speaker gender view."""
    l3_gender = doc.get("L3_gender") or {}
    l4_visual = doc.get("L4_visual") or {}
    l2_speakers = doc.get("L2_speakers") or {}
    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []

    speaker_ids = sorted(
        set(l2_speakers.keys())
        | set(l3_gender.keys())
        | {u["speaker"] for u in utterances if u.get("speaker")}
    )

    profiles: dict[str, dict[str, Any]] = {}
    for speaker_id in speaker_ids:
        l3 = l3_gender.get(speaker_id) or {}
        visual = l4_visual.get(speaker_id) or {}

        value = l3.get("gender", "unknown")
        confidence = float(l3.get("gender_confidence") or 0.0)
        sources: list[str] = []
        evidence: list[str] = list(l3.get("gender_evidence") or [])

        if value not in (None, "unknown"):
            sources.append("L3:text")

        visual_gender = visual.get("gender")
        visual_conf = float(visual.get("gender_confidence") or 0.0)
        if visual_gender in ("male", "female") and visual_conf > confidence:
            value = visual_gender
            confidence = visual_conf
            sources = ["L4:visual"]
            evidence = list(visual.get("gender_evidence") or evidence)

        if value in ("male", "female") and confidence >= GENDER_NARRATION_MIN:
            status = "auto_accepted"
        elif value in ("male", "female"):
            status = "pending_review"
        else:
            status = "unknown"
            value = "unknown"
            confidence = 0.0

        best_utt = _best_utterance_for_speaker(utterances, speaker_id)
        l2_info = l2_speakers.get(speaker_id) or {}
        presentation: dict[str, Any] = {
            "display_label": _build_display_label(speaker_id, l2_info, best_utt),
            "sample_quote": truncate_quote(best_utt["text"]) if best_utt else None,
            "utterance_id": best_utt.get("id") if best_utt else None,
            "timestamp_sec": float(best_utt["start"]) if best_utt else None,
            "thumbnail_s3_key": visual.get("thumbnail_s3_key"),
            "thumbnail_url": visual.get("thumbnail_url"),
        }

        profiles[speaker_id] = {
            "speaker_id": speaker_id,
            "gender": {
                "value": value,
                "confidence": round(confidence, 2),
                "status": status,
                "sources": sources,
                "evidence": evidence,
            },
            "presentation": presentation,
        }

    return profiles


def _build_review_queue(profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for speaker_id, profile in sorted(profiles.items()):
        gender = profile.get("gender") or {}
        if gender.get("status") != "pending_review":
            continue
        if gender.get("value") in (None, "unknown"):
            continue
        presentation = profile.get("presentation") or {}
        queue.append(
            {
                "speaker_id": speaker_id,
                "field": "gender",
                "proposed": gender["value"],
                "confidence": gender["confidence"],
                "evidence": gender.get("evidence") or [],
                "presentation": presentation,
            }
        )
    return queue


def _pronoun_hints_from_profiles(profiles: dict[str, dict[str, Any]]) -> dict[str, str]:
    hints: dict[str, str] = {}
    for speaker_id, profile in profiles.items():
        gender = profile.get("gender") or {}
        if gender.get("status") not in ("auto_accepted", "confirmed"):
            continue
        value = gender.get("value")
        pronoun = _PRONOUN_FOR_GENDER.get(value or "")
        if pronoun:
            hints[speaker_id] = pronoun
    return hints


class L4FinalizeEnricher:
    """Terminal layer: merge all proposals and build the user-facing review queue."""

    layer_id = "L4"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        speaker_profiles = _merge_gender_proposals(doc)
        review_queue = _build_review_queue(speaker_profiles)
        pronoun_hints = _pronoun_hints_from_profiles(speaker_profiles)

        narration_context = deep_copy_doc(doc.get("narration_context") or {})
        narration_context["pronoun_hints"] = pronoun_hints
        narration_context["review_queue"] = review_queue
        narration_context.pop("gender_review_queue", None)

        metadata = deep_copy_doc(doc.get("metadata") or {})
        metadata["latest_layer"] = self.layer_id
        metadata["enrichment_finalized"] = True

        speakers_compat = deep_copy_doc(doc.get("speakers") or {})
        for speaker_id, profile in speaker_profiles.items():
            gender = profile.get("gender") or {}
            if speaker_id not in speakers_compat:
                speakers_compat[speaker_id] = {"speaker_id": speaker_id}
            if gender.get("value") not in (None, "unknown"):
                speakers_compat[speaker_id]["gender"] = gender["value"]
                speakers_compat[speaker_id]["gender_confidence"] = gender.get("confidence", 0)

        utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
        output = deep_copy_doc(doc)
        pipeline_meta = output.get("pipeline_meta") or {}
        mark_layer_ok(pipeline_meta, self.layer_id)
        output["pipeline_meta"] = pipeline_meta
        output["speaker_profiles"] = speaker_profiles
        output["narration_context"] = narration_context
        output["metadata"] = metadata
        output["speakers"] = speakers_compat
        if "segments" not in output:
            output["segments"] = utterances_to_segment_refs(utterances)

        return output
