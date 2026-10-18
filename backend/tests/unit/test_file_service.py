from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import (
    ServerStorageLowError,
    StorageQuotaExceededError,
    StorageUnavailableError,
    UploadDailyLimitError,
)
from app.schemas.file_schema import FileUploadMetadata
from app.services.file_service import FileService
from app.services.file_storage_service import StagedCiphertext, StorageObjectError

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
FILE_ID = UUID("11111111-1111-4111-8111-111111111111")
KEY_ID = UUID("22222222-2222-4222-8222-222222222222")
OBJECT_ID = UUID("33333333-3333-4333-8333-333333333333")
RECOVERY_KEY_ID = UUID("66666666-6666-4666-8666-666666666666")


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _metadata(size: int = 5) -> FileUploadMetadata:
    return FileUploadMetadata.model_validate_json(
        json.dumps(
            {
                "file_id": str(FILE_ID),
                "original_filename": "report.pdf",
                "plaintext_size": size,
                "mime_type": "application/pdf",
                "nonce": _b64(b"n" * 12),
                "auth_tag": _b64(b"t" * 16),
                "owner_key_id": str(KEY_ID),
                "wrapped_file_key": _b64(b"w" * 256),
                "recovery_key_id": str(RECOVERY_KEY_ID),
                "recovery_wrapped_file_key": _b64(b"r" * 256),
                "encrypted_manifest": _b64(b"opaque-manifest"),
            }
        )
    )


def _actor() -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=UUID("44444444-4444-4444-8444-444444444444"),
        session_id=8,
        session_public_id=UUID("55555555-5555-4555-8555-555555555555"),
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


class FakeDb:
    def __init__(self, commit_error: Exception | None = None) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = commit_error

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeRepository:
    def __init__(self) -> None:
        self.file = None
        self.grant = None
        self.wrapping = None
        self.wrappings: list[Any] = []
        self.user_key = SimpleNamespace(
            id=19,
            key_uuid=str(KEY_ID),
            algorithm="RSA-OAEP-SHA256",
            key_size_bits=2048,
        )
        self.recovery_key = SimpleNamespace(
            id=20,
            key_uuid=str(RECOVERY_KEY_ID),
            algorithm="RSA-OAEP-SHA256",
            key_size_bits=2048,
        )

    def get_active_user_key(self, user_id: int, key_id: UUID):
        assert user_id == 7 and key_id == KEY_ID
        return self.user_key

    def file_uuid_exists(self, file_id: UUID) -> bool:
        return False

    stored_bytes = 0
    uploaded_recently = 0
    uploaded_since: datetime | None = None

    def stored_bytes_for_owner(self, owner_id: int) -> int:
        assert owner_id == 7
        return self.stored_bytes

    def uploaded_bytes_since(self, owner_id: int, since: datetime) -> int:
        assert owner_id == 7
        self.uploaded_since = since
        return self.uploaded_recently

    released = False

    def release_connection(self) -> None:
        self.released = True

    def get_active_recovery_key(self, key_id: UUID):
        assert key_id == RECOVERY_KEY_ID
        return self.recovery_key

    def add_file(self, value) -> None:
        self.file = value

    def add_grant(self, value) -> None:
        self.grant = value

    def add_wrapping(self, value) -> None:
        self.wrappings.append(value)
        if value.recipient_type == "USER":
            self.wrapping = value

    def flush(self) -> None:
        self.file.id = 91


class FakeStorage:
    def __init__(self) -> None:
        self.published: list[tuple[Any, str]] = []
        self.discarded: list[Any] = []
        self.deleted: list[str] = []

    repository: FakeRepository | None = None

    async def stage_upload(self, upload, *, max_size_bytes: int) -> StagedCiphertext:
        assert max_size_bytes == 100
        if self.repository is not None:
            # Staging waits on the thread pool; the DB connection must already be released.
            assert self.repository.released
        return StagedCiphertext(token=OBJECT_ID, size_bytes=5, sha256="d" * 64)

    def allocate_object_key(self, file_id: UUID, *, random_id: UUID) -> str:
        return f"{file_id}/{random_id}.ciphertext"

    def publish(self, staged: StagedCiphertext, object_key: str) -> None:
        self.published.append((staged, object_key))

    def discard_staged(self, staged: StagedCiphertext | None) -> None:
        self.discarded.append(staged)

    def delete_object(self, object_key: str) -> None:
        self.deleted.append(object_key)

    free = 10**12

    def free_bytes(self) -> int:
        return self.free


