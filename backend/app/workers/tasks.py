import logging
import os
from datetime import datetime, timezone

import redis
from sqlalchemy import select, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.security import decrypt_api_key
from app.models.job import RecapJob
from app.models.user import User
from app.services.storage import storage
from app.services.user_service import user_requires_api_key
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Celery tasks use sync DB engine (not async)
_sync_db_url = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
sync_engine = create_engine(_sync_db_url)
SyncSession = sessionmaker(bind=sync_engine)

_redis_client = redis.from_url(settings.REDIS_URL)


def _update_job_sync(job_id: str, **kwargs):
    """Update job in DB synchronously (for use in Celery tasks)."""
    with SyncSession() as session:
        job = session.execute(
            select(RecapJob).where(RecapJob.id == job_id)
        ).scalar_one_or_none()
        if not job:
            return
        for key, value in kwargs.items():
            setattr(job, key, value)
        session.commit()


def _publish_progress(job_id: str, **kwargs):
    """Publish progress to Redis pub/sub for WebSocket consumers."""
    import json
    channel = f"job:{job_id}:progress"
    message = json.dumps({
        "type": "progress",
        **kwargs,
    })
    _redis_client.publish(channel, message)


def _combined_update(job_id: str, **kwargs):
    """Update DB and publish to Redis."""
    _update_job_sync(job_id, **{k: v for k, v in kwargs.items()
                                 if k in {"status", "current_step", "current_step_name",
                                          "progress_pct", "error_message", "output_video_key",
                                          "intermediate_keys", "completed_at", "expires_at",
                                          "started_at", "input_video_key"}})
    _publish_progress(job_id, **kwargs)


def _resolve_openai_key(user_id: str) -> str | None:
    """Return the decrypted user key if required, else None (use system key)."""
    with SyncSession() as session:
        user = session.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()
        if not user:
            return None
        if user_requires_api_key(user.email) and user.encrypted_openai_key:
            return decrypt_api_key(user.encrypted_openai_key)
    return None


def _resolve_assemblyai_key(user_id: str) -> tuple[str | None, str]:
    """
    Resolve AssemblyAI API key based on configuration.

    Returns: (key: str|None, source: str)
      - If REQUIRE_ASSEMBLYAI_KEY=True: return (decrypted_user_key, "user")
      - If REQUIRE_ASSEMBLYAI_KEY=False: return (system_key_from_env, "system")

    Raises ValueError if key is required but not available.
    """
    from app.config import settings

    if settings.REQUIRE_ASSEMBLYAI_KEY:
        # User key is required - get from database
        with SyncSession() as session:
            user = session.execute(
                select(User).where(User.id == user_id)
            ).scalar_one_or_none()
            if not user:
                return None, "user"
            if user.encrypted_assemblyai_key:
                key = decrypt_api_key(user.encrypted_assemblyai_key)
                return key, "user"
        # User key required but not found - will be caught in validation
        return None, "user"
    else:
        # User key not required - use system key from .env
        key = settings.ASSEMBLYAI_API_KEY or None
        return key, "system"


