from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import (
    FileResourceNotFoundError,
    RecoveryStateConflictError,
)
from app.repositories.recovery_repository import (
    RecoveryExecutionRecord,
    RecoveryRepository,
    RecoveryRequestLocator,
)
from app.schemas.recovery_schema import (
    RecoveryExecuteRequest,
    RecoveryPublicKeyRegisterRequest,
)
from app.services.recovery_service import RecoveryService

NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
NOW_DB = NOW.replace(tzinfo=None)
REQUEST_ID = UUID("11111111-1111-4111-8111-111111111111")
FILE_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_ID = UUID("33333333-3333-4333-8333-333333333333")
SESSION_ID = UUID("44444444-4444-4444-8444-444444444444")
TARGET_KEY_ID = UUID("55555555-5555-4555-8555-555555555555")
RECOVERY_KEY_ID = UUID("66666666-6666-4666-8666-666666666666")
CONTEXT = RequestContext(ip_address="203.0.113.20", user_agent="recovery-test")


def _actor(*, user_id: int = 7, role: SystemRole = SystemRole.USER) -> ActorContext:
    return ActorContext(
        user_id=user_id,
        user_public_id=USER_ID,
        session_id=9,
        session_public_id=SESSION_ID,
        role=role,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(self, **event: Any) -> None:
        self.events.append(event)


class FakeCrypto:
    def __init__(self) -> None:
        self.validations: list[tuple[bytes, str]] = []

    def validate_wrapped_file_key(self, wrapped: bytes, public_key_pem: str) -> None:
        self.validations.append((wrapped, public_key_pem))

    def load_rsa_public_key(self, public_key_pem: str):
        return SimpleNamespace(key_size=3072)

    def public_key_fingerprint(self, public_key_pem: str) -> str:
        return "f" * 64


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.file = None
        self.grant = None
        self.target_key = None
        self.active_user_wrapping = None
        self.active_recovery_wrapping = None
        self.pending_request = None
        self.request_locator: RecoveryRequestLocator | None = None
        self.request = None
        self.user_wrappings: list[Any] = []
        self.recovery_source = None
        self.added_requests: list[Any] = []
        self.added_wrappings: list[Any] = []
        self.request_record = None
        self.has_download_entitlement = True
        self.execution_record: RecoveryExecutionRecord | None = None
        self.list_requested_by: int | object | None = object()
        self.active_recovery_keys: list[Any] = []
        self.recovery_key_by_uuid = None
        self.recovery_key_by_fingerprint = None
        self.added_recovery_keys: list[Any] = []

    def lock_file(self, file_id: UUID):
        assert file_id == FILE_ID
        self.calls.append("file")
        return self.file

    def lock_file_by_id(self, file_id: int):
        assert self.file is None or file_id == self.file.id
        self.calls.append("file")
        return self.file

    def lock_grant(self, file_id: int, user_id: int):
        self.calls.append("grant")
        return self.grant

    def lock_active_target_key(self, user_id: int, key_id: UUID):
        assert key_id == TARGET_KEY_ID
        self.calls.append("target_key")
        return self.target_key

    def lock_active_user_wrapping(self, file_id: int, user_id: int):
        self.calls.append("active_user_wrapping")
        return self.active_user_wrapping

    def lock_active_recovery_wrapping(self, file_id: int):
        self.calls.append("active_recovery_wrapping")
        return self.active_recovery_wrapping

    def lock_pending_request(self, *, file_id: int, requested_by: int, now: datetime):
        self.calls.append("pending_request")
        return self.pending_request

    def add_request(self, request) -> None:
        self.added_requests.append(request)

    def get_request_record(self, request_id: UUID):
        return self.request_record or SimpleNamespace(request=self.added_requests[-1])

    def get_request_locator(self, request_id: UUID):
        assert request_id == REQUEST_ID
        self.calls.append("request_locator")
        return self.request_locator

    def lock_user_wrappings(self, file_id: int, user_id: int):
        self.calls.append("user_wrappings")
        return list(self.user_wrappings)

    def lock_recovery_source(self, *, file_id: int, recovery_key_id: UUID):
        assert recovery_key_id == RECOVERY_KEY_ID
        self.calls.append("recovery_source")
        return self.recovery_source

    def lock_request(self, request_id: UUID):
        assert request_id == REQUEST_ID
        self.calls.append("request")
        return self.request

    def add_wrapping(self, wrapping) -> None:
        self.added_wrappings.append(wrapping)

    def get_execution_record(self, request_id: UUID):
        assert request_id == REQUEST_ID
        return self.execution_record

    def has_active_download_entitlement(self, file_id: int, user_id: int) -> bool:
        assert self.execution_record is not None
        assert file_id == self.execution_record.file.id
        assert user_id == self.execution_record.request.requested_by
        return self.has_download_entitlement

    def list_request_records(self, *, requested_by: int | None, offset: int, limit: int):
        self.list_requested_by = requested_by
        assert offset == 0
        assert limit == 50
        return [], 0

    def get_recovery_key_by_uuid(self, key_id: UUID, *, for_update: bool = False):
        return self.recovery_key_by_uuid

    def get_recovery_key_by_fingerprint(self, fingerprint: str):
        return self.recovery_key_by_fingerprint

    def lock_active_recovery_keys(self):
        return list(self.active_recovery_keys)

    def add_recovery_key(self, key) -> None:
        self.added_recovery_keys.append(key)

    def flush(self) -> None:
        for index, key in enumerate(self.added_recovery_keys, start=100):
            key.id = index
        for index, wrapping in enumerate(self.added_wrappings, start=200):
            wrapping.id = index


def _service(repository: FakeRepository) -> RecoveryService:
    return RecoveryService(
        db=FakeDb(),  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        audit_service=FakeAudit(),  # type: ignore[arg-type]
        crypto_service=FakeCrypto(),  # type: ignore[arg-type]
        clock=lambda: NOW,
        uuid_factory=lambda: REQUEST_ID,
    )


def _execution_record(*, expires_at: datetime) -> RecoveryExecutionRecord:
    return RecoveryExecutionRecord(
        request=SimpleNamespace(
            request_uuid=str(REQUEST_ID),
            requested_by=7,
            status="APPROVED",
            expires_at=expires_at,
        ),
        file=SimpleNamespace(id=20, file_uuid=str(FILE_ID), status="ACTIVE"),
        requester=SimpleNamespace(user_uuid=str(USER_ID)),
        target_key=SimpleNamespace(
            key_uuid=str(TARGET_KEY_ID),
            status="ACTIVE",
            public_key_pem="TARGET PUBLIC KEY",
        ),
        source_wrapping=SimpleNamespace(wrapped_file_key=b"r" * 384),
        recovery_key=SimpleNamespace(
            key_uuid=str(RECOVERY_KEY_ID),
            public_key_pem="RECOVERY PUBLIC KEY",
        ),
    )


def test_execute_dto_forbids_private_key_material() -> None:
    with pytest.raises(ValidationError):
        RecoveryExecuteRequest.model_validate(
            {
                "wrapped_file_key": base64.b64encode(b"w" * 384).decode("ascii"),
                "recovery_key_id": str(RECOVERY_KEY_ID),
                "target_key_id": str(TARGET_KEY_ID),
                "recovery_private_key_pem": "must never cross the API boundary",
            }
        )


def test_public_key_registration_dto_normalizes_pem() -> None:
    pem = "-----BEGIN PUBLIC KEY-----\n" + "A" * 200 + "\n-----END PUBLIC KEY-----"

    payload = RecoveryPublicKeyRegisterRequest(
        key_id=RECOVERY_KEY_ID,
        public_key_pem=f"  {pem}\r\n",
    )

    assert payload.public_key_pem == pem + "\n"


def test_admin_register_rotates_active_recovery_key_atomically() -> None:
    repository = FakeRepository()
    old_key = SimpleNamespace(id=1, status="ACTIVE", revoked_at=None)
    repository.active_recovery_keys = [old_key]
    service = _service(repository)

    key, created, rotated = service.register_public_key(
        actor=_actor(role=SystemRole.ADMIN),
        key_id=RECOVERY_KEY_ID,
        public_key_pem="RECOVERY PUBLIC KEY",
        algorithm="RSA-OAEP-SHA256",
        context=CONTEXT,
    )

    assert created is True
    assert rotated == 1
    assert key.key_uuid == str(RECOVERY_KEY_ID)
    assert key.key_size_bits == 3072
    assert old_key.status == "REVOKED"
    assert old_key.revoked_at == NOW_DB
    assert service.db.commits == 1
    assert service.audit.events[-1]["action"] == "RECOVERY_KEY_ROTATED"


def test_execution_package_is_approved_unexpired_ciphertext_only() -> None:
    repository = FakeRepository()
    repository.execution_record = _execution_record(expires_at=NOW_DB + timedelta(hours=1))
    service = _service(repository)

    record = service.get_execution_package(
        actor=_actor(role=SystemRole.RECOVERY_OFFICER),
        request_id=REQUEST_ID,
    )

    assert record is repository.execution_record
    assert service.crypto.validations == [(b"r" * 384, "RECOVERY PUBLIC KEY")]


def test_execution_package_rejects_expired_request() -> None:
    repository = FakeRepository()
    repository.execution_record = _execution_record(expires_at=NOW_DB)
    service = _service(repository)

    with pytest.raises(RecoveryStateConflictError, match="expired"):
        service.get_execution_package(
            actor=_actor(role=SystemRole.ADMIN),
            request_id=REQUEST_ID,
        )


def test_execution_package_rejects_revoked_or_non_download_entitlement() -> None:
    repository = FakeRepository()
    repository.execution_record = _execution_record(expires_at=NOW_DB + timedelta(hours=1))
    repository.has_download_entitlement = False
    service = _service(repository)

    with pytest.raises(RecoveryStateConflictError, match="no longer active"):
        service.get_execution_package(
            actor=_actor(role=SystemRole.RECOVERY_OFFICER),
            request_id=REQUEST_ID,
        )

    assert service.crypto.validations == []


def test_download_entitlement_query_requires_active_grant_wrapping_and_key() -> None:
    db = SimpleNamespace(statement=None)

    def scalar(statement):
        db.statement = statement
        return 1

    db.scalar = scalar
    repository = RecoveryRepository(db)  # type: ignore[arg-type]

    assert repository.has_active_download_entitlement(20, 7) is True
    sql = str(db.statement.compile(compile_kwargs={"literal_binds": True}))

    assert "file_access_grants.status = 'ACTIVE'" in sql
    assert "file_access_grants.can_download IS true" in sql
    assert "file_key_wrappings.status = 'ACTIVE'" in sql
    assert "user_keys.status = 'ACTIVE'" in sql


def test_cross_user_create_hides_file_existence() -> None:
    repository = FakeRepository()
    repository.file = SimpleNamespace(id=20, owner_id=999, status="ACTIVE")
    service = _service(repository)

    with pytest.raises(FileResourceNotFoundError):
        service.create_request(
            actor=_actor(),
            file_id=FILE_ID,
            reason="Lost account key",
            target_key_id=TARGET_KEY_ID,
            context=CONTEXT,
        )

    assert service.db.rollbacks == 1


@pytest.mark.parametrize(
    "grant",
    [
        None,
        SimpleNamespace(status="REVOKED", can_download=True),
        SimpleNamespace(status="ACTIVE", can_download=False),
    ],
)
def test_owner_create_requires_active_download_grant(grant) -> None:
    repository = FakeRepository()
    repository.file = SimpleNamespace(
        id=20,
        file_uuid=str(FILE_ID),
        owner_id=7,
        status="ACTIVE",
    )
    repository.grant = grant
    service = _service(repository)

    with pytest.raises(FileResourceNotFoundError):
        service.create_request(
            actor=_actor(),
            file_id=FILE_ID,
            reason="Lost account key",
            target_key_id=TARGET_KEY_ID,
            context=CONTEXT,
        )

    assert repository.calls == ["file", "grant"]
    assert not repository.added_requests
    assert service.db.rollbacks == 1


def test_a_changed_file_is_a_clear_conflict_not_a_missing_file() -> None:
    # The integrity sweep marks a tampered file CORRUPTED. Someone with an active grant who asks
    # for recovery is told what a recovery request can and cannot do, not "not found".
    repository = FakeRepository()
    repository.file = SimpleNamespace(id=20, file_uuid=str(FILE_ID), owner_id=7, status="CORRUPTED")
    repository.grant = SimpleNamespace(status="ACTIVE", can_download=True)
    service = _service(repository)

    with pytest.raises(RecoveryStateConflictError) as raised:
        service.create_request(
            actor=_actor(),
            file_id=FILE_ID,
            reason="Modified",
            target_key_id=TARGET_KEY_ID,
            context=CONTEXT,
        )

    assert "failed its integrity check" in str(raised.value)
    assert "restores the file from backup" in str(raised.value)
    assert repository.calls == ["file", "grant"]
    assert not repository.added_requests
    assert service.db.rollbacks == 1


def test_a_changed_file_still_looks_missing_to_someone_without_a_grant() -> None:
    repository = FakeRepository()
    repository.file = SimpleNamespace(
        id=20, file_uuid=str(FILE_ID), owner_id=999, status="CORRUPTED"
    )
    repository.grant = None
    service = _service(repository)

    with pytest.raises(FileResourceNotFoundError):
        service.create_request(
            actor=_actor(),
            file_id=FILE_ID,
            reason="Modified",
            target_key_id=TARGET_KEY_ID,
            context=CONTEXT,
        )


def test_owner_create_requires_active_user_wrapping() -> None:
    repository = FakeRepository()
    repository.file = SimpleNamespace(id=20, owner_id=7, status="ACTIVE")
    repository.grant = SimpleNamespace(status="ACTIVE", can_download=True)
    repository.target_key = SimpleNamespace(id=19)
    service = _service(repository)

    with pytest.raises(FileResourceNotFoundError):
        service.create_request(
            actor=_actor(),
            file_id=FILE_ID,
            reason="Lost account key",
            target_key_id=TARGET_KEY_ID,
            context=CONTEXT,
        )

    assert repository.calls == ["file", "grant", "target_key", "active_user_wrapping"]
    assert not repository.added_requests


def test_create_locks_entitlement_and_recovery_wrapping_before_request() -> None:
    repository = FakeRepository()
    repository.file = SimpleNamespace(
        id=20,
        file_uuid=str(FILE_ID),
        owner_id=7,
        status="ACTIVE",
    )
    repository.grant = SimpleNamespace(status="ACTIVE", can_download=True)
    repository.target_key = SimpleNamespace(id=19)
    repository.active_user_wrapping = SimpleNamespace(id=31, status="ACTIVE")
    repository.active_recovery_wrapping = SimpleNamespace(id=41, status="ACTIVE")
    service = _service(repository)

    record = service.create_request(
        actor=_actor(),
        file_id=FILE_ID,
        reason="Lost account key",
        target_key_id=TARGET_KEY_ID,
        context=CONTEXT,
    )

    assert record.request is repository.added_requests[0]
    assert repository.calls == [
        "file",
        "grant",
        "target_key",
        "active_user_wrapping",
        "active_recovery_wrapping",
        "pending_request",
    ]
    assert service.db.commits == 1
    assert service.audit.events[-1]["resource_type"] == "RECOVERY"
    assert service.audit.events[-1]["resource_id"] == str(FILE_ID)
    assert service.audit.events[-1]["metadata"]["request_id"] == str(REQUEST_ID)


@pytest.mark.parametrize(
    ("approve", "expected_action", "expected_status"),
    [
        (True, "RECOVERY_REQUEST_APPROVED", "APPROVED"),
        (False, "RECOVERY_REQUEST_REJECTED", "REJECTED"),
    ],
)
def test_review_locks_file_before_request_and_emits_file_scoped_audit(
    approve: bool,
    expected_action: str,
    expected_status: str,
) -> None:
    repository = FakeRepository()
    repository.request_locator = RecoveryRequestLocator(
        file_id=20,
        requested_by=7,
        target_user_key_id=19,
    )
    repository.file = SimpleNamespace(id=20, file_uuid=str(FILE_ID), status="ACTIVE")
    repository.request = SimpleNamespace(
        file_id=20,
        requested_by=7,
        target_user_key_id=19,
        status="PENDING",
        expires_at=NOW_DB + timedelta(hours=1),
        approved_by=None,
        approved_at=None,
        rejected_at=None,
        rejection_reason=None,
        updated_at=NOW_DB,
        revision=1,
    )
    repository.request_record = SimpleNamespace(request=repository.request)
    service = _service(repository)
    reviewer = _actor(user_id=99, role=SystemRole.RECOVERY_OFFICER)

    if approve:
        record = service.approve_request(
            actor=reviewer,
            request_id=REQUEST_ID,
            context=CONTEXT,
        )
    else:
        record = service.reject_request(
            actor=reviewer,
            request_id=REQUEST_ID,
            rejection_reason="Insufficient evidence",
            context=CONTEXT,
        )

    assert record is repository.request_record
    assert repository.request.status == expected_status
    assert repository.calls == ["request_locator", "file", "request"]
    event = service.audit.events[-1]
    assert event["action"] == expected_action
    assert event["resource_id"] == str(FILE_ID)
    assert event["metadata"] == {"request_id": str(REQUEST_ID)}


def test_cancel_locks_file_before_request_and_emits_file_scoped_audit() -> None:
    repository = FakeRepository()
    repository.request_locator = RecoveryRequestLocator(
        file_id=20,
        requested_by=7,
        target_user_key_id=19,
    )
    repository.file = SimpleNamespace(id=20, file_uuid=str(FILE_ID), status="ACTIVE")
    repository.request = SimpleNamespace(
        file_id=20,
        requested_by=7,
        target_user_key_id=19,
        status="APPROVED",
        approved_by=99,
        approved_at=NOW_DB,
        cancelled_at=None,
        updated_at=NOW_DB,
        revision=2,
    )
    repository.request_record = SimpleNamespace(request=repository.request)
    service = _service(repository)

    record, changed = service.cancel_request(
        actor=_actor(),
        request_id=REQUEST_ID,
        context=CONTEXT,
    )

    assert (record, changed) == (repository.request_record, True)
    assert repository.calls == ["request_locator", "file", "request"]
    event = service.audit.events[-1]
    assert event["action"] == "RECOVERY_REQUEST_CANCELLED"
    assert event["resource_id"] == str(FILE_ID)
    assert event["metadata"] == {"request_id": str(REQUEST_ID)}


@pytest.mark.parametrize(
    "grant",
    [
        SimpleNamespace(status="REVOKED", can_download=True, revision=4),
        SimpleNamespace(status="ACTIVE", can_download=False, revision=4),
    ],
)
def test_execute_does_not_revive_owner_entitlement_changed_after_approval(grant) -> None:
    repository = FakeRepository()
    repository.request_locator = RecoveryRequestLocator(
        file_id=20,
        requested_by=7,
        target_user_key_id=19,
    )
    repository.file = SimpleNamespace(id=20, owner_id=7, status="ACTIVE")
    repository.grant = grant
    repository.request = SimpleNamespace(status="APPROVED", revision=3)
    before = (grant.status, grant.can_download, grant.revision)
    service = _service(repository)

    with pytest.raises(RecoveryStateConflictError, match="no longer active"):
        service.execute_request(
            actor=_actor(user_id=99, role=SystemRole.RECOVERY_OFFICER),
            request_id=REQUEST_ID,
            wrapped_file_key=b"w" * 384,
            recovery_key_id=RECOVERY_KEY_ID,
            target_key_id=TARGET_KEY_ID,
            context=CONTEXT,
        )

    assert (grant.status, grant.can_download, grant.revision) == before
    assert repository.request.status == "APPROVED"
    assert repository.calls == ["request_locator", "file", "grant"]
    assert not repository.added_wrappings
    assert service.db.rollbacks == 1


def test_execute_rechecks_active_entitlement_wrapping_before_request_lock() -> None:
    repository = FakeRepository()
    repository.request_locator = RecoveryRequestLocator(
        file_id=20,
        requested_by=7,
        target_user_key_id=19,
    )
    repository.file = SimpleNamespace(id=20, owner_id=7, status="ACTIVE")
    repository.grant = SimpleNamespace(status="ACTIVE", can_download=True)
    repository.target_key = SimpleNamespace(id=19)
    repository.request = SimpleNamespace(status="APPROVED", revision=3)
    service = _service(repository)

    with pytest.raises(RecoveryStateConflictError, match="wrapping is no longer active"):
        service.execute_request(
            actor=_actor(user_id=99, role=SystemRole.RECOVERY_OFFICER),
            request_id=REQUEST_ID,
            wrapped_file_key=b"w" * 384,
            recovery_key_id=RECOVERY_KEY_ID,
            target_key_id=TARGET_KEY_ID,
            context=CONTEXT,
        )

    assert repository.calls == [
        "request_locator",
        "file",
        "grant",
        "target_key",
        "active_user_wrapping",
    ]
    assert repository.request.status == "APPROVED"


def test_execute_rewraps_only_after_current_entitlement_is_locked_and_preserves_grant() -> None:
    repository = FakeRepository()
    repository.request_locator = RecoveryRequestLocator(
        file_id=20,
        requested_by=7,
        target_user_key_id=19,
    )
    repository.file = SimpleNamespace(
        id=20,
        file_uuid=str(FILE_ID),
        owner_id=7,
        status="ACTIVE",
    )
    repository.grant = SimpleNamespace(
        status="ACTIVE",
        can_download=True,
        can_share=False,
        can_revoke=False,
        can_manage=False,
        revision=8,
    )
    repository.target_key = SimpleNamespace(
        id=19,
        public_key_pem="TARGET PUBLIC KEY",
    )
    old_wrapping = SimpleNamespace(
        id=50,
        recipient_type="USER",
        recipient_user_id=7,
        user_key_id=18,
        wrapped_file_key=b"o" * 384,
        status="ACTIVE",
        revoked_at=None,
        updated_at=NOW_DB,
        revision=2,
    )
    target_wrapping = SimpleNamespace(
        id=51,
        recipient_type="USER",
        recipient_user_id=7,
        user_key_id=19,
        wrapped_file_key=b"x" * 384,
        wrapping_algorithm="RSA-OAEP-SHA256",
        status="REVOKED",
        revoked_at=NOW_DB,
        updated_at=NOW_DB,
        revision=3,
    )
    repository.active_user_wrapping = old_wrapping
    repository.user_wrappings = [old_wrapping, target_wrapping]
    repository.recovery_source = (
        SimpleNamespace(wrapped_file_key=b"r" * 384),
        SimpleNamespace(public_key_pem="RECOVERY PUBLIC KEY"),
    )
    repository.request = SimpleNamespace(
        file_id=20,
        requested_by=7,
        target_user_key_id=19,
        result_wrapping_id=None,
        status="APPROVED",
        expires_at=NOW_DB + timedelta(hours=1),
        executed_by=None,
        executed_at=None,
        updated_at=NOW_DB,
        revision=5,
    )
    repository.request_record = SimpleNamespace(request=repository.request)
    grant_before = vars(repository.grant).copy()
    service = _service(repository)

    record, changed = service.execute_request(
        actor=_actor(user_id=99, role=SystemRole.RECOVERY_OFFICER),
        request_id=REQUEST_ID,
        wrapped_file_key=b"w" * 384,
        recovery_key_id=RECOVERY_KEY_ID,
        target_key_id=TARGET_KEY_ID,
        context=CONTEXT,
    )

    assert (record, changed) == (repository.request_record, True)
    assert vars(repository.grant) == grant_before
    assert old_wrapping.status == "REVOKED"
    assert target_wrapping.status == "ACTIVE"
    assert target_wrapping.wrapped_file_key == b"w" * 384
    assert repository.request.status == "EXECUTED"
    assert repository.request.result_wrapping_id == 51
    assert repository.calls == [
        "request_locator",
        "file",
        "grant",
        "target_key",
        "active_user_wrapping",
        "user_wrappings",
        "recovery_source",
        "request",
    ]
    assert service.db.commits == 1
    event = service.audit.events[-1]
    assert event["action"] == "RECOVERY_REQUEST_EXECUTED"
    assert event["resource_id"] == str(FILE_ID)
    assert event["metadata"]["request_id"] == str(REQUEST_ID)


@pytest.mark.parametrize(
    ("role", "expected_requested_by"),
    [
        (SystemRole.USER, 7),
        (SystemRole.RECOVERY_OFFICER, None),
        (SystemRole.ADMIN, None),
    ],
)
def test_request_listing_scope_depends_on_reviewer_role(
    role: SystemRole,
    expected_requested_by: int | None,
) -> None:
    repository = FakeRepository()
    service = _service(repository)

    assert service.list_requests(actor=_actor(role=role), page=1, page_size=50) == ([], 0)
    assert repository.list_requested_by == expected_requested_by