class UnavailableStorage(FakeStorage):
    async def stage_upload(self, upload, *, max_size_bytes: int) -> StagedCiphertext:
        raise StorageObjectError("internal path details must not escape")


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(self, **event: Any) -> None:
        self.events.append(event)


def _service(
    db: FakeDb,
    repository: FakeRepository,
    storage: FakeStorage,
    audit: FakeAudit,
    *,
    quota: int = 0,
    daily: int = 0,
    min_free: int = 0,
):
    return FileService(
        db=db,
        settings=SimpleNamespace(
            MAX_UPLOAD_SIZE_BYTES=100,
            USER_STORAGE_QUOTA_BYTES=quota,
            USER_DAILY_UPLOAD_BYTES=daily,
            UPLOAD_MIN_FREE_DISK_BYTES=min_free,
        ),
        storage=storage,
        audit_service=audit,
        repository=repository,
        clock=lambda: NOW,
        uuid_factory=lambda: OBJECT_ID,
    )


def _upload() -> UploadFile:
    return UploadFile(
        filename="ciphertext.bin",
        file=BytesIO(b"abcde"),
        headers=Headers({"content-type": "application/octet-stream"}),
    )


def test_upload_persists_only_ciphertext_envelope_and_owner_access() -> None:
    db, repository, storage, audit = FakeDb(), FakeRepository(), FakeStorage(), FakeAudit()

    result = asyncio.run(
        _service(db, repository, storage, audit).upload(
            actor=_actor(),
            metadata=_metadata(),
            ciphertext=_upload(),
            context=RequestContext(ip_address="203.0.113.1", user_agent="test"),
        )
    )

    assert db.commits == 1
    assert repository.file.encrypted_sha256 == "d" * 64
    assert repository.file.encrypted_manifest == b"opaque-manifest"
    assert repository.grant.can_manage is True
    assert repository.wrapping.wrapped_file_key == b"w" * 256
    assert repository.wrappings[1].recipient_type == "RECOVERY"
    assert repository.wrappings[1].wrapped_file_key == b"r" * 256
    assert result.crypto_envelope.key_id == KEY_ID
    assert result.crypto_envelope.wrapped_file_key == _b64(b"w" * 256)
    assert audit.events[0]["action"] == "FILE_UPLOADED"
    assert storage.published


def _attempt(service: FileService) -> None:
    asyncio.run(
        service.upload(
            actor=_actor(), metadata=_metadata(), ciphertext=_upload(), context=RequestContext()
        )
    )


def test_upload_releases_its_db_connection_before_waiting_to_stage_the_file() -> None:
    db, repository, storage, audit = FakeDb(), FakeRepository(), FakeStorage(), FakeAudit()
    storage.repository = repository

    _attempt(_service(db, repository, storage, audit))

    assert repository.released and db.commits == 1


def test_upload_over_the_storage_quota_is_refused_before_anything_is_stored() -> None:
    db, repository, storage, audit = FakeDb(), FakeRepository(), FakeStorage(), FakeAudit()
    repository.stored_bytes = 96  # 96 + the 5-byte file > 100

    with pytest.raises(StorageQuotaExceededError) as caught:
        _attempt(_service(db, repository, storage, audit, quota=100))

    assert caught.value.details == {"used_bytes": 96, "quota_bytes": 100}
    assert storage.published == [] and db.commits == 0 and audit.events == []


