from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, generate_uuid


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String, nullable=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    auth_provider: Mapped[str] = mapped_column(String, default="local")
    google_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    otp_code: Mapped[str | None] = mapped_column(String, nullable=True)
    otp_expires_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tier: Mapped[str] = mapped_column(String, default="free")
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    encrypted_openai_key: Mapped[str | None] = mapped_column(String, nullable=True)
    encrypted_assemblyai_key: Mapped[str | None] = mapped_column(String, nullable=True)

    jobs = relationship("RecapJob", back_populates="user", lazy="selectin")
    api_keys = relationship("APIKey", back_populates="user", lazy="selectin")
    subscriptions = relationship("Subscription", back_populates="user", lazy="selectin")
