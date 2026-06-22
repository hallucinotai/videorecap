import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.enrichment.base import EnrichmentContext
from app.enrichment.pipeline import EnrichmentPipeline
from app.enrichment.registry import get_layer, get_processable_layers, intermediate_key_for
from app.enrichment.storage import LayerStorage
from modules.enrichment.document import extract_segments_list, is_assemblyai_enhanced
from modules.enrichment.l1_normalize import L1NormalizeEnricher
from modules.enrichment.l2_speakers import L2SpeakerEnricher
from tests.fixtures.enrichment_samples import SAMPLE_ASSEMBLYAI, WHISPER_LIST


@pytest.fixture
def ctx():
    return EnrichmentContext(job_id="job_test_1", working_dir="/tmp")


def test_registry_has_l0_l1_l2():
    layers = [layer.layer_id for layer in get_processable_layers()]
    assert layers == ["L1", "L2"]
    assert get_layer("L0").is_raw is True
    assert intermediate_key_for("L0") == "transcription"
    assert intermediate_key_for("L2") == "layer.L2"


def test_is_assemblyai_enhanced():
    assert is_assemblyai_enhanced(SAMPLE_ASSEMBLYAI) is True
    assert is_assemblyai_enhanced(WHISPER_LIST) is False


def test_l1_normalize_assigns_utterance_ids(ctx):
    enricher = L1NormalizeEnricher()
    result = enricher.enrich(SAMPLE_ASSEMBLYAI, ctx)

    utterances = result["L1_transcript"]["utterances"]
    assert [u["id"] for u in utterances] == ["u1", "u2", "u3", "u4"]
    assert result["L1_transcript"]["diarization_summary"]["speaker_count"] == 2


def test_l2_speaker_enrichment(ctx):
    l1 = L1NormalizeEnricher().enrich(SAMPLE_ASSEMBLYAI, ctx)
    ctx.raw_speakers = SAMPLE_ASSEMBLYAI["speakers"]
    ctx.raw_metadata = SAMPLE_ASSEMBLYAI["metadata"]

    result = L2SpeakerEnricher().enrich(l1, ctx)

    assert result["L2_speakers"]["A"]["name"] == "James"
    assert result["L2_speakers"]["B"]["name"] == "Sarah"
    assert result["narration_context"]["cast_summary"]
    assert "Sarah" in result["narration_context"]["cast_summary"]
    assert any(f["utterance_id"] == "u4" for f in result["L2_utterance_flags"])
    assert result["segments"]["0"]["utterance_id"] == "u1"
    assert "text" not in result["segments"]["0"]
    assert result["metadata"]["segments_format"] == "utterance_refs"
    resolved = extract_segments_list(result)
    assert resolved[0]["text"]
    assert resolved[0]["speaker_name"] == "James"


def test_enrichment_pipeline_skips_whisper(tmp_path):
    raw_path = tmp_path / "transcription.json"
    with open(raw_path, "w") as f:
        json.dump(WHISPER_LIST, f)

    pipeline = EnrichmentPipeline(output_dir=str(tmp_path / "layers"))
    result = pipeline.run(str(raw_path), EnrichmentContext(job_id="j1", working_dir=str(tmp_path)))

    assert result.skipped is True
    assert result.layer_paths == {}


def test_enrichment_pipeline_writes_layer_files(tmp_path):
    raw_path = tmp_path / "transcription.json"
    with open(raw_path, "w") as f:
        json.dump(SAMPLE_ASSEMBLYAI, f)

    out_dir = tmp_path / "layers"
    pipeline = EnrichmentPipeline(output_dir=str(out_dir))
    ctx = EnrichmentContext(job_id="j1", working_dir=str(tmp_path))
    result = pipeline.run(str(raw_path), ctx)

    assert result.skipped is False
    assert result.latest_layer_id == "L2"
    assert (out_dir / "enrichment_L1.json").exists()
    assert (out_dir / "enrichment_L2.json").exists()

    l2 = json.loads((out_dir / "enrichment_L2.json").read_text())
    segments = extract_segments_list(l2)
    assert len(segments) == 4
    assert l2["metadata"]["latest_layer"] == "L2"


def test_layer_storage_resolve_keys():
    keys = {
        "transcription": "jobs/x/layers/L0/transcription.json",
        "layer.L1": "jobs/x/layers/L1/enrichment_L1.json",
        "step_01.layer_L2": "jobs/x/layers/L2/enrichment_L2.json",
    }
    assert LayerStorage.resolve_s3_key(keys, "L0") == keys["transcription"]
    assert LayerStorage.resolve_s3_key(keys, "L1") == keys["layer.L1"]
    assert LayerStorage.resolve_s3_key(keys, "L2") == keys["step_01.layer_L2"]

    latest_id, latest_key = LayerStorage.resolve_latest_layer_path(keys)
    assert latest_id == "L2"
    assert latest_key == keys["step_01.layer_L2"]
