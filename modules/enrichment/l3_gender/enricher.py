"""L3: Gender enrichment — text analysis + visual hints."""

from __future__ import annotations

from typing import Any

from modules.enrichment.composite import run_sublayers
from modules.enrichment.document import deep_copy_doc, mark_layer_ok
from modules.enrichment.l3_gender.sublayers.s1_text_analysis import S1TextAnalysisEnricher
from modules.enrichment.l3_gender.sublayers.s2_visual_hints import (
    S2VisualHintsEnricher,
    s1_artifact,
    s2_artifact,
)


class L3GenderEnricher:
    layer_id = "L3"

    def __init__(self) -> None:
        self._sublayers = [S1TextAnalysisEnricher(), S2VisualHintsEnricher()]

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        doc, sublayer_paths = run_sublayers(
            doc,
            ctx,
            self.layer_id,
            self._sublayers,
            artifact_builders={"S1": s1_artifact, "S2": s2_artifact},
            artifact_filenames={"S1": "S1_text.json", "S2": "S2_visual.json"},
        )

        metadata = deep_copy_doc(doc.get("metadata") or {})
        metadata["latest_layer"] = self.layer_id

        output = deep_copy_doc(doc)
        pipeline_meta = output.get("pipeline_meta") or {}
        mark_layer_ok(pipeline_meta, self.layer_id)
        output["pipeline_meta"] = pipeline_meta
        output["metadata"] = metadata
        output["_sublayer_paths"] = sublayer_paths
        return output
