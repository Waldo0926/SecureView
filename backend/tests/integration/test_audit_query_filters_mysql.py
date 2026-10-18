"""The `GET /audit-logs` filters on real MySQL: they narrow a caller's page, never widen it.

A non-admin sees what they did, what was done to them, and everything done to a file they
own. Adding `action`, `result`, a time window or a keyword must leave that rule in place: a
stranger who searches for the owner's file name, or for a word only in the owner's rows, still
gets nothing of the owner's. The keyword also reaches the file name through the `files` join
and takes LIKE wildcards literally, both of which only MySQL can prove.

The shared `_test` database is permanent, so every row written here carries a per-run marker
and each assertion looks only at rows with that marker.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from tests.integration._concurrency_support import (
    RegisteredUser,
    active_recovery_key,
    register_real_user,
    session_scope,
    upload_file,
)

from app.core.time import utc_now
from app.domain.enums import SystemRole
from app.schemas.audit_schema import AuditLogQuery
from app.services.audit_log_service import AuditLogService
from app.services.audit_query_service import AuditQueryService

pytestmark = pytest.mark.integration


def _append(engine: Engine, **event) -> None:
    with session_scope(engine) as session:
        AuditLogService(session).append(**event)
        session.commit()


def _visible(
    engine: Engine, caller: RegisteredUser, **filters
) -> list[tuple[str, int | None, str | None]]:
    """(action, actor id, description) of every row this caller gets for these filters."""
    with session_scope(engine) as session:
        rows = AuditQueryService(db=session).list_logs(
            actor=caller.actor(),
            limit=100,
            offset=0,
            filters=AuditLogQuery.model_validate(filters),
        )
        return [(log.action, log.actor_user_id, log.description) for log, _actor, _target in rows]


def test_filters_narrow_the_callers_page_without_ever_widening_it(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    marker = uuid4().hex[:12]
    owner = register_real_user(auth_mysql_engine, prefix="audit-owner")
    stranger = register_real_user(auth_mysql_engine, prefix="audit-stranger")
    admin = register_real_user(auth_mysql_engine, prefix="audit-admin", role=SystemRole.ADMIN)
    with active_recovery_key(auth_mysql_engine) as recovery:
        owned = upload_file(auth_mysql_engine, tmp_path, owner, recovery)
        upload_file(auth_mysql_engine, tmp_path, stranger, recovery)

    before = utc_now() - timedelta(minutes=1)
    _append(
        auth_mysql_engine,
        action="FILE_SHARED",
        result="SUCCESS",
        actor_user_id=owner.user_id,
        resource_type="SHARE",
        resource_id=str(owned.file_id),
        description=f"share {marker}",
    )
    _append(
        auth_mysql_engine,
        action="AUTH_LOGIN_FAILED",
        result="FAIL",
        actor_user_id=owner.user_id,
        description=f"login {marker} 100% wrong",
    )
    _append(
        auth_mysql_engine,
        action="AUTH_LOGIN_SUCCEEDED",
        result="SUCCESS",
        actor_user_id=stranger.user_id,
        description=f"login {marker}",
    )
    after = utc_now() + timedelta(minutes=1)

    # The stranger searches for the marker that is in the owner's rows too: only their own
    # row comes back, whatever else is stacked on top of the keyword.
    stranger_rows = _visible(auth_mysql_engine, stranger, q=marker)
    assert stranger_rows == [("AUTH_LOGIN_SUCCEEDED", stranger.user_id, f"login {marker}")]
    assert _visible(auth_mysql_engine, stranger, q=marker, result="FAIL") == []
    assert _visible(auth_mysql_engine, stranger, q=marker, action="FILE_SHARED") == []
    windowed = _visible(auth_mysql_engine, stranger, q=marker, **{"from": before, "to": after})
    assert windowed == stranger_rows
    assert _visible(auth_mysql_engine, stranger, q=marker, **{"from": after}) == []

    # The owner, with the same filters, gets exactly their own rows.
    assert {row[0] for row in _visible(auth_mysql_engine, owner, q=marker)} == {
        "FILE_SHARED",
        "AUTH_LOGIN_FAILED",
    }
    assert [row[0] for row in _visible(auth_mysql_engine, owner, q=marker, result="FAIL")] == [
        "AUTH_LOGIN_FAILED"
    ]
    assert [
        row[0] for row in _visible(auth_mysql_engine, owner, q=marker, action="FILE_SHARED")
    ] == ["FILE_SHARED"]

    # An administrator is narrowed by the filter alone and sees everyone's.
    admin_rows = _visible(auth_mysql_engine, admin, q=marker)
    assert {(row[0], row[1]) for row in admin_rows} == {
        ("FILE_SHARED", owner.user_id),
        ("AUTH_LOGIN_FAILED", owner.user_id),
        ("AUTH_LOGIN_SUCCEEDED", stranger.user_id),
    }
    assert [row[1] for row in _visible(auth_mysql_engine, admin, q=marker, result="FAIL")] == [
        owner.user_id
    ]


def test_the_keyword_reaches_the_file_name_but_not_another_persons_file(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    owner = register_real_user(auth_mysql_engine, prefix="audit-name-owner")
    stranger = register_real_user(auth_mysql_engine, prefix="audit-name-stranger")
    with active_recovery_key(auth_mysql_engine) as recovery:
        owned = upload_file(auth_mysql_engine, tmp_path, owner, recovery)
        theirs = upload_file(auth_mysql_engine, tmp_path, stranger, recovery)

    def uploads_named(caller: RegisteredUser) -> set[str]:
        # Every fixture upload is called `fixture.bin`; the name is on `files`, not on the
        # audit row, so a hit here proves the join resolved it.
        with session_scope(auth_mysql_engine) as session:
            rows = AuditQueryService(db=session).list_logs(
                actor=caller.actor(),
                limit=100,
                offset=0,
                filters=AuditLogQuery(q="fixture.bin", action="FILE_UPLOADED"),
            )
            return {log.resource_id for log, _actor, _target in rows if log.resource_id}

    assert str(owned.file_id) in uploads_named(owner)
    assert str(theirs.file_id) in uploads_named(stranger)
    assert str(owned.file_id) not in uploads_named(stranger)
    assert str(theirs.file_id) not in uploads_named(owner)


def test_like_wildcards_in_the_keyword_are_literal_on_mysql(auth_mysql_engine: Engine) -> None:
    marker = uuid4().hex[:12]
    admin = register_real_user(auth_mysql_engine, prefix="audit-like-admin", role=SystemRole.ADMIN)
    _append(
        auth_mysql_engine,
        action="AUTH_LOGIN_FAILED",
        result="FAIL",
        actor_user_id=admin.user_id,
        description=f"{marker} 100% wrong",
    )
    _append(
        auth_mysql_engine,
        action="AUTH_LOGIN_FAILED",
        result="FAIL",
        actor_user_id=admin.user_id,
        description=f"{marker}_tail",
    )

    descriptions = lambda q: {row[2] for row in _visible(auth_mysql_engine, admin, q=q)}  # noqa: E731

    # `%` is literal: it finds the one row that contains a percent sign, not every row.
    assert descriptions(f"{marker} 100%") == {f"{marker} 100% wrong"}
    # `_` is literal: it does not stand in for the space in the other row.
    assert descriptions(f"{marker}_") == {f"{marker}_tail"}
    # The search is case-insensitive, as the file search is (utf8mb4_unicode_ci).
    assert descriptions(f"{marker.upper()}_TAIL") == {f"{marker}_tail"}


def test_an_owned_file_id_that_collides_with_an_account_id_does_not_reveal_that_account(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    # The upload's file id is chosen by the client, so an owner can give a file the same id as
    # another person's account or key. Rows about that account carry the id as their resource
    # id; they are not about the file and must stay off the owner's page.
    marker = uuid4().hex[:12]
    owner = register_real_user(auth_mysql_engine, prefix="audit-collide-owner")
    victim = register_real_user(auth_mysql_engine, prefix="audit-collide-victim")
    with active_recovery_key(auth_mysql_engine) as recovery:
        owned = upload_file(auth_mysql_engine, tmp_path, owner, recovery)
    colliding = str(owned.file_id)

    for action, resource_type in (
        ("AUTH_LOGIN_SUCCEEDED", "USER"),
        ("USER_KEY_ADDED", "AUTH"),
        ("FILE_DOWNLOAD_AUTHORIZED", "FILE"),
        ("FILE_SHARED", "SHARE"),
    ):
        _append(
            auth_mysql_engine,
            action=action,
            result="SUCCESS",
            actor_user_id=victim.user_id,
            resource_type=resource_type,
            resource_id=colliding,
            description=f"collide {marker}",
        )

    seen = {row[0] for row in _visible(auth_mysql_engine, owner, q=marker)}
    assert seen == {"FILE_DOWNLOAD_AUTHORIZED", "FILE_SHARED"}
    assert {row[0] for row in _visible(auth_mysql_engine, victim, q=marker)} == {
        "AUTH_LOGIN_SUCCEEDED",
        "USER_KEY_ADDED",
        "FILE_DOWNLOAD_AUTHORIZED",
        "FILE_SHARED",
    }
