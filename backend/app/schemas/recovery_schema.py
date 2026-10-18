from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.key_schema import Base64Value, decode_base64

RecoveryStatus = Literal["PENDING", "APPROVED", "REJECTED", "EXECUTED", "CANCELLED"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RecoveryRequestCreate(_StrictModel):
    file_id: UUID
    reason: str = Field(min_length=1, max_length=2000)
    target_key_id: UUID


class RecoveryRejectRequest(_StrictModel):
    rejection_reason: str = Field(min_length=1, max_length=2000)


class RecoveryExecuteRequest(_StrictModel):
    """Result of an offline recovery-key unwrap and requester-key rewrap.

    A recovery private key is deliberately not part of this transport contract.
    """

    wrapped_file_key: Base64Value = Field(repr=False)
    recovery_key_id: UUID
    target_key_id: UUID

    @field_validator("wrapped_file_key")
    @classmethod
    def validate_wrapped_file_key(cls, value: str) -> str:
        decoded = decode_base64(value, field_name="wrapped_file_key")
        if len(decoded) not in {256, 384, 512}:
            raise ValueError("wrapped_file_key must be an RSA ciphertext")
        return value

    def wrapped_key_bytes(self) -> bytes:
        return decode_base64(self.wrapped_file_key, field_name="wrapped_file_key")


class RecoveryPublicKeyRegisterRequest(_StrictModel):
    key_id: UUID
    public_key_pem: str = Field(min_length=200, max_length=8000)
    algorithm: Literal["RSA-OAEP-SHA256"] = "RSA-OAEP-SHA256"

    @field_validator("public_key_pem")
    @classmethod
    def require_public_key_only(cls, value: str) -> str:
        normalized = value.strip()
        if "PRIVATE KEY" in normalized:
            raise ValueError("public_key_pem must contain only a public key")
        return normalized + "\n"


class RecoveryPublicKeyOut(_StrictModel):
    key_id: UUID
    algorithm: Literal["RSA-OAEP-SHA256"]
    key_size_bits: Literal[2048, 3072, 4096]
    public_key_pem: str
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["ACTIVE", "REVOKED"]
    created_at: datetime


class RecoveryKeyRegistrationResponse(_StrictModel):
    key: RecoveryPublicKeyOut
    created: bool
    rotated_keys: int = Field(ge=0)


class RecoveryKeyStatusResponse(_StrictModel):
    key_id: UUID
    status: Literal["REVOKED"]
    changed: bool


class RecoveryRequestOut(_StrictModel):
    request_id: UUID
    file_id: UUID
    requested_by: UUID
    target_key_id: UUID
    reviewer_id: UUID | None = None
    executor_id: UUID | None = None
    reason: str
    rejection_reason: str | None = None
    status: RecoveryStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    executed_at: datetime | None = None
    cancelled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_public_status_shape(self) -> RecoveryRequestOut:
        if self.status == "PENDING" and any(
            value is not None
            for value in (
                self.approved_at,
                self.rejected_at,
                self.executed_at,
                self.cancelled_at,
            )
        ):
            raise ValueError("PENDING recovery request contains a terminal timestamp")
        return self


class RecoveryRequestActionResponse(_StrictModel):
    request: RecoveryRequestOut
    changed: bool


class RecoveryExecutionKeyOut(_StrictModel):
    key_id: UUID
    algorithm: Literal["RSA-OAEP-SHA256"]
    key_size_bits: Literal[2048, 3072, 4096]
    public_key_pem: str
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecoveryExecutionPackageOut(_StrictModel):
    request_id: UUID
    file_id: UUID
    requester_id: UUID
    expires_at: datetime
    recovery_key: RecoveryExecutionKeyOut
    recovery_wrapped_file_key: str = Field(repr=False)
    target_key: RecoveryExecutionKeyOut


class RecoveryRequestListResponse(_StrictModel):
    requests: list[RecoveryRequestOut]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
