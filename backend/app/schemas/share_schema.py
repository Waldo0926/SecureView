from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.key_schema import Base64Value, decode_base64


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShareFileRequest(_StrictModel):
    target_user_id: UUID
    target_key_id: UUID
    wrapped_file_key: Base64Value = Field(repr=False)
    can_download: bool = True
    can_share: bool = False

    @model_validator(mode="after")
    def validate_wrapped_key(self) -> ShareFileRequest:
        decoded = decode_base64(self.wrapped_file_key, field_name="wrapped_file_key")
        if not 256 <= len(decoded) <= 512:
            raise ValueError("wrapped_file_key has an invalid decoded length")
        return self

    def wrapped_key_bytes(self) -> bytes:
        return decode_base64(self.wrapped_file_key, field_name="wrapped_file_key")


class ShareFileResponse(_StrictModel):
    file_id: UUID
    target_user_id: UUID
    target_key_id: UUID
    status: str
    created: bool


class SharedUserOut(_StrictModel):
    user_id: UUID
    username: str
    key_id: UUID
    can_download: bool
    can_share: bool
    is_owner: bool
    granted_at: datetime


class SharedUsersResponse(_StrictModel):
    file_id: UUID
    users: list[SharedUserOut]


class RevokeAccessRequest(_StrictModel):
    target_user_id: UUID


class RevokeAccessResponse(_StrictModel):
    file_id: UUID
    target_user_id: UUID
    revoked: bool
