"""Recipients file shared files into their own folders, on real MySQL (revision 0010).

The owner's placement lives in files.folder_id and a recipient's on their own grant, so the two
never see or move each other's choice. The shared `_test` database is permanent, so these tests
only look at their own accounts and files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine
from tests.integration._concurrency_support import (
    RegisteredUser,
    UploadedFile,
    active_recovery_key,
    file_service,
    register_real_user,
    request_context,
    rsa_wrap,
    session_scope,
    upload_file,
)

from app.domain.errors import FileFolderNotFoundError, FileResourceNotFoundError
from app.services.sharing_service import SharingService

pytestmark = pytest.mark.integration


def _share(engine: Engine, owner: RegisteredUser, uploaded: UploadedFile, target: RegisteredUser):
    with session_scope(engine) as session:
        SharingService(db=session).share(
            actor=owner.actor(),
            file_id=uploaded.file_id,
            target_user_id=target.user_uuid,
            target_key_id=target.key_id,
            wrapped_file_key=rsa_wrap(target.public_key_pem, uploaded.dek),
            can_download=True,
            can_share=False,
            context=request_context(),
        )


def _setup(engine: Engine, tmp_path: Path):
    owner = register_real_user(engine, prefix="sf-owner")
    recipient = register_real_user(engine, prefix="sf-recipient")
    with active_recovery_key(engine) as recovery:
        shared = upload_file(engine, tmp_path, owner, recovery)
        mine = upload_file(engine, tmp_path, recipient, recovery)
    _share(engine, owner, shared, recipient)
    return owner, recipient, shared, mine


def test_a_recipient_files_a_shared_file_in_their_own_folder(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    owner, recipient, shared, mine = _setup(auth_mysql_engine, tmp_path)

    with session_scope(auth_mysql_engine) as session:
        service = file_service(session, tmp_path)
        folder = service.create_folder(actor=recipient.actor(), name="From colleagues")
        service.move_file(
            actor=recipient.actor(), file_id=shared.file_id, folder_id=folder.folder_id
        )

    with session_scope(auth_mysql_engine) as session:
        service = file_service(session, tmp_path)
        listed = service.list_files(
            actor=recipient.actor(), page=1, page_size=50, folder_id=folder.folder_id
        )
        assert [item.file_id for item in listed.items] == [shared.file_id]
        assert listed.items[0].owner is False and listed.items[0].folder_id == folder.folder_id
        (counted,) = [f for f in service.list_folders(actor=recipient.actor()).items]
        assert (counted.file_count, counted.owned_file_count, counted.shared_file_count) == (
            1,
            0,
            1,
        )

        # The owner's own view of the file is unaffected.
        owner_view = service.list_files(actor=owner.actor(), page=1, page_size=50, scope="mine")
        assert [i.folder_id for i in owner_view.items if i.file_id == shared.file_id] == [None]

        # "No folder" for the recipient now holds only their own file.
        unfiled = service.list_files(actor=recipient.actor(), page=1, page_size=50, unfiled=True)
        assert [item.file_id for item in unfiled.items] == [mine.file_id]


def test_scope_splits_the_list_on_the_server_and_reports_both_totals(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    _, recipient, shared, mine = _setup(auth_mysql_engine, tmp_path)

    with session_scope(auth_mysql_engine) as session:
        service = file_service(session, tmp_path)
        everything = service.list_files(actor=recipient.actor(), page=1, page_size=50)
        only_shared = service.list_files(
            actor=recipient.actor(), page=1, page_size=50, scope="shared"
        )
        only_mine = service.list_files(actor=recipient.actor(), page=1, page_size=50, scope="mine")

    assert (everything.total, everything.owned_total, everything.shared_total) == (2, 1, 1)
    assert [i.file_id for i in only_shared.items] == [shared.file_id] and only_shared.total == 1
    assert [i.file_id for i in only_mine.items] == [mine.file_id] and only_mine.total == 1
    assert only_shared.owned_total == 1 and only_shared.shared_total == 1


def test_deleting_the_folder_unfiles_shared_files_too(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    _, recipient, shared, _ = _setup(auth_mysql_engine, tmp_path)

    with session_scope(auth_mysql_engine) as session:
        service = file_service(session, tmp_path)
        folder = service.create_folder(actor=recipient.actor(), name="Temporary")
        service.move_file(
            actor=recipient.actor(), file_id=shared.file_id, folder_id=folder.folder_id
        )
    with session_scope(auth_mysql_engine) as session:
        result = file_service(session, tmp_path).delete_folder(
            actor=recipient.actor(), folder_id=folder.folder_id
        )
    assert result.files_unfiled == 1

    with session_scope(auth_mysql_engine) as session:
        listed = file_service(session, tmp_path).list_files(
            actor=recipient.actor(), page=1, page_size=50, scope="shared"
        )
    assert [i.folder_id for i in listed.items] == [None]


def test_nobody_can_file_into_someone_elses_folder_or_a_file_they_cannot_open(
    auth_mysql_engine: Engine, tmp_path: Path
) -> None:
    owner, recipient, shared, _ = _setup(auth_mysql_engine, tmp_path)
    stranger = register_real_user(auth_mysql_engine, prefix="sf-stranger")

    with session_scope(auth_mysql_engine) as session:
        owners_folder = file_service(session, tmp_path).create_folder(
            actor=owner.actor(), name="Owner only"
        )
    with session_scope(auth_mysql_engine) as session, pytest.raises(FileFolderNotFoundError):
        file_service(session, tmp_path).move_file(
            actor=recipient.actor(), file_id=shared.file_id, folder_id=owners_folder.folder_id
        )
    with session_scope(auth_mysql_engine) as session, pytest.raises(FileResourceNotFoundError):
        file_service(session, tmp_path).move_file(
            actor=stranger.actor(), file_id=shared.file_id, folder_id=None
        )
