"""Fingerprint a MySQL database's content and schema so two copies can be compared.

A restore that only matches table and row counts can still be wrong: a truncated BLOB, a
lost CHECK constraint, or one row restored with a different value all pass a count check.
This script computes two things per database:

* a **data** fingerprint from MySQL's own `CHECKSUM TABLE`, one value per base table, which
  changes when any byte of any row changes (the release gate proves this by mutating one
  row and expecting the comparison to fail);
* a **schema** fingerprint from `information_schema` -- columns, indexes, CHECK and foreign
  key constraints -- with the database name stripped, so a restore into a differently
  named database compares equal when, and only when, its shape is the same.

`CHECKSUM TABLE` was chosen over hashing `mysqldump` text because a dump of a restored
database is not byte-identical to a dump of the original even when every row is (the
restored DDL spells out character sets the original left implicit), which would make a
text hash fail on a perfectly good restore. The checksum depends on row format, so it is
only comparable between servers of the same MySQL version -- which is exactly the restore
drill's case: the same 8.4 release on both sides.

Usage (connection details come from the environment and are never printed):

    DB_HOST, DB_PORT, ADMIN_DB_USER, ADMIN_DB_PASSWORD[, DB_SSL_CA]

    python scripts/db_fingerprint.py show <database>      # per-table JSON
    python scripts/db_fingerprint.py digest <database>    # one line: data=... schema=...
    python scripts/db_fingerprint.py compare <database_a> <database_b>

`compare` exits 1 and names every table whose data or schema differs.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field

import pymysql

_SCHEMA_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "tables",
        "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'",
    ),
    (
        "columns",
        "SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE, IS_NULLABLE, "
        "COLUMN_DEFAULT, CHARACTER_SET_NAME, COLLATION_NAME, EXTRA, GENERATION_EXPRESSION "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s",
    ),
    (
        "indexes",
        "SELECT TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME, NON_UNIQUE, SUB_PART, "
        "EXPRESSION FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s",
    ),
    (
        "checks",
        "SELECT tc.TABLE_NAME, cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE "
        "FROM information_schema.CHECK_CONSTRAINTS cc "
        "JOIN information_schema.TABLE_CONSTRAINTS tc "
        "  ON tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA "
        " AND tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME "
        "WHERE cc.CONSTRAINT_SCHEMA = %s AND tc.CONSTRAINT_TYPE = 'CHECK'",
    ),
    (
        "foreign_keys",
        "SELECT k.TABLE_NAME, k.CONSTRAINT_NAME, k.COLUMN_NAME, k.ORDINAL_POSITION, "
        "k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME, r.UPDATE_RULE, r.DELETE_RULE "
        "FROM information_schema.KEY_COLUMN_USAGE k "
        "JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
        "  ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA "
        " AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
        "WHERE k.TABLE_SCHEMA = %s AND k.REFERENCED_TABLE_NAME IS NOT NULL",
    ),
)


@dataclass
class Fingerprint:
    database: str
    table_checksums: dict[str, int | None] = field(default_factory=dict)
    table_rows: dict[str, int] = field(default_factory=dict)
    table_schema: dict[str, str] = field(default_factory=dict)

    @property
    def data_sha256(self) -> str:
        return _sha256_lines(f"{t}\t{c}\t{self.table_rows[t]}" for t, c in self._sorted_checks())

    @property
    def schema_sha256(self) -> str:
        return _sha256_lines(f"{t}\t{h}" for t, h in sorted(self.table_schema.items()))

    def _sorted_checks(self) -> list[tuple[str, int | None]]:
        return sorted(self.table_checksums.items())

    def as_dict(self) -> dict[str, object]:
        return {
            "database": self.database,
            "data_sha256": self.data_sha256,
            "schema_sha256": self.schema_sha256,
            "tables": {
                name: {
                    "checksum": self.table_checksums[name],
                    "rows": self.table_rows[name],
                    "schema_sha256": self.table_schema.get(name),
                }
                for name in sorted(self.table_checksums)
            },
        }


def _sha256_lines(lines) -> str:
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def connect_admin(database: str | None = None) -> pymysql.connections.Connection:
    """Connect with the administrator identity from the environment; never logs it."""
    missing = [n for n in ("DB_HOST", "ADMIN_DB_USER", "ADMIN_DB_PASSWORD") if not os.getenv(n)]
    if missing:
        raise SystemExit(f"db_fingerprint: missing required environment: {', '.join(missing)}")
    ssl_ca = os.getenv("DB_SSL_CA")
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.environ["ADMIN_DB_USER"],
        password=os.environ["ADMIN_DB_PASSWORD"],
        database=database,
        ssl_ca=ssl_ca or None,
        ssl_verify_cert=bool(ssl_ca),
        ssl_verify_identity=False,
        connect_timeout=10,
        # Every read sees the latest committed state, never a snapshot opened earlier.
        autocommit=True,
    )


def _quote_identifier(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def fingerprint(connection: pymysql.connections.Connection, database: str) -> Fingerprint:
    result = Fingerprint(database=database)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME",
            (database,),
        )
        tables = [row[0] for row in cursor.fetchall()]
        if not tables:
            raise SystemExit(f"db_fingerprint: database {database!r} has no tables")

        for table in tables:
            qualified = f"{_quote_identifier(database)}.{_quote_identifier(table)}"
            cursor.execute(f"CHECKSUM TABLE {qualified} EXTENDED")
            (_, checksum) = cursor.fetchone()
            if checksum is None:
                raise SystemExit(f"db_fingerprint: CHECKSUM TABLE returned NULL for {table!r}")
            cursor.execute(f"SELECT COUNT(*) FROM {qualified}")
            (rows,) = cursor.fetchone()
            result.table_checksums[table] = int(checksum)
            result.table_rows[table] = int(rows)

        per_table: dict[str, list[str]] = {table: [] for table in tables}
        for label, query in _SCHEMA_QUERIES:
            cursor.execute(query, (database,))
            for row in cursor.fetchall():
                table = row[0]
                if table not in per_table:
                    continue
                per_table[table].append(label + "\t" + "\t".join(repr(value) for value in row))
        for table, lines in per_table.items():
            result.table_schema[table] = _sha256_lines(sorted(lines))
    return result


def differences(a: Fingerprint, b: Fingerprint) -> list[str]:
    problems: list[str] = []
    for table in sorted(set(a.table_checksums) | set(b.table_checksums)):
        if table not in a.table_checksums or table not in b.table_checksums:
            problems.append(f"{table}: present in only one database")
            continue
        if a.table_rows[table] != b.table_rows[table]:
            problems.append(f"{table}: row count {a.table_rows[table]} != {b.table_rows[table]}")
        elif a.table_checksums[table] != b.table_checksums[table]:
            problems.append(f"{table}: content checksum differs with equal row counts")
        if a.table_schema[table] != b.table_schema[table]:
            problems.append(f"{table}: schema (columns/indexes/constraints) differs")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "show":
        connection = connect_admin()
        try:
            print(json.dumps(fingerprint(connection, argv[2]).as_dict(), indent=2))
        finally:
            connection.close()
        return 0
    if len(argv) == 3 and argv[1] == "digest":
        connection = connect_admin()
        try:
            result = fingerprint(connection, argv[2])
        finally:
            connection.close()
        print(f"data={result.data_sha256} schema={result.schema_sha256}")
        return 0
    if len(argv) == 4 and argv[1] == "compare":
        connection = connect_admin()
        try:
            first = fingerprint(connection, argv[2])
            second = fingerprint(connection, argv[3])
        finally:
            connection.close()
        problems = differences(first, second)
        if problems:
            print(f"db_fingerprint: {argv[2]} and {argv[3]} differ:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(
            f"db_fingerprint: {argv[2]} == {argv[3]} "
            f"({len(first.table_checksums)} tables, data {first.data_sha256[:16]}, "
            f"schema {first.schema_sha256[:16]})"
        )
        return 0
    print(
        "usage: db_fingerprint.py show|digest <database> | compare <database_a> <database_b>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
