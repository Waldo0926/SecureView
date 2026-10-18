from __future__ import annotations

import importlib.util
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _load_reconcile():
    """Load the script by path: `scripts/` is a command directory, not a package."""
    spec = importlib.util.spec_from_file_location(
        "reconcile_script", BACKEND_ROOT / "scripts" / "reconcile.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reconcile = _load_reconcile()

CUTOFF = datetime(2026, 7, 25, 12, 0, tzinfo=UTC).replace(tzinfo=None)


def _sql(condition) -> str:
    return str(condition.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))


class CountingDb:
    """Records what would be deleted without touching a database."""

    def __init__(self, count: int = 0) -> None:
        self.count = count
        self.deletes: list[str] = []

    def scalar(self, statement) -> int:
        return self.count

    def execute(self, statement) -> None:
        self.deletes.append(str(statement.compile(dialect=mysql.dialect())))

    def scalars(self, statement):
        return SimpleNamespace(all=lambda: [])


# ---------------------------------------------------------------------------
# The predicates. Each decides what is safe to destroy, so each is worth pinning.
# ---------------------------------------------------------------------------


def test_a_throttle_bucket_that_still_blocks_someone_is_never_removed() -> None:
    """The one predicate here that can undo a security control.

    Deleting a bucket resets its counter. A bucket whose window is old but whose block is
    still running belongs to someone currently locked out, and removing it would hand them
    a fresh allowance -- turning a cleanup job into a way to bypass the lockout.
    """
    db = CountingDb(count=1)
    reconcile._lapsed_throttles(db, CUTOFF, apply=True)

    assert len(db.deletes) == 1
    condition = _sql(reconcile.AuthLoginThrottle.window_started_at < CUTOFF)
    assert "window_started_at" in condition
    assert "blocked_until" in db.deletes[0]


def test_throttle_removal_requires_both_the_window_and_the_block_to_have_lapsed() -> None:
    db = CountingDb(count=1)
    reconcile._lapsed_throttles(db, CUTOFF, apply=True)

    statement = db.deletes[0]
    assert "window_started_at <" in statement
    assert "blocked_until IS NULL" in statement
    assert "blocked_until <" in statement


def test_sessions_take_their_refresh_tokens_with_them() -> None:
    """The foreign key would refuse otherwise, and a stranded token outlives its session."""
    db = CountingDb(count=1)
    reconcile._expired_sessions(db, CUTOFF, apply=True)

    assert len(db.deletes) == 2
    assert "session_refresh_tokens" in db.deletes[0]
    assert "user_sessions" in db.deletes[1]


def test_reporting_never_deletes() -> None:
    """The default mode has to be inert, or "let me see what it would do" is a lie."""
    for run in (
        reconcile._expired_refresh_tokens,
        reconcile._expired_sessions,
        reconcile._lapsed_throttles,
        reconcile._expired_verification_codes,
    ):
        db = CountingDb(count=5)
        assert run(db, CUTOFF, apply=False) == 5
        assert db.deletes == []


# ---------------------------------------------------------------------------
# The storage scan, which can destroy a file that is about to become real.
# ---------------------------------------------------------------------------


def _storage_settings(tmp_path: Path):
    from app.core.config import Settings

    return Settings(
        _env_file=None,
        APP_ENV="test",
        APP_DEBUG=False,
        SECRET_KEY="reconcile-test-secret-key-long-enough",
        ENCRYPTED_FILE_DIR=tmp_path / "objects",
        TEMP_FILE_DIR=tmp_path / "staging",
    )


@pytest.fixture
def storage(tmp_path, monkeypatch):
    settings = _storage_settings(tmp_path)
    monkeypatch.setattr(reconcile, "get_settings", lambda: settings)
    settings.ENCRYPTED_FILE_DIR.mkdir(parents=True)
    settings.TEMP_FILE_DIR.mkdir(parents=True)
    return settings


def _object(settings, name: str, *, age_seconds: float) -> Path:
    path = settings.ENCRYPTED_FILE_DIR / name / "object.ciphertext"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ciphertext")
    stamp = time.time() - age_seconds
    import os

    os.utime(path, (stamp, stamp))
    return path


def test_an_object_younger_than_the_grace_is_left_alone(storage) -> None:
    """`publish` writes the object before the transaction commits.

    An object that appeared moments ago may belong to a request still in flight, and
    deleting it destroys a file that is about to become real. The grace period is the only
    thing standing between this job and that.
    """
    in_flight = _object(storage, "in-flight", age_seconds=5)
    cutoff = time.time() - 3600

    orphans, _, _ = reconcile._storage_objects(CountingDb(), cutoff, apply=True)

    assert orphans == 0
    assert in_flight.exists()


