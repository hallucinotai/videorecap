"""L2: Speaker identity — video reconcile then text names."""

from __future__ import annotations

from typing import Any

from modules.enrichment.composite import run_sublayers
from modules.enrichment.document import deep_copy_doc, mark_layer_ok
from modules.enrichment.l2_identity.merge import apply_l2_merge
from modules.enrichment.l2_identity.sublayers.s1_video_reconcile import (
    S1VideoReconcileEnricher,
    s1_artifact,
)
from modules.enrichment.l2_identity.sublayers.s2_text_names import S2TextNamesEnricher, s2_artifact


class L2IdentityEnricher:
    layer_id = "L2"

    def __init__(self) -> None:
        self._sublayers = [S1VideoReconcileEnricher(), S2TextNamesEnricher()]

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        doc, sublayer_paths = run_sublayers(
            doc,
            ctx,
            self.layer_id,
            self._sublayers,
            artifact_builders={"S1": s1_artifact, "S2": s2_artifact},
            artifact_filenames={"S1": "S1_video.json", "S2": "S2_text.json"},
        )
        doc = apply_l2_merge(doc)

        metadata = deep_copy_doc(doc.get("metadata") or {})
        metadata["latest_layer"] = self.layer_id
        metadata["speaker_diarization_enabled"] = True

        output = deep_copy_doc(doc)
        pipeline_meta = output.get("pipeline_meta") or {}
        mark_layer_ok(pipeline_meta, self.layer_id)
        output["pipeline_meta"] = pipeline_meta
        output["metadata"] = metadata
        output["_sublayer_paths"] = sublayer_paths
        return output
