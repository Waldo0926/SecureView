"""Seed a disposable database and object directory for backup_restore_drill.sh.

Not for use against a real deployment: it refuses any database whose name lacks a
`_test` segment, the same guard the integration suite uses.

    backup_drill_fixture.py seed <database> <objects_dir> <files> <bytes_per_file>
    backup_drill_fixture.py grant-backup <database> <user> <host>   # password on stdin

`seed` inserts users and `files` rows whose `storage_object_key`/`encrypted_sha256` point
at random ciphertext-shaped objects it writes, marks a tenth of them DELETED with their
object removed (as FileService.delete leaves them). `grant-backup` (re)creates an account
with exactly the GRANT from database/mysql/04-backup-account.sql, retargeted to the
disposable database.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_runtime_grants import (
    BACKUP_ACCOUNT_SQL_PATH,
    PRODUCTION_BACKUP_USER,
    extract_grants,
)
from db_fingerprint import connect_admin


def _require_test_database(name: str) -> None:
    if not re.search(r"(?:^|_)test(?:$|_)", name):
        raise SystemExit(f"backup_drill_fixture: refusing non-test database {name!r}")


def seed(database: str, objects_dir: Path, files: int, size: int) -> None:
    _require_test_database(database)
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0) - timedelta(minutes=5)
    connection = connect_admin(database)
    users = max(1, files // 20)
    try:
        with connection.cursor() as cursor:
            user_ids = []
            for index in range(users):
                cursor.execute(
                    "INSERT INTO users (user_uuid, username, email, password_hash, role, "
                    "status, email_verified, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, 'USER', 'ACTIVE', 1, %s, %s)",
                    (
                        str(uuid.uuid4()),
                        f"drill-user-{index}",
                        f"drill-user-{index}@example.invalid",
                        "drill-not-a-real-hash",
                        now,
                        now,
                    ),
                )
                user_ids.append(cursor.lastrowid)
            for index in range(files):
                file_uuid = str(uuid.uuid4())
                key = f"{file_uuid}/{uuid.uuid4()}.ciphertext"
                body = os.urandom(size)
                digest = hashlib.sha256(body).hexdigest()
                deleted = index % 10 == 9
                if not deleted:
                    path = objects_dir / key
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                cursor.execute(
                    "INSERT INTO files (file_uuid, owner_id, original_filename, stored_filename, "
                    "storage_object_key, mime_type, file_size_bytes, encrypted_size_bytes, iv, "
                    "auth_tag, encrypted_sha256, status, created_at, updated_at, deleted_at) "
                    "VALUES (%s, %s, %s, %s, %s, 'application/octet-stream', %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s)",
                    (
                        file_uuid,
                        user_ids[index % users],
                        f"drill-{index}.bin",
                        f"{file_uuid}.ciphertext",
                        key,
                        size,
                        size,
                        os.urandom(12),
                        os.urandom(16),
                        digest,
                        "DELETED" if deleted else "ACTIVE",
                        now,
                        now,
                        now if deleted else None,
                    ),
                )
        connection.commit()
    finally:
        connection.close()
    print(f"backup_drill_fixture: seeded {users} users and {files} files of {size} bytes")


def grant_backup(database: str, user: str, host: str, password: str) -> None:
    _require_test_database(database)
    connection = connect_admin()
    try:
        with connection.cursor() as cursor:
            cursor.execute("DROP USER IF EXISTS %s@%s", (user, host))
            cursor.execute("CREATE USER %s@%s IDENTIFIED BY %s", (user, host, password))
            for statement in extract_grants(
                BACKUP_ACCOUNT_SQL_PATH, PRODUCTION_BACKUP_USER, database, user, host
            ):
                cursor.execute(statement)
    finally:
        connection.close()


def main(argv: list[str]) -> int:
    if len(argv) == 6 and argv[1] == "seed":
        seed(argv[2], Path(argv[3]), int(argv[4]), int(argv[5]))
        return 0
    if len(argv) == 5 and argv[1] == "grant-backup":
        grant_backup(argv[2], argv[3], argv[4], sys.stdin.readline().rstrip("\n"))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
