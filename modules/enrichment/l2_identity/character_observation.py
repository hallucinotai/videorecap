"""Observe distinct video characters from L1 utterance sample points (no speaker merge)."""

from __future__ import annotations

import base64
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from modules.enrichment.l2_identity.face_analysis import VideoFrameReader, detect_faces
from modules.enrichment.l2_identity.reconcile import face_histogram_embedding
from modules.enrichment.l2_identity.sampling import sample_timestamps_for_utterance


# ArcFace: same person is usually >=0.45; fragments across angles/lighting can be ~0.35–0.42.
ARCFACE_MATCH_THRESHOLD = 0.38
ARCFACE_MERGE_THRESHOLD = 0.36
HISTOGRAM_MATCH_THRESHOLD = 0.90
HISTOGRAM_MERGE_THRESHOLD = 0.88
APPEARANCE_MERGE_THRESHOLD = 0.86
APPEARANCE_STRONG_MERGE = 0.92
MIN_FACE_DETECTION_CONFIDENCE = 0.72
MIN_FACE_BBOX_PX = 36
MIN_PORTRAIT_CONFIDENCE = 0.80
FRAGMENT_CLUSTER_RATIO = 0.45

APPEARANCE_SCHEMA_PROMPT = """You analyze a single person visible in a video frame crop.
Return ONLY valid JSON (no markdown) with these keys:
{
  "hair_color": "string or unknown",
  "hair_style": "string or unknown",
  "dress_type": "string or unknown",
  "dress_color": "string or unknown",
  "gender_presentation": "male|female|unknown",
  "face": "brief face description or unknown",
  "eyes": "brief or unknown",
  "hands": "visible|not visible|unknown",
  "distinctive_features": "short phrase or empty",
  "visibility": "face_only|upper_body|partial|unknown"
}
Describe only what is clearly visible. Do not guess dialogue or names."""


@dataclass
class FaceObservation:
    utterance_id: str
    aai_speaker: str
    timestamp_sec: float
    sample_method: str | None
    chunk_text: str | None
    face_index: int
    detection_confidence: float
    faces_in_frame: int
    embedding: np.ndarray
    embedding_method: str
    crop_jpeg_base64: str | None = None
    face_bbox: tuple[int, int, int, int] | None = None
    appearance_signature: np.ndarray | None = None
    character_id: str | None = None


@dataclass
class CharacterObservationReport:
    method: str
    diarization_speaker_count: int
    diarization_speaker_ids: list[str]
    character_count_visual: int
    character_count_significant: int
    min_cluster_samples: int
    count_mismatch: bool
    embedding_method: str
    sample_points: int
    faces_sampled: int
    characters: dict[str, Any]
    observations: list[dict[str, Any]]
    speaker_character_votes: dict[str, dict[str, float]]
    appearance_model: str | None = None
    characters_assets_dir: str | None = None


def load_l1_document(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"Expected JSON object: {path}")
    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
    if not utterances:
        raise ValueError(f"No L1_transcript.utterances in {path}")
    return doc


def _setup_arcface():
    try:
        from insightface.app import FaceAnalysis
    except ImportError:
        return None
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


def _embed_face(crop_bgr: Any, arcface_app: Any | None) -> tuple[np.ndarray | None, str]:
    if arcface_app is not None:
        faces = arcface_app.get(crop_bgr)
        if faces:
            best = max(faces, key=lambda f: float(getattr(f, "det_score", 0.0)))
            emb = np.asarray(best.normed_embedding, dtype=np.float32)
            return emb, "arcface"
        return None, "arcface"
    emb = face_histogram_embedding(crop_bgr)
    if emb is not None:
        return emb, "histogram"
    return None, "none"


def _passes_face_quality_gate(
    confidence: float,
    bbox: tuple[int, int, int, int],
) -> bool:
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    height = y2 - y1
    if width < MIN_FACE_BBOX_PX or height < MIN_FACE_BBOX_PX:
        return False
    if confidence < MIN_FACE_DETECTION_CONFIDENCE:
        return False
    ratio = width / height if height else 0.0
    return 0.55 <= ratio <= 1.6


