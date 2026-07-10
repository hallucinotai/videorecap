import boto3
import redis.asyncio as redis
from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.db.session import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    services = {"database": False, "redis": False, "storage": False}

    # Check database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        services["database"] = True
    except Exception:
        pass

    # Check Redis
    try:
        r = redis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        services["redis"] = True
    except Exception:
        pass

    # Check S3/MinIO
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
        )
        s3.head_bucket(Bucket=settings.S3_BUCKET)
        services["storage"] = True
    except Exception:
        pass

    all_healthy = all(services.values())
    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": services,
    }


@router.get("/meta")
async def app_meta():
    return {
        "version": settings.APP_VERSION,
        "enable_user_api_keys": settings.ENABLE_USER_API_KEYS,
        "api_key_restricted_to_emails": len(settings.API_KEY_ALLOWED_EMAILS) > 0,
        "enable_api_keys_menu": settings.ENABLE_API_KEYS_MENU,
        "enable_billing": settings.ENABLE_BILLING,
        "billing_disabled_message": settings.BILLING_DISABLED_MESSAGE if not settings.ENABLE_BILLING else None,
        "google_client_id": settings.GOOGLE_CLIENT_ID or None,
        "enable_translation": settings.ENABLE_TRANSLATION,
        "debug": settings.DEBUG,
        "min_target_duration_seconds": settings.MIN_TARGET_DURATION_SECONDS,
        "max_target_duration_seconds": settings.MAX_TARGET_DURATION_SECONDS,
    }
