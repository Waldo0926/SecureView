from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.security import PasswordOperationCapacityError
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import (
    AuthenticationError,
    AuthenticationRateLimitedError,
    InvalidCurrentPasswordError,
    LastAdministratorError,
)
from app.services.account_deletion_service import AccountDeletionService
from app.services.file_storage_service import StorageObjectError

# Aware and with a fractional second, as the real clock returns it.
NOW = datetime(2026, 8, 26, 12, 0, 0, 734_512, tzinfo=UTC)
NOW_STORED = datetime(2026, 8, 26, 12, 0, 0)
USER_ID = UUID("11111111-1111-4111-8111-111111111111")


def _actor() -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=USER_ID,
        session_id=8,
        session_public_id=UUID("55555555-5555-4555-8555-555555555555"),
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


def _context() -> RequestContext:
    return RequestContext(ip_address="203.0.113.7", user_agent="pytest")


class FakeDb:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


class FakePasswords:
    def __init__(self, *, correct: str) -> None:
        self.correct = correct

    def verify(self, candidate: str, _hash: str) -> bool:
        return candidate == self.correct


class FakeAuthRepo:
    def __init__(self, user) -> None:
        self.user = user
        self.revoked_reason: str | None = None
        self.released: str | None = None
        # Other administrator rows, besides `user` when it is one.
        self.other_administrators: list = []
        self.calls: list[str] = []

    def lock_administrators(self):
        self.calls.append("lock_administrators")
        admins = [self.user] if self.user.role is SystemRole.ADMIN else []
        return sorted(admins + self.other_administrators, key=lambda row: row.id)

    def get_user(self, _user_id: int):
        return self.user

    def lock_user(self, _user_id: int):
        self.calls.append("lock_user")
        return self.user

    def revoke_all_session_families(self, _user_id: int, *, now, reason: str) -> int:
        self.revoked_reason = reason
        return 3

    def release_identifiers(self, user, *, tombstone: str) -> None:
        self.released = tombstone
        user.username = f"deleted-{tombstone}"
        user.email = f"deleted+{tombstone}@secureview.tech"


class FakeFileRepo:
    def __init__(self, files) -> None:
        self.files = files
        self.revoked: list[int] = []

    def lock_owned_files(self, _owner_id: int):
        return self.files

    def revoke_file_access_rows(self, file_pk: int, *, revoked_at) -> None:
        self.revoked.append(file_pk)


class FakeStorage:
    def __init__(self, *, failing: dict[str, Exception] | None = None) -> None:
        self.deleted: list[str] = []
        self.failing = failing or {}

    def delete_object(self, key: str) -> None:
        if key in self.failing:
            raise self.failing[key]
        self.deleted.append(key)


class FakeReauthentication:
    """Stands in for AuthService's shared re-entry throttle: records, never touches a database."""

    def __init__(self, *, blocked: bool = False) -> None:
        self.blocked = blocked
        self.began: list[str] = []
        self.failures: list[dict] = []
        self.cleared = 0
        self.times: list = []

    def begin_reauthentication(self, *, username: str, context, now):
        self.began.append(username)
        self.times.append(now)
        if self.blocked:
            raise AuthenticationRateLimitedError(retry_after_seconds=300)
        return (("REAUTH_ACCOUNT", "hash-account"), ("REAUTH_IP", "hash-ip"))

    def record_reauthentication_failure(self, *, user, buckets, context, now, action, description):
        self.times.append(now)
        self.failures.append({"user": user, "buckets": buckets, "action": action})

    def clear_reauthentication_throttle(self, *, buckets, now) -> None:
        self.times.append(now)
        self.cleared += 1


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, **values) -> None:
        self.entries.append(values)


def _file(pk: int, key: str):
    return SimpleNamespace(
        id=pk,
        storage_object_key=key,
        status="ACTIVE",
        deleted_at=None,
        updated_at=None,
        revision=1,
    )


def _service(
    *, password="correct-horse", files=None, user=None, blocked=False, role=SystemRole.USER
):
    user = user or SimpleNamespace(
        id=7,
        username="waldo",
        email="waldo@secureview.tech",
        password_hash="argon2-hash",
        role=role,
        status=UserStatus.ACTIVE,
        avatar_object_key=None,
        avatar_content_type=None,
        avatar_sha256=None,
        avatar_bytes=None,
        avatar_updated_at=None,
    )
    db = FakeDb()
    auth_repo = FakeAuthRepo(user)
    file_repo = FakeFileRepo(files if files is not None else [])
    storage = FakeStorage()
    audit = FakeAudit()
    reauth = FakeReauthentication(blocked=blocked)
    service = AccountDeletionService(
        db=db,
        passwords=FakePasswords(correct=password),
        storage=storage,
        reauthentication=reauth,
        auth_repository=auth_repo,
        file_repository=file_repo,
        audit_service=audit,
        clock=lambda: NOW,
    )
    return service, SimpleNamespace(
        db=db,
        auth=auth_repo,
        files=file_repo,
        storage=storage,
        audit=audit,
        user=user,
        reauth=reauth,
    )


