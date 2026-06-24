"""Tests for visual utterance correction logic."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.enrichment.l2_identity.reconcile import (
    apply_visual_utterance_corrections,
    build_cluster_to_canonical_speaker,
    visual_cluster_for_utterance,
)


def test_visual_cluster_for_utterance_weighted_by_lip():
    samples = [
        {"utterance_id": "u4", "cluster_id": 1, "lip_motion_score": 12.0, "detection_confidence": 0.9},
        {"utterance_id": "u4", "cluster_id": 0, "lip_motion_score": 0.5, "detection_confidence": 0.9},
    ]
    assert visual_cluster_for_utterance("u4", samples) == 1


def test_build_cluster_to_canonical():
    samples = [
        {"aai_speaker": "B", "cluster_id": 1, "lip_motion_score": 10.0, "detection_confidence": 0.9},
        {"aai_speaker": "B", "cluster_id": 1, "lip_motion_score": 8.0, "detection_confidence": 0.85},
        {"aai_speaker": "C", "cluster_id": 1, "lip_motion_score": 1.0, "detection_confidence": 0.8},
    ]
    mapping = build_cluster_to_canonical_speaker(samples)
    assert mapping[1] == "B"


def test_apply_visual_utterance_corrections_relabels_hallucinated_c():
    utterances = [
        {"id": "u4", "speaker": "C", "start": 80.0, "end": 86.0, "text": "No. No."},
    ]
    samples = [
        {
            "utterance_id": "u4",
            "aai_speaker": "C",
            "cluster_id": 1,
            "lip_motion_score": 12.4,
            "detection_confidence": 0.9,
        },
    ]
    cluster_to_canonical = {1: "B"}
    updated, corrections, count = apply_visual_utterance_corrections(
        utterances, samples, cluster_to_canonical, min_lip_score=0.5
    )
    assert count == 1
    assert updated[0]["speaker"] == "B"
    assert updated[0]["speaker_original"] == "C"
    assert corrections[0]["to_speaker"] == "B"
