"""
User management endpoints - Development/Local utilities
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr

from app.api.v1.deps import get_current_user, get_current_admin_user, get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


class TierUpgradeResponse(BaseModel):
    message: str
    user_id: str
    email: str
    tier: str
    note: str | None = None


class AdminStatusResponse(BaseModel):
    message: str
    user_id: str
    email: str
    is_admin: bool


class AdminToggleRequest(BaseModel):
    email: EmailStr


class UserInfoResponse(BaseModel):
    id: str
    email: str
    full_name: str
    tier: str
    is_active: bool
    email_verified: bool
    auth_provider: str

    class Config:
        from_attributes = True


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """Get current user profile information"""
    return UserInfoResponse.from_orm(current_user)


@router.post("/upgrade-to-enterprise", response_model=TierUpgradeResponse)
async def upgrade_to_enterprise(
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    DEV-ONLY ENDPOINT: Upgrade current user to enterprise tier

    This endpoint is for local development/testing only.
    Allows you to test enterprise features without upgrading in production.

    Usage:
    ```
    curl -X POST http://localhost:8000/api/v1/users/upgrade-to-enterprise \
      -H "Authorization: Bearer YOUR_JWT_TOKEN"
    ```
    """
    logger.warning(f"User {current_user.id} ({current_user.email}) upgraded to enterprise tier via dev endpoint")

    current_user.tier = "enterprise"
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return TierUpgradeResponse(
        message="Successfully upgraded to enterprise tier",
        user_id=current_user.id,
        email=current_user.email,
        tier=current_user.tier,
        note="This is a development-only endpoint. Use /api/v1/billing for production upgrades."
    )


@router.post("/set-tier/{tier}", response_model=TierUpgradeResponse)
async def set_user_tier(
    tier: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    DEV-ONLY ENDPOINT: Set user tier to any value

    Valid tiers: "free", "pro", "enterprise"

    Usage:
    ```
    curl -X POST http://localhost:8000/api/v1/users/set-tier/pro \
      -H "Authorization: Bearer YOUR_JWT_TOKEN"
    ```
    """
    valid_tiers = ["free", "pro", "enterprise"]
    if tier not in valid_tiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier. Must be one of: {', '.join(valid_tiers)}"
        )

    logger.warning(f"User {current_user.id} ({current_user.email}) set tier to {tier} via dev endpoint")

    current_user.tier = tier
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return TierUpgradeResponse(
        message=f"Successfully set tier to {tier}",
        user_id=current_user.id,
        email=current_user.email,
        tier=current_user.tier,
        note="This is a development-only endpoint."
    )


@router.post("/make-admin", response_model=AdminStatusResponse)
async def make_admin(
    request: AdminToggleRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    DEV-ONLY ENDPOINT: Grant admin role to a user by email

    Only admin users can use this endpoint.

    Usage:
    ```
    curl -X POST http://localhost:8000/api/v1/users/make-admin \
      -H "Authorization: Bearer YOUR_JWT_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"email": "user@example.com"}'
    ```
    """
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email {request.email} not found"
        )

    logger.warning(f"Admin {current_user.email} granted admin role to {user.email}")

    user.is_admin = True
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return AdminStatusResponse(
        message=f"Successfully granted admin role to {user.email}",
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )


@router.post("/remove-admin", response_model=AdminStatusResponse)
async def remove_admin(
    request: AdminToggleRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    DEV-ONLY ENDPOINT: Revoke admin role from a user by email

    Only admin users can use this endpoint.

    Usage:
    ```
    curl -X POST http://localhost:8000/api/v1/users/remove-admin \
      -H "Authorization: Bearer YOUR_JWT_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"email": "user@example.com"}'
    ```
    """
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email {request.email} not found"
        )

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove admin role from yourself"
        )

    logger.warning(f"Admin {current_user.email} revoked admin role from {user.email}")

    user.is_admin = False
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return AdminStatusResponse(
        message=f"Successfully revoked admin role from {user.email}",
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )


@router.get("/tiers", tags=["users"])
async def get_available_tiers():
    """
    Get list of available tiers with their limits
    """
    return [
        {
            "name": "free",
            "price": 0,
            "max_duration": 30,
            "max_jobs_per_month": 3,
            "features": ["Basic voices", "30s max duration", "7-day file retention"]
        },
        {
            "name": "pro",
            "price": 19,
            "max_duration": 120,
            "max_jobs_per_month": 50,
            "features": ["All voices", "HD TTS", "120s max", "30-day retention", "Translation"]
        },
        {
            "name": "enterprise",
            "price": 99,
            "max_duration": 3600,
            "max_jobs_per_month": -1,
            "features": ["Unlimited duration", "Priority queue", "Custom branding", "90-day retention", "Dedicated support"]
        }
    ]