def test_an_old_object_no_row_names_is_removed(storage) -> None:
    orphan = _object(storage, "orphan", age_seconds=7200)
    cutoff = time.time() - 3600

    orphans, _, _ = reconcile._storage_objects(CountingDb(), cutoff, apply=True)

    assert orphans == 1
    assert not orphan.exists()


def test_an_object_a_live_row_names_is_kept_however_old(storage) -> None:
    kept = _object(storage, "referenced", age_seconds=90 * 86400)
    key = str(kept.relative_to(storage.ENCRYPTED_FILE_DIR))

    class DbWithRow(CountingDb):
        def scalars(self, statement):
            return SimpleNamespace(all=lambda: [key])

    orphans, _, _ = reconcile._storage_objects(DbWithRow(), time.time() - 3600, apply=True)

    assert orphans == 0
    assert kept.exists()


def test_a_stale_staged_upload_is_removed_and_a_fresh_one_is_not(storage) -> None:
    import os

    stale = storage.TEMP_FILE_DIR / ".stale.staging"
    stale.write_bytes(b"abandoned")
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    fresh = storage.TEMP_FILE_DIR / ".fresh.staging"
    fresh.write_bytes(b"in progress")

    _, staged, _ = reconcile._storage_objects(CountingDb(), time.time() - 3600, apply=True)

    assert staged == 1
    assert not stale.exists()
    assert fresh.exists()


def test_the_storage_cutoff_is_compared_in_epoch_seconds(storage) -> None:
    """Guards a bug that made the whole scan silently find nothing.

    `st_mtime` is epoch seconds. Calling `.timestamp()` on the naive UTC datetime used for
    the row cutoffs reads it as *local* time, so on a UTC+10 host the cutoff moved ten
    hours into the past and no object was ever old enough to collect.
    """
    orphan = _object(storage, "orphan", age_seconds=7200)

    orphans, _, _ = reconcile._storage_objects(CountingDb(), time.time() - 3600, apply=False)

    assert orphans == 1
    assert orphan.exists(), "report-only must not delete"


def _age(path: Path, seconds: float) -> None:
    import os

    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_a_fresh_empty_directory_survives_because_a_publish_may_be_about_to_use_it(
    storage,
) -> None:
    """`publish` does `mkdir(<file_id>)` and then `link`. Removing the directory in
    between fails a live upload, so an empty directory needs the same grace as an object."""
    fresh = storage.ENCRYPTED_FILE_DIR / "just-created"
    fresh.mkdir()
    old = storage.ENCRYPTED_FILE_DIR / "long-abandoned"
    old.mkdir()
    _age(old, 7200)
    cutoff = time.time() - 3600

    assert reconcile._storage_objects(CountingDb(), cutoff, apply=False) == (0, 0, 1)
    assert reconcile._storage_objects(CountingDb(), cutoff, apply=True) == (0, 0, 1)

    assert fresh.is_dir()
    assert not old.exists()


def test_a_directory_this_run_empties_is_left_for_a_later_run(storage) -> None:
    """Unlinking the last object refreshes the directory's mtime, so it is inside the grace
    again; a retried upload under the same file_id may be about to reuse it."""
    orphan = _object(storage, "retry-target", age_seconds=7200)
    _age(orphan.parent, 7200)
    cutoff = time.time() - 3600

    assert reconcile._storage_objects(CountingDb(), cutoff, apply=True) == (1, 0, 0)
    assert not orphan.exists()
    assert orphan.parent.is_dir()

    _age(orphan.parent, 7200)
    assert reconcile._storage_objects(CountingDb(), cutoff, apply=True) == (0, 0, 1)
    assert not orphan.parent.exists()


def test_a_directory_reused_after_the_scan_is_not_removed(storage) -> None:
    old = storage.ENCRYPTED_FILE_DIR / "reused"
    old.mkdir()
    _age(old, 7200)
    cutoff = time.time() - 3600
    plan = reconcile._plan_storage(CountingDb(), cutoff, 7 * 86400)
    assert plan.empty_dirs.paths == [old]

    # A publish lands between the scan and the removal.
    (old / "new.ciphertext").write_bytes(b"ciphertext")

    assert reconcile._apply_storage(plan, cutoff) == (0, 0, 0)
    assert (old / "new.ciphertext").exists()


def test_storage_boundary_counts_both_sides_of_the_grace(storage) -> None:
    _object(storage, "just-past", age_seconds=2 * 3600)
    _object(storage, "long-past", age_seconds=30 * 86400)
    _object(storage, "inside-grace", age_seconds=60)
    cutoff = time.time() - 3600

    plan = reconcile._plan_storage(CountingDb(), cutoff, 7 * 86400)

    assert len(plan.orphans.paths) == 2
    assert plan.orphans.recent == 1
    assert plan.orphans.upcoming == 1


