"""Prove the runtime and backup accounts cannot do what only an administrator may.

`database/mysql/02-schema.sql` grants the runtime identity ('fyp_user'@'localhost')
table-scoped SELECT/INSERT/UPDATE/DELETE only -- never DDL, never GRANT, never
unrestricted UPDATE on the append-only audit tables. `database/mysql/04-backup-account.sql`
grants the backup identity ('fyp_backup_user'@'localhost') SELECT on the application
database and nothing else. `tests/unit/test_mysql_sql_deployment.py` already checks that
the SQL files say this; it never connects to a live server. This script is the live
counterpart: it applies the exact GRANT statements from those files (renamed to the
disposable release-gate database) against a running MySQL instance, then connects AS each
account and asserts the boundary actually holds there, and separately that the
administrator connection (which applied the grants) is not subject to the same restriction.

Reads connection details from environment variables, mirroring verify_mysql_tls.py:

    DB_HOST, DB_PORT, DB_NAME
    ADMIN_DB_USER, ADMIN_DB_PASSWORD           -- can run DDL/GRANT (e.g. root)
    RUNTIME_DB_USER, RUNTIME_DB_PASSWORD       -- the runtime account being tested
    BACKUP_DB_USER, BACKUP_DB_PASSWORD         -- the backup account being tested

The backup pair is optional so the script still runs where no backup account is wanted,
but it says so loudly; CI always sets it.

Never logs a password. Exits non-zero on the first unexpected grant behaviour.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pymysql

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL_PATH = REPO_ROOT / "database" / "mysql" / "02-schema.sql"
BACKUP_ACCOUNT_SQL_PATH = REPO_ROOT / "database" / "mysql" / "04-backup-account.sql"
PRODUCTION_DATABASE_NAME = "fyp_secure_file_platform"
PRODUCTION_RUNTIME_USER = "fyp_user"
PRODUCTION_BACKUP_USER = "fyp_backup_user"
PRODUCTION_ACCOUNT_HOST = "localhost"

# MySQL error numbers that mean "access denied" for a command, column, database,
# table, or privilege-requiring operation.
ACCESS_DENIED_ERRORS = (1044, 1142, 1143, 1227)


def grant_statement_re(production_user: str) -> re.Pattern[str]:
    # `[^;]+?` keeps each match inside one statement, so a search for one account can
    # never run on past its own terminator into a later GRANT for a different account.
    return re.compile(
        r"^GRANT\s+[^;]+?\s+ON\s+`fyp_secure_file_platform`\.(?:`[a-z0-9_]+`|\*)\s+"
        rf"TO\s+'{re.escape(production_user)}'@'localhost';",
        re.MULTILINE,
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(
            f"check_runtime_grants: missing required environment variable {name}", file=sys.stderr
        )
        sys.exit(2)
    return value


def extract_grants(
    sql_path: Path,
    production_user: str,
    database_name: str,
    target_user: str,
    target_host: str,
) -> list[str]:
    sql = sql_path.read_text(encoding="utf-8")
    statements = grant_statement_re(production_user).findall(sql)
    if not statements:
        raise RuntimeError(f"no GRANT statements for {production_user!r} found in {sql_path}")
    rewritten = []
    for statement in statements:
        statement = statement.replace(f"`{PRODUCTION_DATABASE_NAME}`", f"`{database_name}`")
        statement = statement.replace(
            f"'{production_user}'@'{PRODUCTION_ACCOUNT_HOST}'",
            f"'{target_user}'@'{target_host}'",
        )
        rewritten.append(statement)
    return rewritten


def _connect(
    host: str, port: int, user: str, password: str, database: str
) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=host, port=port, user=user, password=password, database=database, connect_timeout=10
    )


def _expect_denied(cursor: pymysql.cursors.Cursor, sql: str, label: str) -> None:
    try:
        cursor.execute(sql)
    except pymysql.err.OperationalError as exc:
        if exc.args and exc.args[0] in ACCESS_DENIED_ERRORS:
            return
        raise AssertionError(
            f"{label}: unexpected error {exc!r}, wanted an access-denied error"
        ) from exc
    except pymysql.err.ProgrammingError as exc:
        if exc.args and exc.args[0] in ACCESS_DENIED_ERRORS:
            return
        raise AssertionError(
            f"{label}: unexpected error {exc!r}, wanted an access-denied error"
        ) from exc
    else:
        raise AssertionError(f"{label}: statement unexpectedly succeeded: {sql}")


def _provision(
    admin_connection: pymysql.connections.Connection,
    statements: list[str],
    user: str,
    host: str,
    password: str,
) -> None:
    with admin_connection.cursor() as cursor:
        cursor.execute(
            "CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s",
            (user, host, password),
        )
        for statement in statements:
            cursor.execute(statement)
    admin_connection.commit()


def _check_runtime_account(
    host: str, port: int, database: str, runtime_user: str, runtime_password: str, runtime_host: str
) -> None:
    runtime_connection = _connect(host, port, runtime_user, runtime_password, database)
    try:
        with runtime_connection.cursor() as cursor:
            # CRUD on a table the runtime identity is meant to own.
            cursor.execute(
                "INSERT INTO users (user_uuid, username, email, password_hash, role, status, "
                "email_verified) VALUES (%s, %s, %s, %s, 'USER', 'ACTIVE', 0)",
                (
                    "00000000-0000-4000-8000-000000000001",
                    "grant-probe-user",
                    "grant-probe@example.invalid",
                    "not-a-real-hash",
                ),
            )
            runtime_connection.commit()

            _expect_denied(cursor, "CREATE TABLE runtime_should_not_ddl (id INT)", "CREATE TABLE")
            _expect_denied(cursor, "DROP TABLE users", "DROP TABLE")
            _expect_denied(
                cursor,
                f"GRANT SELECT ON `{database}`.`users` TO '{runtime_user}'@'{runtime_host}'",
                "GRANT",
            )
            # audit_logs is append-only for the runtime identity: SELECT, INSERT only.
            _expect_denied(cursor, "DELETE FROM audit_logs", "DELETE FROM audit_logs")
            _expect_denied(
                cursor,
                "UPDATE audit_logs SET description = 'tampered' WHERE id = 1",
                "UPDATE audit_logs (full row)",
            )
            # audit_chain_heads may only have its three named columns updated.
            _expect_denied(
                cursor,
                "UPDATE audit_chain_heads SET schema_revision = 'tampered' WHERE id = 1",
                "UPDATE audit_chain_heads.schema_revision",
            )
            # Leave no trace so a repeat run of this script against the same
            # disposable database stays idempotent.
            cursor.execute(
                "DELETE FROM users WHERE user_uuid = %s",
                ("00000000-0000-4000-8000-000000000001",),
            )
        runtime_connection.commit()
    finally:
        runtime_connection.close()

    print(
        f"check_runtime_grants: {runtime_user!r} is confined to CRUD and cannot perform "
        "DDL, GRANT, or the writes the release-gate schema reserves to the administrator"
    )


def _check_backup_account(
    host: str, port: int, database: str, backup_user: str, backup_password: str, backup_host: str
) -> None:
    connection = _connect(host, port, backup_user, backup_password, database)
    try:
        with connection.cursor() as cursor:
            # It must be able to read every table mysqldump will visit, including the
            # append-only audit tables and the alembic_version marker.
            for table in ("users", "files", "audit_logs", "audit_chain_heads", "alembic_version"):
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                cursor.fetchone()

            _expect_denied(
                cursor,
                "INSERT INTO users (user_uuid, username, email, password_hash, role, status, "
                "email_verified) VALUES ('00000000-0000-4000-8000-000000000003', "
                "'backup-should-not-write', 'backup-should-not-write@example.invalid', "
                "'not-a-real-hash', 'USER', 'ACTIVE', 0)",
                "backup INSERT",
            )
            _expect_denied(
                cursor, "UPDATE users SET username = 'tampered' WHERE id = 1", "backup UPDATE"
            )
            _expect_denied(cursor, "DELETE FROM users", "backup DELETE")
            _expect_denied(cursor, "CREATE TABLE backup_should_not_ddl (id INT)", "backup CREATE")
            _expect_denied(cursor, "ALTER TABLE users ADD COLUMN x INT", "backup ALTER")
            _expect_denied(cursor, "DROP TABLE users", "backup DROP")
            _expect_denied(
                cursor,
                f"GRANT SELECT ON `{database}`.`users` TO '{backup_user}'@'{backup_host}'",
                "backup GRANT",
            )
            _expect_denied(cursor, "LOCK TABLES users READ", "backup LOCK TABLES")
            _expect_denied(cursor, "FLUSH TABLES WITH READ LOCK", "backup FLUSH TABLES")
            _expect_denied(cursor, "SELECT COUNT(*) FROM mysql.user", "backup read mysql.user")
            _expect_denied(
                cursor, "CREATE USER 'backup_should_not_create'@'%'", "backup CREATE USER"
            )
    finally:
        connection.close()

    print(
        f"check_runtime_grants: {backup_user!r} can read every application table but cannot "
        "write, lock, run DDL, GRANT, create users, or read other schemas"
    )


def main() -> int:
    host = _required_env("DB_HOST")
    port = int(os.environ.get("DB_PORT", "3306"))
    database = _required_env("DB_NAME")
    admin_user = _required_env("ADMIN_DB_USER")
    admin_password = _required_env("ADMIN_DB_PASSWORD")
    runtime_user = _required_env("RUNTIME_DB_USER")
    runtime_password = _required_env("RUNTIME_DB_PASSWORD")
    runtime_host = os.environ.get("RUNTIME_DB_HOST", "%")
    backup_user = os.environ.get("BACKUP_DB_USER")
    backup_password = os.environ.get("BACKUP_DB_PASSWORD")
    backup_host = os.environ.get("BACKUP_DB_HOST", "%")

    admin_connection = _connect(host, port, admin_user, admin_password, database)
    try:
        _provision(
            admin_connection,
            extract_grants(
                SCHEMA_SQL_PATH, PRODUCTION_RUNTIME_USER, database, runtime_user, runtime_host
            ),
            runtime_user,
            runtime_host,
            runtime_password,
        )
        if backup_user and backup_password:
            _provision(
                admin_connection,
                extract_grants(
                    BACKUP_ACCOUNT_SQL_PATH,
                    PRODUCTION_BACKUP_USER,
                    database,
                    backup_user,
                    backup_host,
                ),
                backup_user,
                backup_host,
                backup_password,
            )

        # The administrator connection itself must still be able to do DDL --
        # otherwise this whole test would be meaningless.
        with admin_connection.cursor() as cursor:
            cursor.execute("CREATE TABLE IF NOT EXISTS _grant_probe (id INT PRIMARY KEY)")
            cursor.execute("DROP TABLE _grant_probe")
        admin_connection.commit()
    finally:
        admin_connection.close()

    _check_runtime_account(host, port, database, runtime_user, runtime_password, runtime_host)

    if backup_user and backup_password:
        _check_backup_account(host, port, database, backup_user, backup_password, backup_host)
    else:
        print(
            "check_runtime_grants: BACKUP_DB_USER/BACKUP_DB_PASSWORD unset -- the backup "
            "account boundary was NOT checked",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"check_runtime_grants: FAILED -- {exc}", file=sys.stderr)
        sys.exit(1)
