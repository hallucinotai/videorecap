import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.enrichment.base import EnrichmentContext
from app.enrichment.pipeline import EnrichmentPipeline
from app.enrichment.registry import get_processable_layers, terminal_layer_id
from app.enrichment.review import apply_gender_review_decisions, review_required
from modules.enrichment.document import get_review_queue
from modules.enrichment.l1_normalize.enricher import L1NormalizeEnricher
from modules.enrichment.l2_identity.enricher import L2IdentityEnricher
from modules.enrichment.l3_gender.enricher import L3GenderEnricher
from modules.enrichment.l4_finalize.enricher import L4FinalizeEnricher
from tests.fixtures.enrichment_samples import SAMPLE_ASSEMBLYAI

L2SpeakerEnricher = L2IdentityEnricher


@pytest.fixture
def ctx():
    return EnrichmentContext(job_id="job_l3", working_dir="/tmp")


@pytest.fixture
def l2_doc(ctx, tmp_path):
    l1 = L1NormalizeEnricher().enrich(SAMPLE_ASSEMBLYAI, ctx)
    ctx.raw_speakers = SAMPLE_ASSEMBLYAI["speakers"]
    ctx.raw_metadata = SAMPLE_ASSEMBLYAI["metadata"]
    ctx.layers_output_dir = str(tmp_path / "layers")
    ctx.assets_dir = str(tmp_path / "assets")
    return L2SpeakerEnricher().enrich(l1, ctx)


def test_l3_proposals_only_no_review_queue(l2_doc, ctx, tmp_path):
    ctx.layers_output_dir = str(tmp_path / "layers")
    result = L3GenderEnricher().enrich(l2_doc, ctx)

    assert result["L3_gender"]["A"]["gender"] == "male"
    assert result["L3_gender"]["B"]["gender"] == "female"
    assert result["L3_gender"]["A"]["requires_review"] is True
    assert get_review_queue(result) == []
    assert review_required(result) is False
    sub_status = result["pipeline_meta"]["sublayer_status"]
    assert sub_status["L3.S1"] == "ok"
    assert sub_status["L3.S2"].startswith("skipped:")


def test_l4_finalize_builds_presentation_and_queue(l2_doc, ctx, tmp_path):
    ctx.layers_output_dir = str(tmp_path / "layers")
    l3 = L3GenderEnricher().enrich(l2_doc, ctx)
    result = L4FinalizeEnricher().enrich(l3, ctx)

    assert result["speaker_profiles"]["A"]["gender"]["status"] == "pending_review"
    assert result["speaker_profiles"]["B"]["gender"]["status"] == "pending_review"
    assert "James" in result["speaker_profiles"]["A"]["presentation"]["display_label"]
    assert review_required(result) is True

    queue = get_review_queue(result)
    assert len(queue) == 2
    assert queue[0]["presentation"]["display_label"]
    assert "gender_review_queue" not in (result.get("narration_context") or {})


def test_l4_auto_accepts_high_confidence_roadside(ctx, tmp_path):
    raw = {
        "metadata": {"provider": "assemblyai", "speaker_diarization_enabled": True, "language_code": "en"},
        "speakers": {"A": {"speaker_id": "A"}, "B": {"speaker_id": "B"}, "C": {"speaker_id": "C"}},
        "segments": {
            "0": {"text": "No. Do not call the police.", "start": 80.0, "end": 86.0, "speaker": "C", "speaker_confidence": 0.9},
            "1": {
                "text": "What kind of guy would I be to let a pretty girl walk alone down this road?",
                "start": 86.0,
                "end": 148.0,
                "speaker": "A",
                "speaker_confidence": 0.9,
            },
        },
    }
    ctx.layers_output_dir = str(tmp_path / "layers")
    ctx.assets_dir = str(tmp_path / "assets")
    l1 = L1NormalizeEnricher().enrich(raw, ctx)
    ctx.raw_speakers = raw["speakers"]
    l2 = L2SpeakerEnricher().enrich(l1, ctx)
    l3 = L3GenderEnricher().enrich(l2, ctx)
    l4 = L4FinalizeEnricher().enrich(l3, ctx)

    assert l4["speaker_profiles"]["A"]["gender"]["status"] == "auto_accepted"
    assert l4["speaker_profiles"]["C"]["gender"]["status"] == "pending_review"
    assert l4["narration_context"]["pronoun_hints"]["A"] == "he"
    assert len(get_review_queue(l4)) == 1
    assert "Person at" in l4["speaker_profiles"]["C"]["presentation"]["display_label"]


