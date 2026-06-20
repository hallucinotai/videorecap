from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token, hash_api_key
from app.db.session import get_async_session
from app.models.api_key import APIKey
from app.models.user import User
from app.services import user_service

from datetime import datetime, timezone
from sqlalchemy import select


async def get_db(session: AsyncSession = Depends(get_async_session)):
    yield session


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: str = Header(..., alias="Authorization"),
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth header")
    token = authorization[7:]
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id = payload["sub"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await user_service.get_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_user_or_api_key(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> User:
    # Try JWT first
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            payload = decode_token(token)
            if payload.get("type") == "access":
                user = await user_service.get_by_id(db, payload["sub"])
                if user and user.is_active:
                    return user
        except Exception:
            pass

    # Try API key
    if x_api_key:
        hashed = hash_api_key(x_api_key)
        result = await db.execute(
            select(APIKey).where(APIKey.hashed_key == hashed, APIKey.is_active == True)
        )
        api_key = result.scalar_one_or_none()
        if api_key:
            api_key.last_used_at = datetime.now(timezone.utc)
            await db.commit()
            user = await user_service.get_by_id(db, api_key.user_id)
            if user and user.is_active:
                return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user