# ---------------------------------------------------------------------------
# The whole run: volume guard, report contents, and the tables it may touch.
# ---------------------------------------------------------------------------

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
RECONCILED_TABLES = (
    "session_refresh_tokens",
    "user_sessions",
    "auth_login_throttles",
    "email_verification_codes",
)


class RecordingSession(CountingDb):
    """Stands in for `SessionLocal()`: every statement is compiled and kept."""

    def __init__(self, count: int = 0) -> None:
        super().__init__(count)
        self.statements: list[str] = []
        self.committed = False

    def _record(self, statement) -> None:
        self.statements.append(str(statement.compile(dialect=mysql.dialect())))

    def scalar(self, statement) -> int:
        self._record(statement)
        return self.count

    def scalars(self, statement):
        self._record(statement)
        return SimpleNamespace(all=lambda: [])

    def execute(self, statement) -> None:
        self._record(statement)
        super().execute(statement)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


@pytest.fixture
def recording(storage, monkeypatch):
    sessions: list[RecordingSession] = []

    def install(count: int) -> list[RecordingSession]:
        def factory() -> RecordingSession:
            session = RecordingSession(count)
            sessions.append(session)
            return session

        monkeypatch.setattr(reconcile, "SessionLocal", factory)
        return sessions

    return install


def test_an_unusual_volume_deletes_nothing_and_exits_non_zero(storage, recording, capsys) -> None:
    sessions = recording(count=400)  # 4 row categories x 400 = 1600 > the default 1000
    orphan = _object(storage, "orphan", age_seconds=7200)

    status = reconcile.main(["--apply"])

    assert status == reconcile.EXIT_VOLUME_REFUSED != 0
    assert sessions[0].deletes == [] and sessions[0].committed is False
    assert orphan.exists(), "a refused run removed a storage object"
    captured = capsys.readouterr()
    assert "REFUSED" in captured.out and "--max-deletions 1000" in captured.err


def test_too_many_ciphertext_objects_is_refused_on_its_own(storage, recording) -> None:
    sessions = recording(count=0)
    orphans = [_object(storage, f"orphan-{i}", age_seconds=7200) for i in range(3)]

    status = reconcile.main(["--apply", "--max-object-deletions", "2"])

    assert status == reconcile.EXIT_VOLUME_REFUSED
    assert sessions[0].deletes == []
    assert all(path.exists() for path in orphans)


def test_a_report_over_the_limit_only_warns(storage, recording, capsys) -> None:
    recording(count=400)

    assert reconcile.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("would remove")
    assert "WARNING: 1600 deletions exceed --max-deletions 1000" in out


def test_a_run_within_the_limit_deletes_and_commits(storage, recording) -> None:
    sessions = recording(count=1)
    orphan = _object(storage, "orphan", age_seconds=7200)

    assert reconcile.main(["--apply"]) == 0
    assert sessions[0].committed
    assert len(sessions[0].deletes) == 5  # tokens, tokens+sessions, throttles, codes
    assert not orphan.exists()


def test_the_report_prints_counts_and_never_a_name(storage, recording, capsys) -> None:
    recording(count=2)
    _object(storage, "3f9c2d1e-secret-file-id", age_seconds=7200)

    reconcile.main([])
    first = capsys.readouterr().out
    reconcile.main([])
    second = capsys.readouterr().out

    assert "3f9c2d1e" not in first and "secret-file-id" not in first
    assert str(storage.ENCRYPTED_FILE_DIR) not in first
    assert "@" not in first
    for label in ("expired sessions", "orphaned ciphertext objects", "empty per-file directories"):
        assert label in first
    assert "crossed" in first and "crosses" in first

    def without_cutoffs(text: str) -> list[str]:
        # The two cutoff lines carry the run's own timestamp (MYT since #231; it was a UTC
        # "...Z" stamp before, and filtering on that let the two runs differ by a second).
        return [
            line
            for line in text.splitlines()
            if not line.startswith(("  rows lapsed before", "  storage older than"))
        ]

    assert without_cutoffs(first) == without_cutoffs(second)


def test_the_job_never_names_an_audit_key_custody_or_recovery_table(storage, recording) -> None:
    """Report and apply both: the only tables written are the four reconciled ones."""
    import re

    sessions = recording(count=1)
    reconcile.main([])
    reconcile.main(["--apply"])

    statements = [sql for session in sessions for sql in session.statements]
    assert any(sql.startswith("DELETE") for sql in statements)
    for sql in statements:
        for table in FORBIDDEN_TABLES:
            assert not re.search(rf"\b{table}\b", sql), f"{table} named in: {sql}"
        if sql.startswith(("DELETE", "UPDATE", "INSERT")):
            target = re.match(r"(?:DELETE FROM|UPDATE|INSERT INTO) (\w+)", sql)
            assert target is not None and target.group(1) in RECONCILED_TABLES, sql
