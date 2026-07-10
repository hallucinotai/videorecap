"""Unit tests for L2 continuous tracking adapter (no YOLO/GPU required)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.enrichment.l2_identity.continuous_tracking import (
    ContinuousTrackingResult,
    MergedCharacter,
    TrackSample,
    adapt_tracks_to_observations,
    build_report_from_observations,
    frame_to_timestamp,
    merge_tracks_by_arcface,
    tracking_mode_from_env,
    RawTrack,
)


def test_frame_to_timestamp():
    assert frame_to_timestamp(1, 25.0) == 0.0
    assert frame_to_timestamp(26, 25.0) == 1.0
    assert frame_to_timestamp(51, 25.0) == 2.0


def test_tracking_mode_from_env(monkeypatch):
    monkeypatch.delenv("L2_CHARACTER_TRACKING", raising=False)
    assert tracking_mode_from_env() == "continuous"
    monkeypatch.setenv("L2_CHARACTER_TRACKING", "sparse")
    assert tracking_mode_from_env() == "sparse"
    monkeypatch.setenv("L2_CHARACTER_TRACKING", "CONTINUOUS")
    assert tracking_mode_from_env() == "continuous"


def test_adapt_tracks_to_observations_overlap():
    emb = np.ones(512, dtype=np.float32)
    emb /= np.linalg.norm(emb)
    tracking = ContinuousTrackingResult(
        fps=10.0,
        frame_count=100,
        processed_frames=50,
        characters={
            1: MergedCharacter(
                char_index=1,
                frames=[11, 21, 51],  # 1.0s, 2.0s, 5.0s
                samples=[
                    TrackSample(frame=11, bbox=(10, 10, 50, 50), confidence=0.9, embedding=emb),
                    TrackSample(frame=21, bbox=(12, 12, 52, 52), confidence=0.8, embedding=emb),
                    TrackSample(frame=51, bbox=(14, 14, 54, 54), confidence=0.7, embedding=emb),
                ],
                member_track_ids=[1],
            ),
            2: MergedCharacter(
                char_index=2,
                frames=[31],  # 3.0s
                samples=[
                    TrackSample(frame=31, bbox=(100, 100, 140, 140), confidence=0.85, embedding=emb),
                ],
                member_track_ids=[2],
            ),
        },
    )
    utterances = [
        {"id": "u1", "speaker": "A", "start": 0.5, "end": 1.5},
        {"id": "u2", "speaker": "B", "start": 1.8, "end": 2.5},
        {"id": "u3", "speaker": "A", "start": 2.8, "end": 3.5},
        # no utterance covers 5.0s → sample at frame 51 dropped
    ]

    observations = adapt_tracks_to_observations(tracking, utterances)
    assert len(observations) == 3
    by_utt = {o.utterance_id: o for o in observations}
    assert by_utt["u1"].character_id == "char_1"
    assert by_utt["u1"].aai_speaker == "A"
    assert by_utt["u2"].character_id == "char_1"
    assert by_utt["u2"].aai_speaker == "B"
    assert by_utt["u3"].character_id == "char_2"
    assert by_utt["u3"].face_bbox == (100, 100, 140, 140)

    report = build_report_from_observations(
        observations,
        utterances,
        method="continuous_tracking_v1",
        sample_points=4,
    )
    assert report.method == "continuous_tracking_v1"
    assert report.character_count_visual == 2
    assert report.speaker_character_votes["A"]["char_1"] > 0
    assert report.speaker_character_votes["B"]["char_1"] > 0
    assert report.speaker_character_votes["A"]["char_2"] > 0
    assert "u1" in report.characters["char_1"]["utterances_visible"]


def test_adapt_no_overlap_returns_empty():
    tracking = ContinuousTrackingResult(
        fps=25.0,
        frame_count=100,
        processed_frames=10,
        characters={
            1: MergedCharacter(
                char_index=1,
                frames=[100],
                samples=[
                    TrackSample(frame=100, bbox=(0, 0, 10, 10), confidence=0.9, embedding=None),
                ],
                member_track_ids=[1],
            ),
        },
    )
    utterances = [{"id": "u1", "speaker": "A", "start": 0.0, "end": 1.0}]
    assert adapt_tracks_to_observations(tracking, utterances) == []


def test_merge_tracks_by_arcface_merges_similar():
    emb_a = np.zeros(512, dtype=np.float32)
    emb_a[0] = 1.0
    emb_b = emb_a.copy()
    emb_c = np.zeros(512, dtype=np.float32)
    emb_c[1] = 1.0

    raw = {
        1: RawTrack(
            track_id=1,
            frames=list(range(1, 8)),
            embeddings=[emb_a] * 7,
            bboxes=[np.array([0, 0, 10, 10], dtype=np.float32)] * 7,
            confidences=[0.9] * 7,
        ),
        2: RawTrack(
            track_id=2,
            frames=list(range(20, 27)),
            embeddings=[emb_b] * 7,
            bboxes=[np.array([1, 1, 11, 11], dtype=np.float32)] * 7,
            confidences=[0.85] * 7,
        ),
        3: RawTrack(
            track_id=3,
            frames=list(range(40, 47)),
            embeddings=[emb_c] * 7,
            bboxes=[np.array([50, 50, 60, 60], dtype=np.float32)] * 7,
            confidences=[0.8] * 7,
        ),
    }
    merged = merge_tracks_by_arcface(raw, similarity_threshold=0.9, min_track_frames=5)
    assert len(merged) == 2
    member_sets = {frozenset(c.member_track_ids) for c in merged.values()}
    assert frozenset({1, 2}) in member_sets
    assert frozenset({3}) in member_sets


@patch("modules.enrichment.l2_identity.sublayers.s1_video_reconcile.build_video_faces_from_observations")
@patch("modules.enrichment.l2_identity.sublayers.s1_video_reconcile.run_l2_character_observation")
def test_s1_sparse_mode_uses_observation_path(mock_run, mock_portraits, tmp_path, monkeypatch):
    from app.enrichment.base import EnrichmentContext
    from modules.enrichment.l1_normalize.enricher import L1NormalizeEnricher
    from modules.enrichment.l2_identity.character_observation import (
        CharacterObservationReport,
        FaceObservation,
    )
    from modules.enrichment.l2_identity.sublayers.s1_video_reconcile import S1VideoReconcileEnricher
    from tests.fixtures.enrichment_samples import SAMPLE_ASSEMBLYAI

    monkeypatch.setenv("L2_CHARACTER_TRACKING", "sparse")

    emb = np.ones(512, dtype=np.float32)
    emb /= np.linalg.norm(emb)
    report = CharacterObservationReport(
        method="character_observation_v1",
        diarization_speaker_count=2,
        diarization_speaker_ids=["A", "B"],
        character_count_visual=2,
        character_count_significant=2,
        min_cluster_samples=3,
        count_mismatch=False,
        embedding_method="arcface",
        sample_points=4,
        faces_sampled=2,
        characters={"char_1": {"character_id": "char_1", "sample_count": 1}},
        observations=[],
        speaker_character_votes={"A": {"char_1": 1.0}, "B": {"char_2": 1.0}},
    )
    faces = [
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
            character_id="char_1",
            face_bbox=(0, 0, 20, 20),
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
            character_id="char_2",
            face_bbox=(0, 0, 20, 20),
        ),
    ]
    mock_run.return_value = (report, faces)
    mock_portraits.return_value = {}

    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake")
    ctx = EnrichmentContext(
        job_id="job_sparse",
        working_dir=str(tmp_path),
        video_path=str(video_path),
        assets_dir=str(tmp_path / "assets"),
    )
    l1 = L1NormalizeEnricher().enrich(SAMPLE_ASSEMBLYAI, ctx)
    result = S1VideoReconcileEnricher().enrich(l1, ctx)

    mock_run.assert_called_once()
    assert result["L2_reconciliation"]["method"] == "character_observation_v1"
    assert result["L2_reconciliation"]["diagnostics"]["tracking_method"] == "character_observation_v1"
