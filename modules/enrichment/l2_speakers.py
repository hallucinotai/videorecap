"""L2: Speaker identity enrichment and utterance confidence flagging."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from modules.enrichment.document import (
    LOW_CONFIDENCE_THRESHOLD,
    deep_copy_doc,
    mark_layer_ok,
    utterances_to_segment_refs,
)

_SELF_INTRO_RE = re.compile(r"[Ii](?:'m| am) ([A-Z][a-z]+)")
_VOCATIVE_START_RE = re.compile(r"^([A-Z][a-z]+),\s")
_VOCATIVE_END_RE = re.compile(r",\s([A-Z][a-z]+)[.!?]?\s*$")


def _collect_name_evidence(utterances: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Map speaker_id -> name -> mention count with evidence types."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for utterance in utterances:
        speaker_id = utterance["speaker"]
        text = utterance["text"]

        for match in _SELF_INTRO_RE.finditer(text):
            counts[speaker_id][match.group(1)] += 2  # self-intro weighted higher

        voc_start = _VOCATIVE_START_RE.match(text)
        if voc_start:
            # Name at start likely addresses another speaker — skip assigning to current speaker
            pass

        voc_end = _VOCATIVE_END_RE.search(text)
        if voc_end:
            name = voc_end.group(1)
            # "Thank you, James" — assign to addressed speaker if known later; for now boost via cross-ref
            for sid in counts:
                if sid != speaker_id:
                    counts[sid][name] += 1

    return counts


def _resolve_speaker_names(
    utterances: list[dict[str, Any]],
    raw_speakers: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    evidence = _collect_name_evidence(utterances)

    # Seed from AssemblyAI raw speaker names
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
            elif any(_SELF_INTRO_RE.search(u["text"]) and name in u["text"] for u in utterances if u["speaker"] == speaker_id):
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


class L2SpeakerEnricher:
    layer_id = "L2"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        l1 = doc.get("L1_transcript")
        if not l1 or not l1.get("utterances"):
            raise ValueError("L2 requires L1_transcript with utterances")

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

        # Compatibility shim for existing pipeline readers
        metadata = deep_copy_doc(ctx.raw_metadata or {})
        metadata["enriched"] = True
        metadata["latest_layer"] = self.layer_id
        metadata["speaker_diarization_enabled"] = True
        metadata["utterances_source"] = "L1_transcript.utterances"
        metadata["segments_format"] = "utterance_refs"

        speakers_compat = {}
        for speaker_id, info in l2_speakers.items():
            speakers_compat[speaker_id] = {
                "speaker_id": speaker_id,
                "name": info.get("name"),
                "total_words": sum(
                    len(u["text"].split())
                    for u in utterances
                    if u["speaker"] == speaker_id
                ),
                "total_duration_seconds": info["total_speech_sec"],
                "avg_confidence": info["avg_confidence"],
            }
            if info.get("corrected_from"):
                speakers_compat[speaker_id]["corrected_from"] = info["corrected_from"]

        segment_refs = utterances_to_segment_refs(utterances)

        output = deep_copy_doc(doc)
        pipeline_meta = output.get("pipeline_meta") or {}
        mark_layer_ok(pipeline_meta, self.layer_id)
        output["pipeline_meta"] = pipeline_meta

        # Canonical text lives only in L1 utterances
        output["L1_transcript"] = {
            **(output.get("L1_transcript") or {}),
            "utterances": utterances,
        }
        output["L2_speakers"] = l2_speakers
        output["L2_utterance_flags"] = utterance_flags
        output["narration_context"] = narration_context
        output["metadata"] = metadata
        output["speakers"] = speakers_compat
        output["segments"] = segment_refs

        return output
