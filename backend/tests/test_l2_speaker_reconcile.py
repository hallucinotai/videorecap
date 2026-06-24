"""Unit tests for video-based AssemblyAI speaker merge logic."""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.enrichment.l2_identity.reconcile import (
    apply_speaker_merge_to_utterances,
    assign_speakers_to_clusters,
    build_speaker_merge_map,
    cluster_embeddings,
    merge_raw_speakers,
    resolve_canonical_speaker,
)


def _emb(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(32).astype(np.float32)
    return v / np.linalg.norm(v)


def test_cluster_embeddings_groups_similar_faces():
    a, b, c = _emb(1), _emb(1), _emb(99)
    b = a + np.random.default_rng(0).normal(0, 0.01, size=a.shape).astype(np.float32)
    b = b / np.linalg.norm(b)
    labels = cluster_embeddings([a, b, c], min_similarity=0.82)
    assert labels[0] == labels[1]
    assert labels[0] != labels[2]


def test_build_merge_map_collapses_over_segmentation():
    speaker_to_cluster = {"A": 0, "B": 1, "C": 0, "D": 2, "E": 2, "F": 3}
    merge_map, clusters = build_speaker_merge_map(list(speaker_to_cluster.keys()), speaker_to_cluster)
    assert merge_map.get("C") == "A"
    assert merge_map.get("E") == "D"
    assert clusters["cluster_0"]["canonical_speaker_id"] == "A"
    assert sorted(clusters["cluster_0"]["member_speaker_ids"]) == ["A", "C"]


def test_apply_merge_relabels_utterances():
    utterances = [
        {"id": "u1", "speaker": "A", "text": "hi"},
        {"id": "u2", "speaker": "C", "text": "hello"},
    ]
    updated, count = apply_speaker_merge_to_utterances(utterances, {"C": "A"})
    assert count == 1
    assert updated[1]["speaker"] == "A"
    assert updated[1]["speaker_original"] == "C"


def test_assign_speakers_to_clusters_majority():
    samples = [
        {"aai_speaker": "A", "cluster_id": 0, "detection_confidence": 0.9},
        {"aai_speaker": "A", "cluster_id": 0, "detection_confidence": 0.8},
        {"aai_speaker": "F", "cluster_id": 0, "detection_confidence": 0.85},
        {"aai_speaker": "B", "cluster_id": 1, "detection_confidence": 0.9},
    ]
    assigned = assign_speakers_to_clusters(samples)
    assert assigned["A"] == 0
    assert assigned["F"] == 0
    assert assigned["B"] == 1


def test_merge_raw_speakers():
    raw = {
        "A": {"speaker_id": "A", "name": "James"},
        "F": {"speaker_id": "F", "name": None},
    }
    merged = merge_raw_speakers(raw, {"F": "A"})
    assert "F" not in merged
    assert merged["A"]["speaker_id"] == "A"
    assert "F" in merged["A"]["merged_from"]


def test_resolve_canonical_speaker_chain():
    assert resolve_canonical_speaker("F", {"F": "A"}) == "A"
