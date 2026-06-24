"""L1: Normalize raw AssemblyAI transcript into stable utterance IDs."""

from __future__ import annotations

from typing import Any

from modules.enrichment.document import (
    build_diarization_summary,
    deep_copy_doc,
    init_pipeline_meta,
    is_assemblyai_enhanced,
    mark_layer_ok,
    segments_dict_to_utterances,
)


class L1NormalizeEnricher:
    layer_id = "L1"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        if not is_assemblyai_enhanced(doc):
            raise ValueError("L1 requires AssemblyAI enhanced transcript format")

        job_id = ctx.job_id
        utterances = segments_dict_to_utterances(doc["segments"])

        pipeline_meta = init_pipeline_meta(job_id, self.layer_id)
        mark_layer_ok(pipeline_meta, "L0")
        mark_layer_ok(pipeline_meta, self.layer_id)

        output = {
            "pipeline_meta": pipeline_meta,
            "L1_transcript": {
                "utterances": utterances,
                "diarization_summary": build_diarization_summary(utterances),
            },
            "L0_metadata": deep_copy_doc(doc.get("metadata") or {}),
        }
        return output
