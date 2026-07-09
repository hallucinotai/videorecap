"""Resolve per-utterance face crops aligned to the speaking speaker's L2 visual cluster."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np

from modules.enrichment.l2_identity.face_analysis import VideoFrameReader

_CROP_RE = re.compile(r"crop_(\d+)_(u\d+)_([\d.]+)s\.jpg$")

_face_app: Any = None
_CLUSTER_REF_CACHE: dict[str, np.ndarray] = {}
_OBS_BY_CROP: dict[str, dict[str, Any]] = {}


def utterance_face_crop_path(assets_dir: str, utterance_id: str) -> str:
    return os.path.join(assets_dir, "utterance_faces", f"{utterance_id}.jpg")


def _get_face_app() -> Any:
    global _face_app
    if _face_app is not None:
        return _face_app
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    _face_app = app
    return _face_app


def _observation_path(doc: dict[str, Any], ctx: Any) -> Path | None:
    working_dir = getattr(ctx, "working_dir", None)
    if not working_dir:
        return None
    run_name = _run_name(doc, ctx)
    if not run_name:
        return None
    candidate = Path(working_dir) / "output" / "transcriptions" / str(run_name) / "character_observation.json"
    return candidate if candidate.is_file() else None


def _crops_dir(doc: dict[str, Any], ctx: Any) -> Path | None:
    working_dir = getattr(ctx, "working_dir", None)
    if not working_dir:
        return None
    run_name = _run_name(doc, ctx)
    if not run_name:
        return None
    candidate = Path(working_dir) / "output" / "character_crops" / str(run_name)
    return candidate if candidate.is_dir() else None


def _run_name(doc: dict[str, Any], ctx: Any) -> str | None:
    run_name = getattr(ctx, "run_name", None)
    if run_name:
        return str(run_name)
    metadata = doc.get("L0_metadata") or doc.get("metadata") or {}
    return metadata.get("run_name") or metadata.get("video_id")


def _load_crop_observations(doc: dict[str, Any], ctx: Any) -> dict[str, dict[str, Any]]:
    """Map crop filename -> observation row (character_id, timestamp, utterance_id)."""
    global _OBS_BY_CROP
    cache_key = f"{getattr(ctx, 'working_dir', '')}:{_run_name(doc, ctx)}"
    if _OBS_BY_CROP and getattr(_load_crop_observations, "_cache_key", None) == cache_key:
        return _OBS_BY_CROP

    obs_path = _observation_path(doc, ctx)
    crops_dir = _crops_dir(doc, ctx)
    mapping: dict[str, dict[str, Any]] = {}
    if not obs_path or not crops_dir:
        _OBS_BY_CROP = mapping
        _load_crop_observations._cache_key = cache_key
        return mapping

    observations = json.loads(obs_path.read_text()).get("observations") or []
    obs_queue = list(observations)
    for crop_path in sorted(crops_dir.glob("crop_*.jpg")):
        match = _CROP_RE.match(crop_path.name)
        if not match:
            continue
        _idx, uid, ts_text = match.groups()
        ts = float(ts_text)
        while obs_queue:
            obs = obs_queue.pop(0)
            if obs.get("utterance_id") != uid:
                continue
            if abs(float(obs.get("timestamp_sec") or 0) - ts) > 0.06:
                continue
            mapping[crop_path.name] = obs
            break

    _OBS_BY_CROP = mapping
    _load_crop_observations._cache_key = cache_key
    return mapping


def _speaker_cluster_map(doc: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for speaker_id, profile in (doc.get("L2_identity") or {}).items():
        if not speaker_id or str(speaker_id).startswith("_"):
            continue
        cluster_id = (profile.get("face") or {}).get("cluster_id")
        if cluster_id:
            mapping[str(speaker_id)] = str(cluster_id)
    return mapping


def _find_l2_character_sample(
    utterance: dict[str, Any],
    *,
    crop_obs: dict[str, dict[str, Any]],
    speaker_clusters: dict[str, str],
) -> tuple[float, str] | None:
    speaker_id = str(utterance.get("speaker") or "")
    target_cluster = speaker_clusters.get(speaker_id)
    if not target_cluster:
        return None

    uid = str(utterance.get("id") or "")
    start = float(utterance.get("start", 0))
    end = float(utterance.get("end", start))
    target_ts = start + max(0.0, (end - start) / 2.0)

    best_obs: dict[str, Any] | None = None
    best_delta = float("inf")
    for obs in crop_obs.values():
        if obs.get("utterance_id") != uid:
            continue
        if obs.get("character_id") != target_cluster:
            continue
        ts = float(obs.get("timestamp_sec") or 0)
        delta = abs(ts - target_ts)
        if delta < best_delta:
            best_delta = delta
            best_obs = obs
    if best_obs is None:
        return None
    return float(best_obs.get("timestamp_sec") or target_ts), target_cluster


def _extract_face_at_timestamp(
    reader: VideoFrameReader,
    app: Any,
    timestamp: float,
    output_path: str,
    *,
    target_cluster: str | None,
    cluster_refs: dict[str, np.ndarray],
) -> str | None:
    import cv2

    frame = reader.read_at(timestamp)
    if frame is None:
        return None

    faces = app.get(frame)
    if not faces:
        return None

    if target_cluster and target_cluster in cluster_refs:
        ref = cluster_refs[target_cluster]

        def _sim(face: Any) -> float:
            emb = np.asarray(face.embedding, dtype=np.float32)
            denom = float(np.linalg.norm(emb) * np.linalg.norm(ref))
            return float(np.dot(emb, ref) / denom) if denom > 0 else 0.0

        face = max(faces, key=_sim)
    else:
        face = max(faces, key=lambda item: float(getattr(item, "det_score", 0.0)))

    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    h, w = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2]
    if cv2.imwrite(output_path, crop, [cv2.IMWRITE_JPEG_QUALITY, 90]):
        return output_path
    return None


def _load_cluster_references(doc: dict[str, Any], ctx: Any) -> dict[str, np.ndarray]:
    global _CLUSTER_REF_CACHE
    cache_key = f"{getattr(ctx, 'working_dir', '')}:{_run_name(doc, ctx)}"
    if _CLUSTER_REF_CACHE and getattr(_load_cluster_references, "_cache_key", None) == cache_key:
        return _CLUSTER_REF_CACHE

    import cv2

    crops_dir = _crops_dir(doc, ctx)
    crop_obs = _load_crop_observations(doc, ctx)
    cluster_vectors: dict[str, list[np.ndarray]] = {}
    if crops_dir:
        app = _get_face_app()
        for crop_name, obs in crop_obs.items():
            character_id = obs.get("character_id")
            if not character_id:
                continue
            image = cv2.imread(str(crops_dir / crop_name))
            if image is None:
                continue
            faces = app.get(image)
            if not faces:
                continue
            best = max(faces, key=lambda face: float(getattr(face, "det_score", 0.0)))
            cluster_vectors.setdefault(str(character_id), []).append(
                np.asarray(best.embedding, dtype=np.float32)
            )

    refs = {
        character_id: np.mean(np.stack(vectors, axis=0), axis=0)
        for character_id, vectors in cluster_vectors.items()
        if vectors
    }
    _CLUSTER_REF_CACHE = refs
    _load_cluster_references._cache_key = cache_key
    return refs


def extract_speaking_face_crops(
    video_path: str,
    utterances: list[dict[str, Any]],
    *,
    assets_dir: str,
    doc: dict[str, Any] | None = None,
    ctx: Any | None = None,
) -> dict[str, str | None]:
    """Return utterance_id -> face crop path for the speaking speaker."""
    doc = doc or {}
    ctx = ctx or type("Ctx", (), {"working_dir": None, "assets_dir": assets_dir, "run_name": None})()
    crop_obs = _load_crop_observations(doc, ctx)
    speaker_clusters = _speaker_cluster_map(doc)
    cluster_refs = _load_cluster_references(doc, ctx)

    crops: dict[str, str | None] = {}
    os.makedirs(os.path.join(assets_dir, "utterance_faces"), exist_ok=True)

    reader = VideoFrameReader(video_path)
    app = _get_face_app()
    try:
        for utterance in utterances:
            uid = utterance.get("id")
            if not uid:
                continue
            output_path = utterance_face_crop_path(assets_dir, str(uid))
            speaker_id = str(utterance.get("speaker") or "")
            target_cluster = speaker_clusters.get(speaker_id)

            sample = _find_l2_character_sample(
                utterance,
                crop_obs=crop_obs,
                speaker_clusters=speaker_clusters,
            )
            if sample is not None:
                timestamp, cluster = sample
            else:
                start = float(utterance.get("start", 0))
                end = float(utterance.get("end", start))
                timestamp = start + max(0.0, (end - start) / 2.0)
                cluster = target_cluster

            crop_path = _extract_face_at_timestamp(
                reader,
                app,
                timestamp,
                output_path,
                target_cluster=cluster,
                cluster_refs=cluster_refs,
            )
            crops[str(uid)] = crop_path
    finally:
        reader.close()
    return crops


def reset_face_cache() -> None:
    global _face_app, _CLUSTER_REF_CACHE, _OBS_BY_CROP
    _face_app = None
    _CLUSTER_REF_CACHE = {}
    _OBS_BY_CROP = {}
