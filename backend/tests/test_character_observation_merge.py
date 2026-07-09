import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.enrichment.l2_identity.character_observation import (
    FaceObservation,
    _appearance_similarity,
    _merge_by_appearance,
    _normalize_embedding,
    _passes_face_quality_gate,
)


def _obs(
    char_id: str,
    *,
    embedding: np.ndarray,
    appearance: np.ndarray,
    confidence: float = 0.9,
    timestamp: float = 1.0,
) -> FaceObservation:
    return FaceObservation(
        utterance_id="u1",
        aai_speaker="A",
        timestamp_sec=timestamp,
        sample_method="word_chunks",
        chunk_text="hello",
        face_index=0,
        detection_confidence=confidence,
        faces_in_frame=1,
        embedding=embedding,
        embedding_method="arcface",
        face_bbox=(10, 10, 60, 60),
        appearance_signature=appearance,
        character_id=char_id,
    )


def test_passes_face_quality_gate_rejects_bad_aspect_ratio():
    assert _passes_face_quality_gate(0.95, (0, 0, 200, 40)) is False


def test_merge_by_appearance_merges_fragment_with_matching_hair_and_skin():
    base_appearance = _normalize_embedding(np.arange(96, dtype=np.float32))
    variant_appearance = _normalize_embedding(base_appearance + np.random.default_rng(0).normal(0, 0.02, 96))

    emb_a = _normalize_embedding(np.array([1.0, 0.0, 0.0], dtype=np.float32))
    emb_b = _normalize_embedding(np.array([0.92, 0.38, 0.0], dtype=np.float32))

    observations = [
        _obs("char_2", embedding=emb_a, appearance=base_appearance, timestamp=1.0),
        _obs("char_2", embedding=emb_a, appearance=base_appearance, timestamp=2.0),
        _obs("char_2", embedding=emb_a, appearance=base_appearance, timestamp=3.0),
        _obs("char_3", embedding=emb_b, appearance=variant_appearance, timestamp=4.0),
    ]
    merge_map = _merge_by_appearance(observations, "arcface")
    assert merge_map["char_2"] == merge_map["char_3"]
    assert _appearance_similarity(base_appearance, variant_appearance) >= 0.9
