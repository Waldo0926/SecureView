from __future__ import annotations

import pytest

from app.core.migration_defaults import mysql_timestamp_defaults_equivalent


@pytest.mark.parametrize(
    ("inspected", "rendered"),
    [
        ("CURRENT_TIMESTAMP", "now()"),
        ("current_timestamp()", "(NOW())"),
        ("CURRENT_TIMESTAMP(0)", "now()"),
        ("CURRENT_TIMESTAMP(6)", "localtimestamp(6)"),
    ],
)
def test_equivalent_mysql_timestamp_defaults(inspected: str, rendered: str) -> None:
    assert mysql_timestamp_defaults_equivalent(inspected, rendered)


@pytest.mark.parametrize(
    ("inspected", "rendered"),
    [
        ("'A B'", "'AB'"),
        ("'RSA-OAEP-SHA256'", "'rsa-oaep-sha256'"),
        ("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP(3)"),
        ("CURRENT_TIMESTAMP", "now"),
        ("0", "0"),
        (None, None),
    ],
)
def test_non_timestamp_or_distinct_defaults_fall_back_to_alembic(
    inspected: str | None,
    rendered: str | None,
) -> None:
    assert not mysql_timestamp_defaults_equivalent(inspected, rendered)
