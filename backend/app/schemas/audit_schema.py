from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Every action the services write. The filter on `GET /audit-logs` only accepts one of these,
# so a typo or a probe for an action that does not exist is a 422 rather than an empty page
# that looks like "nothing happened". A unit test scans `app/` and `scripts/` for the action
# literals the code writes and fails when one is missing here, so the list cannot drift.
AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "ACCOUNT_DELETED",
        "ACCOUNT_DELETION_PASSWORD_FAILED",
        "ADMIN_PASSWORD_RESET",
        "AUTH_ALL_SESSIONS_REVOKED",
        "AUTH_LOGGED_OUT",
        "AUTH_LOGIN_FAILED",
        "AUTH_LOGIN_SUCCEEDED",
        "AUTH_PASSWORD_CHANGED",
        "AUTH_PASSWORD_CHANGE_FAILED",
        "AUTH_PASSWORD_RESET",
        "AUTH_REFRESH_REJECTED",
        "AUTH_REFRESH_REPLAY_DETECTED",
        "AUTH_REGISTERED",
        "AUTH_SESSION_EXPIRED",
        "AUTH_SESSION_REFRESHED",
        "AUTH_SESSION_REVOKED",
        "AUTH_VERIFICATION_CODE_SENT",
        "AVATAR_DELETED",
        "AVATAR_UPLOADED",
        "FILE_ACCESS_REVOKED",
        "FILE_CIPHERTEXT_PREVIEWED",
        "FILE_DELETED",
        "FILE_DOWNLOAD_AUTHORIZED",
        "FILE_DOWNLOAD_INTEGRITY_FAILED",
        "FILE_INTEGRITY_CHECKED",
        "FILE_RESTORED_FROM_BACKUP",
        "FILE_SHARED",
        "FILE_UPLOADED",
        "INTEGRITY_SWEEP_COMPLETED",
        "KEY_PROTECTION_RESET_WITH_PRIVATE_KEY",
        "KEY_PROTECTION_REWRAPPED",
        "RECOVERY_KEY_REGISTERED",
        "RECOVERY_KEY_REVOKED",
        "RECOVERY_KEY_ROTATED",
        "RECOVERY_REQUEST_APPROVED",
        "RECOVERY_REQUEST_CANCELLED",
        "RECOVERY_REQUEST_CREATED",
        "RECOVERY_REQUEST_EXECUTED",
        "RECOVERY_REQUEST_REJECTED",
        "USER_DISABLED",
        "USER_ENABLED",
        "USER_KEY_ADDED",
    }
)

AUDIT_KEYWORD_MAX_LENGTH = 100


class AuditLogQuery(_StrictModel):
    """The query string of `GET /audit-logs`: the page, plus optional filters.

    Every filter narrows the page the caller could already see; none of them widens it. The
    visibility rule (own actions, actions on you, anything done to a file you own) is applied
    by the repository first and these are added on top, so a filtered page is always a subset
    of the unfiltered one for the same caller.

    `limit` and `offset` live here too because FastAPI only expands a model into query
    parameters when it is the route's sole query argument. An unknown query key is still
    ignored, as before, so an old client that sends extra keys keeps working.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    action: str | None = Field(
        default=None,
        description="One event type, exactly as the API writes it (for example FILE_SHARED).",
    )
    result: Literal["SUCCESS", "FAIL"] | None = Field(
        default=None, description="Only successful or only failed events."
    )
    from_time: datetime | None = Field(
        default=None,
        alias="from",
        description="Earliest `created_at` to include, ISO 8601 in UTC. Inclusive.",
    )
    to_time: datetime | None = Field(
        default=None,
        alias="to",
        description="Latest `created_at` to include, ISO 8601 in UTC. Inclusive.",
    )
    q: str | None = Field(
        default=None,
        max_length=AUDIT_KEYWORD_MAX_LENGTH,
        description="Keyword matched against the description and the file name, case-insensitive.",
    )

    @field_validator("action")
    @classmethod
    def _known_action(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in AUDIT_ACTIONS:
            raise ValueError("unknown audit action")
        return value

    @field_validator("from_time", "to_time")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        # A bare timestamp is taken as UTC, which is the only zone the API speaks; anything
        # with an offset is converted so the comparison against the UTC column is exact.
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("q")
    @classmethod
    def _trimmed_keyword(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def _ordered_window(self) -> AuditLogQuery:
        if (
            self.from_time is not None
            and self.to_time is not None
            and self.from_time > self.to_time
        ):
            raise ValueError("from must not be later than to")
        return self

    @property
    def is_empty(self) -> bool:
        """No filter at all: the plain page the route has always served."""
        return (
            self.action is None
            and self.result is None
            and self.from_time is None
            and self.to_time is None
            and self.q is None
        )


class AuditLogOut(_StrictModel):
    action: str
    resource_type: str
    resource_id: str | None = None
    actor_user_id: UUID | None = None
    # The names cost nothing: the router already has both User rows joined in hand, and a
    # UUID cannot be read by the person looking at their own history. Without them the page
    # can only say "someone", which is the one thing an audit trail must not say.
    actor_username: str | None = None
    target_user_id: UUID | None = None
    target_username: str | None = None
    result: str
    description: str | None = None
    metadata: dict[str, Any]
    created_at: datetime
    # For a row about a file: its original name, and whether the file has since been deleted. A
    # deleted file is a soft delete, so the name is still known; the page labels it "Deleted"
    # instead of asking the file endpoint (which answers 404 for it) one file at a time.
    file_name: str | None = None
    file_deleted: bool = False


class AuditLogListResponse(_StrictModel):
    logs: list[AuditLogOut]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    has_more: bool


class FileAuditLogListResponse(AuditLogListResponse):
    file_id: UUID


class AuditChainVerificationResponse(_StrictModel):
    status: str
    valid: bool
    checked_entries: int = Field(ge=0)
    first_invalid_position: int | None = Field(default=None, ge=1)
