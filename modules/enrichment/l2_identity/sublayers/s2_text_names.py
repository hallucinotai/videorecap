"""L2.S2: Speaker names and utterance flags from transcript text (after video reconcile)."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from modules.enrichment.document import (
    LOW_CONFIDENCE_THRESHOLD,
    deep_copy_doc,
    utterances_to_segment_refs,
)

_SELF_INTRO_RE = re.compile(r"[Ii](?:'m| am) ([A-Z][a-z]+)")
_VOCATIVE_END_RE = re.compile(r",\s([A-Z][a-z]+)[.!?]?\s*$")


def _collect_name_evidence(utterances: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for utterance in utterances:
        speaker_id = utterance["speaker"]
        text = utterance["text"]
        for match in _SELF_INTRO_RE.finditer(text):
            counts[speaker_id][match.group(1)] += 2
        voc_end = _VOCATIVE_END_RE.search(text)
        if voc_end:
            name = voc_end.group(1)
            for sid in counts:
                if sid != speaker_id:
                    counts[sid][name] += 1
    return counts


def _resolve_speaker_names(
    utterances: list[dict[str, Any]],
    raw_speakers: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    evidence = _collect_name_evidence(utterances)
    for speaker_id, info in raw_speakers.items():
        if info.get("name"):
            evidence[speaker_id][info["name"]] += 3

    l2_speakers: dict[str, Any] = {}
    speaker_map: dict[str, str] = {}
    all_speaker_ids = sorted({u["speaker"] for u in utterances} | set(raw_speakers.keys()))

    for speaker_id in all_speaker_ids:
        raw = raw_speakers.get(speaker_id, {})
        names_dict = dict(evidence.get(speaker_id, {}))
        name = None
        name_source = None
        name_confidence = 0.0
        corrected_from: list[str] = []

        if names_dict:
            name = max(names_dict, key=names_dict.get)
            top_count = names_dict[name]
            total = sum(names_dict.values())
            name_confidence = round(min(1.0, top_count / max(total, 1)), 2)
            if raw.get("name") and name == raw["name"]:
                name_source = "assemblyai_and_text"
            elif any(
                _SELF_INTRO_RE.search(u["text"]) and name in u["text"]
                for u in utterances
                if u["speaker"] == speaker_id
            ):
                name_source = "self_introduction"
            else:
                name_source = "text_evidence"
            others = [n for n in names_dict if n != name]
            if others:
                corrected_from = others

        speech_sec = sum(u["end"] - u["start"] for u in utterances if u["speaker"] == speaker_id)
        utterance_count = sum(1 for u in utterances if u["speaker"] == speaker_id)
        confidences = [u["confidence"] for u in utterances if u["speaker"] == speaker_id]
        avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
        name_evidence = [f"{n}:{c}" for n, c in sorted(names_dict.items(), key=lambda x: -x[1])]

        l2_speakers[speaker_id] = {
            "speaker_id": speaker_id,
            "name": name,
            "name_source": name_source,
            "name_confidence": name_confidence,
            "name_evidence": name_evidence,
            "corrected_from": corrected_from,
            "total_speech_sec": round(speech_sec, 1),
            "utterance_count": utterance_count,
            "avg_confidence": avg_confidence,
        }
        if name:
            speaker_map[speaker_id] = name

    return l2_speakers, speaker_map


def _build_utterance_flags(utterances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flags = []
    for utterance in utterances:
        if utterance.get("confidence", 1.0) < LOW_CONFIDENCE_THRESHOLD:
            flags.append(
                {
                    "utterance_id": utterance["id"],
                    "low_confidence": True,
                    "reason": f"speaker_confidence < {LOW_CONFIDENCE_THRESHOLD}",
                }
            )
    return flags


def _build_cast_summary(speaker_map: dict[str, str]) -> str:
    if not speaker_map:
        return ""
    parts = [f"{name} (Speaker {sid})" for sid, name in sorted(speaker_map.items())]
    return ", ".join(parts)


class S2TextNamesEnricher:
    sublayer_id = "S2"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        l1 = doc.get("L1_transcript")
        if not l1 or not l1.get("utterances"):
            raise ValueError("L2.S2 requires L1_transcript with utterances")

        raw_speakers = ctx.raw_speakers or {}
        utterances = deep_copy_doc(l1["utterances"])
        l2_speakers, speaker_map = _resolve_speaker_names(utterances, raw_speakers)

        for utterance in utterances:
            speaker_id = utterance["speaker"]
            if speaker_id in speaker_map:
                utterance["speaker_name"] = speaker_map[speaker_id]

        utterance_flags = _build_utterance_flags(utterances)
        cast_summary = _build_cast_summary(speaker_map)
        narration_context = {
            "cast_summary": cast_summary,
            "speaker_map": speaker_map,
        }

        metadata = deep_copy_doc(ctx.raw_metadata or {})
        metadata["enriched"] = True
        metadata["utterances_source"] = "L1_transcript.utterances"
        metadata["segments_format"] = "utterance_refs"

        speakers_compat = {}
        for speaker_id, info in l2_speakers.items():
            speakers_compat[speaker_id] = {
                "speaker_id": speaker_id,
                "name": info.get("name"),
                "total_words": sum(
                    len(u["text"].split()) for u in utterances if u["speaker"] == speaker_id
                ),
                "total_duration_seconds": info["total_speech_sec"],
                "avg_confidence": info["avg_confidence"],
            }
            if info.get("corrected_from"):
                speakers_compat[speaker_id]["corrected_from"] = info["corrected_from"]

        output = deep_copy_doc(doc)
        output["L1_transcript"] = {**(output.get("L1_transcript") or {}), "utterances": utterances}
        output["L2_speakers"] = l2_speakers
        output["L2_utterance_flags"] = utterance_flags
        output["narration_context"] = narration_context
        output["metadata"] = metadata
        output["speakers"] = speakers_compat
        output["segments"] = utterances_to_segment_refs(utterances)
        return output


def s2_artifact(doc: dict[str, Any], skip_reason: str | None = None, ctx: Any | None = None) -> dict[str, Any]:
    sublayer_status = (doc.get("pipeline_meta") or {}).get("sublayer_status") or {}
    s1_status = sublayer_status.get("L2.S1", "")
    return {
        "L2_speakers": doc.get("L2_speakers") or {},
        "L2_utterance_flags": doc.get("L2_utterance_flags") or [],
        "narration_context": doc.get("narration_context") or {},
        "video_reconcile_status": s1_status,
        "note": (
            "Video reconcile did not run — speaker labels are uncorrected AssemblyAI diarization."
            if s1_status.startswith("skipped:")
            else None
        ),
    }
