from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import to_api_utc, to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext, RequestContext
from app.domain.errors import (
    AvatarNotFoundError,
    AvatarUpdateRateLimitedError,
    ResourceNotFoundError,
)
from app.models.user import User
from app.services.audit_log_service import AuditLogService
from app.services.avatar_storage_service import AvatarStorageService


@dataclass(frozen=True, slots=True)
class AvatarMeta:
    has_avatar: bool
    content_type: str | None
    updated_at: datetime | None
    size_bytes: int | None


@dataclass(frozen=True, slots=True)
class AvatarBytes:
    content_type: str
    body: bytes
    sha256: str


class AvatarService:
    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        storage: AvatarStorageService | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.storage = storage or AvatarStorageService(settings=settings)
        self.audit = audit_service or AuditLogService(db)

    def _lock_user(self, user_id: int) -> User:
        user = self.db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:  # pragma: no cover
            raise ResourceNotFoundError("Account not found")
        return user

    async def upload(
        self,
        *,
        actor: ActorContext,
        upload: UploadFile,
        context: RequestContext,
    ) -> AvatarMeta:
        user = self._lock_user(actor.user_id)
        now = to_second_resolution_utc(utc_now())
        if user.avatar_updated_at is not None:
            earliest = user.avatar_updated_at + timedelta(
                seconds=self.settings.AVATAR_MIN_INTERVAL_SECONDS
            )
            if now < earliest:
                retry_after = max(1, int((earliest - now).total_seconds()))
                raise AvatarUpdateRateLimitedError(retry_after_seconds=retry_after)

        stored = await self.storage.store(upload, user_uuid=UUID(user.user_uuid))
        previous_key = user.avatar_object_key
        user.avatar_object_key = stored.object_key
        user.avatar_content_type = stored.content_type
        user.avatar_sha256 = stored.sha256
        user.avatar_bytes = stored.size_bytes
        user.avatar_updated_at = now
        self.audit.append(
            action="AVATAR_UPLOADED",
            result="SUCCESS",
            actor_user_id=actor.user_id,
            target_user_id=actor.user_id,
            resource_type="USER",
            resource_id=user.user_uuid,
            context_ip_address=context.ip_address,
            context_user_agent=context.user_agent,
            metadata={"content_type": stored.content_type, "bytes": stored.size_bytes},
        )
        self.db.commit()
        if previous_key and previous_key != stored.object_key:
            await self.storage.delete(previous_key)
        return AvatarMeta(
            has_avatar=True,
            content_type=stored.content_type,
            updated_at=to_api_utc(now),
            size_bytes=stored.size_bytes,
        )

    async def get_bytes(self, *, actor: ActorContext) -> AvatarBytes:
        user = self.db.scalar(select(User).where(User.id == actor.user_id))
        if user is None or not user.avatar_object_key or not user.avatar_content_type:
            raise AvatarNotFoundError()
        try:
            body = await self.storage.read(user.avatar_object_key)
        except FileNotFoundError as exc:
            raise AvatarNotFoundError() from exc
        return AvatarBytes(
            content_type=user.avatar_content_type,
            body=body,
            sha256=user.avatar_sha256 or "",
        )

    async def delete(
        self,
        *,
        actor: ActorContext,
        context: RequestContext,
    ) -> AvatarMeta:
        user = self._lock_user(actor.user_id)
        previous_key = user.avatar_object_key
        if previous_key is None:
            return AvatarMeta(
                has_avatar=False,
                content_type=None,
                updated_at=None,
                size_bytes=None,
            )
        user.avatar_object_key = None
        user.avatar_content_type = None
        user.avatar_sha256 = None
        user.avatar_bytes = None
        user.avatar_updated_at = None
        self.audit.append(
            action="AVATAR_DELETED",
            result="SUCCESS",
            actor_user_id=actor.user_id,
            target_user_id=actor.user_id,
            resource_type="USER",
            resource_id=user.user_uuid,
            context_ip_address=context.ip_address,
            context_user_agent=context.user_agent,
            metadata={},
        )
        self.db.commit()
        await self.storage.delete(previous_key)
        return AvatarMeta(
            has_avatar=False,
            content_type=None,
            updated_at=None,
            size_bytes=None,
        )
