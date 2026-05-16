from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, generate_uuid


class RecapJob(Base, TimestampMixin):
    __tablename__ = "recap_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    current_step_name: Mapped[str | None] = mapped_column(String, nullable=True)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    input_video_key: Mapped[str | None] = mapped_column(String, nullable=True)
    output_video_key: Mapped[str | None] = mapped_column(String, nullable=True)
    intermediate_keys: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    keep_original_video: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    emotion_analysis_status: Mapped[str | None] = mapped_column(String, nullable=True)  # "completed", "failed", "skipped"
    emotion_analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)

    started_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="jobs")
