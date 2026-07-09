"""LP: Speaker attribution — text context, visual fusion, multimodal predictions."""

from __future__ import annotations

from typing import Any

from modules.enrichment.composite import run_sublayers
from modules.enrichment.document import deep_copy_doc, mark_layer_ok, mark_sublayer_ok, prune_lp_document
from modules.enrichment.lp_attribution.sublayers.s1_text_context import (
    S1TextContextEnricher,
    s1_artifact,
)
from modules.enrichment.lp_attribution.sublayers.s2_visual_fusion import (
    S2VisualFusionEnricher,
    s2_artifact,
)
from modules.enrichment.lp_attribution.sublayers.s3_fusion import S3FusionEnricher, s3_artifact


def merge_s1_staging(base_doc: dict[str, Any], s1_doc: dict[str, Any]) -> dict[str, Any]:
    """Merge LP.S1 output from a parallel run into the L2 base document."""
    output = deep_copy_doc(base_doc)
    if s1_doc.get("LP_text"):
        output["LP_text"] = deep_copy_doc(s1_doc["LP_text"])
    base_utterances = (output.get("L1_transcript") or {}).get("utterances") or []
    s1_utterances = (s1_doc.get("L1_transcript") or {}).get("utterances") or []
    if s1_utterances and len(s1_utterances) == len(base_utterances):
        merged: list[dict[str, Any]] = []
        for base_row, s1_row in zip(base_utterances, s1_utterances):
            row = dict(base_row)
            for key in ("dialogue_act", "mood", "addressee_hint"):
                if s1_row.get(key) is not None:
                    row[key] = s1_row[key]
            merged.append(row)
        output["L1_transcript"] = {
            **(output.get("L1_transcript") or {}),
            "utterances": merged,
        }
    s1_meta = (s1_doc.get("pipeline_meta") or {}).get("sublayer_status") or {}
    if s1_meta.get("LP.S1"):
        output.setdefault("pipeline_meta", {}).setdefault("sublayer_status", {})["LP.S1"] = s1_meta[
            "LP.S1"
        ]
    return output


class LPAttributionEnricher:
    layer_id = "LP"

    def __init__(self) -> None:
        self._s1 = S1TextContextEnricher()
        self._s2 = S2VisualFusionEnricher()
        self._s3 = S3FusionEnricher()

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        s1_partial = getattr(ctx, "lp_s1_partial", None)
        if s1_partial:
            doc = merge_s1_staging(doc, s1_partial)
            sublayers = [self._s2, self._s3]
        else:
            sublayers = [self._s1, self._s2, self._s3]

        doc, sublayer_paths = run_sublayers(
            doc,
            ctx,
            self.layer_id,
            sublayers,
            artifact_builders={"S2": s2_artifact, "S3": s3_artifact}
            if s1_partial
            else {"S1": s1_artifact, "S2": s2_artifact, "S3": s3_artifact},
            artifact_filenames={
                "S1": "S1_text.json",
                "S2": "S2_visual.json",
                "S3": "S3_fusion.json",
            },
        )

        if s1_partial and "LP.S1" not in (doc.get("pipeline_meta") or {}).get(
            "sublayer_status", {}
        ):
            s1_status = (
                (s1_partial.get("pipeline_meta") or {}).get("sublayer_status") or {}
            ).get("LP.S1", "ok")
            mark_sublayer_ok(doc.setdefault("pipeline_meta", {}), "LP", "S1", s1_status)

        metadata = deep_copy_doc(doc.get("metadata") or {})
        metadata["latest_layer"] = self.layer_id

        output = prune_lp_document(deep_copy_doc(doc))
        pipeline_meta = output.get("pipeline_meta") or {}
        mark_layer_ok(pipeline_meta, self.layer_id)
        output["pipeline_meta"] = pipeline_meta
        output["metadata"] = metadata
        output["_sublayer_paths"] = sublayer_paths
        if s1_partial and s1_partial.get("_sublayer_paths"):
            s1_paths = s1_partial.get("_sublayer_paths") or {}
            if isinstance(s1_paths, dict):
                sublayer_paths.update(s1_paths)
                output["_sublayer_paths"] = sublayer_paths
        return output

    def enrich_s1_only(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """Run LP.S1 in isolation (for parallel execution with L2)."""
        from modules.enrichment.composite import run_sublayers as _run

        doc, sublayer_paths = _run(
            doc,
            ctx,
            self.layer_id,
            [self._s1],
            artifact_builders={"S1": s1_artifact},
            artifact_filenames={"S1": "S1_text.json"},
        )
        doc["_sublayer_paths"] = sublayer_paths
        return doc