@celery_app.task(bind=True, name="app.workers.tasks.process_recap_job")
def process_recap_job(self, job_id: str, resume_from_step: int = 0):
    """Main task: runs the 7-step recap pipeline. Supports resumption from a given step."""
    logger.info(f"Starting recap pipeline for job {job_id} (resume_from_step={resume_from_step})")

    import json

    # Load job config, intermediate keys, and resolve user's API keys
    user_openai_key = None
    user_assemblyai_key = None
    assemblyai_key_source = None
    existing_intermediate_keys = None
    with SyncSession() as session:
        job = session.execute(
            select(RecapJob).where(RecapJob.id == job_id)
        ).scalar_one_or_none()
        if not job:
            logger.error(f"Job {job_id} not found")
            return
        job_config = job.config
        input_video_key = job.input_video_key
        existing_intermediate_keys = job.intermediate_keys or {}
        user_openai_key = _resolve_openai_key(job.user_id)
        user_assemblyai_key, assemblyai_key_source = _resolve_assemblyai_key(job.user_id)

    if not input_video_key:
        msg = (
            "Original upload is no longer available in storage. "
            "Start a new job with a new upload."
        )
        logger.error("Job %s has no input video in storage", job_id)
        _update_job_sync(job_id, status="failed", error_message=msg)
        _redis_client.publish(
            f"job:{job_id}:progress",
            json.dumps({"type": "failed", "error": msg}),
        )
        return

    # Mark job as started
    _update_job_sync(job_id, status="processing", started_at=datetime.now(timezone.utc))

    # Store celery task ID
    _update_job_sync(job_id, celery_task_id=self.request.id)

    # Validate API key availability
    from app.config import settings

    # Check if AssemblyAI key is available (from either user or system)
    if not user_assemblyai_key:
        if settings.REQUIRE_ASSEMBLYAI_KEY:
            msg = (
                "AssemblyAI API key is required but not set. "
                "Please add your AssemblyAI API key in Settings."
            )
        else:
            msg = (
                "AssemblyAI API key not configured. "
                "Add ASSEMBLYAI_API_KEY to your .env file."
            )
        logger.error(f"Job {job_id}: {msg}")
        _update_job_sync(job_id, status="failed", error_message=msg)
        return

    # Inject user's OpenAI API key if present (concurrency=1, no race)
    original_openai_key = os.environ.get("OPENAI_API_KEY")
    if user_openai_key:
        os.environ["OPENAI_API_KEY"] = user_openai_key
        logger.info(f"Using user-provided OpenAI key for job {job_id}")

    # Inject AssemblyAI API key (from user or system)
    original_assemblyai_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if user_assemblyai_key:
        os.environ["ASSEMBLYAI_API_KEY"] = user_assemblyai_key
        logger.info(f"Using {assemblyai_key_source}-provided AssemblyAI key for job {job_id}")

    from app.workers.pipeline import RecapPipeline

    def publish_fn(**kwargs):
        _combined_update(job_id, **kwargs)

    pipeline = RecapPipeline(
        job_id=job_id,
        job_config=job_config,
        input_video_key=input_video_key,
        update_job_fn=lambda jid, **kw: _update_job_sync(jid, **{
            k: v for k, v in kw.items()
            if k in {"status", "current_step", "current_step_name", "progress_pct",
                      "error_message", "output_video_key", "intermediate_keys",
                      "completed_at", "expires_at", "started_at", "input_video_key"}
        }),
        publish_progress_fn=publish_fn,
    )

    try:
        result = pipeline.run(
            resume_from_step=resume_from_step,
            existing_intermediate_keys=existing_intermediate_keys if resume_from_step > 0 else None,
        )
        payload = {
            "type": "completed",
            "step": 7,
            "progress_pct": 100.0,
            "output_video_key": result["output_key"],
        }
        if result.get("input_removed"):
            payload["input_removed"] = True
        _redis_client.publish(
            f"job:{job_id}:progress",
            json.dumps(payload),
        )
        logger.info(f"Pipeline completed for job {job_id}")
    except Exception as e:
        logger.exception(f"Pipeline failed for job {job_id}: {e}")
        # Check if the job was intentionally stopped before publishing failure
        with SyncSession() as session:
            current_status = session.execute(
                select(RecapJob.status).where(RecapJob.id == job_id)
            ).scalar_one_or_none()
        if current_status != "stopped":
            import json
            _redis_client.publish(
                f"job:{job_id}:progress",
                json.dumps({"type": "failed", "error": str(e)}),
            )
    finally:
        # Restore original OpenAI key
        if user_openai_key:
            if original_openai_key is not None:
                os.environ["OPENAI_API_KEY"] = original_openai_key
            else:
                os.environ.pop("OPENAI_API_KEY", None)

        # Restore original AssemblyAI key
        if user_assemblyai_key:
            if original_assemblyai_key is not None:
                os.environ["ASSEMBLYAI_API_KEY"] = original_assemblyai_key
            else:
                os.environ.pop("ASSEMBLYAI_API_KEY", None)


@celery_app.task(name="app.workers.tasks.cleanup_expired_files")
def cleanup_expired_files():
    """Periodic task: delete expired job files from S3."""
    logger.info("Running expired file cleanup")
    now = datetime.now(timezone.utc)

    with SyncSession() as session:
        expired_jobs = session.execute(
            select(RecapJob).where(
                RecapJob.expires_at < now,
                RecapJob.status == "completed",
            )
        ).scalars().all()

        for job in expired_jobs:
            keys_to_delete = []
            if job.output_video_key:
                keys_to_delete.append(job.output_video_key)
            if job.intermediate_keys:
                keys_to_delete.extend(job.intermediate_keys.values())
            if job.input_video_key:
                keys_to_delete.append(job.input_video_key)

            if keys_to_delete:
                storage.delete_files(keys_to_delete)

            job.status = "expired"
            job.output_video_key = None
            job.intermediate_keys = None
            job.input_video_key = None

        session.commit()

    logger.info(f"Cleaned up {len(expired_jobs)} expired jobs")