def test_l3_self_identification_high_confidence(ctx, tmp_path):
    raw = {
        **SAMPLE_ASSEMBLYAI,
        "segments": {
            "0": {
                "text": "I'm a woman and I'm ready.",
                "start": 0.0,
                "end": 3.0,
                "speaker": "B",
                "speaker_confidence": 0.95,
            },
        },
        "speakers": {"B": {"speaker_id": "B", "name": None}},
    }
    ctx.layers_output_dir = str(tmp_path / "layers")
    ctx.assets_dir = str(tmp_path / "assets")
    l1 = L1NormalizeEnricher().enrich(raw, ctx)
    ctx.raw_speakers = raw["speakers"]
    l2 = L2SpeakerEnricher().enrich(l1, ctx)
    l3 = L3GenderEnricher().enrich(l2, ctx)
    l4 = L4FinalizeEnricher().enrich(l3, ctx)

    assert l4["speaker_profiles"]["B"]["gender"]["status"] == "auto_accepted"
    assert l4["narration_context"]["pronoun_hints"]["B"] == "she"
    assert review_required(l4) is False


def test_apply_gender_review_confirm_clears_queue(l2_doc, ctx, tmp_path):
    ctx.layers_output_dir = str(tmp_path / "layers")
    l4 = L4FinalizeEnricher().enrich(L3GenderEnricher().enrich(l2_doc, ctx), ctx)
    updated = apply_gender_review_decisions(
        l4,
        [
            {"speaker_id": "A", "action": "confirm"},
            {"speaker_id": "B", "action": "confirm"},
        ],
    )

    assert updated["speaker_profiles"]["A"]["gender"]["status"] == "confirmed"
    assert updated["narration_context"]["pronoun_hints"]["A"] == "he"
    assert review_required(updated) is False


def test_registry_terminal_layer():
    layers = [layer.layer_id for layer in get_processable_layers()]
    assert layers == ["L1", "L2", "L3", "L4"]
    assert terminal_layer_id() == "L4"


def test_enrichment_pipeline_pauses_at_l4(tmp_path):
    raw_path = tmp_path / "transcription.json"
    with open(raw_path, "w") as f:
        json.dump(SAMPLE_ASSEMBLYAI, f)

    out_dir = tmp_path / "layers"
    result = EnrichmentPipeline(output_dir=str(out_dir)).run(
        str(raw_path),
        EnrichmentContext(job_id="j1", working_dir=str(tmp_path)),
    )

    assert result.latest_layer_id == "L4"
    assert (out_dir / "enrichment_L4.json").exists()
    assert result.review_required is True
    l4 = json.loads((out_dir / "enrichment_L4.json").read_text())
    assert l4["metadata"]["latest_layer"] == "L4"
    assert all(item.get("presentation") for item in get_review_queue(l4))


def test_l3_visual_merges_when_portraits_present(l2_doc, ctx, tmp_path):
    ctx.layers_output_dir = str(tmp_path / "layers")
    l2_doc = dict(l2_doc)
    l2_doc["L2_identity"] = {
        "A": {
            "speaker_id": "A",
            "face": {
                "portrait_s3_key": "jobs/x/assets/speakers/A/portrait.jpg",
                "alignment_confidence": 0.9,
            },
        }
    }
    l3 = L3GenderEnricher().enrich(l2_doc, ctx)
    assert l3["pipeline_meta"]["sublayer_status"]["L3.S2"] == "ok"
    assert "A" in l3.get("L3_visual", {})
