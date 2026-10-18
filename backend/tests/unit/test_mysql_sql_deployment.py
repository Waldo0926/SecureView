from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import app.models  # noqa: F401 -- registers every model with Base.metadata
from app.core.database import Base

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MYSQL_SQL_ROOT = REPOSITORY_ROOT / "database" / "mysql"


def _read_sql(filename: str) -> str:
    return (MYSQL_SQL_ROOT / filename).read_text(encoding="utf-8")


def _permanent_table_blocks(schema_sql: str) -> dict[str, str]:
    return {
        match.group("table"): match.group("body")
        for match in re.finditer(
            r"CREATE TABLE\s+`?(?P<table>[a-z0-9_]+)`?\s*\("
            r"(?P<body>.*?)\)\s+ENGINE=InnoDB",
            schema_sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
    }


def _column_names(table_body: str) -> list[str]:
    columns: list[str] = []
    constraint_keywords = {"primary", "constraint", "foreign", "unique", "check", "on"}
    column_type_prefixes = (
        "bigint",
        "blob",
        "bool",
        "char",
        "datetime",
        "enum",
        "integer",
        "json",
        "smallint",
        "text",
        "tinyint",
        "varbinary",
        "varchar",
    )
    for line in table_body.splitlines():
        match = re.match(r"\s*`?([a-z][a-z0-9_]*)`?\s+", line, flags=re.IGNORECASE)
        remainder = line[match.end() :].lstrip().lower() if match is not None else ""
        if (
            match is not None
            and match.group(1).lower() not in constraint_keywords
            and remainder.startswith(column_type_prefixes)
        ):
            columns.append(match.group(1))
    return columns


def test_root_schema_sql_matches_application_metadata() -> None:
    schema_sql = _read_sql("02-schema.sql")
    table_blocks = _permanent_table_blocks(schema_sql)

    assert set(table_blocks) == {*Base.metadata.tables, "alembic_version"}
    for table in Base.metadata.sorted_tables:
        assert _column_names(table_blocks[table.name]) == [column.name for column in table.columns]
    assert _column_names(table_blocks["alembic_version"]) == ["version_num"]

    actual_indexes = {
        match.group("name"): (
            match.group("table"),
            tuple(column.strip().strip("`") for column in match.group("columns").split(",")),
        )
        for match in re.finditer(
            r"CREATE INDEX\s+(?P<name>[a-z0-9_]+)\s+"
            r"ON\s+`?(?P<table>[a-z0-9_]+)`?\s*\((?P<columns>[^)]+)\)",
            schema_sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
    }
    expected_indexes = {
        index.name: (table.name, tuple(column.name for column in index.columns))
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }
    assert actual_indexes == expected_indexes

    persistent_sql = schema_sql.split("DROP TEMPORARY TABLE fyp_schema_install_guard;", maxsplit=1)[
        1
    ]
    actual_named_constraints = {
        (match.group("name"), match.group("kind").upper())
        for match in re.finditer(
            r"CONSTRAINT\s+(?P<name>[a-z0-9_]+)\s+"
            r"(?P<kind>UNIQUE|FOREIGN KEY|CHECK|PRIMARY KEY)",
            persistent_sql,
            flags=re.IGNORECASE,
        )
    }
    expected_named_constraints: set[tuple[str, str]] = {("alembic_version_pkc", "PRIMARY KEY")}
    constraint_labels = {
        UniqueConstraint: "UNIQUE",
        ForeignKeyConstraint: "FOREIGN KEY",
        CheckConstraint: "CHECK",
    }
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            for constraint_type, label in constraint_labels.items():
                if isinstance(constraint, constraint_type) and constraint.name is not None:
                    expected_named_constraints.add((constraint.name, label))
                    break

    assert actual_named_constraints == expected_named_constraints


def test_root_schema_sql_is_empty_only_and_marks_completion_last() -> None:
    schema_sql = _read_sql("02-schema.sql")
    lowered = schema_sql.lower()

    assert "create table if not exists" not in lowered
    assert "insert ignore" not in lowered
    assert "on duplicate key" not in lowered
    assert "foreign_key_checks" not in lowered
    assert "fyp_migrator" not in schema_sql
    assert "ON `fyp_secure_file_platform`.*" not in schema_sql
    assert len(re.findall(r"(?m)^GRANT ", schema_sql)) == 17
    assert (
        "GRANT SELECT, UPDATE (last_log_id, current_hash, updated_at)\n"
        "    ON `fyp_secure_file_platform`.`audit_chain_heads`"
    ) in schema_sql
    assert (
        "GRANT SELECT, UPDATE\n    ON `fyp_secure_file_platform`.`audit_chain_heads`"
        not in schema_sql
    )
    assert "UPDATE (schema_revision)" not in schema_sql
    assert (
        "schema_revision VARCHAR(64) NOT NULL DEFAULT '0002_auth_identity_sessions'"
    ) in schema_sql
    assert schema_sql.index("INSERT INTO audit_chain_heads") < schema_sql.index("GRANT SELECT")
    assert schema_sql.index("GRANT SELECT") < schema_sql.index("CREATE TABLE alembic_version")
    assert "'0002_auth_identity_sessions'\n);" in schema_sql
    assert schema_sql.index("VALUES ('0011_must_change_password');") < schema_sql.index(
        "ALTER TABLE audit_chain_heads\nALTER COLUMN schema_revision"
    )
    assert schema_sql.index(
        "ALTER TABLE audit_chain_heads\nALTER COLUMN schema_revision"
    ) < schema_sql.index("UPDATE audit_chain_heads")
    assert schema_sql.rstrip().endswith(
        "SET schema_revision = '0011_must_change_password'\nWHERE id = 1;"
    )


def test_root_verification_sql_is_read_only_and_checks_retired_identity() -> None:
    verification_sql = _read_sql("03-verify.sql")
    uncommented = "\n".join(
        line for line in verification_sql.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [statement.strip() for statement in uncommented.split(";") if statement.strip()]

    assert statements
    assert all(statement.upper().startswith(("SELECT", "WITH")) for statement in statements)
    assert "mysql.global_grants" in verification_sql
    assert "fyp_migrator" in verification_sql
    assert "expected_table_grants" in verification_sql
    assert "expected_column_grants" in verification_sql
    assert "'last_log_id' AS column_name" in verification_sql
    assert "'current_hash', 'UPDATE', 'NO'" in verification_sql
    assert "'updated_at', 'UPDATE', 'NO'" in verification_sql
    assert "readiness_marker_default_status" in verification_sql
    assert "MAX(COLUMN_DEFAULT) = '0011_must_change_password'" in verification_sql
    assert "'_utf8mb4', ''" in verification_sql
    assert "'_latin1', ''" in verification_sql
    assert "CHAR(92), ''" in verification_sql
    assert "lengthderivation_saltbetween16and32" in verification_sql


def test_root_verification_accepts_only_a_consistent_live_audit_head() -> None:
    verification_sql = _read_sql("03-verify.sql")

    assert "ELSE 'LIVE_DATA' END AS audit_log_status" in verification_sql
    assert "COUNT(head.id) AS audit_chain_head_rows" in verification_sql
    assert "audit_state.audit_log_rows = 0" in verification_sql
    assert "head.last_log_id = audit_state.max_log_id" in verification_sql
    assert "last_log.current_hash = head.current_hash" in verification_sql
    # Both the genesis and the live branch must name the current revision. A
    # merge that updated only one of them let an inconsistent live deployment
    # fail its release gate, so assert the count and that no stale revision
    # string survives anywhere in the file.
    assert verification_sql.count("head.schema_revision = '0011_must_change_password'") == 4
    assert "0003_client_key_custody" not in verification_sql
    assert "THEN 'LIVE_DATA'\n        ELSE 'REVIEW'" in verification_sql
    assert "ON last_log.id = head.last_log_id" in verification_sql


def test_backup_account_sql_grants_read_only_access_and_nothing_else() -> None:
    backup_sql = _read_sql("04-backup-account.sql")
    statements = [
        line
        for line in backup_sql.splitlines()
        if line and not line.startswith("--") and not line.startswith(" ")
    ]

    assert (
        "CREATE USER IF NOT EXISTS 'fyp_backup_user'@'localhost'\n"
        "    IDENTIFIED WITH caching_sha2_password BY RANDOM PASSWORD\n"
        "    REQUIRE SSL\n"
        "    WITH MAX_USER_CONNECTIONS 2;"
    ) in backup_sql
    grants = [line for line in statements if line.startswith("GRANT ")]
    assert grants == [
        "GRANT SELECT ON `fyp_secure_file_platform`.* TO 'fyp_backup_user'@'localhost';"
    ]
    executable = "\n".join(
        line for line in backup_sql.splitlines() if not line.lstrip().startswith("--")
    ).lower()
    for forbidden in (
        "identified by '",
        "with grant option",
        "lock tables",
        "reload",
        "process",
        "drop ",
        "flush",
        " on *.*",
    ):
        assert forbidden not in executable, forbidden


def test_backup_account_is_not_part_of_the_empty_database_installer() -> None:
    # 02-schema.sql is a run-once installer; a GRANT to an account 01-provision.sql never
    # creates would abort it half-way (MySQL error 1410), so the backup account lives in
    # its own re-runnable file instead.
    assert "fyp_backup_user" not in _read_sql("01-provision.sql")
    assert "fyp_backup_user" not in _read_sql("02-schema.sql")
