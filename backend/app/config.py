from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Video Recap Agent"
    APP_VERSION: str = "dev"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/video_recap"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # S3 / MinIO
    S3_ENDPOINT: str = "http://minio:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "video-recaps"
    S3_REGION: str = "us-east-1"
    S3_PUBLIC_ENDPOINT: str = ""

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_ENTERPRISE: str = ""

    # OpenAI
    OPENAI_API_KEY: str = ""
    WHISPER_MODEL_SIZE: str = "small"

    # AssemblyAI (for speaker diarization)
    ASSEMBLYAI_API_KEY: str = ""
    ASSEMBLYAI_LANGUAGE_CODE: str = "en"

    # Feature Flags
    ENABLE_USER_API_KEYS: bool = False
    API_KEY_ALLOWED_EMAILS: List[str] = []
    ENABLE_API_KEYS_MENU: bool = False
    ENABLE_BILLING: bool = False
    BILLING_DISABLED_MESSAGE: str = "Billing is not available yet. All features are currently free."
    ENABLE_TRANSLATION: bool = False
    ENABLE_ASSEMBLYAI_DIARIZATION: bool = False
    REQUIRE_ASSEMBLYAI_KEY: bool = True  # Require AssemblyAI key in Settings for speaker diarization

    # Email (Resend)
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "Video Recap <noreply@hallucinotai.com>"
    OTP_EXPIRY_MINUTES: int = 10

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # File limits
    MAX_UPLOAD_SIZE_BYTES: int = 2 * 1024 * 1024 * 1024  # 2GB

    # Storage: remove uploaded original from object storage after pipeline succeeds (output retained)
    DELETE_INPUT_VIDEO_ON_COMPLETE: bool = True

    # When True (or unset with DEBUG=true), Celery recap jobs keep tempfile workspace on disk for inspection.
    # When unset, defaults to preserving only when DEBUG is true (typical localhost).
    KEEP_PIPELINE_WORKING_DIR: Optional[bool] = None

    # Celery
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"

    model_config = {"env_file": ".env", "case_sensitive": True}

    def preserve_pipeline_working_dir(self) -> bool:
        """If True, pipeline tempfile output/ tree is kept after jobs finish."""
        if self.KEEP_PIPELINE_WORKING_DIR is not None:
            return self.KEEP_PIPELINE_WORKING_DIR
        return self.DEBUG


settings = Settings()
