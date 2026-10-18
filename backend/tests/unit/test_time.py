from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from app.core.time import to_api_utc, to_database_utc, to_second_resolution_utc

INSTANT = datetime(2026, 8, 24, 8, 6, 34, 691352, tzinfo=UTC)


def test_second_resolution_drops_the_fraction_rather_than_letting_mysql_round_it() -> None:
    """A plain DATETIME column rounds; it does not truncate.

    Handing MySQL 12:00:34.691 stored 12:00:35, so the API answered with an instant that
    was never stored and the row sat half a second in the future.
    """
    assert to_second_resolution_utc(INSTANT) == datetime(2026, 8, 24, 8, 6, 34)


def test_second_resolution_only_ever_moves_a_timestamp_backwards() -> None:
    for microsecond in (0, 1, 499_999, 500_000, 500_001, 999_999):
        value = INSTANT.replace(microsecond=microsecond)
        assert to_second_resolution_utc(value) <= to_database_utc(value)


def test_second_resolution_normalizes_a_non_utc_offset_first() -> None:
    melbourne = timezone(timedelta(hours=10))
    value = datetime(2026, 8, 24, 18, 6, 34, 691352, tzinfo=melbourne)

    assert to_second_resolution_utc(value) == datetime(2026, 8, 24, 8, 6, 34)


def test_second_resolution_accepts_an_already_naive_value() -> None:
    assert to_second_resolution_utc(INSTANT.replace(tzinfo=None)) == datetime(2026, 8, 24, 8, 6, 34)


def test_database_utc_still_keeps_microseconds_for_the_hashed_columns() -> None:
    """`audit_logs` and the key-custody tables are DATETIME(6) on purpose.

    Their values are covered by the audit hash chain and the key-custody signatures, so
    they must keep every digit they were hashed with.
    """
    assert to_database_utc(INSTANT).microsecond == 691352


def test_api_utc_round_trips_a_second_resolution_value() -> None:
    stored = to_second_resolution_utc(INSTANT)

    assert to_api_utc(stored) == datetime(2026, 8, 24, 8, 6, 34, tzinfo=UTC)


def test_the_two_helpers_are_not_interchangeable() -> None:
    """Guards the one thing a later reader is most likely to get wrong.

    Both helpers return a naive UTC datetime, so a call site can use either and nothing
    complains. Which one is correct is decided by the column: plain `DATETIME` rounds a
    fractional value, `DATETIME(6)` keeps it, and the audit chain recomputes its hashes
    from the stored row.
    """
    assert to_second_resolution_utc(INSTANT) != to_database_utc(INSTANT)
    assert to_second_resolution_utc(INSTANT) == to_database_utc(INSTANT).replace(microsecond=0)


def test_services_writing_second_resolution_columns_settle_the_value_themselves() -> None:
    """A source check, because the mistake it catches is invisible at runtime.

    Nothing fails when a service hands MySQL a fractional value for a plain `DATETIME`
    column -- the row is simply not the value the caller kept, and every later read
    disagrees with the response that reported it. These five services write only
    second-resolution columns, with one audited exception in `auth_service` for the two
    `DATETIME(6)` key-custody rows.
    """
    services = Path(__file__).resolve().parents[2] / "app" / "services"
    offenders = []
    for name in (
        "recovery_service.py",
        "verification_service.py",
        "admin_service.py",
        "file_service.py",
        "sharing_service.py",
        "integrity_service.py",
    ):
        if "to_database_utc(" in (services / name).read_text(encoding="utf-8"):
            offenders.append(name)
    assert offenders == [], offenders


def test_the_audit_chain_keeps_full_precision() -> None:
    """`audit_logs.created_at` is DATETIME(6) and verify-chain rehashes the stored row.

    Truncating on the way in would leave every entry unverifiable against its own hash.
    """
    services = Path(__file__).resolve().parents[2] / "app" / "services"
    audit_source = (services / "audit_log_service.py").read_text(encoding="utf-8")
    assert "to_database_utc(" in audit_source
    assert "to_second_resolution_utc(" not in audit_source
