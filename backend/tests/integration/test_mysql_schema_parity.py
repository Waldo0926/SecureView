"""Verify the live, migrated MySQL schema matches the ORM models it backs.

`tests/unit/test_mysql_sql_deployment.py` already proves that
`database/mysql/02-schema.sql` (the from-scratch installer) agrees with
`Base.metadata` -- offline, by parsing the SQL file's text. It never touches a
live server, so it cannot catch a migration that renders correctly as SQL but
behaves differently once MySQL actually applies it (a silently-dropped
constraint, a foreign key MySQL declined to create because of an engine or
collation mismatch, and so on). This module is the live counterpart: it runs
against the database the rest of the MySQL integration suite already migrated
to head, and diffs `information_schema` against `Base.metadata` directly.
"""

from __future__ import annotations

from collections import defaultdict

import pytest
from sqlalchemy import Engine, ForeignKeyConstraint, UniqueConstraint, inspect, text

import app.models  # noqa: F401 -- registers every model with Base.metadata
from app.core.database import Base

pytestmark = pytest.mark.integration


def test_live_foreign_keys_match_orm_metadata(auth_mysql_engine: Engine) -> None:
    inspector = inspect(auth_mysql_engine)

    expected: dict[str, set[tuple[tuple[str, ...], str, str]]] = defaultdict(set)
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            local_columns = tuple(sorted(constraint.column_keys))
            referred_table = next(iter(constraint.elements)).column.table.name
            ondelete = (constraint.ondelete or "RESTRICT").upper()
            expected[table.name].add((local_columns, referred_table, ondelete))

    actual: dict[str, set[tuple[tuple[str, ...], str, str]]] = defaultdict(set)
    for table_name in expected:
        for fk in inspector.get_foreign_keys(table_name):
            local_columns = tuple(sorted(fk["constrained_columns"]))
            ondelete = (fk.get("options", {}).get("ondelete") or "RESTRICT").upper()
            actual[table_name].add((local_columns, fk["referred_table"], ondelete))

    assert dict(actual) == dict(expected)


def test_live_unique_constraints_and_columns_match_orm_metadata(auth_mysql_engine: Engine) -> None:
    inspector = inspect(auth_mysql_engine)

    for table in Base.metadata.tables.values():
        expected_unique_column_sets = {
            tuple(sorted(constraint.columns.keys()))
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        expected_unique_column_sets |= {
            tuple(sorted(index.columns.keys())) for index in table.indexes if index.unique
        }

        actual_unique_column_sets = {
            tuple(sorted(unique_constraint["column_names"]))
            for unique_constraint in inspector.get_unique_constraints(table.name)
        }
        actual_unique_column_sets |= {
            tuple(sorted(index["column_names"]))
            for index in inspector.get_indexes(table.name)
            if index["unique"]
        }

        assert actual_unique_column_sets == expected_unique_column_sets, (
            f"unique-constraint mismatch on {table.name}"
        )

        expected_columns = {column.name for column in table.columns}
        actual_columns = {column["name"] for column in inspector.get_columns(table.name)}
        assert actual_columns == expected_columns, f"column mismatch on {table.name}"


def test_live_check_constraints_are_present(auth_mysql_engine: Engine) -> None:
    """MySQL 8.4 enforces CHECK constraints; confirm the migrated schema kept them.

    `inspector.get_check_constraints` is unreliable across dialect/driver
    versions for MySQL, so this queries `information_schema` directly, the
    same source of truth the runtime-grants and TLS checks use.
    """
    with auth_mysql_engine.connect() as connection:
        database_name = connection.engine.url.database
        rows = connection.execute(
            text(
                "SELECT tc.table_name AS table_name, tc.constraint_name AS constraint_name "
                "FROM information_schema.table_constraints tc "
                "WHERE tc.constraint_schema = :schema AND tc.constraint_type = 'CHECK'"
            ),
            {"schema": database_name},
        ).all()

    live_check_names = {row.constraint_name for row in rows}
    # ck_auth_0002_requires_empty_audit_log is a one-shot upgrade guard: it exists
    # only inside the 0002 migration's transaction and is dropped before it commits,
    # so it must never be present in a database that has finished migrating.
    assert "ck_auth_0002_requires_empty_audit_log" not in live_check_names

    expected_check_names = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint" and constraint.name is not None
    }
    assert expected_check_names <= live_check_names
