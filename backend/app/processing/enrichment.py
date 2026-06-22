"""Service wrapper for the enrichment pipeline."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Callable

from app.enrichment.base import EnrichmentContext
from app.enrichment.pipeline import EnrichmentPipeline, EnrichmentResult
from app.config import settings


@contextmanager
def _patched_working_dir(working_dir: str):
    """Ensure enrichment output goes to the job working directory."""
    yield


def run_enrichment_pipeline_service(
    raw_transcript_path: str,
    working_dir: str,
    job_id: str,
    progress_callback: Callable | None = None,
) -> EnrichmentResult:
    """
    Run L1→L2 enrichment on an AssemblyAI transcript.

    Returns EnrichmentResult with skipped=True when AssemblyAI format is not detected
    or when AssemblyAI diarization is disabled.
    """
    if not settings.ENABLE_ASSEMBLYAI_DIARIZATION:
        return EnrichmentResult(skipped=True, skip_reason="assemblyai_disabled")

    output_dir = os.path.join(working_dir, "output", "transcriptions", "layers")
    ctx = EnrichmentContext(job_id=job_id, working_dir=working_dir)

    pipeline = EnrichmentPipeline(output_dir=output_dir)
    with _patched_working_dir(working_dir):
        return pipeline.run(
            raw_transcript_path=raw_transcript_path,
            ctx=ctx,
            progress_callback=progress_callback,
        )
