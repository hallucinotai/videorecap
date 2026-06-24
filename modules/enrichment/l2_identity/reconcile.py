"""Face clustering and AssemblyAI speaker merge logic for L2 video reconciliation."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import numpy as np

# Cosine similarity above this → same visual identity cluster.
FACE_CLUSTER_SIMILARITY_MIN = 0.82
# Minimum weighted samples linking a diarization label to a cluster before merge.
MIN_SPEAKER_CLUSTER_WEIGHT = 0.35


def face_histogram_embedding(crop_bgr: Any) -> np.ndarray | None:
    """Lightweight face embedding from a BGR crop (no extra ML deps)."""
    try:
        import cv2
    except ImportError:
        return None

    if crop_bgr is None or crop_bgr.size == 0:
        return None
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
    hist = cv2.calcHist([resized], [0], None, [32], [0, 256])
    cv2.normalize(hist, hist)
    vec = hist.flatten().astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm < 1e-8:
        return None
    return vec / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def cluster_embeddings(embeddings: list[np.ndarray], min_similarity: float = FACE_CLUSTER_SIMILARITY_MIN) -> list[int]:
    """
    Greedy agglomerative clustering. Returns cluster index per embedding.
    """
    if not embeddings:
        return []
    n = len(embeddings)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if cosine_similarity(embeddings[i], embeddings[j]) >= min_similarity:
                union(i, j)

    roots = [find(i) for i in range(n)]
    unique_roots = sorted(set(roots))
    root_to_cluster = {r: idx for idx, r in enumerate(unique_roots)}
    return [root_to_cluster[r] for r in roots]


def assign_speakers_to_clusters(
    samples: list[dict[str, Any]],
) -> dict[str, int | None]:
    """
    Map each AssemblyAI speaker_id to a visual cluster index (or None if no face evidence).
    Weighted by detection confidence.
    """
    weights: dict[str, Counter] = defaultdict(Counter)
    for sample in samples:
        speaker_id = sample.get("aai_speaker")
        cluster_id = sample.get("cluster_id")
        if speaker_id is None or cluster_id is None:
            continue
        weight = float(sample.get("detection_confidence") or 0.5)
        weights[speaker_id][cluster_id] += weight

    assignment: dict[str, int | None] = {}
    for speaker_id, counter in weights.items():
        if not counter:
            assignment[speaker_id] = None
            continue
        total = sum(counter.values())
        best_cluster, best_weight = counter.most_common(1)[0]
        if best_weight / total >= MIN_SPEAKER_CLUSTER_WEIGHT:
            assignment[speaker_id] = best_cluster
        else:
            assignment[speaker_id] = None
    return assignment


def build_speaker_merge_map(
    speaker_ids: list[str],
    speaker_to_cluster: dict[str, int | None],
) -> tuple[dict[str, str], dict[str, Any]]:
    """
    Collapse diarization labels that map to the same visual cluster.

    Returns (merge_map, cluster_info) where merge_map maps merged-away IDs → canonical ID.
    """
    cluster_members: dict[int, list[str]] = defaultdict(list)
    unassigned: list[str] = []

    for speaker_id in speaker_ids:
        cluster = speaker_to_cluster.get(speaker_id)
        if cluster is None:
            unassigned.append(speaker_id)
        else:
            cluster_members[cluster].append(speaker_id)

    merge_map: dict[str, str] = {}
    clusters_meta: dict[str, Any] = {}

    for cluster_idx, members in sorted(cluster_members.items()):
        canonical = sorted(members)[0]
        clusters_meta[f"cluster_{cluster_idx}"] = {
            "cluster_id": f"cluster_{cluster_idx}",
            "canonical_speaker_id": canonical,
            "member_speaker_ids": sorted(members),
            "merged": len(members) > 1,
        }
        for speaker_id in members:
            if speaker_id != canonical:
                merge_map[speaker_id] = canonical

    for speaker_id in unassigned:
        clusters_meta[f"unassigned_{speaker_id}"] = {
            "cluster_id": None,
            "canonical_speaker_id": speaker_id,
            "member_speaker_ids": [speaker_id],
            "merged": False,
            "no_face_evidence": True,
        }

    return merge_map, clusters_meta


def resolve_canonical_speaker(speaker_id: str, merge_map: dict[str, str]) -> str:
    """Follow merge chain to canonical speaker id."""
    seen = set()
    current = speaker_id
    while current in merge_map and current not in seen:
        seen.add(current)
        current = merge_map[current]
    return current


def apply_speaker_merge_to_utterances(
    utterances: list[dict[str, Any]],
    merge_map: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    """Rewrite utterance speaker labels; return updated list and relabel count."""
    if not merge_map:
        return utterances, 0

    relabeled = 0
    updated: list[dict[str, Any]] = []
    for utterance in utterances:
        u = dict(utterance)
        original = u.get("speaker")
        if original:
            canonical = resolve_canonical_speaker(original, merge_map)
            if canonical != original:
                u["speaker"] = canonical
                u["speaker_original"] = original
                relabeled += 1
        updated.append(u)
    return updated, relabeled


def merge_raw_speakers(
    raw_speakers: dict[str, Any],
    merge_map: dict[str, str],
) -> dict[str, Any]:
    """Merge AssemblyAI speaker metadata onto canonical ids."""
    if not merge_map:
        return dict(raw_speakers)

    merged: dict[str, Any] = {}
    for speaker_id, info in raw_speakers.items():
        canonical = resolve_canonical_speaker(speaker_id, merge_map)
        if canonical not in merged:
            merged[canonical] = dict(info)
            merged[canonical]["speaker_id"] = canonical
            merged[canonical]["merged_from"] = []
        elif speaker_id != canonical:
            entry = merged[canonical]
            entry.setdefault("merged_from", []).append(speaker_id)
            if info.get("name") and not entry.get("name"):
                entry["name"] = info["name"]
    return merged


def _sample_weight(sample: dict[str, Any]) -> float:
    lip = float(sample.get("lip_motion_score") or 0.0)
    det = float(sample.get("detection_confidence") or 0.5)
    return max(0.1, lip) * det


def visual_cluster_for_utterance(
    utterance_id: str,
    samples: list[dict[str, Any]],
) -> int | None:
    """Dominant visual cluster for an utterance, weighted by lip motion."""
    votes: Counter[int] = Counter()
    for sample in samples:
        if sample.get("utterance_id") != utterance_id:
            continue
        cluster_id = sample.get("cluster_id")
        if cluster_id is None:
            continue
        votes[cluster_id] += _sample_weight(sample)
    if not votes:
        return None
    return votes.most_common(1)[0][0]


def build_cluster_to_canonical_speaker(
    samples: list[dict[str, Any]],
) -> dict[int, str]:
    """
    Map each visual cluster to the AssemblyAI speaker label most associated with it.
    Uses lip-weighted co-occurrence (who is labeled when this face speaks).
    """
    weights: dict[int, Counter] = defaultdict(Counter)
    for sample in samples:
        cluster_id = sample.get("cluster_id")
        aai = sample.get("aai_speaker")
        if cluster_id is None or not aai:
            continue
        weights[cluster_id][aai] += _sample_weight(sample)

    mapping: dict[int, str] = {}
    for cluster_id, counter in weights.items():
        if counter:
            mapping[cluster_id] = counter.most_common(1)[0][0]
    return mapping


def apply_visual_utterance_corrections(
    utterances: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    cluster_to_canonical: dict[int, str],
    *,
    min_lip_score: float = 0.5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """
    Relabel utterances when lip-active face cluster disagrees with AAI speaker label.

    Returns (updated_utterances, correction_log, relabel_count).
    """
    corrections: list[dict[str, Any]] = []
    relabeled = 0
    updated: list[dict[str, Any]] = []

    samples_by_utt: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        uid = sample.get("utterance_id")
        if uid:
            samples_by_utt[uid].append(sample)

    for utterance in utterances:
        u = dict(utterance)
        uid = u.get("id")
        aai_speaker = u.get("speaker")
        visual_cluster = visual_cluster_for_utterance(uid, samples) if uid else None

        if visual_cluster is not None and aai_speaker:
            utt_samples = samples_by_utt.get(uid, [])
            best_lip = max((float(s.get("lip_motion_score") or 0) for s in utt_samples), default=0.0)
            canonical = cluster_to_canonical.get(visual_cluster)
            if (
                canonical
                and canonical != aai_speaker
                and best_lip >= min_lip_score
            ):
                u["speaker"] = canonical
                u["speaker_original"] = aai_speaker
                u["visual_correction"] = {
                    "visual_cluster": visual_cluster,
                    "lip_motion_score": round(best_lip, 3),
                    "method": "lip_motion_vote",
                }
                corrections.append(
                    {
                        "utterance_id": uid,
                        "from_speaker": aai_speaker,
                        "to_speaker": canonical,
                        "visual_cluster": visual_cluster,
                        "lip_motion_score": round(best_lip, 3),
                    }
                )
                relabeled += 1
        updated.append(u)
    return updated, corrections, relabeled