def test_upload_exactly_filling_the_quota_is_allowed() -> None:
    db, repository, storage, audit = FakeDb(), FakeRepository(), FakeStorage(), FakeAudit()
    repository.stored_bytes = 95

    _attempt(_service(db, repository, storage, audit, quota=100))

    assert db.commits == 1


def test_upload_over_the_daily_limit_counts_the_last_24_hours() -> None:
    db, repository, storage, audit = FakeDb(), FakeRepository(), FakeStorage(), FakeAudit()
    repository.uploaded_recently = 98

    with pytest.raises(UploadDailyLimitError):
        _attempt(_service(db, repository, storage, audit, daily=100))

    # Naive UTC, like the DATETIME column it is compared with.
    assert repository.uploaded_since == datetime(2026, 8, 11, 12, 0)
    assert storage.published == []


def test_upload_is_refused_when_it_would_leave_the_disk_below_its_floor() -> None:
    db, repository, storage, audit = FakeDb(), FakeRepository(), FakeStorage(), FakeAudit()
    storage.free = 1_004  # 1,004 - 5 < 1,000

    with pytest.raises(ServerStorageLowError):
        _attempt(_service(db, repository, storage, audit, min_free=1_000))

    assert storage.published == []


def test_upload_preserves_published_object_when_database_commit_outcome_is_ambiguous() -> None:
    failure = RuntimeError("database unavailable")
    db, repository, storage, audit = (
        FakeDb(commit_error=failure),
        FakeRepository(),
        FakeStorage(),
        FakeAudit(),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(
            _service(db, repository, storage, audit).upload(
                actor=_actor(),
                metadata=_metadata(),
                ciphertext=_upload(),
                context=RequestContext(),
            )
        )

    assert db.rollbacks == 1
    assert storage.published
    assert storage.deleted == []


def test_upload_compensates_published_object_when_failure_precedes_commit() -> None:
    db, repository, storage, audit = FakeDb(), FakeRepository(), FakeStorage(), FakeAudit()
    repository.user_key.key_uuid = None

    with pytest.raises(RuntimeError, match="missing its public key identifier"):
        asyncio.run(
            _service(db, repository, storage, audit).upload(
                actor=_actor(),
                metadata=_metadata(),
                ciphertext=_upload(),
                context=RequestContext(),
            )
        )

    assert db.commits == 0
    assert db.rollbacks == 1
    assert storage.deleted == [f"{FILE_ID}/{OBJECT_ID}.ciphertext"]


def test_upload_translates_internal_storage_failure_to_public_domain_error() -> None:
    db, repository, storage, audit = (
        FakeDb(),
        FakeRepository(),
        UnavailableStorage(),
        FakeAudit(),
    )

    with pytest.raises(StorageUnavailableError) as raised:
        asyncio.run(
            _service(db, repository, storage, audit).upload(
                actor=_actor(),
                metadata=_metadata(),
                ciphertext=_upload(),
                context=RequestContext(),
            )
        )

    assert "path details" not in raised.value.message
    assert db.rollbacks == 1


def test_summary_carries_the_recorded_ciphertext_digest() -> None:
    """The list and detail views show the stored object's SHA-256 exactly as recorded at upload."""
    now = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    file_record = SimpleNamespace(
        file_uuid="11111111-1111-4111-8111-111111111111",
        original_filename="notes.txt",
        file_size_bytes=5,
        encrypted_size_bytes=5,
        encrypted_sha256="ab" * 32,
        mime_type="text/plain",
        encryption_algorithm="AES-256-GCM",
        status="ACTIVE",
        owner_id=7,
        owner=SimpleNamespace(username="alice"),
        folder=None,
        created_at=now,
        updated_at=now,
    )
    record = SimpleNamespace(file=file_record, grant=SimpleNamespace(folder=None))

    summary = FileService._summary(object.__new__(FileService), record, actor_user_id=7)

    assert summary.ciphertext_sha256 == "ab" * 32
    assert summary.model_dump(mode="json")["ciphertext_sha256"] == "ab" * 32
