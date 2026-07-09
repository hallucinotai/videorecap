"""Runs registered enrichment layers sequentially."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.enrichment.base import EnrichmentContext
from app.enrichment.registry import get_layer, get_processable_layers, latest_enrichment_layer_id
from app.enrichment.review import review_required
from modules.enrichment.document import deep_copy_doc, get_review_queue, is_assemblyai_enhanced, load_layer_document

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    layer_paths: dict[str, str] = field(default_factory=dict)
    sublayer_paths: dict[str, str] = field(default_factory=dict)
    speaker_asset_paths: dict[str, str] = field(default_factory=dict)
    latest_layer_id: str | None = None
    latest_layer_path: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    review_required: bool = False
    review_queue: list = field(default_factory=list)


def _write_layer_output(
    output_dir: str,
    layer_id: str,
    filename: str,
    current_doc: dict,
) -> str:
    output_path = os.path.join(output_dir, filename)
    write_doc = current_doc
    if layer_id == "L3":
        from modules.enrichment.document import prune_l3_document

        write_doc = prune_l3_document(deep_copy_doc(current_doc))
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(write_doc, f, indent=2)
    return output_path


class EnrichmentPipeline:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def run(
        self,
        raw_transcript_path: str,
        ctx: EnrichmentContext,
        progress_callback=None,
    ) -> EnrichmentResult:
        raw_doc = load_layer_document(raw_transcript_path)

        if not is_assemblyai_enhanced(raw_doc):
            logger.info("Skipping enrichment: input is not AssemblyAI enhanced format")
            return EnrichmentResult(
                skipped=True,
                skip_reason="not_assemblyai_enhanced",
            )

        ctx.raw_speakers = raw_doc.get("speakers") or {}
        ctx.raw_metadata = raw_doc.get("metadata") or {}
        ctx.layers_output_dir = self.output_dir
        if ctx.assets_dir is None:
            ctx.assets_dir = os.path.join(ctx.working_dir, "output", "assets")

        current_doc: dict = raw_doc
        layer_paths: dict[str, str] = {}
        all_sublayer_paths: dict[str, str] = {}

        for layer_def in get_processable_layers():
            if progress_callback:
                progress_callback(
                    step=1,
                    message=f"Running enrichment {layer_def.layer_id}: {layer_def.label}…",
                )

            enricher = layer_def.load_enricher()
            if not enricher:
                continue

            if layer_def.layer_id == "L2":
                lp_enricher = get_layer("LP").load_enricher()
                l1_snapshot = deep_copy_doc(current_doc)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    l2_future = pool.submit(enricher.enrich, deep_copy_doc(l1_snapshot), ctx)
                    s1_future = pool.submit(lp_enricher.enrich_s1_only, deep_copy_doc(l1_snapshot), ctx)
                    current_doc = l2_future.result()
                    ctx.lp_s1_partial = s1_future.result()
            elif layer_def.layer_id == "LP":
                current_doc = enricher.enrich(current_doc, ctx)
                ctx.lp_s1_partial = None
            else:
                current_doc = enricher.enrich(current_doc, ctx)

            sublayer_paths = current_doc.pop("_sublayer_paths", None) or {}
            if isinstance(sublayer_paths, dict):
                all_sublayer_paths.update(sublayer_paths)

            output_path = _write_layer_output(
                self.output_dir,
                layer_def.layer_id,
                layer_def.filename,
                current_doc,
            )
            layer_paths[layer_def.layer_id] = output_path
            logger.info("Enrichment layer %s written to %s", layer_def.layer_id, output_path)

        latest_id = latest_enrichment_layer_id()
        latest_path = layer_paths.get(latest_id) if latest_id else None

        needs_review = False
        queue: list = []
        if latest_path:
            latest_doc = load_layer_document(latest_path)
            needs_review = review_required(latest_doc)
            queue = get_review_queue(latest_doc)

        if progress_callback and latest_id:
            if needs_review:
                progress_callback(
                    step=1,
                    message="Enrichment review required — confirm suggestions",
                )
            else:
                progress_callback(step=1, message=f"Enrichment complete ({latest_id})")

        return EnrichmentResult(
            layer_paths=layer_paths,
            sublayer_paths=all_sublayer_paths,
            speaker_asset_paths=dict(ctx.speaker_asset_paths or {}),
            latest_layer_id=latest_id,
            latest_layer_path=latest_path,
            review_required=needs_review,
            review_queue=queue,
        )
