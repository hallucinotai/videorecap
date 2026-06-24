from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.job import RecapJob


class JobConfig(BaseModel):
    target_duration: int = Field(default=30, ge=10, le=120)
    whisper_model: str = "small"
    tts_voice: str = "nova"
    tts_model: str = "tts-1"
    language: str | None = None
    translate_to: str | None = None
    pad_with_black: bool = False
    include_emotions: bool = False  # Premium tier: emotion analysis from audio


class IntermediateFile(BaseModel):
    """Metadata about an intermediate file generated during processing."""
    key: str  # S3 path
    name: str  # "transcription", "tts_audio", etc.
    size_mb: float | None = None
    download_url: str | None = None  # Only if DEBUG=true


class EnrichmentLayerFile(BaseModel):
    """Download metadata for a single enrichment layer artifact."""
    layer_id: str
    label: str
    description: str
    filename: str
    size_mb: float | None = None
    download_url: str | None = None
    available: bool = False
    sublayer_id: str | None = None
    parent_layer_id: str | None = None
    is_sublayer: bool = False


class CreateJobRequest(BaseModel):
    upload_id: str
    s3_key: str
    original_filename: str
    file_size_bytes: int
    config: JobConfig = JobConfig()


class JobResponse(BaseModel):
    id: str
    user_id: str
    status: str
    current_step: int
    current_step_name: str | None
    progress_pct: float
    error_message: str | None
    original_filename: str
    file_size_bytes: int
    config: dict
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    has_original_in_storage: bool
    keep_original_video: bool | None = None
    emotion_analysis_status: str | None = None  # "completed", "failed", "skipped"
    emotion_analysis_error: str | None = None
    output_video_key: str | None = None  # S3 key for final output (if completed)
    intermediate_keys: dict | None = None  # Raw S3 keys dict
    intermediate_keys_detailed: dict[str, IntermediateFile] | None = None  # With metadata and download URLs
    enrichment_layers: list[EnrichmentLayerFile] | None = None  # DEBUG only

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    per_page: int


class DownloadResponse(BaseModel):
    download_url: str
    expires_in: int = 3600


class ReviewPresentation(BaseModel):
    display_label: str
    sample_quote: str | None = None
    utterance_id: str | None = None
    timestamp_sec: float | None = None
    thumbnail_s3_key: str | None = None
    thumbnail_url: str | None = None


class GenderReviewItem(BaseModel):
    speaker_id: str
    field: str = "gender"
    proposed: str
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    presentation: ReviewPresentation | None = None


class EnrichmentReviewResponse(BaseModel):
    review_queue: list[GenderReviewItem]
    speaker_profiles: dict[str, Any] = Field(default_factory=dict)
    l3_gender: dict[str, Any] = Field(default_factory=dict)


class EnrichmentReviewDecision(BaseModel):
    speaker_id: str
    action: str  # confirm | override | reject
    gender: str | None = None


class EnrichmentReviewSubmit(BaseModel):
    decisions: list[EnrichmentReviewDecision]


def _head_object_size_mb(s3_path: str) -> float | None:
    from app.services.storage import storage

    try:
        obj = storage.client.head_object(Bucket=storage.bucket, Key=s3_path)
        return round(obj["ContentLength"] / (1024 * 1024), 2)
    except Exception:
        return None


