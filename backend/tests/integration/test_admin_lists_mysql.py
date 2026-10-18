"""The admin Users and Files lists filter by status on real MySQL.

Deleted accounts and files stay as tombstones, and on a used platform they outnumber the live
ones, so the admin lists default to CURRENT (everything not deleted). The shared `_test`
database is permanent, so each test looks only for the rows it created.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, update
from tests.integration._concurrency_support import (
    active_recovery_key,
    register_real_user,
    session_scope,
    upload_file,
)

from app.core.time import to_second_resolution_utc, utc_now
from app.domain.enums import SystemRole, UserStatus
from app.models.file import File
from app.models.user import User
from app.services.admin_service import AdminService

pytestmark = pytest.mark.integration


def _usernames(engine: Engine, admin, status: str | None) -> set[str]:
    with session_scope(engine) as session:
        rows = AdminService(db=session).list_users(
            actor=admin.actor(), limit=100, offset=0, status=status
        )
        return {row.username for row in rows}


def test_user_list_filters_by_status_and_current_hides_deleted(auth_mysql_engine: Engine) -> None:
    admin = register_real_user(auth_mysql_engine, prefix="list-admin", role=SystemRole.ADMIN)
    live = register_real_user(auth_mysql_engine, prefix="list-live")
    gone = register_real_user(auth_mysql_engine, prefix="list-gone")
    with session_scope(auth_mysql_engine) as session:
        session.execute(
            update(User).where(User.username == gone.username).values(status=UserStatus.DELETED)
        )
        session.commit()

    current = _usernames(auth_mysql_engine, admin, "CURRENT")
    deleted = _usernames(auth_mysql_engine, admin, "DELETED")
    active = _usernames(auth_mysql_engine, admin, "ACTIVE")

    assert live.username in current and gone.username not in current
    assert gone.username in deleted and live.username not in deleted
    assert live.username in active and gone.username not in active
    assert {live.username, gone.username} <= _usernames(auth_mysql_engine, admin, None)


def test_file_list_filters_by_status(auth_mysql_engine: Engine, tmp_path: Path) -> None:
    admin = register_real_user(auth_mysql_engine, prefix="files-admin", role=SystemRole.ADMIN)
    owner = register_real_user(auth_mysql_engine, prefix="files-owner")
    with active_recovery_key(auth_mysql_engine) as recovery:
        kept = upload_file(auth_mysql_engine, tmp_path, owner, recovery)
        removed = upload_file(auth_mysql_engine, tmp_path, owner, recovery)
    with session_scope(auth_mysql_engine) as session:
        session.execute(
            update(File)
            .where(File.file_uuid == str(removed.file_id))
            .values(status="DELETED", deleted_at=to_second_resolution_utc(utc_now()))
        )
        session.commit()

    def ids(status: str | None) -> set[str]:
        with session_scope(auth_mysql_engine) as session:
            rows = AdminService(db=session).list_files(
                actor=admin.actor(), limit=100, offset=0, status=status
            )
            return {file.file_uuid for file, _owner in rows}

    assert str(kept.file_id) in ids("CURRENT") and str(removed.file_id) not in ids("CURRENT")
    assert str(removed.file_id) in ids("DELETED") and str(kept.file_id) not in ids("DELETED")
    assert str(kept.file_id) in ids("ACTIVE")
