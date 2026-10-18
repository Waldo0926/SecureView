from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.enums import SessionStatus, SystemRole, UserStatus


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Trusted request metadata collected at the HTTP boundary."""

    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    id: UUID
    username: str
    email: str
    role: SystemRole
    status: UserStatus
    email_verified: bool
    created_at: datetime
    last_login_at: datetime | None = None
    has_avatar: bool = False
    # Set by an administrator's password reset; cleared when the holder sets their own.
    must_change_password: bool = False


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Authenticated identity derived only from a validated server-side session."""

    user_id: int
    user_public_id: UUID
    session_id: int
    session_public_id: UUID
    role: SystemRole
    status: UserStatus
    access_token_hash: str = field(repr=False)
    # Set by an administrator's password reset. `get_current_actor` refuses every route
    # outside a short allow-list while it is set.
    must_change_password: bool = False


@dataclass(frozen=True, slots=True)
class TokenPair:
    session_id: UUID
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_expires_at: datetime
    refresh_expires_at: datetime
    token_type: str = "bearer"


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    user: AccountSnapshot
    key_id: UUID
    public_key_fingerprint: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: AccountSnapshot
    tokens: TokenPair = field(repr=False)


@dataclass(frozen=True, slots=True)
class RefreshResult:
    tokens: TokenPair = field(repr=False)


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    id: UUID
    status: SessionStatus
    current: bool
    created_at: datetime
    access_expires_at: datetime
    absolute_expires_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SessionListResult:
    sessions: tuple[SessionSnapshot, ...]


@dataclass(frozen=True, slots=True)
class RevocationResult:
    revoked_sessions: int


@dataclass(frozen=True, slots=True)
class PasswordChangeResult:
    revoked_sessions: int
    reauthentication_required: bool = True