def _build_enrichment_layers(job: RecapJob) -> list[EnrichmentLayerFile] | None:
    from app.config import settings
    from app.enrichment.registry import get_enrichment_layers
    from app.enrichment.storage import LayerStorage

    if not settings.DEBUG:
        return None

    layers: list[EnrichmentLayerFile] = []
    intermediate_keys = job.intermediate_keys or {}

    for layer_def in get_enrichment_layers():
        s3_key = LayerStorage.resolve_s3_key(intermediate_keys, layer_def.layer_id)
        available = s3_key is not None
        size_mb = _head_object_size_mb(s3_key) if s3_key else None
        download_url = (
            LayerStorage.download_url(job.id, layer_def.layer_id) if available else None
        )
        layers.append(
            EnrichmentLayerFile(
                layer_id=layer_def.layer_id,
                label=layer_def.label,
                description=layer_def.description,
                filename=layer_def.filename,
                size_mb=size_mb,
                download_url=download_url,
                available=available,
            )
        )
        for sub in layer_def.sublayers:
            sub_s3 = LayerStorage.resolve_sublayer_s3_key(
                intermediate_keys, layer_def.layer_id, sub.sublayer_id
            )
            sub_available = sub_s3 is not None
            sub_size = _head_object_size_mb(sub_s3) if sub_s3 else None
            sub_url = (
                LayerStorage.download_url(job.id, layer_def.layer_id, sub.sublayer_id)
                if sub_available
                else None
            )
            layers.append(
                EnrichmentLayerFile(
                    layer_id=f"{layer_def.layer_id}.{sub.sublayer_id}",
                    parent_layer_id=layer_def.layer_id,
                    sublayer_id=sub.sublayer_id,
                    is_sublayer=True,
                    label=f"{layer_def.layer_id} · {sub.sublayer_id} {sub.label}",
                    description=f"Sublayer artifact: {sub.label}",
                    filename=sub.artifact_filename,
                    size_mb=sub_size,
                    download_url=sub_url,
                    available=sub_available,
                )
            )
    return layers


def job_to_response(job: RecapJob) -> JobResponse:
    from app.config import settings
    # Build intermediate_keys_detailed if DEBUG is enabled
    intermediate_keys_detailed = None
    if settings.DEBUG and job.intermediate_keys:
        intermediate_keys_detailed = {}
        # Map old-style keys (e.g., "transcription") to new format if they exist
        # Also include new step-based keys (e.g., "step_01.transcript")
        key_mapping = {
            "transcription": "transcription",
            "step_01.transcript": "transcription",
            "translation": "translation",
            "step_02.translation": "translation",
            "step_03.transcript_translated": "translation",
            "recap_data": "recap_data",
            "step_04.recap_data": "recap_data",
            "tts_audio": "tts_audio",
            "step_05.narration_audio": "tts_audio",
            "recap_video": "recap_video",
            "step_06.video_with_clips": "recap_video",
            "emotions": "emotions",
            "step_01.emotions": "emotions",
        }

        # Path slug used in the download URL for each canonical intermediate.
        # Keep these in sync with backend/app/api/v1/endpoints/jobs.py
        url_slug = {
            "transcription": "transcription",
            "translation": "translation",
            "recap_data": "recap",
            "tts_audio": "tts-audio",
            "recap_video": "recap-video",
            "emotions": "emotions",
        }

        for key_name, s3_path in job.intermediate_keys.items():
            # Map to canonical name if it's a new-style key
            canonical_name = key_mapping.get(key_name, key_name)

            # Skip metadata files, layer artifacts, anything we don't have a public route for, and duplicates
            if ".metadata" in key_name or canonical_name in intermediate_keys_detailed:
                continue
            if key_name.startswith("layer.") or key_name.startswith("step_01.layer_"):
                continue
            if canonical_name not in url_slug:
                continue

            size_mb = _head_object_size_mb(s3_path)

            download_url = f"/jobs/{job.id}/debug/{url_slug[canonical_name]}"

            intermediate_keys_detailed[canonical_name] = IntermediateFile(
                key=s3_path,
                name=canonical_name,
                size_mb=size_mb,
                download_url=download_url,
            )

    enrichment_layers = _build_enrichment_layers(job)

    return JobResponse(
        id=job.id,
        user_id=job.user_id,
        status=job.status,
        current_step=job.current_step,
        current_step_name=job.current_step_name,
        progress_pct=job.progress_pct,
        error_message=job.error_message,
        original_filename=job.original_filename,
        file_size_bytes=job.file_size_bytes,
        config=job.config,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
        has_original_in_storage=job.input_video_key is not None,
        keep_original_video=getattr(job, 'keep_original_video', None),
        emotion_analysis_status=getattr(job, 'emotion_analysis_status', None),
        emotion_analysis_error=getattr(job, 'emotion_analysis_error', None),
        output_video_key=job.output_video_key,
        intermediate_keys=job.intermediate_keys,
        intermediate_keys_detailed=intermediate_keys_detailed,
        enrichment_layers=enrichment_layers,
    )
