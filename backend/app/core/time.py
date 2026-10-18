from datetime import UTC, datetime, timedelta, timezone

# Every time shown to a person -- on the site, in the security agent's text, in alert mail -- is
# Kuala Lumpur time; storage and the API stay UTC. Malaysia has kept +08:00 all year since 1982,
# so a fixed offset is exact and needs no tz database. The browser side is
# `frontend/src/utils/site-time.ts`.
SITE_TIME_ZONE = timezone(timedelta(hours=8), "MYT")
SITE_TIME_ZONE_LABEL = "MYT"


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_database_utc(value: datetime) -> datetime:
    """Convert an instant to the naive UTC representation used by MySQL DATETIME."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def to_api_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_second_resolution_utc(value: datetime) -> datetime:
    """Naive UTC truncated to whole seconds, for the second-resolution DATETIME columns.

    Most columns in this schema are plain `DATETIME`, which stores no fractional part.
    MySQL does not truncate a value that carries one -- it rounds it, to the nearest
    second. A row written at 12:00:34.691 therefore came back as 12:00:35: the API
    answered `POST /files/upload` with an instant that was never stored, a later `GET`
    disagreed with it, and the stored instant sat up to half a second in the future.

    Deciding the value here instead of leaving it to the column keeps what the caller
    holds in memory identical to what lands in the row, and only ever moves a timestamp
    backwards.

    Not for `audit_logs`, `audit_chain_heads`, `user_key_protection_profiles`, or
    `encrypted_private_key_bundles`. Those are `DATETIME(6)` on purpose, because their
    values are covered by the audit hash chain and the key-custody signatures, and they
    must keep every digit they were hashed with. Use `to_database_utc` for those.
    """
    return to_database_utc(value).replace(microsecond=0)


def site_stamp(value: datetime, *, seconds: bool = False) -> str:
    """`2026-10-13 02:19 MYT`: an instant as people read it. A naive value is taken as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    clock = "%H:%M:%S" if seconds else "%H:%M"
    return value.astimezone(SITE_TIME_ZONE).strftime(f"%Y-%m-%d {clock} {SITE_TIME_ZONE_LABEL}")
