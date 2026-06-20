import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import hash_password, verify_password, encrypt_api_key
from app.models.user import User


def user_requires_api_key(email: str) -> bool:
    """Check whether a user must provide their own OpenAI API key."""
    if not settings.ENABLE_USER_API_KEYS:
        return False
    if not settings.API_KEY_ALLOWED_EMAILS:
        return True
    return email in settings.API_KEY_ALLOWED_EMAILS


def generate_otp() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


async def create_user(
    db: AsyncSession, email: str, password: str, full_name: str
) -> User:
    otp = generate_otp()
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        auth_provider="local",
        email_verified=False,
        otp_code=otp,
        otp_expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def verify_otp(db: AsyncSession, email: str, code: str) -> User | None:
    user = await get_by_email(db, email)
    if not user or not user.otp_code:
        return None
    if user.otp_code != code:
        return None
    if user.otp_expires_at and datetime.now(timezone.utc) > user.otp_expires_at.replace(tzinfo=timezone.utc if user.otp_expires_at.tzinfo is None else user.otp_expires_at.tzinfo):
        return None
    user.email_verified = True
    user.otp_code = None
    user.otp_expires_at = None
    await db.commit()
    await db.refresh(user)
    return user


async def resend_otp(db: AsyncSession, email: str) -> str | None:
    user = await get_by_email(db, email)
    if not user or user.email_verified:
        return None
    otp = generate_otp()
    user.otp_code = otp
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
    await db.commit()
    return otp


async def authenticate_user(
    db: AsyncSession, email: str, password: str
) -> User | None:
    user = await get_by_email(db, email)
    if not user or not user.hashed_password:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_by_google_id(db: AsyncSession, google_id: str) -> User | None:
    result = await db.execute(select(User).where(User.google_id == google_id))
    return result.scalar_one_or_none()


async def get_or_create_google_user(
    db: AsyncSession, google_id: str, email: str, full_name: str
) -> tuple[User, bool]:
    """Returns (user, was_linked) — was_linked is True when an existing
    email-only account was linked to Google for the first time."""
    user = await get_by_google_id(db, google_id)
    if user:
        return user, False

    user = await get_by_email(db, email)
    if user:
        user.google_id = google_id
        user.email_verified = True
        user.otp_code = None
        user.otp_expires_at = None
        if user.auth_provider == "local":
            user.auth_provider = "both"
        await db.commit()
        await db.refresh(user)
        return user, True

    user = User(
        email=email,
        full_name=full_name,
        auth_provider="google",
        google_id=google_id,
        email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, False


async def update_openai_key(db: AsyncSession, user_id: str, plain_key: str) -> None:
    user = await get_by_id(db, user_id)
    if not user:
        raise ValueError("User not found")
    user.encrypted_openai_key = encrypt_api_key(plain_key)
    await db.commit()


async def clear_openai_key(db: AsyncSession, user_id: str) -> None:
    user = await get_by_id(db, user_id)
    if not user:
        raise ValueError("User not found")
    user.encrypted_openai_key = None
    await db.commit()


async def update_assemblyai_key(db: AsyncSession, user_id: str, plain_key: str) -> None:
    user = await get_by_id(db, user_id)
    if not user:
        raise ValueError("User not found")
    user.encrypted_assemblyai_key = encrypt_api_key(plain_key)
    await db.commit()


async def clear_assemblyai_key(db: AsyncSession, user_id: str) -> None:
    user = await get_by_id(db, user_id)
    if not user:
        raise ValueError("User not found")
    user.encrypted_assemblyai_key = None
    await db.commit()
