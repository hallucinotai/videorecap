from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_db
from app.core.oauth import GoogleOAuthError, verify_google_token
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models.user import User
from app.schemas.auth import (
    AssemblyAIKeyRequest,
    FeatureFlagsResponse,
    GoogleAuthRequest,
    LoginRequest,
    OpenAIKeyRequest,
    OTPResendRequest,
    OTPVerifyRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserResponse,
)
from app.services import user_service
from app.services.email_service import send_otp_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    existing = await user_service.get_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = await user_service.create_user(db, body.email, body.password, body.full_name)
    send_otp_email(user.email, user.otp_code)
    return SignupResponse(
        message="Verification code sent to your email",
        email=user.email,
    )


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(body: OTPVerifyRequest, db: AsyncSession = Depends(get_db)):
    user = await user_service.verify_otp(db, body.email, body.code)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/resend-otp")
async def resend_otp(body: OTPResendRequest, db: AsyncSession = Depends(get_db)):
    otp = await user_service.resend_otp(db, body.email)
    if not otp:
        raise HTTPException(status_code=400, detail="Account not found or already verified")
    send_otp_email(body.email, otp)
    return {"message": "Verification code sent"}


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await user_service.authenticate_user(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.email_verified:
        otp = await user_service.resend_otp(db, body.email)
        if otp:
            send_otp_email(body.email, otp)
        raise HTTPException(status_code=403, detail="Email not verified. A new code has been sent to your email.")
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = await user_service.get_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/google", response_model=TokenResponse)
async def google_auth(body: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    try:
        google_user = verify_google_token(body.token)
    except GoogleOAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user, was_linked = await user_service.get_or_create_google_user(
        db, google_user["sub"], google_user["email"], google_user["name"]
    )
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        accounts_linked=was_linked,
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse.from_user(current_user)


@router.get("/feature-flags", response_model=FeatureFlagsResponse)
async def feature_flags(current_user: User = Depends(get_current_user)):
    from app.config import settings
    requires_openai = user_service.user_requires_api_key(current_user.email)
    requires_assemblyai = settings.REQUIRE_ASSEMBLYAI_KEY
    return FeatureFlagsResponse(
        requires_openai_api_key=requires_openai,
        requires_assemblyai_key=requires_assemblyai
    )


@router.put("/me/openai-key", status_code=status.HTTP_200_OK)
async def set_openai_key(
    body: OpenAIKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not body.openai_api_key or not body.openai_api_key.strip():
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    await user_service.update_openai_key(db, current_user.id, body.openai_api_key.strip())
    return {"detail": "OpenAI API key saved"}


@router.delete("/me/openai-key", status_code=status.HTTP_200_OK)
async def remove_openai_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await user_service.clear_openai_key(db, current_user.id)
    return {"detail": "OpenAI API key removed"}


@router.put("/me/assemblyai-key", status_code=status.HTTP_200_OK)
async def set_assemblyai_key(
    body: AssemblyAIKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not body.assemblyai_api_key or not body.assemblyai_api_key.strip():
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    await user_service.update_assemblyai_key(db, current_user.id, body.assemblyai_api_key.strip())
    return {"detail": "AssemblyAI API key saved"}


@router.delete("/me/assemblyai-key", status_code=status.HTTP_200_OK)
async def remove_assemblyai_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await user_service.clear_assemblyai_key(db, current_user.id)
    return {"detail": "AssemblyAI API key removed"}
