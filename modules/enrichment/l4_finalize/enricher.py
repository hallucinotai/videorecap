"""L4: Terminal enrichment layer — merge proposals, build review queue with presentation."""

from __future__ import annotations

from typing import Any

from modules.enrichment.document import (
    GENDER_NARRATION_MIN,
    deep_copy_doc,
    format_timestamp_sec,
    mark_layer_ok,
    prune_l4_document,
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


def _speaker_display_name(
    speaker_id: str,
    l2_info: dict[str, Any] | None,
    identity: dict[str, Any] | None,
) -> str | None:
    if identity:
        name = (identity.get("name") or {}).get("value")
        if name:
            return str(name)
    if l2_info and l2_info.get("name"):
        return str(l2_info["name"])
    return None


def _build_display_label(
    speaker_id: str,
    l2_info: dict[str, Any] | None,
    identity: dict[str, Any] | None,
    utterance: dict[str, Any] | None,
) -> str:
    name = _speaker_display_name(speaker_id, l2_info, identity)
    if name:
        return name
    if utterance:
        quote = truncate_quote(utterance.get("text", ""))
        ts = format_timestamp_sec(float(utterance.get("start", 0)))
        return f'Person at {ts} — "{quote}"'
    return f"Speaker {speaker_id}"


def _merge_gender_proposals(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    l3_gender = doc.get("L3_gender") or {}
    l3_visual = doc.get("L3_visual") or {}
    l3_audio = doc.get("L3_audio") or {}
    l2_speakers = doc.get("L2_speakers") or {}
    l2_identity = doc.get("L2_identity") or {}
    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []

    speaker_ids = sorted(
        set(l2_speakers.keys())
        | set(l3_gender.keys())
        | set(l3_audio.keys())
        | set(l2_identity.keys())
        | {u["speaker"] for u in utterances if u.get("speaker")}
    )

    profiles: dict[str, dict[str, Any]] = {}
    for speaker_id in speaker_ids:
        if speaker_id.startswith("_"):
            continue
        l3 = l3_gender.get(speaker_id) or {}
        visual = l3_visual.get(speaker_id) or {}
        audio = l3_audio.get(speaker_id) or {}
        identity = l2_identity.get(speaker_id) or {}
        face = identity.get("face") or {}

        value = l3.get("gender", "unknown")
        confidence = float(l3.get("gender_confidence") or 0.0)
        sources: list[str] = []
        evidence: list[str] = list(l3.get("gender_evidence") or [])
        text_value = value if value in ("male", "female") else None
        text_conf = confidence if text_value else 0.0

        if value not in (None, "unknown"):
            sources.append("L3:text")

        visual_gender = visual.get("gender")
        visual_conf = float(visual.get("gender_confidence") or 0.0)
        if (
            visual_gender in ("male", "female")
            and visual_conf > 0
            and visual_conf > confidence
            and value == visual_gender
        ):
            confidence = visual_conf
            sources = list(set(sources + ["L3:visual"]))
            evidence = list(visual.get("gender_evidence") or evidence)

        audio_gender = audio.get("gender")
        audio_conf = float(audio.get("gender_confidence") or 0.0)
        audio_known = audio_gender in ("male", "female") and audio_conf > 0
        text_known = text_value in ("male", "female") and text_conf > 0

        if audio_known:
            if not text_known and value in (None, "unknown"):
                value = audio_gender
                confidence = audio_conf
                sources = ["L3:audio"]
                evidence = list(audio.get("gender_evidence") or [])
            elif audio_gender == value:
                confidence = round(min(1.0, max(confidence, audio_conf)), 2)
                sources = list(set(sources + ["L3:audio"]))
                evidence = list(dict.fromkeys(evidence + list(audio.get("gender_evidence") or [])))
            elif text_known and audio_gender != text_value:
                value = text_value
                confidence = text_conf
                if "L3:text" not in sources:
                    sources.append("L3:text")
                evidence = list(
                    dict.fromkeys(
                        evidence
                        + [f"text:{text_value}:{text_conf:.2f}", f"audio:{audio_gender}:{audio_conf:.2f}"]
                    )
                )

        if value in ("male", "female") and confidence >= GENDER_NARRATION_MIN:
            status = "auto_accepted"
        elif value in ("male", "female"):
            status = "pending_review"
        else:
            status = "unknown"
            value = "unknown"
            confidence = 0.0

        if text_known and audio_known and audio_gender != text_value:
            status = "pending_review"

        best_utt = _best_utterance_for_speaker(utterances, speaker_id)
        l2_info = l2_speakers.get(speaker_id) or {}
        portrait_key = face.get("portrait_s3_key") or visual.get("portrait_s3_key")
        presentation: dict[str, Any] = {
            "display_label": _build_display_label(speaker_id, l2_info, identity, best_utt),
            "sample_quote": truncate_quote(best_utt["text"]) if best_utt else None,
            "utterance_id": best_utt.get("id") if best_utt else None,
            "timestamp_sec": float(best_utt["start"]) if best_utt else None,
            "thumbnail_s3_key": portrait_key,
            "thumbnail_url": None,
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
                "type": "gender",
                "speaker_id": speaker_id,
                "field": "gender",
                "proposed": gender["value"],
                "confidence": gender["confidence"],
                "evidence": gender.get("evidence") or [],
                "presentation": presentation,
            }
        )
    return queue


def _build_attribution_review_queue(utterances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for utterance in utterances:
        if utterance.get("attribution_status") != "pending_review":
            continue
        speaker = utterance.get("speaker")
        predicted = utterance.get("speaker_predicted")
        if not speaker or not predicted or speaker == predicted:
            continue
        queue.append(
            {
                "type": "attribution",
                "utterance_id": utterance.get("id"),
                "speaker_id": speaker,
                "field": "speaker",
                "proposed": predicted,
                "character_predicted": utterance.get("character_predicted"),
                "confidence": utterance.get("attribution_confidence", 0.0),
                "evidence": utterance.get("attribution_evidence") or [],
                "presentation": {
                    "display_label": f"Utterance {utterance.get('id')}",
                    "sample_quote": truncate_quote(utterance.get("text", "")),
                    "utterance_id": utterance.get("id"),
                    "timestamp_sec": float(utterance.get("start", 0)),
                },
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
    layer_id = "L4"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        speaker_profiles = _merge_gender_proposals(doc)
        utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
        review_queue = _build_review_queue(speaker_profiles)
        review_queue.extend(_build_attribution_review_queue(utterances))
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

        return prune_l4_document(output)