def _appearance_signature(crop_bgr: Any) -> np.ndarray | None:
    """HSV histogram signature for hair (upper band) and skin (center band)."""
    import cv2

    if crop_bgr is None or crop_bgr.size == 0:
        return None
    height, width = crop_bgr.shape[:2]
    if height < 20 or width < 20:
        return None

    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    hair = hsv[0 : max(1, height // 3), :]
    skin = hsv[height // 4 : min(height, (3 * height) // 4), width // 4 : (3 * width) // 4]
    parts: list[np.ndarray] = []
    for region in (hair, skin):
        region_hist: list[np.ndarray] = []
        for channel, max_value in ((0, 180), (1, 256), (2, 256)):
            hist = cv2.calcHist([region], [channel], None, [16], [0, max_value])
            cv2.normalize(hist, hist)
            region_hist.append(hist.flatten())
        parts.append(np.concatenate(region_hist))
    vector = np.concatenate(parts).astype(np.float32)
    return _normalize_embedding(vector)


def _appearance_similarity(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right))


def _face_crop_from_bbox(frame: Any, bbox: tuple[int, int, int, int]) -> Any:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    pad = int(0.08 * max(x2 - x1, y2 - y1))
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    return frame[y1:y2, x1:x2].copy()


def _expand_upper_body_crop(frame: Any, bbox: tuple[int, int, int, int]) -> Any:
    import cv2

    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    box_h = y2 - y1
    y1_body = max(0, y1 - int(box_h * 0.15))
    y2_body = min(h, y2 + int(box_h * 2.5))
    x_pad = int((x2 - x1) * 0.35)
    x1_body = max(0, x1 - x_pad)
    x2_body = min(w, x2 + x_pad)
    return frame[y1_body:y2_body, x1_body:x2_body]


def _crop_to_jpeg_b64(crop: Any) -> str | None:
    import cv2

    if crop is None or crop.size == 0:
        return None
    ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return None
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(embedding))
    if norm <= 1e-8:
        return embedding.astype(np.float32, copy=False)
    return (embedding / norm).astype(np.float32, copy=False)


@dataclass
class _CharacterTrack:
    char_id: str
    centroid: np.ndarray
    count: int


def _match_threshold(embedding_method: str) -> float:
    return ARCFACE_MATCH_THRESHOLD if embedding_method == "arcface" else HISTOGRAM_MATCH_THRESHOLD


def _merge_threshold(embedding_method: str) -> float:
    return ARCFACE_MERGE_THRESHOLD if embedding_method == "arcface" else HISTOGRAM_MERGE_THRESHOLD


def _cooccurring_character_pairs(observations: list[FaceObservation]) -> set[tuple[str, str]]:
    """Characters that appeared in the same frame cannot be merged."""
    by_timestamp: dict[float, set[str]] = defaultdict(set)
    for obs in observations:
        if obs.character_id:
            by_timestamp[obs.timestamp_sec].add(obs.character_id)

    pairs: set[tuple[str, str]] = set()
    for char_ids in by_timestamp.values():
        ordered = sorted(char_ids)
        for i, left in enumerate(ordered):
            for right in ordered[i + 1 :]:
                pairs.add((left, right))
    return pairs


def _compute_character_centroids(observations: list[FaceObservation]) -> dict[str, np.ndarray]:
    groups: dict[str, list[np.ndarray]] = defaultdict(list)
    for obs in observations:
        if obs.character_id:
            groups[obs.character_id].append(obs.embedding)
    return {
        char_id: _normalize_embedding(np.mean(embeddings, axis=0))
        for char_id, embeddings in groups.items()
    }


def _assign_characters_online(
    observations: list[FaceObservation],
    embedding_method: str,
) -> list[_CharacterTrack]:
    """Track characters chronologically; never assign two faces in one frame to the same id."""
    if not observations:
        return []

    by_timestamp: dict[float, list[FaceObservation]] = defaultdict(list)
    for obs in observations:
        by_timestamp[obs.timestamp_sec].append(obs)

    tracks: list[_CharacterTrack] = []
    next_id = 1
    match_threshold = _match_threshold(embedding_method)

    for timestamp in sorted(by_timestamp.keys()):
        frame_observations = sorted(
            by_timestamp[timestamp],
            key=lambda o: (-float(o.detection_confidence or 0.0), o.face_index),
        )
        assigned_this_frame: set[str] = set()

        for obs in frame_observations:
            embedding = _normalize_embedding(obs.embedding)
            best_track: _CharacterTrack | None = None
            best_similarity = -1.0

            for track in tracks:
                if track.char_id in assigned_this_frame:
                    continue
                similarity = float(np.dot(embedding, track.centroid))
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_track = track

            if best_track is not None and best_similarity >= match_threshold:
                obs.character_id = best_track.char_id
                assigned_this_frame.add(best_track.char_id)
                sample_count = best_track.count
                best_track.centroid = _normalize_embedding(best_track.centroid * sample_count + embedding)
                best_track.count = sample_count + 1
                continue

            char_id = f"char_{next_id}"
            next_id += 1
            tracks.append(_CharacterTrack(char_id=char_id, centroid=embedding.copy(), count=1))
            obs.character_id = char_id
            assigned_this_frame.add(char_id)

    return tracks


def _compute_character_appearance_centroids(
    observations: list[FaceObservation],
) -> dict[str, np.ndarray]:
    groups: dict[str, list[np.ndarray]] = defaultdict(list)
    for obs in observations:
        if obs.character_id and obs.appearance_signature is not None:
            groups[obs.character_id].append(obs.appearance_signature)
    return {
        char_id: _normalize_embedding(np.mean(signatures, axis=0))
        for char_id, signatures in groups.items()
        if signatures
    }


def _character_sample_counts(observations: list[FaceObservation]) -> Counter:
    return Counter(obs.character_id for obs in observations if obs.character_id)


def _merge_by_appearance(
    observations: list[FaceObservation],
    embedding_method: str,
) -> dict[str, str]:
    """
    Merge fragment tracks that share hair/skin tone even when ArcFace similarity is low.
    Strong appearance match can merge co-occurring ids when one track is a small fragment.
    """
    appearance_centroids = _compute_character_appearance_centroids(observations)
    embedding_centroids = _compute_character_centroids(observations)
    if len(appearance_centroids) <= 1:
        return {char_id: char_id for char_id in appearance_centroids}

    counts = _character_sample_counts(observations)
    cooccurring = _cooccurring_character_pairs(observations)
    char_ids = sorted(appearance_centroids.keys())
    parent = {char_id: char_id for char_id in char_ids}
    merge_threshold = _merge_threshold(embedding_method)

    def find(char_id: str) -> str:
        while parent[char_id] != char_id:
            parent[char_id] = parent[parent[char_id]]
            char_id = parent[char_id]
        return char_id

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            if counts[root_left] >= counts[root_right]:
                parent[root_right] = root_left
            else:
                parent[root_left] = root_right

    for i, left in enumerate(char_ids):
        for right in char_ids[i + 1 :]:
            appearance_sim = _appearance_similarity(
                appearance_centroids[left],
                appearance_centroids[right],
            )
            embedding_sim = float(
                np.dot(embedding_centroids[left], embedding_centroids[right])
            )
            smaller, larger = (
                (left, right) if counts[left] <= counts[right] else (right, left)
            )
            smaller_ratio = counts[smaller] / max(counts[larger], 1)
            cooccur = (left, right) in cooccurring

            should_merge = False
            if appearance_sim >= APPEARANCE_STRONG_MERGE and (
                not cooccur or smaller_ratio <= FRAGMENT_CLUSTER_RATIO
            ):
                should_merge = True
            elif (
                appearance_sim >= APPEARANCE_MERGE_THRESHOLD
                and embedding_sim >= merge_threshold
                and not cooccur
            ):
                should_merge = True
            elif (
                appearance_sim >= APPEARANCE_MERGE_THRESHOLD
                and embedding_sim >= merge_threshold * 0.92
                and smaller_ratio <= FRAGMENT_CLUSTER_RATIO
            ):
                should_merge = True

            if should_merge:
                union(smaller, larger)

    return {char_id: find(char_id) for char_id in char_ids}


def _merge_non_cooccurring_characters(
    observations: list[FaceObservation],
    embedding_method: str,
) -> dict[str, str]:
    """Merge fragment tracks that never appear together and have similar centroids."""
    centroids = _compute_character_centroids(observations)
    if len(centroids) <= 1:
        return {char_id: char_id for char_id in centroids}

    cooccurring = _cooccurring_character_pairs(observations)
    char_ids = sorted(centroids.keys())
    parent = {char_id: char_id for char_id in char_ids}
    merge_threshold = _merge_threshold(embedding_method)

    def find(char_id: str) -> str:
        while parent[char_id] != char_id:
            parent[char_id] = parent[parent[char_id]]
            char_id = parent[char_id]
        return char_id

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for i, left in enumerate(char_ids):
        for right in char_ids[i + 1 :]:
            if (left, right) in cooccurring:
                continue
            similarity = float(np.dot(centroids[left], centroids[right]))
            if similarity >= merge_threshold:
                union(left, right)

    return {char_id: find(char_id) for char_id in char_ids}


def _renumber_characters_by_first_seen(observations: list[FaceObservation]) -> None:
    first_seen: dict[str, float] = {}
    for obs in observations:
        if not obs.character_id:
            continue
        first_seen[obs.character_id] = min(first_seen.get(obs.character_id, obs.timestamp_sec), obs.timestamp_sec)

    remap = {
        old_id: f"char_{index + 1}"
        for index, old_id in enumerate(sorted(first_seen.keys(), key=lambda cid: first_seen[cid]))
    }
    for obs in observations:
        if obs.character_id in remap:
            obs.character_id = remap[obs.character_id]


def _max_simultaneous_characters(observations: list[FaceObservation]) -> int:
    by_timestamp: dict[float, set[str]] = defaultdict(set)
    for obs in observations:
        if obs.character_id:
            by_timestamp[obs.timestamp_sec].add(obs.character_id)
    if not by_timestamp:
        return 0
    return max(len(char_ids) for char_ids in by_timestamp.values())


def _select_primary_characters(
    observations: list[FaceObservation],
    target_count: int,
) -> list[str]:
    """Pick the main on-screen identities (mass + co-occurrence)."""
    masses = Counter(obs.character_id for obs in observations if obs.character_id)
    if not masses:
        return []

    ranked = masses.most_common()
    if target_count <= 1:
        return [ranked[0][0]]

    primaries = [ranked[0][0]]
    cooccurring = _cooccurring_character_pairs(observations)
    partners: list[tuple[str, int]] = []
    for char_id, count in ranked[1:]:
        if any(
            (char_id == left and primaries[0] == right) or (char_id == right and primaries[0] == left)
            for left, right in cooccurring
        ):
            partners.append((char_id, count))
    if partners:
        primaries.append(max(partners, key=lambda item: item[1])[0])
    elif len(ranked) > 1:
        primaries.append(ranked[1][0])

    for char_id, _count in ranked:
        if len(primaries) >= target_count:
            break
        if char_id not in primaries:
            primaries.append(char_id)
    return primaries[:target_count]


def _consolidate_to_primary_characters(
    observations: list[FaceObservation],
    primaries: list[str],
) -> None:
    """Reassign fragment tracks onto the selected primary characters."""
    if not primaries:
        return

    centroids = _compute_character_centroids(observations)
    primary_set = set(primaries)
    remap = {
        char_id: char_id if char_id in primary_set else max(
            primaries,
            key=lambda primary: float(np.dot(centroids[char_id], centroids[primary])),
        )
        for char_id in centroids
    }
    for obs in observations:
        if obs.character_id in remap:
            obs.character_id = remap[obs.character_id]
    _renumber_characters_by_first_seen(observations)


def _assign_character_ids(
    observations: list[FaceObservation],
    embedding_method: str,
) -> None:
    if not observations:
        return

    _assign_characters_online(observations, embedding_method)
    merge_map = _merge_non_cooccurring_characters(observations, embedding_method)
    for obs in observations:
        if obs.character_id in merge_map:
            obs.character_id = merge_map[obs.character_id]

    appearance_map = _merge_by_appearance(observations, embedding_method)
    for obs in observations:
        if obs.character_id in appearance_map:
            obs.character_id = appearance_map[obs.character_id]

    on_screen_count = _max_simultaneous_characters(observations)
    if on_screen_count >= 1:
        primaries = _select_primary_characters(observations, on_screen_count)
        _consolidate_to_primary_characters(observations, primaries)
    else:
        _renumber_characters_by_first_seen(observations)


def _arcface_faces_in_frame(frame: Any, arcface_app: Any) -> list[tuple[np.ndarray, tuple[int, int, int, int], float]]:
    """Return (embedding, bbox, det_score) for each face in frame."""
    faces = arcface_app.get(frame)
    out: list[tuple[np.ndarray, tuple[int, int, int, int], float]] = []
    for face in faces:
        bbox = face.bbox.astype(int)
        x1, y1, x2, y2 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        emb = np.asarray(face.normed_embedding, dtype=np.float32)
        score = float(getattr(face, "det_score", 0.0))
        out.append((emb, (x1, y1, x2, y2), score))
    return out


def collect_observations(
    video_path: Path,
    utterances: list[dict[str, Any]],
    *,
    save_crops_dir: Path | None = None,
) -> tuple[list[FaceObservation], str]:
    arcface = _setup_arcface()
    embedding_method = "arcface" if arcface is not None else "histogram"
    reader = VideoFrameReader(str(video_path))
    observations: list[FaceObservation] = []
    crop_idx = 0

    if save_crops_dir:
        save_crops_dir.mkdir(parents=True, exist_ok=True)

    try:
        for utterance in utterances:
            uid = utterance.get("id") or ""
            aai_speaker = utterance.get("speaker") or ""
            if not aai_speaker:
                continue

            for point in sample_timestamps_for_utterance(utterance):
                ts = float(point["timestamp_sec"])
                frame = reader.read_at(ts)
                if frame is None:
                    continue

                if arcface is not None:
                    arc_faces = _arcface_faces_in_frame(frame, arcface)
                    if not arc_faces:
                        continue
                    for face_idx, (emb, bbox, det_score) in enumerate(arc_faces):
                        if not _passes_face_quality_gate(det_score, bbox):
                            continue
                        face_crop = _face_crop_from_bbox(frame, bbox)
                        appearance_sig = _appearance_signature(face_crop)
                        body_crop = _expand_upper_body_crop(frame, bbox)
                        jpeg = _crop_to_jpeg_b64(body_crop)
                        if save_crops_dir and jpeg:
                            import cv2

                            out = save_crops_dir / f"crop_{crop_idx:04d}_{uid}_{ts:.2f}s.jpg"
                            cv2.imwrite(str(out), body_crop)
                            crop_idx += 1
                        observations.append(
                            FaceObservation(
                                utterance_id=uid,
                                aai_speaker=aai_speaker,
                                timestamp_sec=round(ts, 3),
                                sample_method=point.get("method"),
                                chunk_text=point.get("chunk_text"),
                                face_index=face_idx,
                                detection_confidence=det_score,
                                faces_in_frame=len(arc_faces),
                                embedding=emb,
                                embedding_method="arcface",
                                crop_jpeg_base64=jpeg,
                                face_bbox=bbox,
                                appearance_signature=appearance_sig,
                            )
                        )
                    continue

                faces = detect_faces(frame)
                if not faces:
                    continue

                for face_idx, face in enumerate(faces):
                    crop = face.crop
                    if crop is None:
                        continue
                    if not _passes_face_quality_gate(face.confidence, face.bbox):
                        continue
                    emb, emb_method = _embed_face(crop, arcface)
                    if emb is None:
                        continue
                    face_crop = _face_crop_from_bbox(frame, face.bbox)
                    appearance_sig = _appearance_signature(face_crop)
                    body_crop = _expand_upper_body_crop(frame, face.bbox)
                    jpeg = _crop_to_jpeg_b64(body_crop)
                    if save_crops_dir and jpeg:
                        import cv2

                        out = save_crops_dir / f"crop_{crop_idx:04d}_{uid}_{ts:.2f}s.jpg"
                        cv2.imwrite(str(out), body_crop)
                        crop_idx += 1
                    observations.append(
                        FaceObservation(
                            utterance_id=uid,
                            aai_speaker=aai_speaker,
                            timestamp_sec=round(ts, 3),
                            sample_method=point.get("method"),
                            chunk_text=point.get("chunk_text"),
                            face_index=face_idx,
                            detection_confidence=face.confidence,
                            faces_in_frame=len(faces),
                            embedding=emb,
                            embedding_method=emb_method,
                            crop_jpeg_base64=jpeg,
                            face_bbox=face.bbox,
                            appearance_signature=appearance_sig,
                        )
                    )
    finally:
        reader.close()

    dominant_method = arcface and "arcface" or "histogram"
    if observations:
        methods = {o.embedding_method for o in observations}
        dominant_method = "arcface" if "arcface" in methods else "histogram"
    return observations, dominant_method


def _speaker_character_votes(observations: list[FaceObservation]) -> dict[str, dict[str, float]]:
    votes: dict[str, Counter] = defaultdict(Counter)
    for obs in observations:
        if not obs.character_id:
            continue
        weight = float(obs.detection_confidence or 0.5)
        votes[obs.aai_speaker][obs.character_id] += weight
    return {
        speaker: {cid: round(w, 3) for cid, w in counter.items()}
        for speaker, counter in sorted(votes.items())
    }


def _build_characters(
    observations: list[FaceObservation],
    appearances: dict[str, dict[str, Any]],
    portraits: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    by_char: dict[str, list[FaceObservation]] = defaultdict(list)
    for obs in observations:
        if obs.character_id:
            by_char[obs.character_id].append(obs)

    portraits = portraits or {}
    characters: dict[str, Any] = {}
    for char_id, obs_list in sorted(by_char.items()):
        timestamps = [o.timestamp_sec for o in obs_list]
        utterance_ids = sorted({o.utterance_id for o in obs_list if o.utterance_id})
        aai_labels = Counter(o.aai_speaker for o in obs_list)
        characters[char_id] = {
            "character_id": char_id,
            "sample_count": len(obs_list),
            "first_seen_sec": round(min(timestamps), 3),
            "last_seen_sec": round(max(timestamps), 3),
            "utterances_visible": utterance_ids,
            "aai_speaker_cooccurrence": dict(aai_labels),
            "appearance": appearances.get(char_id),
            "portrait": portraits.get(char_id),
        }
    return characters


def _best_observation_per_character(
    observations: list[FaceObservation],
    *,
    min_confidence: float = MIN_PORTRAIT_CONFIDENCE,
) -> dict[str, FaceObservation]:
    by_char: dict[str, FaceObservation] = {}
    for obs in observations:
        if not obs.character_id or not obs.face_bbox:
            continue
        if float(obs.detection_confidence or 0.0) < min_confidence:
            continue
        prev = by_char.get(obs.character_id)
        score = float(obs.detection_confidence or 0.0)
        prev_score = float(prev.detection_confidence or 0.0) if prev else -1.0
        if prev is None or score > prev_score:
            by_char[obs.character_id] = obs
    return by_char


def save_character_portraits(
    *,
    video_path: Path,
    observations: list[FaceObservation],
    characters_dir: Path,
    working_dir: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Save one face crop per visual character (best detection confidence).
    Returns portrait metadata keyed by character_id for JSON embedding.
    """
    import cv2

    characters_dir.mkdir(parents=True, exist_ok=True)
    best_by_char = _best_observation_per_character(observations)
    if not best_by_char:
        best_by_char = _best_observation_per_character(observations, min_confidence=MIN_FACE_DETECTION_CONFIDENCE)
    if not best_by_char:
        return {}

    reader = VideoFrameReader(str(video_path))
    portraits: dict[str, dict[str, Any]] = {}
    try:
        for char_id, obs in sorted(best_by_char.items()):
            frame = reader.read_at(float(obs.timestamp_sec))
            if frame is None:
                continue
            face_crop = _face_crop_from_bbox(frame, obs.face_bbox)
            if face_crop is None or face_crop.size == 0:
                continue

            char_dir = characters_dir / char_id
            char_dir.mkdir(parents=True, exist_ok=True)
            face_path = char_dir / "face.jpg"
            cv2.imwrite(str(face_path), face_crop, [cv2.IMWRITE_JPEG_QUALITY, 90])

            relative_path = (
                face_path.relative_to(working_dir)
                if working_dir and face_path.is_relative_to(working_dir)
                else face_path
            )
            portraits[char_id] = {
                "face_local_path": str(face_path),
                "face_relative_path": str(relative_path),
                "face_s3_key": None,
                "sample_timestamp_sec": obs.timestamp_sec,
                "utterance_id": obs.utterance_id,
                "detection_confidence": round(float(obs.detection_confidence or 0.0), 3),
            }
    finally:
        reader.close()

    return portraits


def _describe_appearances(
    observations: list[FaceObservation],
    *,
    model: str = "gpt-4o-mini",
) -> dict[str, dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {}

    try:
        from openai import OpenAI
    except ImportError:
        return {}

    client = OpenAI(api_key=api_key)
    by_char = _best_observation_per_character(
        [obs for obs in observations if obs.crop_jpeg_base64],
        min_confidence=MIN_FACE_DETECTION_CONFIDENCE,
    )

    appearances: dict[str, dict[str, Any]] = {}
    for char_id, obs in sorted(by_char.items()):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": APPEARANCE_SCHEMA_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Character sample at {obs.timestamp_sec}s "
                                    f"(utterance {obs.utterance_id}, diarization speaker {obs.aai_speaker})."
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{obs.crop_jpeg_base64}",
                                    "detail": "low",
                                },
                            },
                        ],
                    },
                ],
                response_format={"type": "json_object"},
                max_tokens=400,
            )
            raw = response.choices[0].message.content or "{}"
            appearances[char_id] = json.loads(raw)
        except Exception as exc:
            appearances[char_id] = {"error": str(exc)}
    return appearances


def _significant_character_count(characters: dict[str, Any], min_samples: int) -> int:
    return sum(1 for c in characters.values() if int(c.get("sample_count") or 0) >= min_samples)


def observe_characters(
    *,
    video_path: Path,
    l1_doc: dict[str, Any],
    describe: bool = False,
    appearance_model: str = "gpt-4o-mini",
    save_crops_dir: Path | None = None,
    characters_dir: Path | None = None,
    working_dir: Path | None = None,
    min_cluster_samples: int = 3,
) -> CharacterObservationReport:
    utterances = (l1_doc.get("L1_transcript") or {}).get("utterances") or []
    speaker_ids = sorted({u["speaker"] for u in utterances if u.get("speaker")})

    sample_point_count = sum(len(sample_timestamps_for_utterance(u)) for u in utterances)
    observations, embedding_method = collect_observations(
        video_path,
        utterances,
        save_crops_dir=save_crops_dir,
    )

    if not observations:
        return CharacterObservationReport(
            method="character_observation_v1",
            diarization_speaker_count=len(speaker_ids),
            diarization_speaker_ids=speaker_ids,
            character_count_visual=0,
            character_count_significant=0,
            min_cluster_samples=min_cluster_samples,
            count_mismatch=len(speaker_ids) != 0,
            embedding_method=embedding_method,
            sample_points=sample_point_count,
            faces_sampled=0,
            characters={},
            observations=[],
            speaker_character_votes={},
        )

    _assign_character_ids(observations, embedding_method)
    character_count = len({o.character_id for o in observations if o.character_id})
    appearances = _describe_appearances(observations, model=appearance_model) if describe else {}
    portraits: dict[str, dict[str, Any]] = {}
    if characters_dir is not None:
        portraits = save_character_portraits(
            video_path=video_path,
            observations=observations,
            characters_dir=characters_dir,
            working_dir=working_dir,
        )
    speaker_votes = _speaker_character_votes(observations)
    characters = _build_characters(observations, appearances, portraits)
    significant_count = _significant_character_count(characters, min_cluster_samples)

    obs_rows: list[dict[str, Any]] = []
    for obs in observations:
        obs_rows.append(
            {
                "utterance_id": obs.utterance_id,
                "aai_speaker": obs.aai_speaker,
                "timestamp_sec": obs.timestamp_sec,
                "character_id": obs.character_id,
                "sample_method": obs.sample_method,
                "chunk_text": obs.chunk_text,
                "detection_confidence": round(obs.detection_confidence, 3),
                "faces_in_frame": obs.faces_in_frame,
                "embedding_method": obs.embedding_method,
            }
        )

    return CharacterObservationReport(
        method="character_observation_v1",
        diarization_speaker_count=len(speaker_ids),
        diarization_speaker_ids=speaker_ids,
        character_count_visual=character_count,
        character_count_significant=significant_count,
        min_cluster_samples=min_cluster_samples,
        count_mismatch=character_count != len(speaker_ids),
        embedding_method=embedding_method,
        sample_points=sample_point_count,
        faces_sampled=len(observations),
        characters=characters,
        observations=obs_rows,
        speaker_character_votes=speaker_votes,
        appearance_model=appearance_model if describe else None,
        characters_assets_dir=str(characters_dir) if characters_dir else None,
    )


def report_to_dict(report: CharacterObservationReport) -> dict[str, Any]:
    warnings: list[str] = []
    if report.embedding_method == "histogram":
        warnings.append(
            "Using weak histogram embeddings — install insightface + onnxruntime for ArcFace "
            "(pip install insightface onnxruntime). Histogram tends to over-count characters."
        )
    if report.character_count_significant > report.diarization_speaker_count * 2:
        warnings.append(
            "Significant character count exceeds diarization — review crops or use --describe "
            "to merge by appearance."
        )
    return {
        "method": report.method,
        "diarization_speaker_count": report.diarization_speaker_count,
        "diarization_speaker_ids": report.diarization_speaker_ids,
        "character_count_visual": report.character_count_visual,
        "character_count_significant": report.character_count_significant,
        "min_cluster_samples": report.min_cluster_samples,
        "count_mismatch": report.count_mismatch,
        "embedding_method": report.embedding_method,
        "warnings": warnings,
        "sample_points": report.sample_points,
        "faces_sampled": report.faces_sampled,
        "characters": report.characters,
        "observations": report.observations,
        "speaker_character_votes": report.speaker_character_votes,
        "appearance_model": report.appearance_model,
        "characters_assets_dir": report.characters_assets_dir,
        "note": "Observe-only — counts on-screen characters; does not modify diarization labels.",
    }


def dominant_character_per_utterance(observations: list[FaceObservation]) -> dict[str, str]:
    by_utterance: dict[str, Counter] = defaultdict(Counter)
    for obs in observations:
        if not obs.character_id or not obs.utterance_id:
            continue
        by_utterance[obs.utterance_id][obs.character_id] += float(obs.detection_confidence or 0.5)
    return {
        utterance_id: counter.most_common(1)[0][0]
        for utterance_id, counter in by_utterance.items()
        if counter
    }


def dominant_character_per_speaker(speaker_votes: dict[str, dict[str, float]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for speaker_id, weights in speaker_votes.items():
        if weights:
            mapping[speaker_id] = max(weights.items(), key=lambda item: item[1])[0]
    return mapping


def l2_character_observation_summary(report: CharacterObservationReport) -> dict[str, Any]:
    """Compact block persisted on enrichment L2 (no per-sample rows)."""
    return {
        "method": report.method,
        "diarization_speaker_count": report.diarization_speaker_count,
        "diarization_speaker_ids": report.diarization_speaker_ids,
        "character_count_visual": report.character_count_visual,
        "character_count_significant": report.character_count_significant,
        "min_cluster_samples": report.min_cluster_samples,
        "count_mismatch": report.count_mismatch,
        "embedding_method": report.embedding_method,
        "sample_points": report.sample_points,
        "faces_sampled": report.faces_sampled,
        "characters": report.characters,
        "speaker_character_votes": report.speaker_character_votes,
    }


def run_l2_character_observation(
    doc: dict[str, Any],
    video_path: Path,
    *,
    min_cluster_samples: int = 3,
) -> tuple[CharacterObservationReport, list[FaceObservation]]:
    """Run observe-only character counting; returns report and in-memory face observations."""
    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
    speaker_ids = sorted({u["speaker"] for u in utterances if u.get("speaker")})
    sample_point_count = sum(len(sample_timestamps_for_utterance(u)) for u in utterances)

    observations, embedding_method = collect_observations(video_path, utterances)
    if not observations:
        empty = CharacterObservationReport(
            method="character_observation_v1",
            diarization_speaker_count=len(speaker_ids),
            diarization_speaker_ids=speaker_ids,
            character_count_visual=0,
            character_count_significant=0,
            min_cluster_samples=min_cluster_samples,
            count_mismatch=len(speaker_ids) != 0,
            embedding_method=embedding_method,
            sample_points=sample_point_count,
            faces_sampled=0,
            characters={},
            observations=[],
            speaker_character_votes={},
        )
        return empty, []

    _assign_character_ids(observations, embedding_method)
    character_count = len({o.character_id for o in observations if o.character_id})
    speaker_votes = _speaker_character_votes(observations)
    characters = _build_characters(observations, {})
    significant_count = _significant_character_count(characters, min_cluster_samples)

    obs_rows: list[dict[str, Any]] = []
    for obs in observations:
        obs_rows.append(
            {
                "utterance_id": obs.utterance_id,
                "aai_speaker": obs.aai_speaker,
                "timestamp_sec": obs.timestamp_sec,
                "character_id": obs.character_id,
                "sample_method": obs.sample_method,
                "chunk_text": obs.chunk_text,
                "detection_confidence": round(obs.detection_confidence, 3),
                "faces_in_frame": obs.faces_in_frame,
                "embedding_method": obs.embedding_method,
            }
        )

    report = CharacterObservationReport(
        method="character_observation_v1",
        diarization_speaker_count=len(speaker_ids),
        diarization_speaker_ids=speaker_ids,
        character_count_visual=character_count,
        character_count_significant=significant_count,
        min_cluster_samples=min_cluster_samples,
        count_mismatch=character_count != len(speaker_ids),
        embedding_method=embedding_method,
        sample_points=sample_point_count,
        faces_sampled=len(observations),
        characters=characters,
        observations=obs_rows,
        speaker_character_votes=speaker_votes,
    )
    return report, observations


def build_video_faces_from_observations(
    observations: list[FaceObservation],
    speaker_to_character: dict[str, str],
    *,
    assets_dir: str,
    job_id: str,
    ctx: Any,
) -> dict[str, Any]:
    """Write speaker portraits from dominant character crops; no speaker label changes."""
    import base64
    import os

    import cv2
    import numpy as np

    best_by_character: dict[str, FaceObservation] = {}
    for obs in observations:
        if not obs.character_id:
            continue
        prev = best_by_character.get(obs.character_id)
        if prev is None or float(obs.detection_confidence or 0) > float(prev.detection_confidence or 0):
            best_by_character[obs.character_id] = obs

    if not hasattr(ctx, "speaker_asset_paths"):
        ctx.speaker_asset_paths = {}

    video_faces: dict[str, Any] = {}
    for speaker_id, character_id in sorted(speaker_to_character.items()):
        obs = best_by_character.get(character_id)
        if obs is None or not obs.crop_jpeg_base64:
            continue

        decoded = base64.b64decode(obs.crop_jpeg_base64)
        crop = cv2.imdecode(np.frombuffer(decoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if crop is None or crop.size == 0:
            continue

        speaker_assets = os.path.join(assets_dir, "speakers", speaker_id)
        os.makedirs(speaker_assets, exist_ok=True)
        portrait_path = os.path.join(speaker_assets, "portrait.jpg")
        cv2.imwrite(portrait_path, crop)
        portrait_s3_key = f"jobs/{job_id}/assets/speakers/{speaker_id}/portrait.jpg"
        ctx.speaker_asset_paths[speaker_id] = portrait_path
        video_faces[speaker_id] = {
            "cluster_id": character_id,
            "character_id": character_id,
            "visible_ratio": 1.0,
            "alignment_confidence": round(float(obs.detection_confidence or 0), 3),
            "portrait_local_path": portrait_path,
            "portrait_s3_key": portrait_s3_key,
            "frame_timestamp_sec": obs.timestamp_sec,
            "utterance_id": obs.utterance_id,
            "visual_cluster_index": int(character_id.replace("char_", "") or 0)
            if character_id.startswith("char_")
            else None,
        }
    return video_faces


def annotate_utterances_with_characters(
    utterances: list[dict[str, Any]],
    observations: list[FaceObservation],
) -> list[dict[str, Any]]:
    """Add character_id to utterances without changing diarization speaker labels."""
    character_by_utterance = dominant_character_per_utterance(observations)
    updated: list[dict[str, Any]] = []
    for utterance in utterances:
        row = dict(utterance)
        character_id = character_by_utterance.get(utterance.get("id") or "")
        if character_id:
            row["character_id"] = character_id
        updated.append(row)
    return updated
