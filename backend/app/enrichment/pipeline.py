"""Runs registered enrichment layers sequentially."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from app.enrichment.base import EnrichmentContext
from app.enrichment.registry import get_processable_layers, latest_enrichment_layer_id
from app.enrichment.review import review_required
from modules.enrichment.document import get_review_queue, is_assemblyai_enhanced, load_layer_document

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
            current_doc = enricher.enrich(current_doc, ctx)

            sublayer_paths = current_doc.pop("_sublayer_paths", None) or {}
            if isinstance(sublayer_paths, dict):
                all_sublayer_paths.update(sublayer_paths)

            output_path = os.path.join(self.output_dir, layer_def.filename)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(current_doc, f, indent=2)

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
                    message="Enrichment review required — confirm gender suggestions",
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
