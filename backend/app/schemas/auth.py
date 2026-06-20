from datetime import datetime

from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    accounts_linked: bool = False


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    auth_provider: str
    is_active: bool
    tier: str
    is_admin: bool
    has_openai_key: bool = False
    has_assemblyai_key: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            auth_provider=user.auth_provider,
            is_active=user.is_active,
            tier=user.tier,
            is_admin=user.is_admin,
            has_openai_key=user.encrypted_openai_key is not None,
            has_assemblyai_key=user.encrypted_assemblyai_key is not None,
            created_at=user.created_at,
        )


class FeatureFlagsResponse(BaseModel):
    requires_openai_api_key: bool
    requires_assemblyai_key: bool = True  # AssemblyAI is required by default for speaker diarization


class OpenAIKeyRequest(BaseModel):
    openai_api_key: str


class AssemblyAIKeyRequest(BaseModel):
    assemblyai_api_key: str


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class OTPResendRequest(BaseModel):
    email: EmailStr


class SignupResponse(BaseModel):
    message: str
    email: str
    requires_verification: bool = True
