"""Tests for L2.S1 character observation sublayer."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.enrichment.base import EnrichmentContext
from modules.enrichment.composite import SublayerSkipped
from modules.enrichment.l1_normalize.enricher import L1NormalizeEnricher
from modules.enrichment.l2_identity.character_observation import CharacterObservationReport, FaceObservation
from modules.enrichment.l2_identity.sublayers.s1_video_reconcile import S1VideoReconcileEnricher
from tests.fixtures.enrichment_samples import SAMPLE_ASSEMBLYAI


def _fake_report() -> CharacterObservationReport:
    return CharacterObservationReport(
        method="character_observation_v1",
        diarization_speaker_count=2,
        diarization_speaker_ids=["A", "B"],
        character_count_visual=2,
        character_count_significant=2,
        min_cluster_samples=3,
        count_mismatch=False,
        embedding_method="arcface",
        sample_points=4,
        faces_sampled=4,
        characters={
            "char_1": {"character_id": "char_1", "sample_count": 2},
            "char_2": {"character_id": "char_2", "sample_count": 2},
        },
        observations=[],
        speaker_character_votes={"A": {"char_1": 1.0}, "B": {"char_2": 1.0}},
    )


def _fake_face_observations() -> list[FaceObservation]:
    emb = np.ones(512, dtype=np.float32)
    emb /= np.linalg.norm(emb)
    jpeg = "Zm9v"  # unused if portrait path mocked
    return [
        FaceObservation(
            utterance_id="u1",
            aai_speaker="A",
            timestamp_sec=1.0,
            sample_method="word_chunks",
            chunk_text="hi",
            face_index=0,
            detection_confidence=0.9,
            faces_in_frame=1,
            embedding=emb,
            embedding_method="arcface",
            crop_jpeg_base64=jpeg,
            character_id="char_1",
        ),
        FaceObservation(
            utterance_id="u2",
            aai_speaker="B",
            timestamp_sec=2.0,
            sample_method="word_chunks",
            chunk_text="hey",
            face_index=0,
            detection_confidence=0.85,
            faces_in_frame=1,
            embedding=emb,
            embedding_method="arcface",
            crop_jpeg_base64=jpeg,
            character_id="char_2",
        ),
    ]


@patch("modules.enrichment.l2_identity.sublayers.s1_video_reconcile.build_video_faces_from_observations")
@patch("modules.enrichment.l2_identity.sublayers.s1_video_reconcile.run_l2_character_observation")
def test_s1_character_observation_enriches_without_relabel(mock_run, mock_portraits, tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake")
    mock_run.return_value = (_fake_report(), _fake_face_observations())
    mock_portraits.return_value = {
        "A": {"cluster_id": "char_1", "character_id": "char_1", "portrait_s3_key": "jobs/j/assets/speakers/A/portrait.jpg"},
        "B": {"cluster_id": "char_2", "character_id": "char_2", "portrait_s3_key": "jobs/j/assets/speakers/B/portrait.jpg"},
    }

    ctx = EnrichmentContext(
        job_id="job_vid",
        working_dir=str(tmp_path),
        video_path=str(video_path),
        assets_dir=str(tmp_path / "assets"),
    )
    l1 = L1NormalizeEnricher().enrich(SAMPLE_ASSEMBLYAI, ctx)

    result = S1VideoReconcileEnricher().enrich(l1, ctx)

    assert result["L2_reconciliation"]["method"] == "character_observation_v1"
    assert result["L2_reconciliation"]["character_count_visual"] == 2
    assert result["L2_reconciliation"]["utterances_relabeled"] == 0
    assert result["L2_character_observation"]["character_count_visual"] == 2
    utterances = result["L1_transcript"]["utterances"]
    assert utterances[0]["speaker"] == "A"
    assert utterances[0].get("character_id") == "char_1"
    assert "speaker_correction" not in (result.get("L1_transcript") or {})


def test_s1_skips_without_video(tmp_path):
    ctx = EnrichmentContext(
        job_id="j1",
        working_dir=str(tmp_path),
        assets_dir=str(tmp_path / "assets"),
    )
    l1 = L1NormalizeEnricher().enrich(SAMPLE_ASSEMBLYAI, ctx)
    with pytest.raises(SublayerSkipped, match="no_video"):
        S1VideoReconcileEnricher().enrich(l1, ctx)
