"""Multi-connection races against real MySQL 8.4 (issue #58).

Every test here drives the real services from several independent connections at once --
real threads released together by a barrier, each with its own `Engine.connect()` and
`Session` -- because a single connection can never observe the blocking the services'
`SELECT ... FOR UPDATE` locks exist to provide. Each test states the invariant the lock
protects and checks it in the database afterwards, not just in the return values.

See `_concurrency_support.py` for why registered users and their audit rows are left in
the database rather than cleaned up.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import Engine, event, func, select
from tests.integration._concurrency_support import (
    RegisteredUser,
    UploadedFile,
    active_recovery_key,
    fresh_ip,
    integration_settings,
    outcome_names,
    race,
    register_real_user,
    request_context,
    rsa_unwrap,
    rsa_wrap,
    session_scope,
    sign_rsa_pss_sha256,
    upload_file,
)
from tests.integration.test_file_lifecycle_mysql import _public_pem_and_fingerprint

from app.core.security import PasswordManager
from app.domain.enums import LoginThrottleScope, SessionStatus, SystemRole
from app.domain.errors import (
    AuthenticationRateLimitedError,
    FileResourceNotFoundError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    KeyBundleRevisionConflictError,
    RecoveryStateConflictError,
)
from app.domain.keys import KeyProtectionProfileInput
from app.models.audit_log import AuditLog
from app.models.auth_login_throttle import AuthLoginThrottle
from app.models.file import File
from app.models.file_access_grant import FileAccessGrant
from app.models.file_key_wrapping import FileKeyWrapping
from app.models.recovery_request import RecoveryRequest
from app.models.user_key import UserKey
from app.models.user_key_protection_profile import UserKeyProtectionProfile
from app.models.user_session import UserSession
from app.services.audit_log_service import AuditLogService
from app.services.audit_query_service import AuditQueryService
from app.services.auth_service import AuthService
from app.services.key_service import KeyService
from app.services.recovery_service import RecoveryService
from app.services.sharing_service import SharingService

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Authentication: session limit, throttle counter, refresh-token reuse.
# ---------------------------------------------------------------------------


def test_concurrent_logins_hold_the_session_limit_exactly(auth_mysql_engine: Engine) -> None:
    """Eight simultaneous logins against a limit of three leave exactly three sessions.

    `login` locks the user row before counting active sessions. Without that lock each
    racer reads the same stale count, evicts nothing, and the account ends up with eight.
    """
    user = register_real_user(auth_mysql_engine, prefix="concy-sess")
    settings = integration_settings(AUTH_MAX_ACTIVE_SESSIONS=3)
    racers = 8
    # One capacity slot per racer, as a server with that many workers would have; the
    # default of two would reject most racers before they reached the code under test.
    passwords = PasswordManager(max_concurrent_operations=racers)
    ip = fresh_ip()

    def login(_: int) -> None:
        with session_scope(auth_mysql_engine) as session:
            AuthService(db=session, settings=settings, passwords=passwords).login(
                username=user.username,
                password=user.password,
                context=request_context(ip_address=ip),
            )

    assert outcome_names(race(login, racers)) == ["ok"] * racers

    with session_scope(auth_mysql_engine) as session:
        statuses = session.scalars(
            select(UserSession.status).where(UserSession.user_id == user.user_id)
        ).all()
    assert len(statuses) == racers
    assert statuses.count(SessionStatus.ACTIVE) == settings.AUTH_MAX_ACTIVE_SESSIONS


def test_two_simultaneous_fresh_account_logins_never_surface_a_deadlock(
    auth_mysql_engine: Engine,
) -> None:
    """Two brand-new accounts signing in at the same instant must not 500 (issue #139).

    Each has no `user_sessions` row yet, so `lock_active_sessions`'s `SELECT ... FOR UPDATE`
    matches nothing and InnoDB takes a gap lock on the still-empty tail of
    `idx_user_sessions_user_status` instead of a single row. Two such accounts -- the two
    newest in the table -- land in the same gap; whichever inserts its new session second
    deadlocks against the other under MySQL error 1213. `login` retries the whole attempt on
    exactly that error (`app.core.db_retry`), so this must come back clean every time, not
    just on average. A single iteration reproduced the deadlock on the unfixed code about
    70% of the time, so the loop below would almost certainly have caught a regression even
    without asserting on every iteration -- it asserts on every one anyway.
    """
    settings = integration_settings()
    passwords = PasswordManager(max_concurrent_operations=2)

    for _ in range(5):
        first = register_real_user(auth_mysql_engine, prefix="concy-fresh-a")
        second = register_real_user(auth_mysql_engine, prefix="concy-fresh-b")
        accounts = (first, second)

        def login(index: int, accounts: tuple = accounts) -> None:
            user = accounts[index]
            with session_scope(auth_mysql_engine) as session:
                AuthService(db=session, settings=settings, passwords=passwords).login(
                    username=user.username,
                    password=user.password,
                    context=request_context(),
                )

        results = race(login, 2)
        assert outcome_names(results) == ["ok", "ok"], results

    with session_scope(auth_mysql_engine) as session:
        for user in (first, second):
            statuses = session.scalars(
                select(UserSession.status).where(UserSession.user_id == user.user_id)
            ).all()
            assert statuses == [SessionStatus.ACTIVE]


def test_concurrent_wrong_passwords_are_all_counted_and_lock_the_account(
    auth_mysql_engine: Engine,
) -> None:
    """No failed attempt is lost to a racing increment, and the lockout then holds.

    `_record_login_failure` increments the bucket under a row lock. A lost update would
    let an attacker spend N guesses while being charged for fewer, and use concurrency
    to stay under the lockout indefinitely.
    """
    user = register_real_user(auth_mysql_engine, prefix="concy-throt")
    settings = integration_settings()
    racers = settings.AUTH_LOGIN_ACCOUNT_MAX_FAILURES + 2
    passwords = PasswordManager(max_concurrent_operations=racers)
    ip = fresh_ip()

    def wrong_password(_: int) -> None:
        with session_scope(auth_mysql_engine) as session:
            AuthService(db=session, settings=settings, passwords=passwords).login(
                username=user.username,
                password="definitely-not-the-password",
                context=request_context(ip_address=ip),
            )

    results = race(wrong_password, racers)
    assert all(
        isinstance(r, InvalidCredentialsError | AuthenticationRateLimitedError) for r in results
    ), results
    rejected_as_wrong = sum(isinstance(r, InvalidCredentialsError) for r in results)

    with session_scope(auth_mysql_engine) as session:
        service = AuthService(db=session, settings=settings, passwords=passwords)
        account_bucket = next(
            key_hash
            for scope, key_hash in service._login_buckets(
                user.username, request_context(ip_address=ip)
            )
            if scope is LoginThrottleScope.ACCOUNT
        )
        throttle = session.scalar(
            select(AuthLoginThrottle).where(
                AuthLoginThrottle.scope == LoginThrottleScope.ACCOUNT,
                AuthLoginThrottle.key_hash == account_bucket,
            )
        )
        assert throttle is not None
        # Every attempt that got as far as checking the password was charged, exactly once.
        assert throttle.failed_count == rejected_as_wrong
        assert throttle.failed_count >= settings.AUTH_LOGIN_ACCOUNT_MAX_FAILURES
        assert throttle.blocked_until is not None

        # And the lockout is real: even the right password is refused while it holds.
        with pytest.raises(AuthenticationRateLimitedError):
            service.login(
                username=user.username,
                password=user.password,
                context=request_context(ip_address=ip),
            )


def test_racing_refreshes_of_one_token_let_at_most_one_through(
    auth_mysql_engine: Engine,
) -> None:
    """Eight simultaneous presentations of one refresh token: one rotation, then reuse.

    `refresh` locks the stored token row before reading `consumed_at`. Whoever gets the
    lock first rotates; everyone after sees a consumed token, which is indistinguishable
    from a stolen copy, so the whole family -- the winner's fresh tokens included -- is
    revoked. Without the lock, several racers would each mint a live session.
    """
    user = register_real_user(auth_mysql_engine, prefix="concy-refresh")
    settings = integration_settings(AUTH_REFRESH_MIN_INTERVAL_SECONDS=1)
    ip = fresh_ip()
    with session_scope(auth_mysql_engine) as session:
        login = AuthService(db=session, settings=settings).login(
            username=user.username, password=user.password, context=request_context(ip_address=ip)
        )
    # Rows hold whole seconds; wait out the one-second minimum interval with margin.
    time.sleep(2.1)

    def refresh(_: int) -> None:
        with session_scope(auth_mysql_engine) as session:
            AuthService(db=session, settings=settings).refresh(
                refresh_token=login.tokens.refresh_token,
                context=request_context(ip_address=ip),
            )

    racers = 8
    results = race(refresh, racers)

    assert outcome_names(results).count("ok") == 1, results
    assert sum(isinstance(r, InvalidRefreshTokenError) for r in results) == racers - 1

    with session_scope(auth_mysql_engine) as session:
        family = session.scalars(
            select(UserSession).where(UserSession.user_id == user.user_id)
        ).all()
        assert [s.status for s in family] == [SessionStatus.REVOKED]
        replay_rows = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "AUTH_REFRESH_REPLAY_DETECTED",
                AuditLog.resource_id == str(login.tokens.session_id),
            )
        )
        assert replay_rows == racers - 1


# ---------------------------------------------------------------------------
# The audit hash chain under concurrent writers, some of which roll back.
# ---------------------------------------------------------------------------


def test_concurrent_audit_appends_and_rollbacks_leave_one_valid_chain(
    auth_mysql_engine: Engine,
) -> None:
    """Twenty writers append at once; a fifth of them fail mid-transaction and roll back.

    `AuditLogService.append` reads and advances the singleton chain head under a row lock.
    If two writers read the same head, both rows link to the same parent and the chain
    forks. A writer that rolls back after linking must leave the head exactly where it was.
    The check is the product's own verifier, run over the entire table.
    """
    user = register_real_user(auth_mysql_engine, prefix="concy-audit", role=SystemRole.ADMIN)
    marker = f"concy-audit-{uuid4().hex}"
    writers = 20

    class InjectedFailure(RuntimeError):
        pass

    def append(index: int) -> int:
        with session_scope(auth_mysql_engine) as session:
            log = AuditLogService(session).append(
                action="AUTH_LOGIN_SUCCEEDED",
                result="SUCCESS",
                actor_user_id=user.user_id,
                target_user_id=user.user_id,
                resource_id=f"{marker}-{index}",
                context_ip_address="198.51.100.7",
                context_user_agent="concurrency-suite",
            )
            if index % 5 == 0:
                # The row and the head update are flushed; now the request fails.
                session.rollback()
                raise InjectedFailure
            session.commit()
            return log.id

    results = race(append, writers)
    committed = {r for r in results if isinstance(r, int)}
    assert len(committed) == writers - writers // 5
    assert sum(isinstance(r, InjectedFailure) for r in results) == writers // 5

    with session_scope(auth_mysql_engine) as session:
        stored = session.scalars(
            select(AuditLog).where(AuditLog.resource_id.like(f"{marker}-%"))
        ).all()
        # Only committed rows exist, and no two of them share a parent.
        assert {row.id for row in stored} == committed
        assert len({row.previous_hash for row in stored}) == len(stored)

        verdict = AuditQueryService(db=session).verify_chain(actor=user.actor())
    assert verdict["valid"] is True, verdict


# ---------------------------------------------------------------------------
# Key rotation: two rewraps prepared against the same revision.
# ---------------------------------------------------------------------------


def _rewrap_input(user: RegisteredUser, salt: bytes) -> KeyProtectionProfileInput:
    return KeyProtectionProfileInput(
        profile_id=user.profile_id,
        format_version=1,
        kdf_algorithm="ARGON2ID",
        kdf_version=19,
        kdf_salt=salt,
        kdf_memory_kib=65_536,
        kdf_iterations=3,
        kdf_parallelism=4,
        derived_key_length=32,
        amk_wrapping_algorithm="AES-256-GCM",
        wrapped_amk=b"W" * 32,
        amk_nonce=b"N" * 12,
        amk_auth_tag=b"T" * 16,
        aad_version=1,
    )


def test_racing_key_rewraps_at_one_revision_yield_one_winner_and_a_clean_conflict(
    auth_mysql_engine: Engine,
) -> None:
    """Two devices change the passphrase at once, both starting from revision R.

    As over HTTP, each device first fetches the signing payload (its own request, its own
    transaction) and signs it; only then do the two submissions race. The profile row lock
    plus the revision check must let exactly one through and hand the other a conflict --
    never apply both, which would leave the stored AMK wrapped under whichever passphrase
    happened to write last while the other device believes it succeeded.
    """
    user = register_real_user(auth_mysql_engine, prefix="concy-rot")
    settings = integration_settings()
    with session_scope(auth_mysql_engine) as session:
        start = session.scalar(
            select(UserKeyProtectionProfile.revision).where(
                UserKeyProtectionProfile.user_id == user.user_id
            )
        )
    assert start is not None

    salts = [b"A" * 16, b"B" * 16]
    signed = []
    for salt in salts:
        with session_scope(auth_mysql_engine) as session:
            payload = KeyService(db=session, settings=settings).get_rewrap_signing_payload(
                actor=user.actor(),
                authorizing_key_id=user.key_id,
                expected_revision=start,
                protection=_rewrap_input(user, salt),
            )
            session.rollback()
        signed.append(sign_rsa_pss_sha256(user.private_key, payload))

    def submit(index: int) -> bytes:
        with session_scope(auth_mysql_engine) as session:
            KeyService(db=session, settings=settings).rewrap_protection_profile(
                actor=user.actor(),
                authorizing_key_id=user.key_id,
                expected_revision=start,
                protection=_rewrap_input(user, salts[index]),
                authorization_signature=signed[index],
                context=request_context(),
            )
            return salts[index]

    results = race(submit, 2)
    assert outcome_names(results) == ["KeyBundleRevisionConflictError", "ok"], results
    winner = next(r for r in results if isinstance(r, bytes))

    with session_scope(auth_mysql_engine) as session:
        profile = session.scalar(
            select(UserKeyProtectionProfile).where(UserKeyProtectionProfile.user_id == user.user_id)
        )
        assert profile is not None
        assert profile.revision == start + 1
        assert profile.kdf_salt == winner

    # The loser retrying with its stale revision is still refused, not silently applied.
    with (
        session_scope(auth_mysql_engine) as session,
        pytest.raises(KeyBundleRevisionConflictError),
    ):
        KeyService(db=session, settings=settings).rewrap_protection_profile(
            actor=user.actor(),
            authorizing_key_id=user.key_id,
            expected_revision=start,
            protection=_rewrap_input(user, salts[0] if winner == salts[1] else salts[1]),
            authorization_signature=signed[0] if winner == salts[1] else signed[1],
            context=request_context(),
        )


# ---------------------------------------------------------------------------
# Sharing and recovery.
# ---------------------------------------------------------------------------


def _share(session, owner: RegisteredUser, uploaded: UploadedFile, target: RegisteredUser):
    return SharingService(db=session).share(
        actor=owner.actor(),
        file_id=uploaded.file_id,
        target_user_id=target.user_uuid,
        target_key_id=target.key_id,
        wrapped_file_key=rsa_wrap(target.public_key_pem, uploaded.dek),
        can_download=True,
        can_share=False,
        context=request_context(),
    )


def _access_rows(engine: Engine, uploaded: UploadedFile, user: RegisteredUser):
    with session_scope(engine) as session:
        file_row = session.scalar(select(File).where(File.file_uuid == str(uploaded.file_id)))
        assert file_row is not None
        grants = session.scalars(
            select(FileAccessGrant).where(
                FileAccessGrant.file_id == file_row.id,
                FileAccessGrant.user_id == user.user_id,
            )
        ).all()
        wrappings = session.scalars(
            select(FileKeyWrapping).where(
                FileKeyWrapping.file_id == file_row.id,
                FileKeyWrapping.recipient_user_id == user.user_id,
            )
        ).all()
        return file_row, grants, wrappings


def test_two_simultaneous_shares_to_one_recipient_create_one_grant(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    """A double-clicked share must not produce two grants or two live wrappings."""
    owner = register_real_user(auth_mysql_engine, prefix="concy-share-o")
    recipient = register_real_user(auth_mysql_engine, prefix="concy-share-r")
    with active_recovery_key(auth_mysql_engine) as recovery:
        uploaded = upload_file(auth_mysql_engine, tmp_path, owner, recovery)

        def share(_: int):
            with session_scope(auth_mysql_engine) as session:
                return _share(session, owner, uploaded, recipient)

        results = race(share, 2)

    assert outcome_names(results) == ["ok", "ok"], results
    assert sorted(created for created, _status in results) == [False, True]
    _file, grants, wrappings = _access_rows(auth_mysql_engine, uploaded, recipient)
    assert len(grants) == 1
    assert grants[0].status == "ACTIVE"
    assert grants[0].revision == 2
    assert [w.status for w in wrappings] == ["ACTIVE"]


def test_a_share_racing_a_delete_never_leaves_live_access_to_a_deleted_file(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    """Whichever commits first, a deleted file ends with no active grant or wrapping."""
    from tests.integration._concurrency_support import file_service

    owner = register_real_user(auth_mysql_engine, prefix="concy-del-o")
    recipient = register_real_user(auth_mysql_engine, prefix="concy-del-r")
    with active_recovery_key(auth_mysql_engine) as recovery:
        uploaded = upload_file(auth_mysql_engine, tmp_path, owner, recovery)

        def act(index: int):
            with session_scope(auth_mysql_engine) as session:
                if index == 0:
                    return _share(session, owner, uploaded, recipient)
                return file_service(session, tmp_path).delete(
                    actor=owner.actor(), file_id=uploaded.file_id, context=request_context()
                )

        share_result, delete_result = race(act, 2)

    assert not isinstance(delete_result, Exception), delete_result
    # The share either won the lock (and was then revoked by the delete) or lost it and
    # found the file gone. Nothing else is acceptable.
    assert not isinstance(share_result, Exception) or isinstance(
        share_result, FileResourceNotFoundError
    ), share_result
    file_row, grants, wrappings = _access_rows(auth_mysql_engine, uploaded, recipient)
    assert file_row.status == "DELETED"
    assert all(g.status == "REVOKED" for g in grants)
    assert all(w.status == "REVOKED" for w in wrappings)


def test_simultaneous_recovery_requests_for_one_file_open_exactly_one(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    """The pending-request check happens under the file lock, so four racers get one."""
    owner = register_real_user(auth_mysql_engine, prefix="concy-rec-o")
    with active_recovery_key(auth_mysql_engine) as recovery:
        uploaded = upload_file(auth_mysql_engine, tmp_path, owner, recovery)

        def request(_: int):
            with session_scope(auth_mysql_engine) as session:
                return RecoveryService(db=session).create_request(
                    actor=owner.actor(),
                    file_id=uploaded.file_id,
                    reason="lost the passphrase on this device",
                    target_key_id=owner.key_id,
                    context=request_context(),
                )

        results = race(request, 4)

    assert outcome_names(results) == ["RecoveryStateConflictError"] * 3 + ["ok"], results
    with session_scope(auth_mysql_engine) as session:
        statuses = session.scalars(
            select(RecoveryRequest.status)
            .join(File, File.id == RecoveryRequest.file_id)
            .where(File.file_uuid == str(uploaded.file_id))
        ).all()
    assert statuses == ["PENDING"]


def test_a_recovery_execution_racing_a_revocation_cannot_restore_revoked_access(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    """The dangerous interleaving: an admin executes a recipient's approved recovery while
    the owner revokes that recipient.

    If execution checked the grant, then the revoke committed, then execution wrote its new
    wrapping, the recipient would hold a live file key to a file they were just removed
    from. Both paths lock the file row first, so one must fully precede the other.
    """
    owner = register_real_user(auth_mysql_engine, prefix="concy-rx-o")
    recipient = register_real_user(auth_mysql_engine, prefix="concy-rx-r")
    admin = register_real_user(auth_mysql_engine, prefix="concy-rx-a", role=SystemRole.ADMIN)
    # The realistic case: the recipient has since added a key on a new device (successor
    # keys stay ACTIVE beside the old one) and asks for the file to be recovered to it, so
    # execution must write a brand-new wrapping rather than touch the existing one.
    new_device_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_device_pem, new_device_fingerprint = _public_pem_and_fingerprint(new_device_private)
    new_device_key_id = uuid4()
    with session_scope(auth_mysql_engine) as session:
        session.add(
            UserKey(
                key_uuid=str(new_device_key_id),
                user_id=recipient.user_id,
                public_key_pem=new_device_pem,
                algorithm="RSA-OAEP-SHA256",
                key_size_bits=2048,
                fingerprint=new_device_fingerprint,
                status="ACTIVE",
            )
        )
        session.commit()
    with active_recovery_key(auth_mysql_engine) as recovery:
        uploaded = upload_file(auth_mysql_engine, tmp_path, owner, recovery)
        with session_scope(auth_mysql_engine) as session:
            _share(session, owner, uploaded, recipient)
        with session_scope(auth_mysql_engine) as session:
            record = RecoveryService(db=session).create_request(
                actor=recipient.actor(),
                file_id=uploaded.file_id,
                reason="new device",
                target_key_id=new_device_key_id,
                context=request_context(),
            )
            request_id = UUID(record.request.request_uuid)
        with session_scope(auth_mysql_engine) as session:
            RecoveryService(db=session).approve_request(
                actor=admin.actor(), request_id=request_id, context=request_context()
            )
        # What the administrator computes offline: open the recovery wrapping with the
        # recovery private key, rewrap the same DEK to the requester's key.
        file_row, _grants, _wrappings = _access_rows(auth_mysql_engine, uploaded, recipient)
        with session_scope(auth_mysql_engine) as session:
            recovery_wrapped = session.scalar(
                select(FileKeyWrapping.wrapped_file_key).where(
                    FileKeyWrapping.file_id == file_row.id,
                    FileKeyWrapping.recipient_type == "RECOVERY",
                )
            )
        dek = rsa_unwrap(recovery.private_key, recovery_wrapped)
        assert dek == uploaded.dek
        rewrapped = rsa_wrap(new_device_pem, dek)

        # Hold the executing transaction just before its first write -- after it has
        # checked the grant -- and let the revoke run in that window. With the file-row
        # lock the revoke cannot proceed, so the pause simply times out; without it, the
        # revoke commits first and the execution then writes a live wrapping anyway.
        execution_checked = threading.Event()
        revoke_finished = threading.Event()

        def pause_before_first_write(_conn, _cursor, statement, *_args) -> None:
            if not execution_checked.is_set() and statement.lstrip().startswith(
                ("UPDATE", "INSERT")
            ):
                execution_checked.set()
                revoke_finished.wait(timeout=2)

        def act(index: int):
            with session_scope(auth_mysql_engine) as session:
                if index == 0:
                    event.listen(
                        session.connection(), "before_cursor_execute", pause_before_first_write
                    )
                    return RecoveryService(db=session).execute_request(
                        actor=admin.actor(),
                        request_id=request_id,
                        wrapped_file_key=rewrapped,
                        recovery_key_id=recovery.key_id,
                        target_key_id=new_device_key_id,
                        context=request_context(),
                    )
                assert execution_checked.wait(timeout=10)
                try:
                    return SharingService(db=session).revoke(
                        actor=owner.actor(),
                        file_id=uploaded.file_id,
                        target_user_id=recipient.user_uuid,
                        context=request_context(),
                    )
                finally:
                    revoke_finished.set()

        execute_result, revoke_result = race(act, 2)

    print("OUTCOMES", repr(execute_result), repr(revoke_result))
    assert revoke_result is True, revoke_result
    assert not isinstance(execute_result, Exception) or isinstance(
        execute_result, RecoveryStateConflictError
    ), execute_result
    _file, grants, wrappings = _access_rows(auth_mysql_engine, uploaded, recipient)
    assert [g.status for g in grants] == ["REVOKED"]
    assert all(w.status == "REVOKED" for w in wrappings), [w.status for w in wrappings]
