from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import (
    AuthorizationError,
    FileResourceNotFoundError,
    LastAdministratorError,
    ShareStateConflictError,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.sharing_repository import SharingRepository
from app.services.admin_service import AdminService
from app.services.audit_log_service import AuditLogService
from app.services.audit_query_service import AuditQueryService
from app.services.sharing_service import SharingService

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
FILE_ID = UUID("11111111-1111-4111-8111-111111111111")
TARGET_USER_ID = UUID("22222222-2222-4222-8222-222222222222")
TARGET_KEY_ID = UUID("33333333-3333-4333-8333-333333333333")


def _actor(role: SystemRole = SystemRole.USER, *, user_id: int = 7) -> ActorContext:
    return ActorContext(
        user_id=user_id,
        user_public_id=UUID("44444444-4444-4444-8444-444444444444"),
        session_id=8,
        session_public_id=UUID("55555555-5555-4555-8555-555555555555"),
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
        self.events = []

    def append(self, **event) -> None:
        self.events.append(event)


def _public_key_pem() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


class FakeSharingRepository:
    def __init__(self) -> None:
        self.file = SimpleNamespace(id=91, owner_id=7, status="ACTIVE")
        self.actor_grant = SimpleNamespace(
            status="ACTIVE",
            can_download=True,
            can_share=True,
            can_revoke=True,
            can_manage=False,
        )
        self.target_user = SimpleNamespace(id=9, user_uuid=str(TARGET_USER_ID))
        self.target_key = SimpleNamespace(
            id=19,
            key_uuid=str(TARGET_KEY_ID),
            public_key_pem=_public_key_pem(),
        )
        self.target_grant = None
        self.target_wrappings = []
        self.grants = []
        self.wrappings = []

    def lock_file(self, file_id: UUID):
        assert file_id == FILE_ID
        return self.file

    def lock_grant(self, file_id: int, user_id: int):
        assert file_id == 91
        if user_id == 7:
            return self.actor_grant
        if user_id == self.target_user.id:
            return self.target_grant
        return None

    def has_active_wrapping(self, file_id: int, user_id: int) -> bool:
        return file_id == 91 and user_id == 7

    def lock_target_user_and_key(self, user_id: UUID, key_id: UUID):
        assert user_id == TARGET_USER_ID and key_id == TARGET_KEY_ID
        return self.target_user, self.target_key

    def lock_user_wrappings(self, file_id: int, user_id: int):
        assert file_id == 91 and user_id == 9
        return self.target_wrappings

    def add_grant(self, grant) -> None:
        self.grants.append(grant)

    def add_wrapping(self, wrapping) -> None:
        self.wrappings.append(wrapping)


def test_share_atomically_persists_only_target_wrapped_dek_and_permissions() -> None:
    db = FakeDb()
    repository = FakeSharingRepository()
    audit = FakeAudit()
    service = SharingService(
        db=db,
        repository=repository,
        audit_service=audit,
        clock=lambda: NOW,
    )

    created, status = service.share(
        actor=_actor(),
        file_id=FILE_ID,
        target_user_id=TARGET_USER_ID,
        target_key_id=TARGET_KEY_ID,
        wrapped_file_key=b"w" * 256,
        can_download=True,
        can_share=False,
        context=RequestContext(ip_address="203.0.113.7"),
    )

    assert (created, status) == (True, "ACTIVE")
    assert db.commits == 1
    assert repository.grants[0].user_id == 9
    assert repository.grants[0].can_revoke is False
    assert repository.wrappings[0].wrapped_file_key == b"w" * 256
    assert repository.wrappings[0].user_key_id == 19
    assert audit.events[0]["action"] == "FILE_SHARED"


class NotifyingSharingRepository(FakeSharingRepository):
    """Adds the reads `share` makes after the commit to address the email."""

    def get_user_by_uuid(self, user_id: UUID):
        assert user_id == TARGET_USER_ID
        return SimpleNamespace(id=9, email="bob@example.com", username="bob")

    def get_user(self, user_id: int):
        return SimpleNamespace(id=user_id, username="alice")

    def count_shares_since(self, _since) -> int:
        return 0


class FakeShareNotifier:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.sent_today = None

    def notify_shared(self, **values) -> bool:
        self.sent.append(values)
        return True


def _existing_grant(status: str):
    return SimpleNamespace(
        granted_by=7,
        can_download=True,
        can_share=False,
        can_revoke=False,
        can_manage=False,
        status=status,
        revoked_at=None if status == "ACTIVE" else NOW.replace(tzinfo=None),
        revision=3,
        updated_at=None,
    )


def _share_with_notifier(repository) -> tuple[FakeShareNotifier, tuple[bool, str]]:
    notifier = FakeShareNotifier()
    service = SharingService(
        db=FakeDb(),
        repository=repository,
        audit_service=FakeAudit(),
        notifier=notifier,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = service.share(
        actor=_actor(),
        file_id=FILE_ID,
        target_user_id=TARGET_USER_ID,
        target_key_id=TARGET_KEY_ID,
        wrapped_file_key=b"w" * 256,
        can_download=True,
        can_share=False,
        context=RequestContext(),
    )
    return notifier, result


def test_a_new_share_emails_the_recipient() -> None:
    notifier, result = _share_with_notifier(NotifyingSharingRepository())

    assert result == (True, "ACTIVE")
    (sent,) = notifier.sent
    assert sent["recipient_email"] == "bob@example.com"
    assert sent["sender_username"] == "alice"


def test_restoring_a_revoked_share_emails_the_recipient_again() -> None:
    # They had lost the file; being able to open it again is news to them.
    repository = NotifyingSharingRepository()
    repository.target_grant = _existing_grant("REVOKED")

    notifier, result = _share_with_notifier(repository)

    assert result == (False, "ACTIVE")
    assert repository.target_grant.status == "ACTIVE"
    assert len(notifier.sent) == 1


def test_sharing_again_to_someone_who_already_has_the_file_sends_no_email() -> None:
    # Changing permissions or re-wrapping the key is not a new share from the recipient's
    # side, and each call used to mail them "shared with you" again.
    repository = NotifyingSharingRepository()
    repository.target_grant = _existing_grant("ACTIVE")

    notifier, result = _share_with_notifier(repository)

    assert result == (False, "ACTIVE")
    assert repository.target_grant.revision == 4
    assert notifier.sent == []


def test_share_denial_is_uniform_not_found_and_rolls_back() -> None:
    db = FakeDb()
    repository = FakeSharingRepository()
    repository.actor_grant.can_share = False
    service = SharingService(
        db=db,
        repository=repository,
        audit_service=FakeAudit(),
        clock=lambda: NOW,
    )

    with pytest.raises(FileResourceNotFoundError):
        service.share(
            actor=_actor(),
            file_id=FILE_ID,
            target_user_id=TARGET_USER_ID,
            target_key_id=TARGET_KEY_ID,
            wrapped_file_key=b"w" * 256,
            can_download=True,
            can_share=False,
            context=RequestContext(),
        )

    assert db.rollbacks == 1
    assert not repository.grants


def test_delegated_sharer_cannot_grant_capability_they_do_not_have() -> None:
    db = FakeDb()
    repository = FakeSharingRepository()
    repository.file.owner_id = 1
    repository.actor_grant.can_download = False
    audit = FakeAudit()
    service = SharingService(
        db=db,
        repository=repository,
        audit_service=audit,
        clock=lambda: NOW,
    )

    with pytest.raises(ShareStateConflictError):
        service.share(
            actor=_actor(),
            file_id=FILE_ID,
            target_user_id=TARGET_USER_ID,
            target_key_id=TARGET_KEY_ID,
            wrapped_file_key=b"w" * 256,
            can_download=True,
            can_share=False,
            context=RequestContext(),
        )

    assert db.commits == 0
    assert db.rollbacks == 1
    assert not repository.grants
    assert not repository.wrappings
    assert not audit.events


def _target_grant(*, granted_by: int, status: str = "ACTIVE") -> SimpleNamespace:
    return SimpleNamespace(
        file_id=91,
        user_id=9,
        granted_by=granted_by,
        can_download=False,
        can_share=False,
        can_revoke=False,
        can_manage=False,
        status=status,
        revoked_at=NOW.replace(tzinfo=None) if status == "REVOKED" else None,
        revision=3,
        updated_at=NOW.replace(tzinfo=None),
    )


@pytest.mark.parametrize("existing_status", ["ACTIVE", "REVOKED"])
def test_delegated_sharer_cannot_overwrite_or_reactivate_third_party_grant(
    existing_status: str,
) -> None:
    db = FakeDb()
    repository = FakeSharingRepository()
    repository.file.owner_id = 1
    repository.target_grant = _target_grant(granted_by=12, status=existing_status)
    audit = FakeAudit()
    service = SharingService(
        db=db,
        repository=repository,
        audit_service=audit,
        clock=lambda: NOW,
    )
    before = vars(repository.target_grant).copy()

    with pytest.raises(ShareStateConflictError):
        service.share(
            actor=_actor(),
            file_id=FILE_ID,
            target_user_id=TARGET_USER_ID,
            target_key_id=TARGET_KEY_ID,
            wrapped_file_key=b"w" * 256,
            can_download=False,
            can_share=False,
            context=RequestContext(),
        )

    assert vars(repository.target_grant) == before
    assert db.commits == 0
    assert db.rollbacks == 1
    assert not repository.grants
    assert not repository.wrappings
    assert not audit.events


@pytest.mark.parametrize("manager_kind", ["owner", "can_manage"])
def test_owner_or_manager_can_manage_existing_third_party_grant(manager_kind: str) -> None:
    db = FakeDb()
    repository = FakeSharingRepository()
    repository.target_grant = _target_grant(granted_by=12, status="REVOKED")
    repository.actor_grant.can_manage = True
    if manager_kind == "can_manage":
        repository.file.owner_id = 1
    audit = FakeAudit()
    service = SharingService(
        db=db,
        repository=repository,
        audit_service=audit,
        clock=lambda: NOW,
    )

    created, status = service.share(
        actor=_actor(),
        file_id=FILE_ID,
        target_user_id=TARGET_USER_ID,
        target_key_id=TARGET_KEY_ID,
        wrapped_file_key=b"w" * 256,
        can_download=True,
        can_share=True,
        context=RequestContext(),
    )

    assert (created, status) == (False, "ACTIVE")
    assert repository.target_grant.status == "ACTIVE"
    assert repository.target_grant.can_download is True
    assert repository.target_grant.can_share is True
    assert repository.target_grant.revision == 4
    assert db.commits == 1
    assert db.rollbacks == 0
    assert len(repository.wrappings) == 1
    assert audit.events[0]["action"] == "FILE_SHARED"


def test_original_grantor_can_idempotently_update_existing_grant() -> None:
    db = FakeDb()
    repository = FakeSharingRepository()
    repository.file.owner_id = 1
    repository.target_grant = _target_grant(granted_by=7)
    audit = FakeAudit()
    service = SharingService(
        db=db,
        repository=repository,
        audit_service=audit,
        clock=lambda: NOW,
    )

    created, status = service.share(
        actor=_actor(),
        file_id=FILE_ID,
        target_user_id=TARGET_USER_ID,
        target_key_id=TARGET_KEY_ID,
        wrapped_file_key=b"w" * 256,
        can_download=False,
        can_share=False,
        context=RequestContext(),
    )

    assert (created, status) == (False, "ACTIVE")
    assert repository.target_grant.granted_by == 7
    assert repository.target_grant.revision == 4
    assert db.commits == 1
    assert db.rollbacks == 0
    assert len(repository.wrappings) == 1
    assert audit.events[0]["target_user_id"] == repository.target_user.id


def test_delegated_sharer_cannot_replace_canonical_owner_grant() -> None:
    db = FakeDb()
    repository = FakeSharingRepository()
    repository.file.owner_id = repository.target_user.id
    audit = FakeAudit()
    service = SharingService(
        db=db,
        repository=repository,
        audit_service=audit,
        clock=lambda: NOW,
    )

    with pytest.raises(ShareStateConflictError, match="canonical owner grant"):
        service.share(
            actor=_actor(),
            file_id=FILE_ID,
            target_user_id=TARGET_USER_ID,
            target_key_id=TARGET_KEY_ID,
            wrapped_file_key=b"w" * 256,
            can_download=False,
            can_share=False,
            context=RequestContext(),
        )

    assert db.rollbacks == 1
    assert db.commits == 0
    assert not repository.grants
    assert not repository.wrappings
    assert not audit.events


class FakeDisabledRevokeRepository(FakeSharingRepository):
    def __init__(self) -> None:
        super().__init__()
        self.target_user.status = UserStatus.DISABLED
        self.target_grant = SimpleNamespace(
            status="ACTIVE",
            revoked_at=None,
            revision=1,
            updated_at=NOW.replace(tzinfo=None),
        )
        self.target_wrapping = SimpleNamespace(
            status="ACTIVE",
            revoked_at=None,
            revision=1,
            updated_at=NOW.replace(tzinfo=None),
        )

    def get_user_by_uuid(self, user_id: UUID):
        assert user_id == TARGET_USER_ID
        return self.target_user

    def lock_grant(self, file_id: int, user_id: int):
        assert file_id == 91
        if user_id == 7:
            return self.actor_grant
        if user_id == self.target_user.id:
            return self.target_grant
        return None

    def lock_user_wrappings(self, file_id: int, user_id: int):
        assert file_id == 91 and user_id == self.target_user.id
        return [self.target_wrapping]


def test_revoke_can_clean_up_disabled_recipient_entitlement() -> None:
    db = FakeDb()
    repository = FakeDisabledRevokeRepository()
    audit = FakeAudit()
    service = SharingService(
        db=db,
        repository=repository,
        audit_service=audit,
        clock=lambda: NOW,
    )

    changed = service.revoke(
        actor=_actor(),
        file_id=FILE_ID,
        target_user_id=TARGET_USER_ID,
        context=RequestContext(),
    )

    assert changed is True
    assert repository.target_user.status is UserStatus.DISABLED
    assert repository.target_grant.status == "REVOKED"
    assert repository.target_wrapping.status == "REVOKED"
    assert db.commits == 1
    assert db.rollbacks == 0
    assert audit.events[0]["target_user_id"] == repository.target_user.id


class CapturingSharingDb:
    def __init__(self) -> None:
        self.statements = []
        self.disabled_user = SimpleNamespace(
            id=9,
            user_uuid=str(TARGET_USER_ID),
            username="disabled-recipient",
            status=UserStatus.DISABLED,
        )
        self.grant = SimpleNamespace(file_id=91, user_id=9, status="ACTIVE")
        self.key = SimpleNamespace(user_id=9, status="ACTIVE")

    def scalar(self, statement):
        self.statements.append(statement)
        return self.disabled_user

    def execute(self, statement):
        self.statements.append(statement)
        return [(self.grant, self.disabled_user, self.key)]


def _where_clause(statement) -> str:
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    marker = "WHERE "
    assert marker in sql
    return sql.split(marker, maxsplit=1)[1]


def test_revoke_lookup_and_shared_user_listing_do_not_filter_disabled_users() -> None:
    db = CapturingSharingDb()
    repository = SharingRepository(db)

    found = repository.get_user_by_uuid(TARGET_USER_ID)
    rows = repository.list_shared_users(91)

    assert found is db.disabled_user
    assert rows == [(db.grant, db.disabled_user, db.key)]
    assert "users.status" not in _where_clause(db.statements[0])
    assert "users.status" not in _where_clause(db.statements[1])
    assert "file_access_grants.status" in _where_clause(db.statements[1])
    assert "user_keys.status" in _where_clause(db.statements[1])


class FakeAdminRepository:
    def __init__(self) -> None:
        self.user = SimpleNamespace(
            id=9,
            user_uuid=str(TARGET_USER_ID),
            role=SystemRole.USER,
            status=UserStatus.ACTIVE,
            updated_at=NOW.replace(tzinfo=None),
        )
        self.lock_calls = 0
        self.order: list[str] | None = None

    def lock_user_by_uuid(self, user_id: UUID):
        assert user_id == TARGET_USER_ID
        self.lock_calls += 1
        if self.order is not None:
            self.order.append("lock_user_by_uuid")
        return self.user


class FakeAuthRepository:
    def __init__(self) -> None:
        self.calls = []
        self.administrators: list = []
        self.order: list[str] | None = None

    def lock_administrators(self):
        if self.order is not None:
            self.order.append("lock_administrators")
        return self.administrators

    def revoke_all_session_families(self, user_id: int, *, now: datetime, reason: str) -> int:
        self.calls.append((user_id, now, reason))
        return 2


def test_admin_disable_is_atomic_and_revokes_target_sessions() -> None:
    db = FakeDb()
    repository = FakeAdminRepository()
    auth_repository = FakeAuthRepository()
    audit = FakeAudit()
    service = AdminService(
        db=db,
        repository=repository,
        auth_repository=auth_repository,
        audit_service=audit,
        clock=lambda: NOW,
    )

    user, changed, revoked = service.set_user_enabled(
        actor=_actor(SystemRole.ADMIN),
        user_id=TARGET_USER_ID,
        enabled=False,
        context=RequestContext(),
    )

    assert (changed, revoked) == (True, 2)
    assert user.status is UserStatus.DISABLED
    assert db.commits == 1
    assert auth_repository.calls[0][2] == "account_disabled"
    assert audit.events[0]["action"] == "USER_DISABLED"


def _admin_service(repository, auth_repository, db=None, audit=None) -> AdminService:
    return AdminService(
        db=db or FakeDb(),
        repository=repository,
        auth_repository=auth_repository,
        audit_service=audit or FakeAudit(),
        clock=lambda: NOW,
    )


def test_disabling_the_last_active_administrator_is_refused() -> None:
    # The acting administrator cannot disable themselves, so this is the case where they were
    # disabled a moment ago by the administrator they are now disabling. Both requests take
    # the administrator rows first, so the second sees the first one's change.
    db = FakeDb()
    repository = FakeAdminRepository()
    repository.user.role = SystemRole.ADMIN
    actor_row = SimpleNamespace(id=7, role=SystemRole.ADMIN, status=UserStatus.DISABLED)
    auth_repository = FakeAuthRepository()
    auth_repository.administrators = [actor_row, repository.user]
    service = _admin_service(repository, auth_repository, db=db)

    with pytest.raises(LastAdministratorError):
        service.set_user_enabled(
            actor=_actor(SystemRole.ADMIN),
            user_id=TARGET_USER_ID,
            enabled=False,
            context=RequestContext(),
        )

    assert repository.user.status is UserStatus.ACTIVE
    assert auth_repository.calls == []
    assert (db.commits, db.rollbacks) == (0, 1)


def test_an_administrator_can_be_disabled_while_another_stays_active() -> None:
    repository = FakeAdminRepository()
    repository.user.role = SystemRole.ADMIN
    auth_repository = FakeAuthRepository()
    auth_repository.administrators = [
        SimpleNamespace(id=7, role=SystemRole.ADMIN, status=UserStatus.ACTIVE),
        repository.user,
    ]
    order: list[str] = []
    repository.order = auth_repository.order = order
    service = _admin_service(repository, auth_repository)

    user, changed, _revoked = service.set_user_enabled(
        actor=_actor(SystemRole.ADMIN),
        user_id=TARGET_USER_ID,
        enabled=False,
        context=RequestContext(),
    )

    assert changed is True
    assert user.status is UserStatus.DISABLED
    # The same lock order as account deletion, so the two cannot deadlock or interleave.
    assert order == ["lock_administrators", "lock_user_by_uuid"]


def test_enabling_an_account_does_not_lock_the_administrators() -> None:
    repository = FakeAdminRepository()
    repository.user.status = UserStatus.DISABLED
    auth_repository = FakeAuthRepository()
    order: list[str] = []
    repository.order = auth_repository.order = order
    service = _admin_service(repository, auth_repository)

    _user, changed, _revoked = service.set_user_enabled(
        actor=_actor(SystemRole.ADMIN),
        user_id=TARGET_USER_ID,
        enabled=True,
        context=RequestContext(),
    )

    assert changed is True
    assert order == ["lock_user_by_uuid"]


def test_non_admin_service_call_is_denied_before_repository_access() -> None:
    repository = FakeAdminRepository()
    service = AdminService(
        db=FakeDb(),
        repository=repository,
        auth_repository=FakeAuthRepository(),
        audit_service=FakeAudit(),
    )

    with pytest.raises(AuthorizationError):
        service.list_users(actor=_actor(), limit=10, offset=0)

    assert repository.lock_calls == 0


class FakeAuditRepository:
    def __init__(self, logs, head) -> None:
        self.logs = logs
        self.head = head
        self.chain_calls = 0

    def chain_rows(self):
        self.chain_calls += 1
        return self.logs, self.head


def _valid_chain():
    timestamp = NOW.replace(tzinfo=None)
    log_service = AuditLogService(SimpleNamespace())
    values = {
        "action": "FILE_SHARED",
        "actor_user_id": 7,
        "created_at": timestamp,
        "description": None,
        "ip_address": None,
        "metadata": {"can_share": False},
        "resource_id": str(FILE_ID),
        "resource_type": "SHARE",
        "result": "SUCCESS",
        "target_user_id": 9,
        "user_agent": None,
    }
    current_hash = log_service.build_log_hash(
        log_service.GENESIS_HASH,
        log_service.make_log_content(**values),
    )
    log = SimpleNamespace(
        id=1,
        previous_hash=log_service.GENESIS_HASH,
        current_hash=current_hash,
        metadata_json=values.pop("metadata"),
        **values,
    )
    head = SimpleNamespace(last_log_id=1, current_hash=current_hash)
    return log_service, [log], head


def test_audit_chain_verification_detects_tampering_and_requires_admin() -> None:
    log_service, logs, head = _valid_chain()
    repository = FakeAuditRepository(logs, head)
    service = AuditQueryService(
        db=SimpleNamespace(),
        repository=repository,
        audit_log_service=log_service,
    )

    assert service.verify_chain(actor=_actor(SystemRole.ADMIN))["valid"] is True
    logs[0].current_hash = "f" * 64
    invalid = service.verify_chain(actor=_actor(SystemRole.ADMIN))
    assert invalid["valid"] is False
    assert invalid["first_invalid_position"] == 1

    with pytest.raises(AuthorizationError):
        service.verify_chain(actor=_actor())
    assert repository.chain_calls == 2


def test_audit_metadata_allowlist_drops_untrusted_values() -> None:
    assert AuditQueryService.safe_metadata(
        {
            "can_share": True,
            "request_id": str(TARGET_KEY_ID),
            "wrapped_file_key": "secret",
            "private_key": "secret",
        }
    ) == {"can_share": True, "request_id": str(TARGET_KEY_ID)}


class CapturingAuditDb:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return []


def test_file_scoped_audit_query_keeps_the_recovery_and_file_type_filters() -> None:
    db = CapturingAuditDb()
    repository = AuditRepository(db)  # type: ignore[arg-type]

    assert (
        repository.list_logs(
            actor_user_id=7,
            admin=False,
            limit=51,
            offset=0,
            resource_id=str(FILE_ID),
        )
        == []
    )

    where = _where_clause(db.statements[-1])
    assert "audit_logs.resource_type IN ('FILE', 'SHARE', 'INTEGRITY')" in where
    assert "audit_logs.resource_type = 'RECOVERY'" in where
    assert "'RECOVERY_REQUEST_CREATED'" in where
    assert "'RECOVERY_REQUEST_EXECUTED'" in where
    assert f"audit_logs.resource_id = '{FILE_ID}'" in where
    assert "RECOVERY_KEY_REGISTERED" not in where


def test_a_file_scoped_query_is_still_scoped_to_what_the_caller_may_see() -> None:
    """The visibility filter applies to file-scoped queries too.

    It used to be skipped for them, on the reasoning that the service had already checked
    entitlement. But entitlement is not ownership: a recipient holds an ACTIVE grant, so any
    recipient could read the whole trail of a shared file -- learning that other recipients
    existed and when each of them downloaded it.
    """
    db = CapturingAuditDb()
    repository = AuditRepository(db)  # type: ignore[arg-type]

    repository.list_logs(
        actor_user_id=7,
        admin=False,
        limit=51,
        offset=0,
        resource_id=str(FILE_ID),
    )

    where = _where_clause(db.statements[-1])
    assert "audit_logs.actor_user_id = 7" in where
    assert "audit_logs.target_user_id = 7" in where
    # ...plus everything on a file this caller owns, which is what lets an owner see the
    # downloads their recipients made.
    assert "files.owner_id = 7" in where


def test_an_admin_is_not_narrowed_at_all() -> None:
    db = CapturingAuditDb()
    repository = AuditRepository(db)  # type: ignore[arg-type]

    repository.list_logs(actor_user_id=7, admin=True, limit=51, offset=0, resource_id=None)

    # No filter at all for an unscoped admin query, so there is no WHERE clause to inspect.
    sql = str(db.statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "WHERE" not in sql


def test_the_account_wide_query_also_reaches_files_the_caller_owns() -> None:
    # The reported symptom: an owner's Access Records showed zero downloads, because the
    # filter only matched rows where they were the actor or the target -- and a download by
    # a recipient is neither.
    db = CapturingAuditDb()
    repository = AuditRepository(db)  # type: ignore[arg-type]

    repository.list_logs(actor_user_id=7, admin=False, limit=51, offset=0, resource_id=None)

    where = _where_clause(db.statements[-1])
    assert "files.owner_id = 7" in where


class FileAuditAccessRepository:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.list_calls = []
        self.unrelated_recovery_row = object()

    def can_access_file(self, user_id: int, file_id: UUID) -> bool:
        assert user_id == 7
        assert file_id == FILE_ID
        return self.allowed

    def list_logs(self, **values):
        self.list_calls.append(values)
        return [self.unrelated_recovery_row]


def test_file_audit_returns_complete_trail_only_after_live_access_check() -> None:
    allowed_repository = FileAuditAccessRepository(allowed=True)
    allowed_service = AuditQueryService(
        db=SimpleNamespace(),
        repository=allowed_repository,  # type: ignore[arg-type]
    )

    rows = allowed_service.list_logs(
        actor=_actor(),
        limit=50,
        offset=0,
        file_id=FILE_ID,
    )

    assert rows == [allowed_repository.unrelated_recovery_row]
    assert allowed_repository.list_calls[-1]["resource_id"] == str(FILE_ID)

    denied_repository = FileAuditAccessRepository(allowed=False)
    denied_service = AuditQueryService(
        db=SimpleNamespace(),
        repository=denied_repository,  # type: ignore[arg-type]
    )
    with pytest.raises(FileResourceNotFoundError):
        denied_service.list_logs(
            actor=_actor(),
            limit=50,
            offset=0,
            file_id=FILE_ID,
        )
    assert denied_repository.list_calls == []


def test_file_labels_come_back_with_the_deleted_flag_in_one_query() -> None:
    class _Db:
        def __init__(self) -> None:
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            return [
                (str(FILE_ID), "report.pdf", "ACTIVE"),
                ("22222222-2222-4222-8222-222222222222", "old.txt", "DELETED"),
            ]

    db = _Db()
    repository = AuditRepository(db)  # type: ignore[arg-type]

    labels = repository.file_labels([str(FILE_ID), "22222222-2222-4222-8222-222222222222", ""])

    assert labels == {
        str(FILE_ID): ("report.pdf", False),
        "22222222-2222-4222-8222-222222222222": ("old.txt", True),
    }
    # One query for the whole page of rows, never one per file.
    assert len(db.statements) == 1
    assert repository.file_labels([]) == {}
    assert len(db.statements) == 1


def test_only_rows_about_a_file_are_looked_up_for_a_name() -> None:
    asked = []

    class _Repository:
        def file_labels(self, ids):
            asked.append(set(ids))
            return {}

    service = AuditQueryService(db=SimpleNamespace(), repository=_Repository())  # type: ignore[arg-type]

    def row(resource_type: str, resource_id: str | None):
        return (SimpleNamespace(resource_type=resource_type, resource_id=resource_id), None, None)

    service.file_labels(
        [
            row("FILE", "a"),
            row("SHARE", "b"),
            row("INTEGRITY", "c"),
            row("USER", "d"),
            row("RECOVERY", "e"),
            row("FILE", None),
        ]
    )

    assert asked == [{"a", "b", "c"}]


def test_admin_list_status_filters_compile_to_the_right_where_clauses() -> None:
    from sqlalchemy.dialects import mysql

    from app.repositories.admin_repository import AdminRepository

    statements: list[str] = []

    class _Db:
        def _sql(self, statement) -> str:
            sql = str(
                statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
            )
            statements.append(sql)
            return sql

        def scalars(self, statement):
            self._sql(statement)
            return []

        def execute(self, statement):
            self._sql(statement)
            return []

    repository = AdminRepository(_Db())  # type: ignore[arg-type]
    repository.list_users(limit=5, offset=0, status="CURRENT")
    repository.list_users(limit=5, offset=0, status="DISABLED")
    repository.list_users(limit=5, offset=0)
    repository.list_files(limit=5, offset=0, status="CURRENT")
    repository.list_files(limit=5, offset=0, status="CORRUPTED")

    assert "users.status != 'DELETED'" in statements[0]
    assert "users.status = 'DISABLED'" in statements[1]
    assert "WHERE" not in statements[2]
    assert "files.status != 'DELETED'" in statements[3]
    assert "files.status = 'CORRUPTED'" in statements[4]
