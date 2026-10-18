from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import SystemRole, UserStatus


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminUserOut(_StrictModel):
    user_id: UUID
    username: str
    email: str | None = None
    email_verified: bool | None = None
    role: SystemRole
    status: UserStatus
    created_at: datetime
    last_login_at: datetime | None = None
    password_changed_at: datetime | None = None


class AdminUserDetailOut(AdminUserOut):
    """One account as an administrator sees it. No password, hash or key material: the login
    password is stored only as a one-way hash, and the encryption passphrase never reaches the
    server at all."""

    file_count: int = Field(ge=0)
    stored_bytes: int = Field(ge=0)
    shared_by_them: int = Field(ge=0)
    shared_with_them: int = Field(ge=0)
    active_sessions: int = Field(ge=0)


class AdminPasswordResetOut(_StrictModel):
    user_id: UUID
    username: str
    # Shown once, to the administrator who asked for it, and never stored in clear.
    temporary_password: str
    revoked_sessions: int = Field(ge=0)
    notice_sent: bool


class AdminUserListResponse(_StrictModel):
    users: list[AdminUserOut]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    has_more: bool


class AdminFileOut(_StrictModel):
    file_id: UUID
    owner_id: UUID
    owner_username: str
    original_filename: str
    mime_type: str | None = None
    file_size: int
    encrypted_size: int | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class AdminFileListResponse(_StrictModel):
    files: list[AdminFileOut]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    has_more: bool


class AdminUserStatusResponse(_StrictModel):
    user_id: UUID
    status: UserStatus
    changed: bool
    revoked_sessions: int = Field(ge=0)


class AdminUserStats(_StrictModel):
    total: int = Field(ge=0)
    active: int = Field(ge=0)
    disabled: int = Field(ge=0)
    deleted: int = Field(ge=0)
    administrators: int = Field(ge=0)
    created_last_7_days: int = Field(ge=0)
    signed_in_last_24_hours: int = Field(ge=0)


class AdminFileStats(_StrictModel):
    """Counts of files that exist (not deleted), plus how many were deleted along the way."""

    total: int = Field(ge=0)
    active: int = Field(ge=0)
    corrupted: int = Field(ge=0)
    deleted: int = Field(ge=0)
    uploaded_last_24_hours: int = Field(ge=0)
    original_bytes: int = Field(ge=0)
    stored_bytes: int = Field(ge=0)
    by_algorithm: dict[str, int]


class AdminShareStats(_StrictModel):
    active_shares: int = Field(ge=0)
    files_shared: int = Field(ge=0)


class AdminIntegrityStats(_StrictModel):
    checks_last_24_hours: int = Field(ge=0)
    failed_checks_last_24_hours: int = Field(ge=0)


class AdminRecoveryStats(_StrictModel):
    pending_requests: int = Field(ge=0)


class AdminAuditEventOut(_StrictModel):
    action: str
    result: str
    created_at: datetime
    actor_username: str | None = None


class AdminAuditStats(_StrictModel):
    events_total: int = Field(ge=0)
    events_last_24_hours: int = Field(ge=0)
    failures_last_24_hours: int = Field(ge=0)
    recent_failures: list[AdminAuditEventOut]


class AdminStatsOut(_StrictModel):
    """A point-in-time summary for the administrator dashboard.

    Counts only. No file name, no key material, no IP address and no event metadata appears
    here: the dashboard answers "how big and how healthy", and the audit log answers "who".
    """

    generated_at: datetime
    users: AdminUserStats
    files: AdminFileStats
    shares: AdminShareStats
    integrity: AdminIntegrityStats
    recovery: AdminRecoveryStats
    audit: AdminAuditStats


class AdminDamagedFileOut(_StrictModel):
    """One file whose stored ciphertext is not known to be intact, and what was last seen."""

    file_id: UUID
    owner_username: str
    original_filename: str
    status: str
    last_result: str | None = None
    last_message: str | None = None
    last_checked_at: datetime | None = None


class AdminIntegrityCoverage(_StrictModel):
    """How much of the store has actually been looked at, and when the last automatic pass was."""

    candidates: int = Field(ge=0)
    never_checked: int = Field(ge=0)
    checked_last_24_hours: int = Field(ge=0)
    last_sweep_at: datetime | None = None


class AdminIntegrityReportOut(_StrictModel):
    generated_at: datetime
    coverage: AdminIntegrityCoverage
    damaged: list[AdminDamagedFileOut]
    has_more: bool


class AdminIntegrityScanOut(_StrictModel):
    scanned: int = Field(ge=0)
    valid: int = Field(ge=0)
    damaged: int = Field(ge=0)
    candidates: int = Field(ge=0)
    stopped_early: bool
    damaged_file_ids: list[UUID]
