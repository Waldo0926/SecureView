"""Restore one encrypted backup set onto a clean database and object directory, verify it,
and record how long each step took.

This is both the clean-host restore procedure and its drill (issue #56). It never writes
over anything: the target database must not exist yet (or be empty) and the target object
directory must be empty, so it can be pointed at a fresh MySQL host or a disposable
database beside a live one.

Refuses -- exits non-zero, drops the target database it created, and empties the object
directory it filled -- when any of these fail:

* each artifact's SHA-256 matches index.json;
* each artifact decrypts and authenticates under the backup private key *and* this set's
  manifest id and role (so an artifact from another backup set cannot be mixed in);
* the manifest id inside the manifest, the dump's first line, and the archive's MANIFEST_ID
  member all equal the index's id;
* the decrypted dump and archive match the SHA-256s in the manifest, and the dump ends
  with mysqldump's completion trailer;
* after loading, every ACTIVE `files` row has its object in the archive, and the object's
  bytes hash to `files.encrypted_sha256` -- the restored metadata references exactly the
  restored object set;
* the restored `alembic_version` equals the revision recorded at backup time and
  `alembic check` finds no drift from the application models;
* with `--expect-source-db`, db_fingerprint.py finds the restored database identical in
  content (CHECKSUM TABLE) and schema to that source (used by the CI/local drill, where the
  source is quiesced; on a real restore the source is usually gone).

Connection details for the target server come from the environment, never the command
line: DB_HOST, DB_PORT, ADMIN_DB_USER, ADMIN_DB_PASSWORD[, DB_SSL_CA]. The private key
passphrase, if the key has one, comes from BACKUP_PRIVATE_KEY_PASSPHRASE or a prompt.

    .venv/bin/python scripts/restore_drill.py --backup-set /mnt/offsite/20260924T091500Z-3f9c2a1b \
        --private-key /media/custodian/backup_priv.pem \
        --target-db fyp_secure_file_platform --objects-dir encrypted_files \
        --report restore-report.json
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymysql
from backup_encrypted import (
    ARTIFACTS,
    DUMP_HEADER_PREFIX,
    MANIFEST_ID_RE,
    dump_trailer_present,
    envelope_context,
    is_object_key,
)
from backup_envelope import (
    EnvelopeError,
    decrypt_file,
    load_private_key,
    sha256_file,
)
from db_fingerprint import connect_admin, differences, fingerprint

BACKEND_DIR = Path(__file__).resolve().parents[1]


class RestoreRefused(Exception):
    pass


def verify_restored_objects(
    rows: list[tuple[str, str, str]], manifest_objects: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Given restored (storage_object_key, encrypted_sha256, status) rows and the manifest's
    key->sha256 map, return (problems, keys_to_restore)."""
    problems: list[str] = []
    to_restore: list[str] = []
    for key, expected_sha, status in rows:
        archived_sha = manifest_objects.get(key)
        if archived_sha is None:
            if status == "ACTIVE":
                problems.append(f"ACTIVE file object {key} is not in this backup set")
            continue
        if status == "ACTIVE" and archived_sha != expected_sha:
            problems.append(f"ACTIVE file object {key} does not match files.encrypted_sha256")
            continue
        to_restore.append(key)
    return problems, to_restore


