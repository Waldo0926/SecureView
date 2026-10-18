"""Administrator account view and login-password reset (no schema change, no key material)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.api.dependencies import get_admin_service
from app.core.config import Settings
from app.core.security import PasswordOperationCapacityError, password_policy_error
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import (
    AuthenticationRateLimitedError,
    AuthorizationError,
    ConflictError,
    ResourceNotFoundError,
)
from app.repositories.admin_repository import AdminRepository
from app.services.account_notice_service import AccountNoticeService
from app.services.admin_service import AdminService, temporary_password
from app.services.email_service import EmailDeliveryError

NOW = datetime(2026, 10, 6, 9, 30, tzinfo=UTC)
ADMIN_ID = UUID("44444444-4444-4444-8444-444444444444")
TARGET_ID = UUID("22222222-2222-4222-8222-222222222222")
TEMPORARY = re.compile(r"^[A-HJ-NP-Za-km-z2-9]{4}(-[A-HJ-NP-Za-km-z2-9]{4}){3}$")


def _actor(role: SystemRole = SystemRole.ADMIN) -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=ADMIN_ID,
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


class FakeRepository:
    def __init__(self, user) -> None:
        self.user = user
        self.locks = 0

    def lock_user_by_uuid(self, user_id: UUID):
        self.locks += 1
        return self.user if user_id == TARGET_ID else None


class FakeAuthRepository:
    def __init__(self) -> None:
        self.calls = []

    def revoke_all_session_families(self, user_id: int, *, now: datetime, reason: str) -> int:
        self.calls.append((user_id, reason))
        return 3


class FakeNotices:
    def __init__(self, sent: bool = True) -> None:
        self.sent = sent
        self.calls = []

    def notify_admin_password_reset(self, *, email: str, username: str) -> bool:
        self.calls.append((email, username))
        return self.sent


def _user(role: SystemRole = SystemRole.USER, status: UserStatus = UserStatus.ACTIVE):
    return SimpleNamespace(
        id=9,
        user_uuid=str(TARGET_ID),
        username="demo-bob",
        email="demo-bob@secureview.tech",
        role=role,
        status=status,
        password_hash="old-hash",
        password_changed_at=None,
        updated_at=None,
        must_change_password=False,
    )


def _service(user, *, notices=None):
    db, audit, auth = FakeDb(), FakeAudit(), FakeAuthRepository()
    service = AdminService(
        db=db,
        repository=FakeRepository(user),
        auth_repository=auth,
        audit_service=audit,
        notices=notices if notices is not None else FakeNotices(),
        hash_password=lambda value: f"hashed:{value}",
        clock=lambda: NOW,
    )
    return service, db, audit, auth


def test_reset_stores_only_a_hash_signs_out_everywhere_and_audits_without_the_password() -> None:
    user = _user()
    notices = FakeNotices()
    service, db, audit, auth = _service(user, notices=notices)

    returned, temporary, revoked, notice_sent = service.reset_user_password(
        actor=_actor(), user_id=TARGET_ID, context=RequestContext()
    )

    assert returned is user
    assert TEMPORARY.match(temporary)
    assert user.password_hash == f"hashed:{temporary}"
    assert user.password_changed_at is not None and user.updated_at == user.password_changed_at
    # The holder is sent to choose their own password at the next sign-in.
    assert user.must_change_password is True
    assert (revoked, notice_sent) == (3, True)
    assert auth.calls == [(9, "admin_password_reset")]
    assert db.commits == 1 and db.rollbacks == 0
    (event,) = audit.events
    assert event["action"] == "ADMIN_PASSWORD_RESET"
    assert event["target_user_id"] == 9 and event["actor_user_id"] == 7
    assert temporary not in repr(event)
    assert notices.calls == [("demo-bob@secureview.tech", "demo-bob")]


def test_a_failed_notice_does_not_undo_the_reset() -> None:
    user = _user()
    service, db, _, _ = _service(user, notices=FakeNotices(sent=False))

    _, temporary, _, notice_sent = service.reset_user_password(
        actor=_actor(), user_id=TARGET_ID, context=RequestContext()
    )

    assert notice_sent is False
    assert user.password_hash == f"hashed:{temporary}"
    assert db.commits == 1


def test_no_memory_for_a_password_hash_is_a_brief_429_and_changes_nothing() -> None:
    user = _user()
    notices = FakeNotices()
    service, db, audit, auth = _service(user, notices=notices)

    def no_capacity(_value: str) -> str:
        raise PasswordOperationCapacityError()

    service.hash_password = no_capacity

    with pytest.raises(AuthenticationRateLimitedError) as excinfo:
        service.reset_user_password(actor=_actor(), user_id=TARGET_ID, context=RequestContext())

    assert excinfo.value.headers["Retry-After"] == "1"
    assert user.password_hash == "old-hash" and user.must_change_password is False
    assert (db.commits, db.rollbacks) == (0, 1)
    assert auth.calls == [] and audit.events == [] and notices.calls == []


def test_the_route_hashes_with_the_apps_password_manager() -> None:
    # The app's manager carries the cap on concurrent hashes; the module-level one does not
    # share it, so a reset could otherwise add memory-hard work past the cap.
    class Manager:
        def hash(self, value: str) -> str:
            return f"app:{value}"

    manager = Manager()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(_env_file=None, APP_ENV="test"), password_manager=manager
            )
        )
    )

    service = get_admin_service(request, db=FakeDb())  # type: ignore[arg-type]

    assert service.hash_password("x") == "app:x"


def test_an_administrator_cannot_reset_their_own_password_here() -> None:
    service, db, audit, _ = _service(_user())

    with pytest.raises(ConflictError):
        service.reset_user_password(actor=_actor(), user_id=ADMIN_ID, context=RequestContext())

    assert service.repository.locks == 0 and db.commits == 0 and audit.events == []


def test_another_administrators_password_cannot_be_reset() -> None:
    user = _user(role=SystemRole.ADMIN)
    service, db, audit, _ = _service(user)

    with pytest.raises(ConflictError):
        service.reset_user_password(actor=_actor(), user_id=TARGET_ID, context=RequestContext())

    assert user.password_hash == "old-hash"
    assert user.must_change_password is False
    assert (db.commits, db.rollbacks) == (0, 1)
    assert audit.events == []


@pytest.mark.parametrize("user", [None, _user(status=UserStatus.DELETED)])
def test_a_missing_or_deleted_account_is_not_found(user) -> None:
    service, db, _, _ = _service(user)

    with pytest.raises(ResourceNotFoundError):
        service.reset_user_password(actor=_actor(), user_id=TARGET_ID, context=RequestContext())

    assert db.commits == 0


def test_only_an_administrator_can_reset_or_view() -> None:
    service, _, _, _ = _service(_user())

    with pytest.raises(AuthorizationError):
        service.reset_user_password(
            actor=_actor(SystemRole.USER), user_id=TARGET_ID, context=RequestContext()
        )
    with pytest.raises(AuthorizationError):
        service.user_detail(actor=_actor(SystemRole.RECOVERY_OFFICER), user_id=TARGET_ID)
    assert service.repository.locks == 0


def test_temporary_passwords_pass_the_policy_avoid_the_account_details_and_differ() -> None:
    made = {temporary_password(context_values=("demo-bob", "demo-bob@x.tech")) for _ in range(200)}

    assert len(made) == 200
    for value in made:
        assert TEMPORARY.match(value)
        assert password_policy_error(value, context_values=("demo-bob", "demo-bob@x.tech")) is None


class FakeEmail:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent = []
        self.error = error

    def send(self, message) -> None:
        if self.error:
            raise self.error
        self.sent.append(message)


def test_the_notice_never_contains_a_password_and_escapes_the_username() -> None:
    email = FakeEmail()
    settings = SimpleNamespace(APP_PUBLIC_URL="https://secureview.tech/")
    notices = AccountNoticeService(settings=settings, email=email)

    assert notices.notify_admin_password_reset(email="x@secureview.tech", username="<b>eve</b>")

    (message,) = email.sent
    assert message.to_address == "x@secureview.tech"
    assert "&lt;b&gt;eve&lt;/b&gt;" in message.html_body and "<b>eve</b>" not in message.html_body
    assert "https://secureview.tech/settings" in message.text_body
    assert "encryption passphrase" in message.text_body
    assert not re.search(r"[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-", message.text_body + message.html_body)


def test_a_delivery_error_is_reported_as_not_sent() -> None:
    settings = SimpleNamespace(APP_PUBLIC_URL="")
    notices = AccountNoticeService(settings=settings, email=FakeEmail(EmailDeliveryError("down")))

    assert notices.notify_admin_password_reset(email="x@secureview.tech", username="eve") is False


class CapturingDb:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(one=lambda: (4, 1234))

    def scalar(self, statement):
        self.statements.append(statement)
        return 2


def _sql(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def test_account_activity_counts_only_live_files_grants_and_sessions() -> None:
    db = CapturingDb()

    activity = AdminRepository(db).user_activity(9, now=NOW.replace(tzinfo=None))

    assert (activity.file_count, activity.stored_bytes) == (4, 1234)
    assert (activity.shared_by_them, activity.shared_with_them, activity.active_sessions) == (
        2,
        2,
        2,
    )
    files, by_them, with_them, sessions = (_sql(s) for s in db.statements)
    assert "files.owner_id = 9" in files and "files.status != 'DELETED'" in files
    assert "files.owner_id = 9" in by_them and "file_access_grants.user_id != 9" in by_them
    assert "file_access_grants.user_id = 9" in with_them and "files.owner_id != 9" in with_them
    assert "file_access_grants.status = 'ACTIVE'" in by_them + with_them
    assert "user_sessions.user_id = 9" in sessions and "absolute_expires_at >" in sessions
    # Numbers only: no file names, keys or hashes are selected.
    for sql in (files, by_them, with_them, sessions):
        select_list = sql.split("FROM", 1)[0]
        assert "original_filename" not in select_list and "password_hash" not in select_list
