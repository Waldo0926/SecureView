from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.time import to_database_utc
from app.domain.auth import ActorContext
from app.domain.enums import SystemRole
from app.domain.errors import AuthorizationError, FileResourceNotFoundError
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit_schema import AuditLogQuery
from app.services.audit_log_service import AuditLogService

_SAFE_METADATA_KEYS = {
    "can_download",
    "can_share",
    "changed",
    "evicted_sessions",
    "generation",
    "request_id",
    "revision",
    "revoked_sessions",
    "target_key_id",
    "target_user_id",
}


class AuditQueryService:
    def __init__(
        self,
        *,
        db: Session,
        repository: AuditRepository | None = None,
        audit_log_service: AuditLogService | None = None,
    ) -> None:
        self.db = db
        self.repository = repository or AuditRepository(db)
        self.audit_log_service = audit_log_service or AuditLogService(db)

    @staticmethod
    def safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        source = metadata or {}
        return {key: source[key] for key in sorted(source) if key in _SAFE_METADATA_KEYS}

    def list_logs(
        self,
        *,
        actor: ActorContext,
        limit: int,
        offset: int,
        file_id: UUID | None = None,
        filters: AuditLogQuery | None = None,
    ):
        admin = actor.role is SystemRole.ADMIN
        if (
            file_id is not None
            and not admin
            and not self.repository.can_access_file(actor.user_id, file_id)
        ):
            raise FileResourceNotFoundError()
        query = filters or AuditLogQuery()
        return self.repository.list_logs(
            actor_user_id=actor.user_id,
            admin=admin,
            limit=limit + 1,
            offset=offset,
            resource_id=str(file_id) if file_id is not None else None,
            action=query.action,
            result=query.result,
            # `audit_logs.created_at` is naive UTC (DATETIME(6)); the filter arrives aware.
            created_from=to_database_utc(query.from_time) if query.from_time else None,
            created_to=to_database_utc(query.to_time) if query.to_time else None,
            keyword=query.q,
        )

    def file_labels(self, rows) -> dict[str, tuple[str, bool]]:
        """Names for the files that rows already visible to the caller are about.

        Only rows about a file (a FILE, SHARE or INTEGRITY entry) are looked up, and only the ids
        in rows this caller was already allowed to read: no new row becomes visible, a row that
        was about a file just says which one.
        """
        ids = {
            log.resource_id
            for log, _actor, _target in rows
            if log.resource_type in ("FILE", "SHARE", "INTEGRITY") and log.resource_id
        }
        return self.repository.file_labels(ids)

    def verify_chain(self, *, actor: ActorContext) -> dict[str, int | bool | None | str]:
        if actor.role is not SystemRole.ADMIN:
            raise AuthorizationError()
        return self._verify_chain()

    def verify_chain_for_trusted_job(self) -> dict[str, int | bool | None | str]:
        """Verify the chain with no signed-in actor, for a server-side job run by the operator.

        Only scripts started on the server call this (the daily security-agent check). No HTTP
        route does, and a unit test fails if one starts to: over HTTP, `verify_chain` and its
        administrator check are the only way in. The result is the same verdict either way, and
        verifying writes nothing.
        """
        return self._verify_chain()

    def _verify_chain(self) -> dict[str, int | bool | None | str]:
        logs, head = self.repository.chain_rows()
        previous_hash = self.audit_log_service.GENESIS_HASH
        for position, log in enumerate(logs, start=1):
            content = self.audit_log_service.make_log_content(
                action=log.action,
                actor_user_id=log.actor_user_id,
                created_at=log.created_at,
                description=log.description,
                ip_address=log.ip_address,
                metadata=log.metadata_json,
                resource_id=log.resource_id,
                resource_type=log.resource_type,
                result=log.result,
                target_user_id=log.target_user_id,
                user_agent=log.user_agent,
            )
            expected = self.audit_log_service.build_log_hash(previous_hash, content)
            if log.previous_hash != previous_hash or log.current_hash != expected:
                return {
                    "status": "INVALID",
                    "valid": False,
                    "checked_entries": position - 1,
                    "first_invalid_position": position,
                }
            previous_hash = log.current_hash

        expected_last_id = logs[-1].id if logs else None
        if (
            head is None
            or head.last_log_id != expected_last_id
            or head.current_hash != previous_hash
        ):
            return {
                "status": "INVALID",
                "valid": False,
                "checked_entries": len(logs),
                "first_invalid_position": len(logs) + 1,
            }
        return {
            "status": "VALID",
            "valid": True,
            "checked_entries": len(logs),
            "first_invalid_position": None,
        }