class Drill:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.set_dir = Path(args.backup_set)
        self.target_db = args.target_db
        self.objects_dir = Path(args.objects_dir)
        self.timings: dict[str, float] = {}
        self.created_db = False
        self.wrote_objects = False
        self.report: dict[str, object] = {}

    def _time(self, label: str, started: float) -> None:
        self.timings[label] = round(time.monotonic() - started, 3)

    def _mysql(self, sql_file: Path) -> None:
        option_file = self.work / "client.cnf"
        if not option_file.exists():
            fd = os.open(option_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            password = os.environ["ADMIN_DB_PASSWORD"].replace("\\", "\\\\").replace('"', '\\"')
            lines = [
                "[client]",
                f"host={os.environ['DB_HOST']}",
                f"port={os.getenv('DB_PORT', '3306')}",
                f"user={os.environ['ADMIN_DB_USER']}",
                f'password="{password}"',
                "protocol=TCP",
            ]
            if os.getenv("DB_SSL_CA"):
                lines += ["ssl-mode=VERIFY_CA", f"ssl-ca={os.environ['DB_SSL_CA']}"]
            with os.fdopen(fd, "w") as handle:
                handle.write("\n".join(lines) + "\n")
        mysql = os.getenv("MYSQL_BIN", "mysql")
        with sql_file.open("rb") as handle:
            result = subprocess.run(
                [mysql, f"--defaults-extra-file={option_file}", self.target_db],
                stdin=handle,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()[-500:]
            raise RestoreRefused(f"loading the dump failed: {detail}")

    def _private_key(self):
        passphrase = os.getenv("BACKUP_PRIVATE_KEY_PASSPHRASE")
        key_path = Path(self.args.private_key)
        if key_path.stat().st_mode & 0o077:
            print(
                "restore_drill: warning: the private key file is readable by group/others",
                file=sys.stderr,
            )
        try:
            return load_private_key(key_path, passphrase.encode() if passphrase else None)
        except EnvelopeError:
            if passphrase is None and sys.stdin.isatty():
                entered = getpass.getpass("Backup private key passphrase: ")
                return load_private_key(key_path, entered.encode())
            raise

    def preflight_target(self) -> None:
        if self.objects_dir.exists() and any(self.objects_dir.iterdir()):
            raise RestoreRefused(f"object directory {self.objects_dir} is not empty")
        with self.admin.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                (self.target_db,),
            )
            (exists,) = cursor.fetchone()
            if exists:
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                    (self.target_db,),
                )
                (tables,) = cursor.fetchone()
                if tables:
                    raise RestoreRefused(f"target database {self.target_db} is not empty")
            else:
                cursor.execute(
                    f"CREATE DATABASE `{self.target_db}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
                self.created_db = True

    def run(self) -> None:
        overall = time.monotonic()

        # 1. Index and ciphertext integrity, before touching any key material.
        started = time.monotonic()
        index_path = self.set_dir / "index.json"
        if not index_path.is_file():
            raise RestoreRefused("index.json is missing: the backup set is incomplete")
        index = json.loads(index_path.read_text(encoding="utf-8"))
        manifest_id = str(index.get("manifest_id", ""))
        if not MANIFEST_ID_RE.match(manifest_id) or self.set_dir.name != manifest_id:
            raise RestoreRefused(
                f"index manifest id {manifest_id!r} does not match set directory "
                f"{self.set_dir.name!r}"
            )
        artifacts = index.get("artifacts", {})
        for role, filename in ARTIFACTS.items():
            entry = artifacts.get(role) or {}
            path = self.set_dir / filename
            if entry.get("file") != filename or not path.is_file():
                raise RestoreRefused(f"{role} artifact {filename} is missing")
            if sha256_file(path) != entry.get("sha256"):
                raise RestoreRefused(f"{role} artifact {filename} does not match index.json")
        self._time("verify_ciphertext_seconds", started)

        # 2. Decrypt all three artifacts into the private work directory.
        started = time.monotonic()
        key = self._private_key()
        plain = {
            "db": self.work / "db.sql",
            "objects": self.work / "objects.tar",
            "manifest": self.work / "manifest.json",
        }
        for role, filename in ARTIFACTS.items():
            try:
                decrypt_file(
                    self.set_dir / filename,
                    plain[role],
                    key,
                    envelope_context(manifest_id, role),
                )
            except EnvelopeError as exc:
                raise RestoreRefused(f"{role} artifact: {exc}") from exc
        del key
        self._time("decrypt_seconds", started)

        # 3. Every embedded manifest id must agree; plaintext hashes must match.
        started = time.monotonic()
        manifest = json.loads(plain["manifest"].read_text(encoding="utf-8"))
        if manifest.get("manifest_id") != manifest_id:
            raise RestoreRefused("manifest.json names a different manifest id than index.json")
        with plain["db"].open("rb") as handle:
            first_line = handle.readline().decode("utf-8", "replace").strip()
        if first_line != f"{DUMP_HEADER_PREFIX}{manifest_id}".strip():
            raise RestoreRefused("database dump belongs to a different backup set")
        if not dump_trailer_present(plain["db"]):
            raise RestoreRefused("database dump is truncated (no mysqldump completion trailer)")
        if sha256_file(plain["db"]) != manifest["db"]["sha256"]:
            raise RestoreRefused("database dump does not match the manifest")
        if sha256_file(plain["objects"]) != manifest["objects_tar"]["sha256"]:
            raise RestoreRefused("object archive does not match the manifest")
        with tarfile.open(plain["objects"], mode="r") as tar:
            marker = tar.extractfile("MANIFEST_ID")
            archived_id = marker.read().decode().strip() if marker else ""
        if archived_id != manifest_id:
            raise RestoreRefused("object archive belongs to a different backup set")
        manifest_objects = {str(o["key"]): str(o["sha256"]) for o in manifest["objects"]}
        self._time("verify_manifest_seconds", started)

        # 4. Load the database into the clean target.
        self.preflight_target()
        started = time.monotonic()
        self._mysql(plain["db"])
        self._time("database_restore_seconds", started)

        # 5. Reconcile restored metadata against the archive, then restore those objects.
        started = time.monotonic()
        with self.admin.cursor() as cursor:
            cursor.execute(
                f"SELECT storage_object_key, encrypted_sha256, status FROM `{self.target_db}`.files"
            )
            rows = [(str(k), str(s), str(st)) for k, s, st in cursor.fetchall()]
        problems, to_restore = verify_restored_objects(rows, manifest_objects)
        if problems:
            shown = "; ".join(problems[:5])
            raise RestoreRefused(f"restored metadata references objects this set lacks: {shown}")
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        wanted = set(to_restore)
        restored = 0
        with tarfile.open(plain["objects"], mode="r") as tar:
            for member in tar:
                if member.name == "MANIFEST_ID":
                    continue
                relative = PurePosixPath(member.name)
                if relative.parts[:1] != ("objects",) or not member.isfile():
                    raise RestoreRefused(f"unexpected archive member {member.name!r}")
                key = PurePosixPath(*relative.parts[1:])
                if not is_object_key(key):
                    raise RestoreRefused(f"unsafe object key in archive: {member.name!r}")
                if str(key) not in wanted:
                    continue
                destination = self.objects_dir.joinpath(*key.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                assert source is not None
                self.wrote_objects = True
                with destination.open("xb") as out:
                    shutil.copyfileobj(source, out)
                if sha256_file(destination) != manifest_objects[str(key)]:
                    raise RestoreRefused(f"object {key} changed between archive and disk")
                restored += 1
        if restored != len(wanted):
            raise RestoreRefused(f"restored {restored} objects, expected {len(wanted)}")
        self._time("object_restore_seconds", started)

        # 6. Schema revision and model parity; optional full fingerprint comparison.
        started = time.monotonic()
        with self.admin.cursor() as cursor:
            cursor.execute(f"SELECT version_num FROM `{self.target_db}`.alembic_version")
            row = cursor.fetchone()
        revision = row[0] if row else None
        if revision != index.get("schema_revision"):
            raise RestoreRefused(
                f"restored revision {revision!r} != recorded {index.get('schema_revision')!r}"
            )
        self._alembic_check()
        fingerprint_match = None
        if self.args.expect_source_db:
            source = fingerprint(self.admin, self.args.expect_source_db)
            restored_fp = fingerprint(self.admin, self.target_db)
            diffs = differences(source, restored_fp)
            if diffs:
                raise RestoreRefused("restored database differs from source: " + "; ".join(diffs))
            fingerprint_match = restored_fp.data_sha256
        self._time("verify_restore_seconds", started)
        self._time("total_seconds", overall)

        self.report = {
            "result": "restored",
            "manifest_id": manifest_id,
            "schema_revision": revision,
            "file_rows": len(rows),
            "objects_restored": restored,
            "objects_in_archive_not_referenced": len(manifest_objects) - len(wanted),
            "db_dump_bytes": manifest["db"]["bytes"],
            "objects_tar_bytes": manifest["objects_tar"]["bytes"],
            "fingerprint_matched_source": fingerprint_match,
            "timings": self.timings,
        }

    def _alembic_check(self) -> None:
        env = dict(os.environ)
        env.update(
            DB_HOST=os.environ["DB_HOST"],
            DB_PORT=os.getenv("DB_PORT", "3306"),
            DB_USER=os.environ["ADMIN_DB_USER"],
            DB_PASSWORD=os.environ["ADMIN_DB_PASSWORD"],
            DB_NAME=self.target_db,
        )
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "check"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RestoreRefused("alembic check found drift between the restore and the models")

    def cleanup_after_refusal(self) -> None:
        if self.created_db:
            with self.admin.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS `{self.target_db}`")
        if self.wrote_objects and self.objects_dir.is_dir():
            for child in self.objects_dir.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()

    def execute(self) -> int:
        with tempfile.TemporaryDirectory(prefix="fyp-restore-") as tmp:
            self.work = Path(tmp)
            os.chmod(self.work, 0o700)
            self.admin = connect_admin()
            try:
                self.run()
            except RestoreRefused as exc:
                self.cleanup_after_refusal()
                print(f"restore_drill: REFUSED -- {exc}", file=sys.stderr)
                return 1
            finally:
                self.admin.close()
        if self.args.report:
            Path(self.args.report).write_text(json.dumps(self.report, indent=2), encoding="utf-8")
        print(json.dumps(self.report))
        return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--backup-set", required=True, help="directory <dest>/<manifest-id>")
    parser.add_argument("--private-key", required=True, help="PEM backup private key")
    parser.add_argument("--target-db", required=True, help="new or empty database to restore")
    parser.add_argument("--objects-dir", required=True, help="new or empty object directory")
    parser.add_argument("--expect-source-db", help="compare the restore against this database")
    parser.add_argument("--report", help="write the JSON report with timings here")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    for name in ("DB_HOST", "ADMIN_DB_USER", "ADMIN_DB_PASSWORD"):
        if not os.getenv(name):
            print(f"restore_drill: missing required environment variable {name}", file=sys.stderr)
            return 2
    try:
        return Drill(parse_args(argv)).execute()
    except (EnvelopeError, OSError, pymysql.MySQLError) as exc:
        print(f"restore_drill: FAILED -- {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
