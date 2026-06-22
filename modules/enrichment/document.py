"""Shared helpers for enrichment layer documents."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "1.2"
LOW_CONFIDENCE_THRESHOLD = 0.85
GENDER_NARRATION_MIN = 0.75
GENDER_REVIEW_MAX = 0.75
GENDER_NAME_HINT_CONFIDENCE = 0.40


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_timestamp_sec(seconds: float) -> str:
    total = max(0, int(seconds))
    mins, secs = divmod(total, 60)
    return f"{mins}:{secs:02d}"


def truncate_quote(text: str, max_len: int = 80) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def get_review_queue(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """User-facing review queue — only populated by the terminal enrichment layer."""
    narration = doc.get("narration_context") or {}
    return narration.get("review_queue") or narration.get("gender_review_queue") or []


def load_layer_document(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_assemblyai_enhanced(doc: dict[str, Any]) -> bool:
    if not isinstance(doc, dict):
        return False
    metadata = doc.get("metadata") or {}
    if metadata.get("provider") != "assemblyai":
        return False
    return isinstance(doc.get("speakers"), dict) and isinstance(doc.get("segments"), dict)


def init_pipeline_meta(job_id: str, layer_id: str, source_provider: str = "assemblyai") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "layer_id": layer_id,
        "layer_status": {},
        "source_provider": source_provider,
        "processed_at": utc_now_iso(),
    }


def mark_layer_ok(meta: dict[str, Any], layer_id: str) -> None:
    meta.setdefault("layer_status", {})[layer_id] = "ok"
    meta["layer_id"] = layer_id
    meta["processed_at"] = utc_now_iso()


def deep_copy_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(doc)


def segments_dict_to_utterances(segments: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert AssemblyAI segments dict to ordered utterance list with stable IDs."""
    ordered = sorted(
        segments.items(),
        key=lambda item: float(item[1].get("start", 0)),
    )
    utterances = []
    for index, (_seg_id, segment) in enumerate(ordered, start=1):
        utterances.append(
            {
                "id": f"u{index}",
                "start": float(segment.get("start", 0)),
                "end": float(segment.get("end", 0)),
                "text": (segment.get("text") or "").strip(),
                "speaker": segment.get("speaker") or "Unknown",
                "confidence": float(
                    segment.get("speaker_confidence")
                    if segment.get("speaker_confidence") is not None
                    else segment.get("confidence", 0.0)
                ),
            }
        )
    return utterances


def utterances_to_segment_refs(utterances: list[dict[str, Any]]) -> dict[str, Any]:
    """Build lightweight segment index pointing at L1 utterances (no duplicated text/times)."""
    segments: dict[str, Any] = {}
    for index, utterance in enumerate(utterances):
        entry: dict[str, Any] = {
            "utterance_id": utterance["id"],
            "speaker": utterance["speaker"],
            "speaker_confidence": utterance.get("confidence", 0.0),
        }
        if utterance.get("speaker_name"):
            entry["speaker_name"] = utterance["speaker_name"]
        segments[str(index)] = entry
    return segments


def _utterances_index(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    l1 = doc.get("L1_transcript") or {}
    utterances = l1.get("utterances") or []
    return {u["id"]: u for u in utterances if u.get("id")}


def _segment_is_utterance_ref(segment: dict[str, Any]) -> bool:
    return "utterance_id" in segment and "text" not in segment


def resolve_utterance_to_segment(utterance: dict[str, Any], ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """Materialize a flat segment dict from a canonical utterance (+ optional ref overrides)."""
    ref = ref or {}
    seg: dict[str, Any] = {
        "start": float(utterance["start"]),
        "end": float(utterance["end"]),
        "text": utterance.get("text", ""),
        "speaker": ref.get("speaker", utterance.get("speaker")),
        "speaker_confidence": ref.get(
            "speaker_confidence",
            ref.get("confidence", utterance.get("confidence", 0.0)),
        ),
    }
    speaker_name = ref.get("speaker_name") or utterance.get("speaker_name")
    if speaker_name:
        seg["speaker_name"] = speaker_name
    return seg


def utterances_to_segments_dict(utterances: list[dict[str, Any]]) -> dict[str, Any]:
    """Deprecated alias — use utterances_to_segment_refs for enriched layer output."""
    return utterances_to_segment_refs(utterances)


def build_diarization_summary(utterances: list[dict[str, Any]]) -> dict[str, Any]:
    speakers = {u["speaker"] for u in utterances}
    return {
        "speaker_count": len(speakers),
        "utterance_count": len(utterances),
    }


def extract_segments_list(data: Any) -> list[dict[str, Any]]:
    """Extract a flat segment list from raw, enhanced, or enriched transcript JSON."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    utterances_by_id = _utterances_index(data)

    if "segments" in data and isinstance(data["segments"], dict):
        ordered = sorted(data["segments"].items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else 0)
        segments = []
        for _seg_id, segment in ordered:
            if _segment_is_utterance_ref(segment) and utterances_by_id:
                utterance = utterances_by_id.get(segment["utterance_id"])
                if utterance:
                    segments.append(resolve_utterance_to_segment(utterance, segment))
                    continue
            # Legacy/full segment (raw AssemblyAI or older enriched format)
            seg = {
                "start": float(segment.get("start", 0)),
                "end": float(segment.get("end", 0)),
                "text": segment.get("text", ""),
            }
            for key in ("speaker", "speaker_name", "speaker_confidence"):
                if key in segment:
                    seg[key] = segment[key]
            segments.append(seg)
        if segments:
            return segments

    if "segments" in data and isinstance(data["segments"], list):
        return data["segments"]

    l1 = data.get("L1_transcript") or {}
    if l1.get("utterances"):
        return [resolve_utterance_to_segment(u) for u in l1["utterances"]]

    return []


def is_wrapped_transcript(data: Any) -> bool:
    return isinstance(data, dict) and not isinstance(data, list)


def apply_translated_segments_to_document(doc: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Write translated text into canonical L1 utterances (single source of truth)."""
    l1 = doc.get("L1_transcript")
    if l1 and l1.get("utterances"):
        for utterance, seg in zip(l1["utterances"], segments):
            utterance["text"] = seg["text"]
        return doc

    # Legacy enhanced format without L1 — update inline segment text
    if "segments" in doc and isinstance(doc["segments"], dict):
        keys = sorted(
            doc["segments"].keys(),
            key=lambda k: float(doc["segments"][k].get("start", 0)),
        )
        for key, seg in zip(keys, segments):
            if "text" in doc["segments"][key]:
                doc["segments"][key]["text"] = seg["text"]

    return doc
