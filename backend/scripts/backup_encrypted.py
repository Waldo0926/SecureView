"""Take one coordinated, encrypted backup of MySQL metadata and ciphertext objects.

Policy and reasoning live in docs/BACKUP_AND_RECOVERY.md; this is the mechanism.

One run produces one **backup set** named by a manifest id (UTC time plus random suffix,
e.g. `20260924T091500Z-3f9c2a1b`):

    <dest>/<manifest-id>/db.sql.enc          mysqldump --single-transaction, id in line 1
    <dest>/<manifest-id>/objects.tar.enc     ciphertext objects, id in member MANIFEST_ID
    <dest>/<manifest-id>/manifest.json.enc   id, dump window, every object's SHA-256
    <dest>/<manifest-id>/index.json          plaintext: id, artifact hashes, key fingerprint

Consistency: the dump is one InnoDB snapshot. Objects are write-once and published before
their row commits, and a delete commits the row before unlinking the object, so copying
objects *after* the dump means every row ACTIVE in the snapshot still has its object --
unless it was deleted in the seconds between. The coordination check below catches that
case, and any storage corruption, by comparing every `files` row that could be ACTIVE in
the snapshot against the archived bytes and `encrypted_sha256`, and fails the run rather
than shipping a set whose metadata points at missing objects. `restore_drill.py` repeats
the same check against the restored rows and refuses a set that fails it.

Encryption: each artifact is sealed with backup_envelope.py to the backup **public** key.
This host never holds the private key. Nothing leaves the temporary work directory
unencrypted, and index.json is written to the destination last, so a set without it is
incomplete by definition.

Destination (`--dest`):

* a local directory path -- used by CI and local drills. On a single host this is a
  stand-in for off-server storage, not the real thing;
* `user@host:/path` -- copied with rsync over SSH (use a restricted, write-only key);
* `s3://bucket/prefix` -- copied with `aws s3 cp` (`BACKUP_S3_ENDPOINT_URL` for an
  S3-compatible provider; use a put-only credential).
The two remote forms are wired but have not been exercised against a real target yet.

Credentials come from the environment and are never printed or put on a command line
(mysqldump reads them from a 0600 option file inside the private work directory):

    BACKUP_DB_HOST (127.0.0.1), BACKUP_DB_PORT (3306), BACKUP_DB_NAME
    (fyp_secure_file_platform), BACKUP_DB_USER, BACKUP_DB_PASSWORD, BACKUP_DB_SSL_CA

Exit status is non-zero on any failure, with a single `backup_encrypted: FAILED -- ...`
line on stderr for the scheduler (systemd) to surface.

    .venv/bin/python scripts/backup_encrypted.py --public-key /etc/.../backup_pub.pem \
        --objects-dir encrypted_files --dest /var/backups/mcs21
    .venv/bin/python scripts/backup_encrypted.py --check-freshness /var/backups/mcs21
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymysql
from backup_envelope import (
    EnvelopeError,
    encrypt_file,
    load_public_key,
    public_key_fingerprint,
    sha256_file,
)

FORMAT_VERSION = 1
MANIFEST_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
OBJECT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DUMP_HEADER_PREFIX = "-- fyp-backup-manifest-id: "
DUMP_TRAILER_PREFIX = "-- Dump completed"
ARTIFACTS = {"db": "db.sql.enc", "objects": "objects.tar.enc", "manifest": "manifest.json.enc"}
# Timestamps are stored at second resolution; widen the dump window by this much on each
# side so rounding can only make the coordination check stricter, never looser.
WINDOW_SLACK = timedelta(seconds=2)


class BackupError(Exception):
    pass


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    ssl_ca: str | None


def envelope_context(manifest_id: str, role: str) -> str:
    return f"fyp-backup/{FORMAT_VERSION}/{manifest_id}/{role}"


def new_manifest_id(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def is_object_key(relative: PurePosixPath) -> bool:
    return bool(relative.parts) and all(OBJECT_SEGMENT_RE.fullmatch(p) for p in relative.parts)


def _db_config_from_env() -> DbConfig:
    user = os.getenv("BACKUP_DB_USER")
    password = os.getenv("BACKUP_DB_PASSWORD")
    if not user or not password:
        raise BackupError("BACKUP_DB_USER and BACKUP_DB_PASSWORD must be set")
    return DbConfig(
        host=os.getenv("BACKUP_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("BACKUP_DB_PORT", "3306")),
        database=os.getenv("BACKUP_DB_NAME", "fyp_secure_file_platform"),
        user=user,
        password=password,
        ssl_ca=os.getenv("BACKUP_DB_SSL_CA") or None,
    )


def _connect(config: DbConfig) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        ssl_ca=config.ssl_ca,
        ssl_verify_cert=bool(config.ssl_ca),
        ssl_verify_identity=False,
        connect_timeout=10,
    )


def _db_utc_now(connection: pymysql.connections.Connection) -> datetime:
    with connection.cursor() as cursor:
        cursor.execute("SELECT UTC_TIMESTAMP()")
        (value,) = cursor.fetchone()
    return value


def _write_option_file(work: Path, config: DbConfig) -> Path:
    path = work / "client.cnf"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    lines = [
        "[client]",
        f"host={config.host}",
        f"port={config.port}",
        f"user={config.user}",
        'password="{}"'.format(config.password.replace("\\", "\\\\").replace('"', '\\"')),
        "protocol=TCP",
    ]
    if config.ssl_ca:
        lines += ["ssl-mode=VERIFY_CA", f"ssl-ca={config.ssl_ca}"]
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def dump_database(work: Path, config: DbConfig, manifest_id: str) -> Path:
    """Write the dump with the manifest id as its first line; fail on any mysqldump error."""
    option_file = _write_option_file(work, config)
    dump_path = work / "db.sql"
    mysqldump = os.getenv("MYSQLDUMP_BIN", "mysqldump")
    command = [
        mysqldump,
        f"--defaults-extra-file={option_file}",
        # One consistent InnoDB snapshot; implies no LOCK TABLES.
        "--single-transaction",
        # Tablespace metadata needs PROCESS, which the backup account does not have.
        "--no-tablespaces",
        # The schema defines no triggers, routines, events, or views (02-schema.sql's
        # preflight refuses to install over any), and reading triggers would need the
        # TRIGGER privilege, which also permits creating and dropping them.
        "--skip-triggers",
        "--hex-blob",
        config.database,
    ]
    fd = os.open(dump_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(f"{DUMP_HEADER_PREFIX}{manifest_id}\n".encode())
        out.flush()
        result = subprocess.run(command, stdout=out, stderr=subprocess.PIPE, check=False)
    option_file.unlink()
    stderr = result.stderr.decode("utf-8", "replace").strip()
    if result.returncode != 0:
        raise BackupError(f"mysqldump exited {result.returncode}: {stderr[-500:]}")
    for line in stderr.splitlines():
        print(f"backup_encrypted: mysqldump said: {line}", file=sys.stderr)
    if not dump_trailer_present(dump_path):
        raise BackupError("mysqldump output has no completion trailer; the dump is truncated")
    return dump_path


def dump_trailer_present(path: Path) -> bool:
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 512))
        tail = handle.read().decode("utf-8", "replace")
    return DUMP_TRAILER_PREFIX in tail


def collect_objects(objects_dir: Path) -> tuple[list[tuple[str, Path]], list[str]]:
    """Return (object_key, path) pairs to archive, and the relative paths skipped.

    Only files whose path is a valid storage object key are archived. Anything else is
    skipped -- and a file that looks like a private key aborts the run, because the backup
    scope must never carry key material (see the recovery-key custody section).
    """
    if not objects_dir.is_dir():
        raise BackupError(f"objects directory {objects_dir} does not exist")
    selected: list[tuple[str, Path]] = []
    skipped: list[str] = []
    for path in sorted(objects_dir.rglob("*")):
        relative = PurePosixPath(path.relative_to(objects_dir).as_posix())
        if path.is_symlink():
            skipped.append(f"{relative} (symlink)")
            continue
        if not path.is_file():
            continue
        if relative.name == ".gitkeep":
            continue
        with path.open("rb") as handle:
            head = handle.read(4096)
        if b"PRIVATE KEY-----" in head:
            raise BackupError(
                f"refusing to back up {relative}: it looks like a private key, and key "
                "material must never enter the routine backup"
            )
        if not is_object_key(relative):
            skipped.append(str(relative))
            continue
        selected.append((str(relative), path))
    return selected, skipped


class _HashingReader:
    def __init__(self, handle) -> None:
        self._handle = handle
        self._digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self._handle.read(size)
        self._digest.update(data)
        return data

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def archive_objects(
    work: Path, manifest_id: str, objects: list[tuple[str, Path]]
) -> tuple[Path, list[dict[str, object]]]:
    tar_path = work / "objects.tar"
    marker = work / "MANIFEST_ID"
    marker.write_text(manifest_id + "\n", encoding="utf-8")
    entries: list[dict[str, object]] = []
    fd = os.open(tar_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with (
        os.fdopen(fd, "wb") as raw,
        tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        tar.add(marker, arcname="MANIFEST_ID", recursive=False)
        for key, path in objects:
            info = tar.gettarinfo(str(path), arcname=f"objects/{key}")
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as handle:
                # Hash exactly the bytes that go into the archive, in the same pass.
                reader = _HashingReader(handle)
                info.size = os.fstat(handle.fileno()).st_size
                tar.addfile(info, reader)
            entries.append({"key": key, "sha256": reader.hexdigest(), "bytes": info.size})
    marker.unlink()
    return tar_path, entries


def coordination_problems(rows: list[tuple[str, str, str]], archived: dict[str, str]) -> list[str]:
    """Rows are (storage_object_key, encrypted_sha256, status) that may be ACTIVE in the dump."""
    problems: list[str] = []
    for key, expected_sha, status in rows:
        actual = archived.get(key)
        if status == "CORRUPTED":
            continue
        if actual is None:
            reason = (
                "was deleted while the backup ran; re-run the backup"
                if status == "DELETED"
                else "is missing from object storage"
            )
            problems.append(f"object {key} {reason}")
        elif actual != expected_sha:
            problems.append(f"object {key} does not match files.encrypted_sha256")
    return problems


def check_coordination(
    config: DbConfig, window_start: datetime, window_end: datetime, archived: dict[str, str]
) -> int:
    connection = _connect(config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT storage_object_key, encrypted_sha256, status FROM files "
                "WHERE created_at <= %s AND (status <> 'DELETED' OR deleted_at >= %s)",
                (window_end + WINDOW_SLACK, window_start - WINDOW_SLACK),
            )
            rows = [(str(k), str(s), str(st)) for k, s, st in cursor.fetchall()]
    finally:
        connection.close()
    problems = coordination_problems(rows, archived)
    if problems:
        shown = "; ".join(problems[:5])
        more = f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""
        raise BackupError(f"database and object store disagree: {shown}{more}")
    return len(rows)


def ship(set_dir: Path, dest: str, manifest_id: str) -> str:
    """Copy a finished set to the destination, index.json last. Returns where it went."""
    ordered = [set_dir / name for name in ARTIFACTS.values()] + [set_dir / "index.json"]
    if dest.startswith("s3://"):
        aws = shutil.which("aws")
        if not aws:
            raise BackupError("destination is s3:// but the aws CLI is not installed")
        endpoint = os.getenv("BACKUP_S3_ENDPOINT_URL")
        for path in ordered:
            command = [aws, "s3", "cp", "--only-show-errors", str(path)]
            command.append(f"{dest.rstrip('/')}/{manifest_id}/{path.name}")
            if endpoint:
                command += ["--endpoint-url", endpoint]
            subprocess.run(command, check=True)
        return f"{dest.rstrip('/')}/{manifest_id}/"
    if re.match(r"^[^/]+@[^/:]+:", dest):
        rsync = shutil.which("rsync")
        if not rsync:
            raise BackupError("destination is remote but rsync is not installed")
        target = f"{dest.rstrip('/')}/{manifest_id}/"
        for path in ordered:
            subprocess.run([rsync, "--chmod=D700,F600", "--mkpath", str(path), target], check=True)
        return target
    root = Path(dest)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial = root / f"{manifest_id}.partial"
    final = root / manifest_id
    if final.exists() or partial.exists():
        raise BackupError(f"backup set {manifest_id} already exists at the destination")
    partial.mkdir(mode=0o700)
    for path in ordered:
        shutil.copyfile(path, partial / path.name)
        os.chmod(partial / path.name, 0o600)
    partial.rename(final)
    return str(final)


def select_for_pruning(set_names: list[str], keep_daily: int, keep_weekly: int) -> list[str]:
    """Keep the newest `keep_daily` sets plus the newest set of each of the `keep_weekly`
    most recent ISO weeks not already covered; return the names to delete."""
    ordered = sorted((n for n in set_names if MANIFEST_ID_RE.match(n)), reverse=True)
    keep = set(ordered[:keep_daily])
    weeks_seen: list[tuple[int, int]] = []
    for name in ordered:
        stamp = datetime.strptime(name.split("-")[0], "%Y%m%dT%H%M%SZ")
        week = stamp.isocalendar()[:2]
        if week in weeks_seen:
            continue
        weeks_seen.append(week)
        if len(weeks_seen) > keep_weekly:
            break
        keep.add(name)
    return [name for name in ordered if name not in keep]


def prune_local(dest: Path, keep_daily: int, keep_weekly: int) -> list[str]:
    complete = [p.name for p in dest.iterdir() if p.is_dir() and (p / "index.json").is_file()]
    doomed = select_for_pruning(complete, keep_daily, keep_weekly)
    for name in doomed:
        shutil.rmtree(dest / name)
    return doomed


def check_freshness(dest: Path, max_age_hours: float) -> int:
    complete = sorted(
        p.name
        for p in dest.iterdir()
        if p.is_dir() and MANIFEST_ID_RE.match(p.name) and (p / "index.json").is_file()
    )
    if not complete:
        raise BackupError(f"no complete backup set in {dest}")
    newest = complete[-1]
    stamp = datetime.strptime(newest.split("-")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    age = datetime.now(UTC) - stamp
    if age > timedelta(hours=max_age_hours):
        raise BackupError(
            f"newest complete backup {newest} is {age.total_seconds() / 3600:.1f}h old "
            f"(limit {max_age_hours}h)"
        )
    print(f"backup_encrypted: newest complete backup {newest} is fresh")
    return 0


def run_backup(args: argparse.Namespace) -> int:
    config = _db_config_from_env()
    public_key = load_public_key(Path(args.public_key))
    fingerprint = public_key_fingerprint(public_key)
    manifest_id = new_manifest_id()
    timings: dict[str, float] = {}
    started = time.monotonic()

    work_parent = Path(args.work_dir) if args.work_dir else None
    with tempfile.TemporaryDirectory(prefix="fyp-backup-", dir=work_parent) as tmp:
        work = Path(tmp)
        os.chmod(work, 0o700)

        connection = _connect(config)
        try:
            window_start = _db_utc_now(connection)
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                row = cursor.fetchone()
            schema_revision = row[0] if row else None
        finally:
            connection.close()

        phase = time.monotonic()
        dump_path = dump_database(work, config, manifest_id)
        timings["dump_seconds"] = time.monotonic() - phase

        connection = _connect(config)
        try:
            window_end = _db_utc_now(connection)
        finally:
            connection.close()

        phase = time.monotonic()
        objects, skipped = collect_objects(Path(args.objects_dir))
        tar_path, entries = archive_objects(work, manifest_id, objects)
        timings["archive_seconds"] = time.monotonic() - phase
        for item in skipped:
            print(f"backup_encrypted: skipped non-object file {item}", file=sys.stderr)

        phase = time.monotonic()
        archived = {str(e["key"]): str(e["sha256"]) for e in entries}
        checked_rows = check_coordination(config, window_start, window_end, archived)
        timings["coordination_check_seconds"] = time.monotonic() - phase

        manifest = {
            "format": FORMAT_VERSION,
            "manifest_id": manifest_id,
            "database": config.database,
            "schema_revision": schema_revision,
            "dump_window_utc": [window_start.isoformat(), window_end.isoformat()],
            "db": {"sha256": sha256_file(dump_path), "bytes": dump_path.stat().st_size},
            "objects_tar": {"sha256": sha256_file(tar_path), "bytes": tar_path.stat().st_size},
            "objects": entries,
            "coordination_rows_checked": checked_rows,
            "skipped_non_object_files": len(skipped),
        }
        manifest_path = work / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        phase = time.monotonic()
        set_dir = work / "set"
        set_dir.mkdir(mode=0o700)
        plaintexts = {"db": dump_path, "objects": tar_path, "manifest": manifest_path}
        for role, filename in ARTIFACTS.items():
            encrypt_file(
                plaintexts[role],
                set_dir / filename,
                public_key,
                envelope_context(manifest_id, role),
            )
            plaintexts[role].unlink()
        timings["encrypt_seconds"] = time.monotonic() - phase

        index = {
            "format": FORMAT_VERSION,
            "manifest_id": manifest_id,
            "created_at_utc": window_start.isoformat(),
            "schema_revision": schema_revision,
            "public_key_sha256": fingerprint,
            "artifacts": {
                role: {
                    "file": filename,
                    "sha256": sha256_file(set_dir / filename),
                    "bytes": (set_dir / filename).stat().st_size,
                }
                for role, filename in ARTIFACTS.items()
            },
        }
        (set_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

        phase = time.monotonic()
        location = ship(set_dir, args.dest, manifest_id)
        timings["ship_seconds"] = time.monotonic() - phase

    pruned: list[str] = []
    if args.prune and Path(args.dest).is_dir():
        pruned = prune_local(Path(args.dest), args.keep_daily, args.keep_weekly)

    timings["total_seconds"] = time.monotonic() - started
    summary = {
        "manifest_id": manifest_id,
        "location": location,
        "objects": len(entries),
        "coordination_rows_checked": checked_rows,
        "pruned": pruned,
        "timings": {k: round(v, 3) for k, v in timings.items()},
    }
    print(json.dumps(summary))
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--public-key", help="PEM RSA public key (>= 3072 bits)")
    parser.add_argument(
        "--objects-dir",
        default=os.getenv("ENCRYPTED_FILE_DIR", "encrypted_files"),
        help="ciphertext object root (default: $ENCRYPTED_FILE_DIR or encrypted_files)",
    )
    parser.add_argument("--dest", help="local directory, user@host:/path, or s3://bucket/prefix")
    parser.add_argument("--work-dir", help="parent for the private temporary work directory")
    parser.add_argument("--prune", action="store_true", help="apply retention (local dest only)")
    parser.add_argument("--keep-daily", type=int, default=7)
    parser.add_argument("--keep-weekly", type=int, default=4)
    parser.add_argument(
        "--check-freshness",
        metavar="DEST",
        help="only check that DEST holds a complete set newer than --max-age-hours",
    )
    parser.add_argument("--max-age-hours", type=float, default=26.0)
    args = parser.parse_args(argv)
    if not args.check_freshness and (not args.public_key or not args.dest):
        parser.error("--public-key and --dest are required to take a backup")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        if args.check_freshness:
            return check_freshness(Path(args.check_freshness), args.max_age_hours)
        return run_backup(args)
    except (BackupError, EnvelopeError, OSError, pymysql.MySQLError) as exc:
        print(f"backup_encrypted: FAILED -- {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"backup_encrypted: FAILED -- {exc.cmd[0]} exited {exc.returncode}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
