from datetime import UTC, datetime
from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.services.audit_log_service import AuditLogService


def _content(
    service: AuditLogService,
    *,
    metadata: dict[str, object] | None,
) -> dict[str, object]:
    return service.make_log_content(
        action="AUTH_TESTED",
        actor_user_id=17,
        created_at=datetime(2026, 8, 4, 12, 30, 15, 654321, tzinfo=UTC),
        description=None,
        ip_address="203.0.113.10",
        metadata=metadata,
        resource_id="resource-1",
        resource_type="AUTH",
        result="SUCCESS",
        target_user_id=17,
        user_agent="audit-test",
    )


def test_none_and_empty_metadata_have_one_canonical_hash_representation() -> None:
    service = AuditLogService(Mock(spec=Session))

    content_from_none = _content(service, metadata=None)
    content_from_empty_object = _content(service, metadata={})

    assert content_from_none == content_from_empty_object
    assert content_from_none["metadata"] == {}
    assert content_from_none["created_at"] == "2026-08-04T12:30:15.654321Z"
    assert service.build_log_hash(None, content_from_none) == service.build_log_hash(
        None,
        content_from_empty_object,
    )
