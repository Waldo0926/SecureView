"""Remove the rows and storage objects that nothing will ever read again.

Four tables grow without bound today. Sessions, refresh tokens, throttle buckets and
verification codes are all written on ordinary traffic and none of them is ever deleted:
a failed login leaves a throttle bucket behind for good, and every sign-in leaves a
session row that stays there long after the session stopped being usable. Nothing reads
them once they lapse -- expiry is decided from the timestamps at request time, never from
a stored flag -- so they are pure accumulation.

Storage has the mirror problem. A process that dies between publishing a ciphertext object
and committing its row leaves an object no row names, and a `delete` whose unlink failed
leaves an object whose row already says `DELETED`. Neither is reachable through the API
and neither is ever cleaned up.

Run from `backend/` with the deployment environment loaded:

    .venv/bin/python scripts/reconcile.py                  # report only
    .venv/bin/python scripts/reconcile.py --apply          # actually delete

Reporting is the default on purpose. The first run on a real deployment should be read,
not trusted, and a reconciler is exactly the kind of job whose bugs are discovered by
what it removed. The report shows each category from both sides of its cutoff: how many
candidates crossed it within the last seven days, and how many are still inside the
retention window but will cross it within the next seven. It prints counts only -- never
a token hash, an email address, or a file name.

A run that would delete more than `--max-deletions` things in total, or more than
`--max-object-deletions` ciphertext objects, deletes nothing and exits with status 3, so a
systemd unit running it fails and its OnFailure= alert fires. A job that suddenly wants to
remove far more than usual is likelier to be misconfigured (wrong storage root, wrong
clock, wrong database) than to have found a genuine backlog; a real backlog is cleared by
running it once by hand with a limit sized from the report.

What this never touches, deliberately:

* `audit_logs` and `audit_chain_heads` -- append-only by design, covered by a hash chain
  that `POST /audit-logs/verify-chain` recomputes from the stored rows. Deleting from the
  middle of a hash chain destroys the property the table exists to provide, and the
  runtime grant is `SELECT, INSERT` precisely so this cannot happen by accident.
* `files`, `file_access_grants`, `file_key_wrappings`, `integrity_checks` -- a deleted
  file is a soft delete that stays queryable, and the integrity history is evidence.
  `files` is read, to learn which objects are live, and never written.
* `users`, `user_keys`, and the key-custody tables (`user_key_protection_profiles`,
  `encrypted_private_key_bundles`, `recovery_keys`) -- an account's key material outlives
  the account's activity, and a key still wraps files uploaded under it.
* `recovery_requests` -- an expired request records that someone asked for a file and
  nobody acted on it, which is accountability information rather than debris.

`tests/unit/test_reconcile.py` and `tests/integration/test_reconcile_mysql.py` capture
every statement the job issues and fail if one names any of these tables.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.time import site_stamp, to_second_resolution_utc, utc_now
from app.models.auth_login_throttle import AuthLoginThrottle
from app.models.email_verification_code import EmailVerificationCode
from app.models.file import File
from app.models.session_refresh_token import SessionRefreshToken
from app.models.user_session import UserSession

DEFAULT_RETAIN_DAYS = 30
DEFAULT_STORAGE_GRACE_MINUTES = 60
BOUNDARY_DAYS = 7

# Sized for this deployment, not for a busy one. The staging object store holds a few dozen
# ciphertext objects in total, and an orphan only appears when a request dies between
# publish and commit, so more than ten orphaned objects in one run means the job is looking
# at the wrong directory or the wrong database -- exactly the case in which it would
# otherwise empty the store. Rows accrue at about one session per sign-in plus one refresh
# token per half hour of activity; a handful of testers and the end-to-end suites produce
# tens to a few hundred a day, and a daily run removes about one day's worth. A thousand is
# several days of that, so it is exceeded only by a clock or cutoff mistake, or by the
# first run's backlog -- which is cleared by hand after the report has been read.
DEFAULT_MAX_DELETIONS = 1000
DEFAULT_MAX_OBJECT_DELETIONS = 10

EXIT_OK = 0
EXIT_VOLUME_REFUSED = 3

ORPHANS = "orphaned ciphertext objects"
STAGED = "stale staged uploads"
EMPTY_DIRS = "empty per-file directories"


@dataclass
class Finding:
    what: str
    count: int
    # Candidates that crossed the cutoff within the last BOUNDARY_DAYS (a subset of count).
    recent: int = 0
    # Not candidates yet: inside the retention window (for storage, inside the grace
    # period) and due to cross the cutoff within the next BOUNDARY_DAYS.
    upcoming: int = 0
    storage: bool = False


@dataclass
class Report:
    cutoff: datetime
    storage_cutoff: datetime
    applied: bool
    apply_requested: bool = False
    retain_days: int = DEFAULT_RETAIN_DAYS
    storage_grace_minutes: int = DEFAULT_STORAGE_GRACE_MINUTES
    max_deletions: int = DEFAULT_MAX_DELETIONS
    max_object_deletions: int = DEFAULT_MAX_OBJECT_DELETIONS
    refused: str | None = None
    findings: list[Finding] = field(default_factory=list)

    def add(
        self,
        what: str,
        count: int,
        *,
        recent: int = 0,
        upcoming: int = 0,
        storage: bool = False,
    ) -> Finding:
        finding = Finding(what=what, count=count, recent=recent, upcoming=upcoming, storage=storage)
        self.findings.append(finding)
        return finding

    def finding(self, what: str) -> Finding:
        return next(finding for finding in self.findings if finding.what == what)

    @property
    def total(self) -> int:
        return sum(finding.count for finding in self.findings)


# ---------------------------------------------------------------------------
# Row predicates. Each is monotonic in the cutoff -- a row eligible at one cutoff is
# eligible at every later one -- which is what lets a boundary count be the difference
# of two counts.
# ---------------------------------------------------------------------------


def _session_condition(cutoff: datetime):
    return (UserSession.absolute_expires_at < cutoff) | (UserSession.revoked_at < cutoff)


def _refresh_token_condition(cutoff: datetime):
    """Tokens that lapsed themselves, or whose session is being removed.

    The last clause keeps the count honest: a session's removal takes every one of its
    tokens with it, lapsed or not, and those deletions belong in the total too.
    """
    doomed_sessions = select(UserSession.id).where(_session_condition(cutoff))
    return (
        (SessionRefreshToken.expires_at < cutoff)
        | (SessionRefreshToken.consumed_at < cutoff)
        | (SessionRefreshToken.revoked_at < cutoff)
        | SessionRefreshToken.session_id.in_(doomed_sessions)
    )


def _throttle_condition(cutoff: datetime):
    return (AuthLoginThrottle.window_started_at < cutoff) & (
        (AuthLoginThrottle.blocked_until.is_(None)) | (AuthLoginThrottle.blocked_until < cutoff)
    )


def _verification_code_condition(cutoff: datetime):
    return EmailVerificationCode.expires_at < cutoff


def _count(db: Session, model, condition) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(condition)) or 0)


def _expired_refresh_tokens(db: Session, cutoff: datetime, *, apply: bool) -> int:
    """Tokens that expired, were consumed, or were revoked before the cutoff.

    A refresh token is single use: once consumed it is only ever compared against, never
    honoured, and the rotation chain that would want it is itself long gone by the cutoff.
    """
    condition = _refresh_token_condition(cutoff)
    count = _count(db, SessionRefreshToken, condition)
    if apply and count:
        db.execute(delete(SessionRefreshToken).where(condition))
    return count


def _expired_sessions(db: Session, cutoff: datetime, *, apply: bool) -> int:
    """Sessions past their absolute expiry, or revoked, before the cutoff.

    Expiry is derived from `absolute_expires_at` at request time rather than from the
    stored status, so a lapsed session is unusable regardless of what its status column
    says. An access token authenticates only by joining to its session row, so removing
    the row can only make a token less usable, never more. Refresh tokens reference
    sessions, so they go first.
    """
    condition = _session_condition(cutoff)
    doomed = select(UserSession.id).where(condition).subquery()
    count = _count(db, UserSession, condition)
    if apply and count:
        db.execute(
            delete(SessionRefreshToken).where(
                SessionRefreshToken.session_id.in_(select(doomed.c.id))
            )
        )
        db.execute(delete(UserSession).where(condition))
    return count


def _lapsed_throttles(db: Session, cutoff: datetime, *, apply: bool) -> int:
    """Buckets whose counting window and any block have both lapsed.

    Removing a bucket resets its counter, so a bucket that still blocks somebody must
    survive: `blocked_until` is checked as well as the window, and a NULL block counts as
    lapsed only because the window already has.
    """
    condition = _throttle_condition(cutoff)
    count = _count(db, AuthLoginThrottle, condition)
    if apply and count:
        db.execute(delete(AuthLoginThrottle).where(condition))
    return count


def _expired_verification_codes(db: Session, cutoff: datetime, *, apply: bool) -> int:
    """Codes past their expiry. Only the keyed digest was ever stored, never the code."""
    condition = _verification_code_condition(cutoff)
    count = _count(db, EmailVerificationCode, condition)
    if apply and count:
        db.execute(delete(EmailVerificationCode).where(condition))
    return count


# (label, model, predicate, deleter), in deletion order: tokens before their sessions.
ROW_CATEGORIES = (
    (
        "expired refresh tokens",
        SessionRefreshToken,
        _refresh_token_condition,
        _expired_refresh_tokens,
    ),
    ("expired sessions", UserSession, _session_condition, _expired_sessions),
    ("lapsed throttle buckets", AuthLoginThrottle, _throttle_condition, _lapsed_throttles),
    (
        "expired verification codes",
        EmailVerificationCode,
        _verification_code_condition,
        _expired_verification_codes,
    ),
)


def _row_boundary(
    db: Session, model, condition, cutoff: datetime, window: timedelta
) -> tuple[int, int, int]:
    """(eligible now, of those crossed within `window`, will cross within `window`)."""
    before = _count(db, model, condition(cutoff - window))
    now = _count(db, model, condition(cutoff))
    after = _count(db, model, condition(cutoff + window))
    return now, max(now - before, 0), max(after - now, 0)


# ---------------------------------------------------------------------------
# Storage.
# ---------------------------------------------------------------------------


@dataclass
class Candidates:
    paths: list[Path] = field(default_factory=list)
    recent: int = 0
    upcoming: int = 0


@dataclass
class StoragePlan:
    orphans: Candidates = field(default_factory=Candidates)
    staged: Candidates = field(default_factory=Candidates)
    empty_dirs: Candidates = field(default_factory=Candidates)


def _classify(
    candidates: Candidates, path: Path, mtime: float, cutoff: float, window: float
) -> None:
    if mtime < cutoff:
        candidates.paths.append(path)
        if mtime >= cutoff - window:
            candidates.recent += 1
    else:
        candidates.upcoming += 1


def _plan_storage(db: Session, storage_cutoff_epoch: float, window_seconds: float) -> StoragePlan:
    """Ciphertext objects, staged files and directories that no live row accounts for.

    The grace period is the important part. `publish` writes the object before the
    transaction commits, so an object younger than the grace may belong to a request still
    in flight; removing it would destroy a file that is about to become real. Only objects
    older than the cutoff are considered, and only when the database says nothing needs
    them. Unreferenced objects still inside the grace are counted as upcoming.

    Directories get the same grace. `publish` creates `<file_id>/` and then hard-links the
    object into it, and a client may retry an upload under the same `file_id` into a
    directory an earlier failed attempt left behind. Removing an empty directory between
    that `mkdir` and that `link` fails the upload, so an empty directory is a candidate only
    once its mtime is older than the cutoff. Unlinking a directory's last object refreshes
    its mtime, so a directory this run empties is collected by a later run, not this one.
    """
    settings = get_settings()
    object_root = settings.ENCRYPTED_FILE_DIR
    staging_root = settings.TEMP_FILE_DIR

    live_keys = set(
        db.scalars(select(File.storage_object_key).where(File.status != "DELETED")).all()
    )
    # Compared as epoch seconds throughout. `st_mtime` is epoch, and calling `.timestamp()`
    # on the naive UTC datetime used for the row cutoffs would read it as local time --
    # which on a UTC+10 host moves the cutoff ten hours and quietly makes this find
    # nothing at all.
    cutoff = storage_cutoff_epoch

    plan = StoragePlan()
    if object_root.is_dir():
        for path in sorted(object_root.rglob("*.ciphertext")):
            if str(path.relative_to(object_root)) in live_keys:
                continue
            _classify(plan.orphans, path, path.stat().st_mtime, cutoff, window_seconds)
        for directory in sorted(object_root.iterdir()):
            if not directory.is_dir() or any(directory.iterdir()):
                continue
            _classify(plan.empty_dirs, directory, directory.stat().st_mtime, cutoff, window_seconds)

    if staging_root.is_dir():
        for path in sorted(staging_root.glob("*.staging")):
            _classify(plan.staged, path, path.stat().st_mtime, cutoff, window_seconds)

    return plan


def _unlink_all(paths: list[Path]) -> int:
    removed = 0
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed += 1
    return removed


def _apply_storage(plan: StoragePlan, storage_cutoff_epoch: float) -> tuple[int, int, int]:
    removed_objects = _unlink_all(plan.orphans.paths)
    removed_staged = _unlink_all(plan.staged.paths)
    removed_dirs = 0
    for directory in plan.empty_dirs.paths:
        # Checked again immediately before removal: a publish that reused the directory
        # since the scan has refreshed its mtime, and rmdir refuses one it has linked into.
        try:
            if directory.stat().st_mtime >= storage_cutoff_epoch:
                continue
            directory.rmdir()
        except OSError:
            continue
        removed_dirs += 1
    return removed_objects, removed_staged, removed_dirs


def _storage_objects(
    db: Session,
    storage_cutoff_epoch: float,
    *,
    apply: bool,
    window_seconds: float = BOUNDARY_DAYS * 86400,
) -> tuple[int, int, int]:
    """Plan, and with `apply` carry out, the storage clean-up; returns the three counts."""
    plan = _plan_storage(db, storage_cutoff_epoch, window_seconds)
    if apply:
        return _apply_storage(plan, storage_cutoff_epoch)
    return len(plan.orphans.paths), len(plan.staged.paths), len(plan.empty_dirs.paths)


# ---------------------------------------------------------------------------
# The run.
# ---------------------------------------------------------------------------


def _volume_refusal(report: Report) -> str | None:
    objects = report.finding(ORPHANS).count
    if objects > report.max_object_deletions:
        return (
            f"{objects} ciphertext objects exceed --max-object-deletions "
            f"{report.max_object_deletions}"
        )
    if report.total > report.max_deletions:
        return f"{report.total} deletions exceed --max-deletions {report.max_deletions}"
    return None


def reconcile(
    *,
    retain_days: int,
    storage_grace_minutes: int,
    apply: bool,
    max_deletions: int = DEFAULT_MAX_DELETIONS,
    max_object_deletions: int = DEFAULT_MAX_OBJECT_DELETIONS,
) -> Report:
    instant = utc_now()
    now = to_second_resolution_utc(instant)
    cutoff = now - timedelta(days=retain_days)
    storage_cutoff_epoch = (instant - timedelta(minutes=storage_grace_minutes)).timestamp()
    window = timedelta(days=BOUNDARY_DAYS)
    report = Report(
        cutoff=cutoff,
        storage_cutoff=now - timedelta(minutes=storage_grace_minutes),
        applied=False,
        apply_requested=apply,
        retain_days=retain_days,
        storage_grace_minutes=storage_grace_minutes,
        max_deletions=max_deletions,
        max_object_deletions=max_object_deletions,
    )

    with SessionLocal() as db:
        try:
            # Everything is counted before anything is deleted, so the volume guard judges
            # the whole run and a refused run removes nothing at all.
            for label, model, condition, _ in ROW_CATEGORIES:
                count, recent, upcoming = _row_boundary(db, model, condition, cutoff, window)
                report.add(label, count, recent=recent, upcoming=upcoming)
            plan = _plan_storage(db, storage_cutoff_epoch, window.total_seconds())
            for label, candidates in (
                (ORPHANS, plan.orphans),
                (STAGED, plan.staged),
                (EMPTY_DIRS, plan.empty_dirs),
            ):
                report.add(
                    label,
                    len(candidates.paths),
                    recent=candidates.recent,
                    upcoming=candidates.upcoming,
                    storage=True,
                )

            report.refused = _volume_refusal(report)
            if not apply or report.refused:
                db.rollback()
                return report

            for label, _, _, deleter in ROW_CATEGORIES:
                report.finding(label).count = deleter(db, cutoff, apply=True)
            db.commit()
        except Exception:
            db.rollback()
            raise

    objects, staged, dirs = _apply_storage(plan, storage_cutoff_epoch)
    report.finding(ORPHANS).count = objects
    report.finding(STAGED).count = staged
    report.finding(EMPTY_DIRS).count = dirs
    report.applied = True
    return report


def format_report(report: Report) -> str:
    """Counts and cutoffs only. Deterministic for a given database, store, and instant."""
    if report.applied:
        heading = "removed"
    elif report.apply_requested and report.refused:
        heading = "REFUSED -- nothing was deleted"
    else:
        heading = "would remove (report only; pass --apply to act)"
    last = f"last {BOUNDARY_DAYS}d"
    upcoming = f"next {BOUNDARY_DAYS}d"
    lines = [
        heading,
        f"  rows lapsed before   {site_stamp(report.cutoff, seconds=True)}"
        f"  (retain {report.retain_days} days)",
        f"  storage older than   {site_stamp(report.storage_cutoff, seconds=True)}"
        f"  (grace {report.storage_grace_minutes} minutes)",
        "",
        f"  {'eligible':>8}  {'crossed':>8}  {'crosses':>8}",
        f"  {'':>8}  {last:>8}  {upcoming:>8}",
    ]
    for finding in report.findings:
        marker = " *" if finding.storage else ""
        lines.append(
            f"  {finding.count:>8}  {finding.recent:>8}  {finding.upcoming:>8}  "
            f"{finding.what}{marker}"
        )
    lines += [
        "",
        f"  {report.total:>8}  total",
        "",
        f"  crossed {last}: eligible, and crossed the cutoff within the last {BOUNDARY_DAYS} days",
        f"  crosses {upcoming}: kept today, crosses the cutoff within the next {BOUNDARY_DAYS} days",
        "  * storage: 'crosses' counts unreferenced entries still inside the grace period",
        f"  limits: {report.max_deletions} deletions in total, "
        f"{report.max_object_deletions} ciphertext objects",
    ]
    if report.refused:
        lines.append(f"  WARNING: {report.refused}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without it the script only reports what it would remove.",
    )
    parser.add_argument(
        "--retain-days",
        type=int,
        default=DEFAULT_RETAIN_DAYS,
        help=f"Keep lapsed rows this long before removing them (default {DEFAULT_RETAIN_DAYS}).",
    )
    parser.add_argument(
        "--storage-grace-minutes",
        type=int,
        default=DEFAULT_STORAGE_GRACE_MINUTES,
        help=(
            "Ignore storage entries younger than this, so an upload still in flight is "
            f"never mistaken for an orphan (default {DEFAULT_STORAGE_GRACE_MINUTES})."
        ),
    )
    parser.add_argument(
        "--max-deletions",
        type=int,
        default=DEFAULT_MAX_DELETIONS,
        help=(
            "With --apply, delete nothing and exit 3 if the run would remove more than this "
            f"many rows, objects and directories in total (default {DEFAULT_MAX_DELETIONS})."
        ),
    )
    parser.add_argument(
        "--max-object-deletions",
        type=int,
        default=DEFAULT_MAX_OBJECT_DELETIONS,
        help=(
            "With --apply, delete nothing and exit 3 if the run would remove more than this "
            f"many ciphertext objects (default {DEFAULT_MAX_OBJECT_DELETIONS})."
        ),
    )
    args = parser.parse_args(argv)
    if args.retain_days < 1:
        parser.error("--retain-days must be at least 1")
    if args.storage_grace_minutes < 5:
        parser.error("--storage-grace-minutes must be at least 5, to stay clear of live uploads")
    if args.max_deletions < 0 or args.max_object_deletions < 0:
        parser.error("--max-deletions and --max-object-deletions must not be negative")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = reconcile(
        retain_days=args.retain_days,
        storage_grace_minutes=args.storage_grace_minutes,
        apply=args.apply,
        max_deletions=args.max_deletions,
        max_object_deletions=args.max_object_deletions,
    )
    print(format_report(report), flush=True)
    if args.apply and report.refused:
        print(
            f"reconcile: REFUSED -- {report.refused}; nothing was deleted. Read the report, "
            "then rerun by hand with a larger limit only if the volume is genuine.",
            file=sys.stderr,
        )
        return EXIT_VOLUME_REFUSED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
