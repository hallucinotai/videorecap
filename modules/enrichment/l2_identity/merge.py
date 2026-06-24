"""Merge L2 sublayer outputs into L2_identity and legacy L2_speakers."""

from __future__ import annotations

from typing import Any

from modules.enrichment.document import deep_copy_doc, l2_speakers_from_identity


def build_l2_identity(doc: dict[str, Any]) -> dict[str, Any]:
    l2_speakers = doc.get("L2_speakers") or {}
    video_faces = doc.get("L2_video_faces") or {}
    reconciliation = doc.get("L2_reconciliation") or {}
    merge_map = doc.get("L2_speaker_merge_map") or {}
    face_clusters = doc.get("L2_face_clusters") or {}

    identity: dict[str, Any] = {}
    for speaker_id, sp in l2_speakers.items():
        face = video_faces.get(speaker_id) or {}
        name = sp.get("name")
        diarization: dict[str, Any] = {
            "utterance_count": sp.get("utterance_count", 0),
            "avg_confidence": sp.get("avg_confidence", 0.0),
            "total_speech_sec": sp.get("total_speech_sec", 0.0),
        }
        merged_from = [
            sid for sid, canonical in merge_map.items() if canonical == speaker_id
        ]
        if merged_from:
            diarization["merged_from"] = sorted(merged_from)
            diarization["original_speaker_ids"] = sorted(merged_from + [speaker_id])

        identity[speaker_id] = {
            "speaker_id": speaker_id,
            "name": {
                "value": name,
                "confidence": sp.get("name_confidence", 0.0),
                "sources": ["S2:text"] if name else [],
                "evidence": sp.get("name_evidence") or [],
                "corrected_from": sp.get("corrected_from") or [],
            },
            "face": {
                "cluster_id": face.get("cluster_id"),
                "visible_ratio": face.get("visible_ratio"),
                "alignment_confidence": face.get("alignment_confidence"),
                "portrait_s3_key": face.get("portrait_s3_key"),
                "portrait_local_path": face.get("portrait_local_path"),
                "frame_timestamp_sec": face.get("frame_timestamp_sec"),
                "visual_cluster_index": face.get("visual_cluster_index"),
            }
            if face
            else None,
            "diarization": diarization,
        }

    if reconciliation:
        identity["_reconciliation"] = reconciliation
    if face_clusters:
        identity["_face_clusters"] = face_clusters
    return identity


def apply_l2_merge(doc: dict[str, Any]) -> dict[str, Any]:
    doc = deep_copy_doc(doc)
    identity = build_l2_identity(doc)
    doc["L2_identity"] = identity
    doc["L2_speakers"] = l2_speakers_from_identity(identity)
    return doc
