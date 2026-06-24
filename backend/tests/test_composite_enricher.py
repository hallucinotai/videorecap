"""Composite enricher sublayer orchestration tests."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.enrichment.base import EnrichmentContext
from modules.enrichment.composite import SublayerSkipped, run_sublayers


class _SkipEnricher:
    sublayer_id = "S9"

    def enrich(self, doc, ctx):
        raise SublayerSkipped("test_reason")


class _OkEnricher:
    sublayer_id = "S1"

    def enrich(self, doc, ctx):
        doc = dict(doc)
        doc["test_flag"] = True
        return doc


def test_run_sublayers_marks_skipped_and_ok(tmp_path):
    ctx = EnrichmentContext(
        job_id="j1",
        working_dir=str(tmp_path),
        layers_output_dir=str(tmp_path / "layers"),
    )
    doc = {"pipeline_meta": {}}
    result, paths = run_sublayers(
        doc,
        ctx,
        "L9",
        [_OkEnricher(), _SkipEnricher()],
        artifact_builders={"S1": lambda d: {"ok": True}},
        artifact_filenames={"S1": "S1_test.json"},
    )
    assert result["test_flag"] is True
    status = result["pipeline_meta"]["sublayer_status"]
    assert status["L9.S1"] == "ok"
    assert status["L9.S9"] == "skipped:test_reason"
    assert "L9.S1" in paths
    assert Path(paths["L9.S1"]).exists()