def test_deletes_the_owned_files_and_their_ciphertext() -> None:
    service, fakes = _service(files=[_file(1, "objects/a"), _file(2, "objects/b")])

    result = service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert result.files_deleted == 2
    assert [f.status for f in fakes.files.files] == ["DELETED", "DELETED"]
    assert fakes.storage.deleted == ["objects/a", "objects/b"]
    # A share handed to someone else must not outlive the account that granted it.
    assert fakes.files.revoked == [1, 2]


def test_ciphertext_is_removed_only_after_the_commit() -> None:
    # If the process dies between the two, rows marked DELETED with objects still present is
    # the recoverable state; live rows whose ciphertext is gone is not.
    service, fakes = _service(files=[_file(1, "objects/a")])
    order: list[str] = []
    fakes.db.commit = lambda: order.append("commit")  # type: ignore[method-assign]
    fakes.storage.delete_object = lambda key: order.append("unlink")  # type: ignore[method-assign]

    service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert order == ["commit", "unlink"]


def test_closes_the_account_and_ends_every_session() -> None:
    service, fakes = _service()

    result = service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert fakes.user.status is UserStatus.DELETED
    assert result.sessions_revoked == 3
    assert fakes.auth.revoked_reason == "account_deleted"


def test_frees_the_username_and_email_for_a_new_account() -> None:
    # The whole point of closing the account is to be able to start over, and
    # identifier_exists does not filter by status -- so leaving these in place would reserve
    # them forever.
    service, fakes = _service()

    service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert fakes.user.username != "waldo"
    assert fakes.user.email != "waldo@secureview.tech"
    # A reserved TLD would register fine and then break serialization wherever it is read back.
    assert fakes.user.email.endswith("@secureview.tech")


def test_a_wrong_password_deletes_nothing() -> None:
    # A live session on an unattended machine must not be enough for the one irreversible
    # action in the application.
    service, fakes = _service(files=[_file(1, "objects/a")])

    with pytest.raises(InvalidCurrentPasswordError):
        service.delete_account(actor=_actor(), password="not-it", context=_context())

    assert fakes.files.files[0].status == "ACTIVE"
    assert fakes.storage.deleted == []
    assert fakes.user.status is UserStatus.ACTIVE
    assert fakes.db.committed == 0
    assert fakes.db.rolled_back == 1


def test_an_already_closed_account_cannot_be_closed_again() -> None:
    closed = SimpleNamespace(
        id=7,
        username="deleted-abc",
        email="deleted+abc@secureview.tech",
        password_hash="argon2-hash",
        role=SystemRole.USER,
        status=UserStatus.DELETED,
    )
    service, fakes = _service(user=closed)

    with pytest.raises(AuthenticationError):
        service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert fakes.storage.deleted == []


def test_records_what_was_destroyed_against_the_real_username() -> None:
    # Written before the identifiers are released, or the history says "deleted-<uuid>" did it.
    service, fakes = _service(files=[_file(1, "objects/a")])

    service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    entry = fakes.audit.entries[0]
    assert entry["action"] == "ACCOUNT_DELETED"
    assert entry["metadata"]["username"] == "waldo"
    assert entry["metadata"]["files_deleted"] == 1


def test_a_wrong_password_counts_against_the_shared_reauthentication_buckets() -> None:
    # Same buckets as change-password, so guesses made here and there add up, and the
    # failure is written to the audit log under its own action.
    service, fakes = _service()

    with pytest.raises(InvalidCurrentPasswordError):
        service.delete_account(actor=_actor(), password="not-it", context=_context())

    assert fakes.reauth.began == ["waldo"]
    (failure,) = fakes.reauth.failures
    assert failure["action"] == "ACCOUNT_DELETION_PASSWORD_FAILED"
    assert failure["user"] is fakes.user
    assert fakes.reauth.cleared == 0
    assert fakes.audit.entries == []


def test_a_blocked_account_is_refused_before_the_password_is_checked() -> None:
    # The 429 comes from the shared throttle and nothing below it runs: no hash comparison,
    # no file touched, no row changed.
    service, fakes = _service(files=[_file(1, "objects/a")], blocked=True)
    verified: list[str] = []
    service.passwords.verify = lambda candidate, _hash: verified.append(candidate) or True  # type: ignore[method-assign]

    with pytest.raises(AuthenticationRateLimitedError):
        service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert verified == []
    assert fakes.files.files[0].status == "ACTIVE"
    assert fakes.user.status is UserStatus.ACTIVE
    assert fakes.db.committed == 0


def test_a_correct_password_clears_the_account_bucket() -> None:
    service, fakes = _service()

    service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert fakes.reauth.cleared == 1
    assert fakes.reauth.failures == []


