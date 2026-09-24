"""Shared helpers for enrichment layer documents."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "1.4"
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


def mark_sublayer_ok(
    meta: dict[str, Any],
    layer_id: str,
    sublayer_id: str,
    status: str = "ok",
) -> None:
    meta.setdefault("sublayer_status", {})[f"{layer_id}.{sublayer_id}"] = status


def is_real_speaker_id(speaker_id: str) -> bool:
    return bool(speaker_id) and not str(speaker_id).startswith("_")


def real_speaker_ids(mapping: dict[str, Any]) -> list[str]:
    return sorted(k for k in mapping if is_real_speaker_id(k))


def language_code_from_doc(doc: dict[str, Any]) -> str:
    meta = doc.get("L0_metadata") or doc.get("metadata") or {}
    return str(meta.get("language_code") or "en")


def build_utterance_speaker_correction(
    *,
    from_speaker: str,
    to_speaker: str,
    method: str,
    sublayer: str = "S1",
    layer: str = "L2",
    **extra: Any,
) -> dict[str, Any]:
    correction: dict[str, Any] = {
        "layer": layer,
        "sublayer": sublayer,
        "method": method,
        "from_speaker": from_speaker,
        "to_speaker": to_speaker,
    }
    correction.update(extra)
    return correction


def corrected_utterance_refs(utterances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lightweight utterance rows for sublayer artifacts (corrections only)."""
    refs: list[dict[str, Any]] = []
    for utterance in utterances:
        if not utterance.get("speaker_original") and not utterance.get("speaker_correction"):
            continue
        row: dict[str, Any] = {
            "id": utterance.get("id"),
            "speaker": utterance.get("speaker"),
            "speaker_original": utterance.get("speaker_original"),
        }
        if utterance.get("speaker_correction"):
            row["speaker_correction"] = utterance["speaker_correction"]
        refs.append(row)
    return refs


