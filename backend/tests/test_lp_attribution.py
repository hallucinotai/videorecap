import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.enrichment.base import EnrichmentContext
from app.enrichment.review import apply_attribution_review_decisions
from modules.enrichment.l4_finalize.enricher import (
    L4FinalizeEnricher,
    _build_attribution_review_queue,
)
from modules.enrichment.lp_attribution.enricher import LPAttributionEnricher
from modules.enrichment.lp_attribution.fusion import fuse_speaker_prediction
from modules.enrichment.lp_attribution.sublayers.s2_visual_fusion import S2VisualFusionEnricher
from modules.enrichment.lp_attribution.sublayers.s3_fusion import S3FusionEnricher
from tests.fixtures.enrichment_samples import SAMPLE_ASSEMBLYAI


@pytest.fixture
def ctx():
    return EnrichmentContext(job_id="job_test", working_dir="/tmp")


def _l2_doc_with_visual() -> dict:
    from modules.enrichment.l1_normalize.enricher import L1NormalizeEnricher

    l1 = L1NormalizeEnricher().enrich(SAMPLE_ASSEMBLYAI, EnrichmentContext(job_id="j", working_dir="/tmp"))
    utterances = l1["L1_transcript"]["utterances"]
    for row in utterances:
        row["character_id"] = "char_1" if row["speaker"] == "B" else "char_2"
    l1["L2_identity"] = {
        "A": {"speaker_id": "A", "face": {"cluster_id": "char_2"}},
        "B": {"speaker_id": "B", "face": {"cluster_id": "char_1"}},
    }
    l1["L2_character_observation"] = {
        "count_mismatch": False,
        "speaker_character_votes": {
            "A": {"char_1": 10.0, "char_2": 70.0},
            "B": {"char_1": 80.0, "char_2": 20.0},
        },
    }
    return l1


MOCK_LLM = {
    "utterances": [
        {
            "id": "u1",
            "dialogue_act": "greeting",
            "mood": "warm",
            "addressee_hint": None,
            "speaker_hint": "A",
            "text_evidence": "direct address",
        },
        {
            "id": "u4",
            "dialogue_act": "statement",
            "mood": "assertive",
            "addressee_hint": "Sarah",
            "speaker_hint": "B",
            "text_evidence": "vocative Sarah",
        },
    ],
    "speakers": {
        "A": {
            "speaking_style": "brief",
            "typical_mood": "warm",
            "context_summary": "Host greeting guest.",
        },
        "B": {
            "speaking_style": "apologetic",
            "typical_mood": "neutral",
            "context_summary": "Guest introducing herself.",
        },
    },
}


def test_fuse_speaker_prediction_disagreement():
    predicted, confidence, evidence = fuse_speaker_prediction(
        diarization_speaker="A",
        llm_speaker="B",
        visual_speaker="B",
        count_mismatch=False,
    )
    assert predicted == "B"
    assert confidence > 0
    assert evidence


@patch("modules.enrichment.lp_attribution.sublayers.s1_text_context.openai_available", return_value=True)
@patch(
    "modules.enrichment.lp_attribution.sublayers.s1_text_context.run_attribution_llm_batch",
    return_value={
        "method": "llm_batch_v1",
        "model": "gpt-4o-mini",
        "utterances": {row["id"]: row for row in MOCK_LLM["utterances"]},
        "speakers": MOCK_LLM["speakers"],
        "raw_response": MOCK_LLM,
    },
)
def test_lp_s1_annotates_utterances(_mock_llm, _mock_openai, ctx):
    doc = _l2_doc_with_visual()
    result = LPAttributionEnricher()._s1.enrich(doc, ctx)
    u1 = next(u for u in result["L1_transcript"]["utterances"] if u["id"] == "u1")
    assert u1.get("dialogue_act") == "greeting"
    assert result["LP_text"]["speakers"]["A"]["context_summary"]


def test_lp_s2_visual_fusion(ctx):
    doc = _l2_doc_with_visual()
    result = S2VisualFusionEnricher().enrich(doc, ctx)
    u4 = result["LP_visual"]["utterances"]["u4"]
    assert u4["speaker_visual"] in ("A", "B")
    assert u4.get("character_visual")


def test_lp_s3_pending_review_on_mismatch(ctx):
    doc = _l2_doc_with_visual()
    doc["LP_text"] = {
        "utterances": {
            "u4": {
                "speaker_hint": "B",
                "text_evidence": "Sarah vocative",
            }
        },
        "speakers": {},
    }
    doc = S2VisualFusionEnricher().enrich(doc, ctx)
    result = S3FusionEnricher().enrich(doc, ctx)
    u4 = next(u for u in result["L1_transcript"]["utterances"] if u["id"] == "u4")
    assert u4.get("speaker") == "A"
    if u4.get("speaker_predicted") != u4.get("speaker"):
        assert u4.get("attribution_status") == "pending_review"
        assert u4.get("attribution_correction")


def test_l4_attribution_review_queue(ctx):
    doc = _l2_doc_with_visual()
    utterances = doc["L1_transcript"]["utterances"]
    utterances[3]["speaker_predicted"] = "B"
    utterances[3]["attribution_status"] = "pending_review"
    utterances[3]["attribution_confidence"] = 0.8
    doc["L1_transcript"]["utterances"] = utterances
    doc["L3_gender"] = {
        "A": {"gender": "male", "gender_confidence": 0.9, "gender_evidence": []},
        "B": {"gender": "female", "gender_confidence": 0.9, "gender_evidence": []},
    }
    doc["L2_speakers"] = {"A": {}, "B": {}}
    result = L4FinalizeEnricher().enrich(doc, ctx)
    queue = result["narration_context"]["review_queue"]
    attr_items = [item for item in queue if item.get("type") == "attribution"]
    assert len(attr_items) >= 1
    assert attr_items[0]["utterance_id"] == "u4"


def test_apply_attribution_review_confirm():
    doc = {
        "L1_transcript": {
            "utterances": [
                {
                    "id": "u4",
                    "speaker": "A",
                    "speaker_predicted": "B",
                    "attribution_status": "pending_review",
                }
            ]
        },
        "speaker_profiles": {},
        "L3_gender": {},
        "L2_speakers": {},
        "L2_identity": {},
    }
    updated = apply_attribution_review_decisions(
        doc,
        [{"utterance_id": "u4", "action": "confirm"}],
    )
    u4 = updated["L1_transcript"]["utterances"][0]
    assert u4["attribution_status"] == "confirmed"
    assert u4["speaker_confirmed"] == "B"


def test_build_attribution_review_queue_skips_proposed():
    utterances = [
        {"id": "u1", "speaker": "A", "speaker_predicted": "A", "attribution_status": "proposed"},
        {"id": "u2", "speaker": "A", "speaker_predicted": "B", "attribution_status": "pending_review"},
    ]
    queue = _build_attribution_review_queue(utterances)
    assert len(queue) == 1
    assert queue[0]["utterance_id"] == "u2"
