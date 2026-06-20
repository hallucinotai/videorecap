from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_or_api_key, get_db
from app.models.user import User
from app.schemas.job import CreateJobRequest, DownloadResponse, JobListResponse, JobResponse, job_to_response
from app.services import job_service
from app.services.storage import storage

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: CreateJobRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    # Check quota before creating job
    from app.core.permissions import check_quota
    await check_quota(db, current_user.id, current_user.tier)

    # Check if user must supply their own OpenAI key
    from app.services.user_service import user_requires_api_key
    if user_requires_api_key(current_user.email) and not current_user.encrypted_openai_key:
        raise HTTPException(
            status_code=400,
            detail="You must set your OpenAI API key in Settings before creating a job",
        )

    # Verify the upload exists in S3
    if not storage.file_exists(body.s3_key):
        raise HTTPException(status_code=400, detail="Upload not found")

    job = await job_service.create_job(
        db,
        user_id=current_user.id,
        s3_key=body.s3_key,
        config=body.config,
        original_filename=body.original_filename,
        file_size_bytes=body.file_size_bytes,
    )

    # Record usage
    from app.services.billing_service import record_usage
    await record_usage(db, current_user.id, job.id)

    # Dispatch to Celery
    from app.workers.tasks import process_recap_job
    process_recap_job.delay(job.id)

    return job_to_response(job)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    jobs, total = await job_service.list_jobs(
        db, current_user.id, page=page, per_page=per_page, status_filter=status_filter
    )
    return JobListResponse(
        items=[job_to_response(j) for j in jobs],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    job = await job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_to_response(job)


@router.get("/{job_id}/download")
async def download_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    import logging
    logger = logging.getLogger(__name__)

    job = await job_service.get_job(db, job_id, current_user.id)
    if not job:
        logger.warning(f"Download attempt: job {job_id} not found for user {current_user.id}")
        raise HTTPException(status_code=404, detail="Job not found")

    logger.info(f"Download attempt for job {job_id}: status={job.status}, output_video_key={job.output_video_key}")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail=f"Job not completed (status: {job.status})")
    if not job.output_video_key:
        raise HTTPException(status_code=400, detail="Job completed but output video key not set. Please try again.")

    filename = job.original_filename.rsplit(".", 1)[0] + "_recap.mp4"

    try:
        def stream():
            body = storage.client.get_object(Bucket=storage.bucket, Key=job.output_video_key)["Body"]
            for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                yield chunk

        return StreamingResponse(
            stream(),
            media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.error(f"Download failed for job {job_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.post("/{job_id}/stop", response_model=JobResponse)
async def stop_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Stop a running job. It can be resumed later."""
    job = await job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("pending", "processing"):
        raise HTTPException(status_code=400, detail="Job is not running")

    if job.celery_task_id:
        from app.workers.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")

    job.status = "stopped"
    job.error_message = None
    await db.commit()
    await db.refresh(job)

    import json
    from app.config import settings
    import redis as _redis
    rc = _redis.from_url(settings.REDIS_URL)
    rc.publish(
        f"job:{job_id}:progress",
        json.dumps({"type": "stopped", "step": job.current_step, "progress_pct": job.progress_pct}),
    )

    return job_to_response(job)


@router.post("/{job_id}/resume", response_model=JobResponse)
async def resume_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Resume a failed or stopped job from the step where it left off."""
    job = await job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("failed", "stopped"):
        raise HTTPException(status_code=400, detail="Only failed or stopped jobs can be resumed")

    if not job.input_video_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "Original upload is no longer on our servers, so this job cannot be resumed. "
                "Start a new job with a new upload."
            ),
        )

    resume_step = job.current_step or 1

    job.status = "processing"
    job.error_message = None
    job.progress_pct = 0.0
    await db.commit()
    await db.refresh(job)

    from app.workers.tasks import process_recap_job
    process_recap_job.delay(job.id, resume_from_step=resume_step)

    return job_to_response(job)


async def _download_intermediate_debug(
    job_id: str,
    intermediate_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Generic debug endpoint to download any intermediate file."""
    from app.config import settings as app_settings
    if not app_settings.DEBUG:
        raise HTTPException(status_code=404, detail="Debug endpoints are disabled")

    job = await job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    intermediate_keys = job.intermediate_keys or {}
    s3_key = intermediate_keys.get(intermediate_key)
    if not s3_key:
        raise HTTPException(status_code=404, detail=f"Intermediate '{intermediate_key}' not available for this job")

    # Determine filename and media type
    filename_map = {
        "transcription": ("transcription.json", "application/json"),
        "translation": ("translated.json", "application/json"),
        "recap_data": ("recap_data.json", "application/json"),
        "tts_audio": ("recap_narration.mp3", "audio/mpeg"),
        "recap_video": ("recap_video.mp4", "video/mp4"),
    }
    default_name, default_media = filename_map.get(intermediate_key, (f"{intermediate_key}.bin", "application/octet-stream"))
    filename = job.original_filename.rsplit(".", 1)[0] + "_" + default_name

    def stream():
        body = storage.client.get_object(Bucket=storage.bucket, Key=s3_key)["Body"]
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            yield chunk

    return StreamingResponse(
        stream(),
        media_type=default_media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{job_id}/debug/transcription")
async def download_transcription_debug(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Download the transcription JSON. Only available when DEBUG=true."""
    return await _download_intermediate_debug(job_id, "transcription", db, current_user)


@router.get("/{job_id}/debug/translation")
async def download_translation_debug(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Download the translated transcription JSON (if translation was enabled). Only available when DEBUG=true."""
    return await _download_intermediate_debug(job_id, "translation", db, current_user)


@router.get("/{job_id}/debug/recap")
async def download_recap_data_debug(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Download the recap data JSON (clip timings and metadata). Only available when DEBUG=true."""
    return await _download_intermediate_debug(job_id, "recap_data", db, current_user)


@router.get("/{job_id}/debug/tts-audio")
async def download_narration_audio(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Download the TTS narration audio separately. Only available when DEBUG=true."""
    return await _download_intermediate_debug(job_id, "tts_audio", db, current_user)


@router.get("/{job_id}/debug/recap-video")
async def download_recap_video_debug(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Download the recap video with clips extracted but before audio merge. Only available when DEBUG=true."""
    return await _download_intermediate_debug(job_id, "recap_video", db, current_user)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    deleted = await job_service.delete_job(db, job_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")
