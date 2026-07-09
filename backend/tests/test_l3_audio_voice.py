"""Tests for L3.S3 frame gender classifier and L4 audio merge."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.enrichment.base import EnrichmentContext
from modules.enrichment.l1_normalize.enricher import L1NormalizeEnricher
from modules.enrichment.l2_identity.enricher import L2IdentityEnricher
from modules.enrichment.l3_gender.enricher import L3GenderEnricher
from modules.enrichment.l3_gender.sublayers.s3_audio_voice import S3AudioVoiceEnricher
from modules.enrichment.l4_finalize.enricher import L4FinalizeEnricher
from modules.enrichment.l3_gender import voice_classifier
from tests.fixtures.enrichment_samples import SAMPLE_ASSEMBLYAI


@pytest.fixture
def ctx():
    return EnrichmentContext(job_id="job_l3_audio", working_dir="/tmp")


@pytest.fixture
def l2_doc(ctx, tmp_path):
    l1 = L1NormalizeEnricher().enrich(SAMPLE_ASSEMBLYAI, ctx)
    ctx.raw_speakers = SAMPLE_ASSEMBLYAI["speakers"]
    ctx.raw_metadata = SAMPLE_ASSEMBLYAI["metadata"]
    ctx.layers_output_dir = str(tmp_path / "layers")
    ctx.assets_dir = str(tmp_path / "assets")
    return L2IdentityEnricher().enrich(l1, ctx)


def test_l3_s3_skipped_without_video(l2_doc, ctx, tmp_path):
    ctx.layers_output_dir = str(tmp_path / "layers")
    ctx.assets_dir = str(tmp_path / "assets")
    ctx.video_path = None

    result = L3GenderEnricher().enrich(l2_doc, ctx)
    sub_status = result["pipeline_meta"]["sublayer_status"]
    assert sub_status["L3.S1"] == "ok"
    assert sub_status["L3.S3"].startswith("skipped:no_video")


def test_l3_s3_skipped_without_torch(l2_doc, ctx, tmp_path):
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"not-a-real-video")
    ctx.layers_output_dir = str(tmp_path / "layers")
    ctx.assets_dir = str(tmp_path / "assets")
    ctx.video_path = str(video_path)
    ctx.working_dir = str(tmp_path)

    with patch.object(voice_classifier, "torch_available", return_value=False):
        result = L3GenderEnricher().enrich(l2_doc, ctx)

    assert result["pipeline_meta"]["sublayer_status"]["L3.S3"] == "skipped:torch_unavailable"


def test_l3_s3_classifies_utterances_and_builds_l3_audio(l2_doc, ctx, tmp_path):
    ctx.layers_output_dir = str(tmp_path / "layers")
    ctx.assets_dir = str(tmp_path / "assets")
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fake")
    ctx.video_path = str(video_path)
    ctx.working_dir = str(tmp_path)

    fake_frames = {
        "u1": str(tmp_path / "assets" / "utterance_faces" / "u1.jpg"),
        "u2": str(tmp_path / "assets" / "utterance_faces" / "u2.jpg"),
        "u3": str(tmp_path / "assets" / "utterance_faces" / "u3.jpg"),
        "u4": str(tmp_path / "assets" / "utterance_faces" / "u4.jpg"),
    }
    for path in fake_frames.values():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"fake")

    def fake_classify(path: str) -> tuple[str, float]:
        if "u1" in path or "u3" in path:
            return "male", 0.91
        return "female", 0.88

    with patch.object(voice_classifier, "torch_available", return_value=True), patch.object(
        voice_classifier, "_get_model", return_value=(object(), object(), object())
    ), patch(
        "modules.enrichment.l3_gender.sublayers.s3_audio_voice.extract_speaking_face_crops",
        return_value=fake_frames,
    ), patch.object(voice_classifier, "classify_image", side_effect=fake_classify):
        result = S3AudioVoiceEnricher().enrich(l2_doc, ctx)

    utterances = result["L1_transcript"]["utterances"]
    u1 = next(u for u in utterances if u["id"] == "u1")
    assert u1["voice_gender"] == "male"
    assert u1["voice_gender_confidence"] == 0.91

    l3_audio = result["L3_audio"]
    assert l3_audio["A"]["gender"] == "male"
    assert l3_audio["B"]["gender"] == "female"


def test_l4_audio_agreement_boosts_sources(l2_doc, ctx, tmp_path):
    ctx.layers_output_dir = str(tmp_path / "layers")
    ctx.assets_dir = str(tmp_path / "assets")

    l3 = L3GenderEnricher().enrich(l2_doc, ctx)
    l3["L3_audio"] = {
        "A": {
            "speaker_id": "A",
            "gender": "male",
            "gender_confidence": 0.9,
            "gender_evidence": ["frame:u1:0.91"],
            "gender_source": "gender_classifier_mini",
        },
        "B": {
            "speaker_id": "B",
            "gender": "female",
            "gender_confidence": 0.88,
            "gender_evidence": ["frame:u2:0.88"],
            "gender_source": "gender_classifier_mini",
        },
    }

    l4 = L4FinalizeEnricher().enrich(l3, ctx)
    profile_a = l4["speaker_profiles"]["A"]
    assert "L3:audio" in profile_a["gender"]["sources"]
    assert profile_a["gender"]["value"] == "male"


def test_l4_audio_text_conflict_forces_pending_review(l2_doc, ctx, tmp_path):
    ctx.layers_output_dir = str(tmp_path / "layers")
    ctx.assets_dir = str(tmp_path / "assets")

    l3 = L3GenderEnricher().enrich(l2_doc, ctx)
    l3["L3_audio"] = {
        "A": {
            "speaker_id": "A",
            "gender": "female",
            "gender_confidence": 0.92,
            "gender_evidence": ["frame:u1:0.92"],
            "gender_source": "gender_classifier_mini",
        }
    }

    l4 = L4FinalizeEnricher().enrich(l3, ctx)
    profile_a = l4["speaker_profiles"]["A"]
    assert profile_a["gender"]["status"] == "pending_review"
    assert profile_a["gender"]["value"] == "male"
    evidence = profile_a["gender"]["evidence"]
    assert any("text:male" in item for item in evidence)
    assert any("audio:female" in item for item in evidence)