@pytest.mark.parametrize("password", ["correct-horse", "not-it"])
def test_the_throttle_gets_the_naive_second_resolution_time_it_stores(password: str) -> None:
    # The throttle rows hold naive UTC to the second. Handing them this service's aware
    # clock made the comparison raise a TypeError, which the live stack saw as a 500.
    service, fakes = _service()

    with contextlib.suppress(InvalidCurrentPasswordError):
        service.delete_account(actor=_actor(), password=password, context=_context())

    assert fakes.reauth.times
    assert set(fakes.reauth.times) == {NOW_STORED}


def test_the_file_rows_get_the_same_naive_second_resolution_time() -> None:
    # One instant for the whole deletion, in the form the DATETIME columns store, so what is
    # written is exactly what a later read returns.
    service, fakes = _service(files=[_file(1, "objects/a")])

    service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    (deleted,) = fakes.files.files
    assert deleted.deleted_at == deleted.updated_at == NOW_STORED
    assert set(fakes.reauth.times) == {NOW_STORED}


def test_no_memory_for_a_password_hash_is_a_brief_429_not_a_500() -> None:
    service, fakes = _service(files=[_file(1, "objects/a")])

    def no_capacity(_candidate: str, _hash: str) -> bool:
        raise PasswordOperationCapacityError()

    service.passwords.verify = no_capacity  # type: ignore[method-assign]

    with pytest.raises(AuthenticationRateLimitedError) as excinfo:
        service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert excinfo.value.headers["Retry-After"] == "1"
    # Nothing was checked, so nothing counts as a wrong guess and nothing is deleted.
    assert fakes.reauth.failures == []
    assert fakes.files.files[0].status == "ACTIVE"
    assert fakes.user.status is UserStatus.ACTIVE
    assert fakes.db.committed == 0
    assert fakes.db.rolled_back == 1


@pytest.mark.parametrize(
    "error",
    [StorageObjectError("disk gone"), PermissionError("denied"), ValueError("bad key")],
)
def test_a_failed_unlink_after_the_commit_is_logged_and_the_rest_are_still_removed(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    # The account is already closed when the objects are removed. Answering with an error
    # would tell the person it was not, and stopping would leave the later objects behind.
    service, fakes = _service(
        files=[_file(1, "objects/a"), _file(2, "objects/b"), _file(3, "objects/c")]
    )
    fakes.storage.failing = {"objects/b": error}

    with caplog.at_level(logging.WARNING, logger="app.services.account_deletion_service"):
        result = service.delete_account(
            actor=_actor(), password="correct-horse", context=_context()
        )

    assert result.files_deleted == 3
    assert fakes.user.status is UserStatus.DELETED
    assert fakes.db.committed == 1
    assert fakes.storage.deleted == ["objects/a", "objects/c"]
    (record,) = caplog.records
    assert type(error).__name__ in record.getMessage()


def test_a_failed_avatar_unlink_after_the_commit_is_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, fakes = _service()
    fakes.user.avatar_object_key = "ab/cdef"

    class BrokenAvatars:
        def delete_sync(self, _key: str) -> None:
            raise OSError("read-only file system")

    service.avatar_storage = BrokenAvatars()  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING, logger="app.services.account_deletion_service"):
        service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert fakes.user.status is UserStatus.DELETED
    assert fakes.user.avatar_object_key is None
    assert len(caplog.records) == 1


def _administrator(pk: int, status: UserStatus = UserStatus.ACTIVE):
    return SimpleNamespace(id=pk, role=SystemRole.ADMIN, status=status)


def test_the_last_active_administrator_cannot_close_their_account() -> None:
    # Nothing in the application can appoint an administrator, so this would leave the
    # admin console out of reach. A disabled administrator does not count as the one who stays.
    service, fakes = _service(files=[_file(1, "objects/a")], role=SystemRole.ADMIN)
    fakes.auth.other_administrators = [_administrator(3, UserStatus.DISABLED)]
    verified: list[str] = []
    service.passwords.verify = lambda candidate, _hash: verified.append(candidate) or True  # type: ignore[method-assign]

    with pytest.raises(LastAdministratorError) as excinfo:
        service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert excinfo.value.code == "last_admin"
    assert verified == []
    assert fakes.user.status is UserStatus.ACTIVE
    assert fakes.files.files[0].status == "ACTIVE"
    assert fakes.storage.deleted == []
    assert fakes.db.committed == 0
    assert fakes.db.rolled_back == 1


def test_an_administrator_can_close_their_account_while_another_is_active() -> None:
    service, fakes = _service(role=SystemRole.ADMIN)
    fakes.auth.other_administrators = [_administrator(3)]

    service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert fakes.user.status is UserStatus.DELETED
    assert fakes.db.committed == 1
    # The administrator rows are locked before the account's own row, in the order an
    # administrator disable takes them, so two such changes cannot interleave.
    assert fakes.auth.calls == ["lock_administrators", "lock_user"]


def test_an_ordinary_account_does_not_lock_the_administrators() -> None:
    service, fakes = _service()

    service.delete_account(actor=_actor(), password="correct-horse", context=_context())

    assert fakes.user.status is UserStatus.DELETED
    assert fakes.auth.calls == ["lock_user"]
