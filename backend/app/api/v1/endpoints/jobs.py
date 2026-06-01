from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

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
    job = await job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_video_key:
        raise HTTPException(status_code=400, detail="Job not ready for download")

    # - Server generates a temporary URL (valid for 600 seconds / 10 minutes)
    # - Client receives just the URL 
    # - Client downloads directly from S3 using that URL
    # - Server doesn't handle the actual file transfer
    url = storage.generate_presigned_url(job.output_video_key, expires_in=600)
    return {"download_url": url}


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


@router.get("/{job_id}/debug/narration")
async def download_narration_audio(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Download the TTS narration audio separately. Only available when DEBUG=true."""
    from app.config import settings as app_settings
    if not app_settings.DEBUG:
        raise HTTPException(status_code=404, detail="Debug endpoints are disabled")

    job = await job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    tts_key = (job.intermediate_keys or {}).get("tts_audio")
    if not tts_key:
        raise HTTPException(status_code=404, detail="Narration audio not available for this job")

    filename = job.original_filename.rsplit(".", 1)[0] + "_narration.mp3"

    def stream():
        body = storage.client.get_object(Bucket=storage.bucket, Key=tts_key)["Body"]
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            yield chunk

    return StreamingResponse(
        stream(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    deleted = await job_service.delete_job(db, job_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")


class ConfirmOriginalVideoRequest(BaseModel):
    keep_original: bool


@router.post("/{job_id}/confirm-original-video", response_model=JobResponse)
async def confirm_original_video(
    job_id: str,
    body: ConfirmOriginalVideoRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_or_api_key),
):
    """Confirm whether to keep or delete the original video after job completion."""
    job = await job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job must be completed to confirm original video")

    job.keep_original_video = body.keep_original

    if not body.keep_original and job.input_video_key:
        storage.delete_file(job.input_video_key)
        job.input_video_key = None

    await db.commit()
    await db.refresh(job)

    return job_to_response(job)
