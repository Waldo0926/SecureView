import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import to_database_utc, utc_now
from app.models.audit_chain_head import AuditChainHead
from app.models.audit_log import AuditLog


class AuditLogService:
    """Append audit events while holding the single chain-head row lock."""

    GENESIS_HASH = "0" * 64

    def __init__(self, db: Session, *, clock=utc_now) -> None:
        self.db = db
        self.clock = clock

    def build_log_hash(self, previous_hash: str | None, log_content: dict[str, Any]) -> str:
        previous = previous_hash or self.GENESIS_HASH
        canonical = json.dumps(
            log_content,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()

    @staticmethod
    def make_log_content(
        *,
        action: str,
        actor_user_id: int | None,
        created_at: datetime,
        description: str | None,
        ip_address: str | None,
        metadata: dict[str, Any] | None,
        resource_id: str | None,
        resource_type: str,
        result: str,
        target_user_id: int | None,
        user_agent: str | None,
    ) -> dict[str, Any]:
        database_created_at = to_database_utc(created_at)
        return {
            "action": action,
            "actor_user_id": actor_user_id,
            "created_at": database_created_at.isoformat(timespec="microseconds") + "Z",
            "description": description,
            "ip_address": ip_address,
            "metadata": {} if metadata is None else metadata,
            "resource_id": resource_id,
            "resource_type": resource_type,
            "result": result,
            "target_user_id": target_user_id,
            "user_agent": user_agent,
        }

    def append(
        self,
        *,
        action: str,
        result: str,
        actor_user_id: int | None = None,
        target_user_id: int | None = None,
        resource_type: str = "AUTH",
        resource_id: str | None = None,
        context_ip_address: str | None = None,
        context_user_agent: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        head = self.db.scalar(
            select(AuditChainHead).where(AuditChainHead.id == 1).with_for_update()
        )
        if head is None:  # pragma: no cover - migration invariant
            raise RuntimeError("The audit chain head has not been initialized")

        created_at = to_database_utc(self.clock())
        normalized_metadata = {} if metadata is None else metadata
        log_content = self.make_log_content(
            action=action,
            actor_user_id=actor_user_id,
            created_at=created_at,
            description=description,
            ip_address=context_ip_address,
            metadata=normalized_metadata,
            resource_id=resource_id,
            resource_type=resource_type,
            result=result,
            target_user_id=target_user_id,
            user_agent=context_user_agent,
        )
        previous_hash = head.current_hash or self.GENESIS_HASH
        current_hash = self.build_log_hash(previous_hash, log_content)

        audit_log = AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            target_user_id=target_user_id,
            result=result,
            ip_address=context_ip_address,
            user_agent=context_user_agent,
            description=description,
            metadata_json=normalized_metadata,
            previous_hash=previous_hash,
            current_hash=current_hash,
            created_at=created_at,
        )
        self.db.add(audit_log)
        self.db.flush()

        head.last_log_id = audit_log.id
        head.current_hash = current_hash
        head.updated_at = created_at
        return audit_log
