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
    include_emotions: bool = False  # Premium tier: emotion analysis from audio


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
    )
