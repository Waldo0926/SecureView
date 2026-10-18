"""`scripts/reconcile.py` against the real migrated schema (issue #57).

The unit tests pin each predicate and the storage scan in isolation. These run the whole
job the way the systemd unit does -- one `reconcile()` call over a real MySQL 8.4 schema
and a real object store -- and check the four properties the staging timer depends on:

* the report shows every category from both sides of its cutoff;
* a run over the volume limit deletes nothing and exits non-zero;
* two consecutive runs converge: the second finds nothing;
* no statement the job sends names an audit, identity, key-custody or recovery table,
  and live rows, the audit chain head, and referenced objects are untouched.

Seeded rows use timestamps relative to now and a fresh UUID per row, so the tests only
reason about differences they caused and never collide with rows other suites leave.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import sessionmaker
from tests.integration._concurrency_support import (
    RecoveryKeyPair,
    RegisteredUser,
    active_recovery_key,
    integration_settings,
    register_real_user,
    session_scope,
    upload_file,
)

from app.core.time import to_second_resolution_utc, utc_now
from app.domain.enums import LoginThrottleScope, VerificationPurpose
from app.models.audit_chain_head import AuditChainHead
from app.models.audit_log import AuditLog
from app.models.auth_login_throttle import AuthLoginThrottle
from app.models.email_verification_code import EmailVerificationCode
from app.models.session_refresh_token import SessionRefreshToken
from app.models.user import User
from app.models.user_session import UserSession

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RETAIN_DAYS = 30
GRACE_MINUTES = 60
GENEROUS = 1_000_000

FORBIDDEN_TABLES = (
    "audit_logs",
    "audit_chain_heads",
    "users",
    "user_keys",
    "user_key_protection_profiles",
    "encrypted_private_key_bundles",
    "recovery_keys",
    "recovery_requests",
    "file_key_wrappings",
    "file_access_grants",
    "file_folders",
    "integrity_checks",
)
RECONCILED_TABLES = frozenset(
    {"session_refresh_tokens", "user_sessions", "auth_login_throttles", "email_verification_codes"}
)


def _load_reconcile():
    spec = importlib.util.spec_from_file_location(
        "reconcile_mysql_under_test", BACKEND_ROOT / "scripts" / "reconcile.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def job(auth_mysql_engine: Engine, tmp_path: Path, monkeypatch):
    module = _load_reconcile()
    settings = integration_settings(
        ENCRYPTED_FILE_DIR=tmp_path / "objects", TEMP_FILE_DIR=tmp_path / "staging"
    )
    settings.ENCRYPTED_FILE_DIR.mkdir(parents=True)
    settings.TEMP_FILE_DIR.mkdir(parents=True)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        module, "SessionLocal", sessionmaker(bind=auth_mysql_engine, expire_on_commit=False)
    )
    return module


def _run(job, *, apply: bool, max_deletions: int = GENEROUS, max_object_deletions: int = GENEROUS):
    return job.reconcile(
        retain_days=RETAIN_DAYS,
        storage_grace_minutes=GRACE_MINUTES,
        apply=apply,
        max_deletions=max_deletions,
        max_object_deletions=max_object_deletions,
    )


def _counts(report) -> dict[str, tuple[int, int, int]]:
    return {f.what: (f.count, f.recent, f.upcoming) for f in report.findings}


@pytest.fixture(scope="module")
def owner(auth_mysql_engine: Engine) -> RegisteredUser:
    return register_real_user(auth_mysql_engine, prefix="reconcile-owner")


@pytest.fixture
def recovery(auth_mysql_engine: Engine) -> Iterator[RecoveryKeyPair]:
    with active_recovery_key(auth_mysql_engine) as pair:
        yield pair


def _hash() -> str:
    return (uuid4().hex + uuid4().hex)[:64]


@dataclass
class Seeded:
    past_session: int
    past_token: int
    inside_session: int
    inside_token: int
    live_session: int
    past_throttle: str
    blocking_throttle: str
    past_code: int
    inside_code: int


def _seed_rows(engine: Engine, owner: RegisteredUser) -> Seeded:
    """One row each side of every row cutoff, plus rows that must survive regardless.

    "past" lapsed 3 days before the 30-day cutoff (eligible, crossed within 7 days).
    "inside" lapsed 27 days ago -- kept today, crosses the cutoff in 3 days.
    """
    now = to_second_resolution_utc(utc_now())
    past = now - timedelta(days=RETAIN_DAYS + 3)
    inside = now - timedelta(days=RETAIN_DAYS - 3)

    def session_row(expires: datetime) -> UserSession:
        return UserSession(
            user_id=owner.user_id,
            access_token_hash=_hash(),
            created_at=expires - timedelta(days=7),
            updated_at=expires - timedelta(days=7),
            access_expires_at=expires - timedelta(days=6),
            absolute_expires_at=expires,
        )

    def token_row(session: UserSession, expires: datetime) -> SessionRefreshToken:
        return SessionRefreshToken(
            session_id=session.id,
            token_hash=_hash(),
            generation=1,
            created_at=expires - timedelta(days=7),
            expires_at=expires,
        )

    def code_row(expires: datetime) -> EmailVerificationCode:
        return EmailVerificationCode(
            purpose=VerificationPurpose.REGISTRATION,
            email=f"reconcile-{uuid4().hex[:12]}@example.com",
            code_hash=_hash(),
            created_at=expires - timedelta(minutes=10),
            expires_at=expires,
        )

    with session_scope(engine) as db:
        past_session = session_row(past)
        inside_session = session_row(inside)
        live_session = session_row(now + timedelta(days=7))
        db.add_all([past_session, inside_session, live_session])
        db.flush()
        past_token = token_row(past_session, past)
        inside_token = token_row(inside_session, inside)
        past_throttle = AuthLoginThrottle(
            scope=LoginThrottleScope.IP, key_hash=_hash(), failed_count=3, window_started_at=past
        )
        # An old window whose block still runs: removing it would lift a lockout.
        blocking_throttle = AuthLoginThrottle(
            scope=LoginThrottleScope.ACCOUNT,
            key_hash=_hash(),
            failed_count=10,
            window_started_at=past,
            blocked_until=now + timedelta(hours=1),
        )
        past_code = code_row(past)
        inside_code = code_row(inside)
        db.add_all([past_token, inside_token, past_throttle, blocking_throttle])
        db.add_all([past_code, inside_code])
        db.commit()
        return Seeded(
            past_session=past_session.id,
            past_token=past_token.id,
            inside_session=inside_session.id,
            inside_token=inside_token.id,
            live_session=live_session.id,
            past_throttle=past_throttle.key_hash,
            blocking_throttle=blocking_throttle.key_hash,
            past_code=past_code.id,
            inside_code=inside_code.id,
        )


def _age(path: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _seed_storage(root: Path) -> dict[str, Path]:
    objects = root / "objects"
    paths = {
        "past_orphan": objects / str(uuid4()) / f"{uuid4()}.ciphertext",
        "inside_orphan": objects / str(uuid4()) / f"{uuid4()}.ciphertext",
        "old_empty_dir": objects / str(uuid4()),
        "fresh_empty_dir": objects / str(uuid4()),
        "past_staged": root / "staging" / f".{uuid4().hex}.staging",
    }
    for key in ("past_orphan", "inside_orphan"):
        paths[key].parent.mkdir(parents=True)
        paths[key].write_bytes(b"orphaned ciphertext")
    paths["old_empty_dir"].mkdir()
    paths["fresh_empty_dir"].mkdir()
    paths["past_staged"].write_bytes(b"abandoned upload")
    for key in ("past_orphan", "old_empty_dir", "past_staged"):
        _age(paths[key], 2 * 3600)
    _age(paths["past_orphan"].parent, 2 * 3600)
    return paths


def _exists(engine: Engine, model, column, value) -> bool:
    with session_scope(engine) as db:
        return db.scalar(select(func.count()).select_from(model).where(column == value)) == 1


def _audit_state(engine: Engine) -> tuple[int, int | None, str | None, int]:
    with session_scope(engine) as db:
        head = db.scalar(select(AuditChainHead).where(AuditChainHead.id == 1))
        assert head is not None
        logs = db.scalar(select(func.count()).select_from(AuditLog))
        users = db.scalar(select(func.count()).select_from(User))
        return int(logs or 0), head.last_log_id, head.current_hash, int(users or 0)


# ---------------------------------------------------------------------------


def test_the_report_shows_every_row_boundary_from_both_sides(
    job, auth_mysql_engine: Engine, owner: RegisteredUser, tmp_path: Path
) -> None:
    before = _counts(_run(job, apply=False))
    seeded = _seed_rows(auth_mysql_engine, owner)
    _seed_storage(tmp_path)
    after = _counts(_run(job, apply=False))

    def delta(what: str) -> tuple[int, int, int]:
        return tuple(a - b for a, b in zip(after[what], before[what], strict=True))

    # (eligible, crossed in the last 7 days, crosses in the next 7 days)
    assert delta("expired refresh tokens") == (1, 1, 1)
    assert delta("expired sessions") == (1, 1, 1)
    assert delta("lapsed throttle buckets") == (1, 1, 0)  # the blocking bucket is on neither side
    assert delta("expired verification codes") == (1, 1, 1)
    assert after["orphaned ciphertext objects"] == (1, 1, 1)
    assert after["empty per-file directories"] == (1, 1, 1)
    assert after["stale staged uploads"] == (1, 1, 0)

    # Report only: every seeded row is still there.
    assert _exists(auth_mysql_engine, UserSession, UserSession.id, seeded.past_session)
    assert _exists(
        auth_mysql_engine, AuthLoginThrottle, AuthLoginThrottle.key_hash, seeded.past_throttle
    )


def test_a_run_over_the_limit_deletes_nothing_and_exits_3(
    job, auth_mysql_engine: Engine, owner: RegisteredUser, tmp_path: Path, capsys
) -> None:
    seeded = _seed_rows(auth_mysql_engine, owner)
    storage = _seed_storage(tmp_path)

    status = job.main(["--apply", "--max-deletions", "0"])

    assert status == job.EXIT_VOLUME_REFUSED == 3
    assert "REFUSED" in capsys.readouterr().err
    assert _exists(auth_mysql_engine, UserSession, UserSession.id, seeded.past_session)
    assert _exists(
        auth_mysql_engine, SessionRefreshToken, SessionRefreshToken.id, seeded.past_token
    )
    assert _exists(
        auth_mysql_engine, EmailVerificationCode, EmailVerificationCode.id, seeded.past_code
    )
    assert storage["past_orphan"].exists()
    assert storage["old_empty_dir"].exists()
    assert storage["past_staged"].exists()


def test_apply_removes_only_what_crossed_and_a_second_run_finds_nothing(
    job,
    auth_mysql_engine: Engine,
    owner: RegisteredUser,
    recovery: RecoveryKeyPair,
    tmp_path: Path,
) -> None:
    seeded = _seed_rows(auth_mysql_engine, owner)
    storage = _seed_storage(tmp_path)
    live = upload_file(auth_mysql_engine, tmp_path, owner, recovery)
    live_object = next((tmp_path / "objects" / str(live.file_id)).glob("*.ciphertext"))
    _age(live_object, 90 * 86400)
    audit_before = _audit_state(auth_mysql_engine)

    first = _run(job, apply=True)
    assert first.applied and first.refused is None

    gone = [
        (UserSession, UserSession.id, seeded.past_session),
        (SessionRefreshToken, SessionRefreshToken.id, seeded.past_token),
        (AuthLoginThrottle, AuthLoginThrottle.key_hash, seeded.past_throttle),
        (EmailVerificationCode, EmailVerificationCode.id, seeded.past_code),
    ]
    kept = [
        (UserSession, UserSession.id, seeded.inside_session),
        (UserSession, UserSession.id, seeded.live_session),
        (SessionRefreshToken, SessionRefreshToken.id, seeded.inside_token),
        (AuthLoginThrottle, AuthLoginThrottle.key_hash, seeded.blocking_throttle),
        (EmailVerificationCode, EmailVerificationCode.id, seeded.inside_code),
    ]
    for model, column, value in gone:
        assert not _exists(auth_mysql_engine, model, column, value), model.__tablename__
    for model, column, value in kept:
        assert _exists(auth_mysql_engine, model, column, value), model.__tablename__
    assert not storage["past_orphan"].exists()
    assert storage["past_orphan"].parent.is_dir(), "a directory this run emptied was removed"
    assert storage["inside_orphan"].exists()
    assert not storage["old_empty_dir"].exists()
    assert storage["fresh_empty_dir"].is_dir()
    assert not storage["past_staged"].exists()
    assert live_object.exists(), "a referenced object was removed"
    # The job wrote nothing the audit chain would record, and removed no account.
    assert _audit_state(auth_mysql_engine) == audit_before

    second = _run(job, apply=True)
    assert second.total == 0, _counts(second)
    assert live_object.exists()


def test_no_statement_names_an_audit_identity_key_custody_or_recovery_table(
    job, auth_mysql_engine: Engine, owner: RegisteredUser, tmp_path: Path
) -> None:
    _seed_rows(auth_mysql_engine, owner)
    _seed_storage(tmp_path)
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    event.listen(auth_mysql_engine, "before_cursor_execute", capture)
    try:
        _run(job, apply=False)
        _run(job, apply=True)
    finally:
        event.remove(auth_mysql_engine, "before_cursor_execute", capture)

    writes = [s for s in statements if re.match(r"\s*(DELETE|UPDATE|INSERT|REPLACE)\b", s, re.I)]
    assert writes, "the apply run sent no DELETE, so this check proves nothing"
    for statement in statements:
        for table in FORBIDDEN_TABLES:
            assert not re.search(rf"\b{table}\b", statement), f"{table}: {statement}"
    for statement in writes:
        target = re.match(r"\s*(?:DELETE\s+FROM|UPDATE|INSERT\s+INTO)\s+`?(\w+)", statement, re.I)
        assert target is not None and target.group(1) in RECONCILED_TABLES, statement