def build_s1_video_artifact(
    doc: dict[str, Any],
    *,
    skip_reason: str | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    """Clean L2.S1 sublayer download artifact (no av_samples / intermediate face blobs)."""
    reconciliation = slim_l2_reconciliation(doc.get("L2_reconciliation") or {})
    if skip_reason and not reconciliation:
        reconciliation = {"status": "skipped", "skip_reason": skip_reason}
        if hint:
            reconciliation["hint"] = hint

    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
    artifact: dict[str, Any] = {
        "status": reconciliation.get("status", "ok" if not skip_reason else "skipped"),
        "L2_reconciliation": reconciliation,
        "L2_character_observation": doc.get("L2_character_observation") or {},
        "corrected_utterances": corrected_utterance_refs(utterances),
        "utterance_count": len(utterances),
    }
    if skip_reason:
        artifact["skip_reason"] = skip_reason
    if reconciliation.get("hint"):
        artifact["hint"] = reconciliation["hint"]
    return strip_local_asset_paths(artifact)


def slim_l2_reconciliation(reconciliation: dict[str, Any]) -> dict[str, Any]:
    """Keep run-level reconciliation summary without per-sample debug fields."""
    if not reconciliation:
        return {}
    slim: dict[str, Any] = {
        "method": reconciliation.get("method"),
        "status": reconciliation.get("status"),
    }
    if reconciliation.get("skip_reason"):
        slim["skip_reason"] = reconciliation["skip_reason"]
        diagnostics = reconciliation.get("diagnostics") or {}
        if diagnostics.get("hint"):
            slim["hint"] = diagnostics["hint"]
    for key in (
        "diarization_speaker_count",
        "canonical_speaker_count",
        "visual_cluster_count",
        "character_count_visual",
        "character_count_significant",
        "count_mismatch",
        "utterances_relabeled",
        "utterances_visual_corrected",
        "utterances_merge_corrected",
        "over_segmentation_corrected",
        "faces_sampled",
        "sample_points",
        "embedding_method",
    ):
        if key in reconciliation:
            slim[key] = reconciliation[key]
    return slim


def strip_local_asset_paths(value: Any) -> Any:
    """Remove worker-local paths from nested dicts/lists before persisting layer JSON."""
    if isinstance(value, dict):
        cleaned = {k: strip_local_asset_paths(v) for k, v in value.items()}
        cleaned.pop("portrait_local_path", None)
        cleaned.pop("audio_clip_local_path", None)
        cleaned.pop("utterance_frame_local_path", None)
        cleaned.pop("utterance_face_local_path", None)
        return cleaned
    if isinstance(value, list):
        return [strip_local_asset_paths(item) for item in value]
    return value


def prune_l2_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Drop intermediate L2 debug fields from persisted layer output."""
    for key in (
        "L2_av_samples",
        "L2_video_faces",
        "L2_face_clusters",
        "L2_speaker_merge_map",
        "L2_utterance_flags",
    ):
        doc.pop(key, None)

    reconciliation = doc.get("L2_reconciliation")
    if reconciliation:
        doc["L2_reconciliation"] = slim_l2_reconciliation(reconciliation)

    l1 = doc.get("L1_transcript") or {}
    speaker_correction = l1.get("speaker_correction")
    if isinstance(speaker_correction, dict):
        speaker_correction.pop("visual_corrections", None)

    identity = doc.get("L2_identity") or {}
    doc["L2_identity"] = {
        speaker_id: profile
        for speaker_id, profile in identity.items()
        if is_real_speaker_id(speaker_id)
    }

    return strip_local_asset_paths(doc)


def prune_lp_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Drop verbose LP debug fields from persisted layer output."""
    lp_text = doc.get("LP_text") or {}
    if lp_text:
        doc["LP_text"] = {
            "method": lp_text.get("method"),
            "model": lp_text.get("model"),
            "utterances": lp_text.get("utterances") or {},
            "speakers": lp_text.get("speakers") or {},
        }
    lp_visual = doc.get("LP_visual") or {}
    if lp_visual:
        doc["LP_visual"] = {
            "method": lp_visual.get("method"),
            "count_mismatch": lp_visual.get("count_mismatch"),
            "utterances": lp_visual.get("utterances") or {},
            "char_to_speaker": lp_visual.get("char_to_speaker") or {},
        }
    return strip_local_asset_paths(doc)


def prune_l3_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Drop phantom speaker keys from L3 output files (L3_visual/L3_audio kept until L4)."""
    l3_gender = doc.get("L3_gender") or {}
    doc["L3_gender"] = {
        speaker_id: profile
        for speaker_id, profile in l3_gender.items()
        if is_real_speaker_id(speaker_id)
    }
    l3_audio = doc.get("L3_audio") or {}
    doc["L3_audio"] = {
        speaker_id: profile
        for speaker_id, profile in l3_audio.items()
        if is_real_speaker_id(speaker_id)
    }
    return strip_local_asset_paths(doc)


def prune_l4_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Terminal cleanup — keep utterances + speaker_profiles, drop stale debug shells."""
    for key in (
        "L2_av_samples",
        "L2_video_faces",
        "L2_face_clusters",
        "L2_speaker_merge_map",
        "L2_utterance_flags",
        "LP_text",
        "LP_visual",
        "L3_visual",
        "L3_audio",
        "L0_metadata",
    ):
        doc.pop(key, None)

    reconciliation = doc.get("L2_reconciliation")
    if reconciliation:
        doc["L2_reconciliation"] = slim_l2_reconciliation(reconciliation)

    l3_gender = doc.get("L3_gender") or {}
    doc["L3_gender"] = {
        speaker_id: profile
        for speaker_id, profile in l3_gender.items()
        if is_real_speaker_id(speaker_id)
    }

    identity = doc.get("L2_identity") or {}
    doc["L2_identity"] = {
        speaker_id: profile
        for speaker_id, profile in identity.items()
        if is_real_speaker_id(speaker_id)
    }

    narration = doc.get("narration_context") or {}
    if (
        not narration.get("cast_summary")
        and not narration.get("speaker_map")
        and not narration.get("review_queue")
        and not narration.get("pronoun_hints")
        and not narration.get("scene_summary")
        and not narration.get("scene_segments")
    ):
        doc.pop("narration_context", None)
    elif narration.get("speaker_map") == {}:
        narration.pop("speaker_map", None)
        doc["narration_context"] = narration

    return strip_local_asset_paths(doc)


def l2_speakers_from_identity(l2_identity: dict[str, Any]) -> dict[str, Any]:
    """Build legacy L2_speakers block from L2_identity."""
    speakers: dict[str, Any] = {}
    for speaker_id, profile in l2_identity.items():
        if not is_real_speaker_id(speaker_id):
            continue
        name_block = profile.get("name") or {}
        diar = profile.get("diarization") or {}
        speakers[speaker_id] = {
            "speaker_id": speaker_id,
            "name": name_block.get("value"),
            "name_source": "identity" if name_block.get("value") else None,
            "name_confidence": name_block.get("confidence", 0.0),
            "name_evidence": name_block.get("evidence") or [],
            "corrected_from": name_block.get("corrected_from") or [],
            "total_speech_sec": diar.get("total_speech_sec", 0.0),
            "utterance_count": diar.get("utterance_count", 0),
            "avg_confidence": diar.get("avg_confidence", 0.0),
        }
    return speakers


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
        utterance: dict[str, Any] = {
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
        if segment.get("words"):
            utterance["words"] = segment["words"]
        utterances.append(utterance)
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
