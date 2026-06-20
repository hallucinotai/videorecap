from __future__ import annotations

from datetime import datetime

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


class IntermediateFile(BaseModel):
    """Metadata about an intermediate file generated during processing."""
    key: str  # S3 path
    name: str  # "transcription", "tts_audio", etc.
    size_mb: float | None = None
    download_url: str | None = None  # Only if DEBUG=true


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
    output_video_key: str | None = None  # S3 key for final output (if completed)
    intermediate_keys: dict | None = None  # Raw S3 keys dict
    intermediate_keys_detailed: dict[str, IntermediateFile] | None = None  # With metadata and download URLs

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    per_page: int


class DownloadResponse(BaseModel):
    download_url: str
    expires_in: int = 3600


def job_to_response(job: RecapJob) -> JobResponse:
    from app.config import settings
    from app.services.storage import storage

    # Build intermediate_keys_detailed if DEBUG is enabled
    intermediate_keys_detailed = None
    if settings.DEBUG and job.intermediate_keys:
        intermediate_keys_detailed = {}
        for key_name, s3_path in job.intermediate_keys.items():
            try:
                # Get file size from S3
                obj = storage.client.head_object(Bucket=storage.bucket, Key=s3_path)
                size_mb = round(obj["ContentLength"] / (1024 * 1024), 2)
            except Exception:
                size_mb = None

            # Generate download URL for this intermediate
            download_url = f"/jobs/{job.id}/debug/{key_name if key_name != 'tts_audio' else 'tts-audio'}"
            if key_name == "recap_video":
                download_url = f"/jobs/{job.id}/debug/recap-video"

            intermediate_keys_detailed[key_name] = IntermediateFile(
                key=s3_path,
                name=key_name,
                size_mb=size_mb,
                download_url=download_url,
            )

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
        output_video_key=job.output_video_key,
        intermediate_keys=job.intermediate_keys,
        intermediate_keys_detailed=intermediate_keys_detailed,
    )
