from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.domain.enums import SessionStatus, SystemRole, UserStatus, VerificationPurpose
from app.schemas.key_schema import ClientKeyRegistrationIn

VERIFICATION_CODE_PATTERN = r"^[0-9]{6,10}$"


def _normalize_verification_code(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().replace(" ", "")
    return value


class _AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _AuthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


def _normalize_password(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    return value


def _normalize_username(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _validate_username(value: str) -> str:
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if any(char not in allowed_chars for char in value):
        raise ValueError("Username can only contain letters, numbers, underscore, dot, and hyphen")
    return value


class AuthUserResponse(_AuthResponse):
    id: UUID
    username: str
    email: EmailStr
    role: SystemRole
    status: UserStatus
    email_verified: bool
    created_at: datetime
    last_login_at: datetime | None = None
    has_avatar: bool = False
    # True after an administrator reset the login password, until the holder sets their own.
    # The frontend sends the holder to Settings on it; no API is refused because of it.
    must_change_password: bool = False


class AvatarMetaResponse(_AuthResponse):
    has_avatar: bool
    content_type: str | None = None
    updated_at: datetime | None = None
    size_bytes: int | None = None


class SendVerificationCodeRequest(_AuthRequest):
    email: EmailStr = Field(max_length=255)
    purpose: VerificationPurpose

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()


class SendVerificationCodeResponse(_AuthResponse):
    """Deliberately uniform. A caller cannot tell whether the address exists."""

    code_sent: bool = True
    expires_in_seconds: int = Field(ge=1)
    resend_available_in_seconds: int = Field(ge=1)


class UserRegisterRequest(_AuthRequest):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr = Field(max_length=255)
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        repr=False,
    )
    verification_code: str = Field(pattern=VERIFICATION_CODE_PATTERN, repr=False)
    key_material: ClientKeyRegistrationIn = Field(repr=False)

    _strip_username = field_validator("username", mode="before")(_normalize_username)
    _check_username = field_validator("username")(_validate_username)
    _normalize_password = field_validator("password", mode="before")(_normalize_password)
    _strip_code = field_validator("verification_code", mode="before")(_normalize_verification_code)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()


class UserRegisterResponse(_AuthResponse):
    user: AuthUserResponse
    key_id: UUID
    public_key_fingerprint: str


class UserLoginRequest(_AuthRequest):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH, repr=False)

    _strip_username = field_validator("username", mode="before")(_normalize_username)
    _check_username = field_validator("username")(_validate_username)
    _normalize_password = field_validator("password", mode="before")(_normalize_password)


class UserLoginResponse(_AuthResponse):
    user: AuthUserResponse
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    access_expires_at: datetime
    refresh_expires_at: datetime
    session_id: UUID


class AuthRefreshRequest(_AuthRequest):
    refresh_token: str = Field(min_length=1, max_length=512, repr=False)


class AuthRefreshResponse(_AuthResponse):
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    access_expires_at: datetime
    refresh_expires_at: datetime
    session_id: UUID


class AuthMeResponse(_AuthResponse):
    user: AuthUserResponse


class UserLogoutResponse(_AuthResponse):
    logged_out: bool = True


class UserLogoutAllResponse(_AuthResponse):
    revoked_sessions: int = Field(ge=0)


class DeleteAccountRequest(_AuthRequest):
    """Closing the account requires the password again, not just a live session.

    `confirmation` must be the literal word so the request cannot be produced by a stray
    click or a replayed body -- the caller has to have meant this specific thing.
    """

    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH, repr=False)
    confirmation: Literal["DELETE"]


class DeleteAccountResponse(_AuthResponse):
    files_deleted: int = Field(ge=0)
    sessions_revoked: int = Field(ge=0)


class ChangePasswordRequest(_AuthRequest):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH, repr=False)
    new_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        repr=False,
    )

    _normalize_current_password = field_validator("current_password", mode="before")(
        _normalize_password
    )
    _normalize_new_password = field_validator("new_password", mode="before")(_normalize_password)


class ChangePasswordResponse(_AuthResponse):
    password_changed: bool = True
    revoked_sessions: int = Field(ge=0)
    reauthentication_required: bool = True


class PasswordResetRequest(_AuthRequest):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr = Field(max_length=255)
    verification_code: str = Field(pattern=VERIFICATION_CODE_PATTERN, repr=False)
    new_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        repr=False,
    )

    _strip_username = field_validator("username", mode="before")(_normalize_username)
    _check_username = field_validator("username")(_validate_username)
    _normalize_new_password = field_validator("new_password", mode="before")(_normalize_password)
    _strip_code = field_validator("verification_code", mode="before")(_normalize_verification_code)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()


class PasswordResetResponse(_AuthResponse):
    password_reset: bool = True
    revoked_sessions: int = Field(ge=0)
    # Resetting the login password never touches the client-held encryption
    # passphrase, so existing key envelopes stay usable.
    key_envelopes_unchanged: Literal[True] = True


class AuthSessionResponse(_AuthResponse):
    session_id: UUID = Field(validation_alias=AliasChoices("session_id", "id", "session_uuid"))
    status: SessionStatus
    current: bool
    created_at: datetime
    access_expires_at: datetime
    absolute_expires_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    revoked_at: datetime | None = None


class AuthSessionListResponse(_AuthResponse):
    sessions: list[AuthSessionResponse]


class AuthSessionRevokeResponse(_AuthResponse):
    session_id: UUID
    revoked: bool = True
