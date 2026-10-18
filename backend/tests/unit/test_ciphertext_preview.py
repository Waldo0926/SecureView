"""The bounded ciphertext preview: what it returns, what it refuses, and what it records."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.config import Settings
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import FileCapability, SystemRole, UserStatus
from app.domain.errors import StorageUnavailableError
from app.repositories.file_repository import FileAccessRecord
from app.services.file_service import CIPHERTEXT_PREVIEW_BYTES, FileService
from app.services.file_storage_service import (
    FileStorageService,
    StorageObjectError,
    StorageObjectMissingError,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
FILE_ID = UUID("11111111-1111-4111-8111-111111111111")
DIGEST = "d" * 64


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeAudit:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[dict] = []
        self.fail = fail

    def append(self, **event) -> None:
        if self.fail:
            raise RuntimeError("audit store down")
        self.events.append(event)


class FakeAccess:
    def __init__(self, *, deny: Exception | None = None) -> None:
        self.deny = deny
        self.requested: list[FileCapability] = []

    def require(self, *, user_id: int, file_id: UUID, capability: FileCapability):
        self.requested.append(capability)
        if self.deny is not None:
            raise self.deny
        return _record()


class FakeStorage:
    def __init__(self, content: bytes = b"", *, failure: Exception | None = None) -> None:
        self.content = content
        self.failure = failure
        self.reads: list[tuple[str, int]] = []

    def read_head(self, object_key: str, limit: int) -> bytes:
        self.reads.append((object_key, limit))
        if self.failure is not None:
            raise self.failure
        return self.content[:limit]


def _actor() -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=UUID("22222222-2222-4222-8222-222222222222"),
        session_id=8,
        session_public_id=UUID("33333333-3333-4333-8333-333333333333"),
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


def _record() -> FileAccessRecord:
    return FileAccessRecord(
        file=SimpleNamespace(
            id=91,
            file_uuid=str(FILE_ID),
            storage_object_key="opaque/object.ciphertext",
            encryption_algorithm="AES-256-GCM",
            file_size_bytes=4096,
            encrypted_size_bytes=4096,
            encrypted_sha256=DIGEST,
            status="ACTIVE",
        ),
        grant=SimpleNamespace(),
        wrapping=SimpleNamespace(),
        user_key=SimpleNamespace(),
    )


def _service(storage, *, audit=None, access=None, db=None) -> FileService:
    return FileService(
        db=db or FakeDb(),
        settings=SimpleNamespace(),
        storage=storage,
        audit_service=audit or FakeAudit(),
        repository=SimpleNamespace(),
        access_control=access or FakeAccess(),
        integrity_service=SimpleNamespace(),
        clock=lambda: NOW,
    )


def _preview(service: FileService):
    return service.ciphertext_preview(actor=_actor(), file_id=FILE_ID, context=RequestContext())


def test_preview_returns_the_first_bytes_as_hex_with_the_metadata_the_caller_already_has() -> None:
    content = bytes(range(256)) * 4
    result = _preview(_service(FakeStorage(content)))

    assert result.sample_offset == 0
    assert result.sample_length == CIPHERTEXT_PREVIEW_BYTES == 128
    assert bytes.fromhex(result.sample_hex) == content[:128]
    assert result.ciphertext_sha256 == DIGEST
    assert result.encryption_algorithm == "AES-256-GCM"
    # AES-GCM and ChaCha20-Poly1305 are length-preserving: the tag is stored separately.
    assert result.plaintext_size == result.ciphertext_size == 4096
    assert result.status == "ACTIVE"


def test_preview_is_bounded_by_the_server_whatever_the_object_size() -> None:
    storage = FakeStorage(b"\xaa" * 10_000_000)

    result = _preview(_service(storage))

    assert storage.reads == [("opaque/object.ciphertext", CIPHERTEXT_PREVIEW_BYTES)]
    assert result.sample_length == 128 and len(result.sample_hex) == 256


def test_preview_of_a_short_object_returns_what_exists() -> None:
    result = _preview(_service(FakeStorage(b"\x01\x02\x03")))

    assert result.sample_length == 3
    assert result.sample_hex == "010203"


def test_preview_needs_the_download_capability_and_reads_nothing_without_it() -> None:
    denial = RuntimeError("not allowed")
    storage = FakeStorage(b"secret-looking bytes")
    access = FakeAccess(deny=denial)
    audit = FakeAudit()

    with pytest.raises(RuntimeError, match="not allowed"):
        _preview(_service(storage, audit=audit, access=access))

    assert access.requested == [FileCapability.DOWNLOAD]
    assert storage.reads == []
    assert audit.events == []


def test_preview_is_audited_under_its_own_action_and_never_as_a_download() -> None:
    audit = FakeAudit()
    db = FakeDb()

    _preview(_service(FakeStorage(b"\x00" * 64), audit=audit, db=db))

    assert db.commits == 1 and db.rollbacks == 0
    assert len(audit.events) == 1
    event = audit.events[0]
    assert event["action"] == "FILE_CIPHERTEXT_PREVIEWED"
    assert "DOWNLOAD" not in event["action"]
    assert event["result"] == "SUCCESS"
    assert event["resource_id"] == str(FILE_ID)
    assert event["actor_user_id"] == 7
    assert event["metadata"] == {"sample_length": 64}
    # The sample itself never goes into the audit trail.
    assert "00" * 8 not in str(event)


@pytest.mark.parametrize(
    "failure", [StorageObjectError("host path must stay private"), StorageObjectMissingError("x")]
)
def test_unreadable_storage_gives_the_stable_public_error_and_records_nothing(
    failure: Exception,
) -> None:
    audit = FakeAudit()
    db = FakeDb()

    with pytest.raises(StorageUnavailableError):
        _preview(_service(FakeStorage(failure=failure), audit=audit, db=db))

    assert audit.events == [] and db.commits == 0


def test_a_failing_audit_write_rolls_back_and_does_not_hand_out_the_sample() -> None:
    db = FakeDb()

    with pytest.raises(RuntimeError, match="audit store down"):
        _preview(_service(FakeStorage(b"\x00" * 16), audit=FakeAudit(fail=True), db=db))

    assert db.rollbacks == 1 and db.commits == 0


# --- the storage primitive --------------------------------------------------------------


def _storage(tmp_path) -> FileStorageService:
    return FileStorageService(
        settings=Settings(
            _env_file=None,
            APP_ENV="test",
            APP_DEBUG=False,
            SECRET_KEY="test-secret-key-that-is-long-enough",
            TEMP_FILE_DIR=tmp_path / "staging",
            ENCRYPTED_FILE_DIR=tmp_path / "objects",
        )
    )


def _put(storage: FileStorageService, key: str, content: bytes) -> None:
    path = storage._object_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_read_head_returns_only_the_leading_bytes(tmp_path) -> None:
    storage = _storage(tmp_path)
    _put(storage, "file-a/object.ciphertext", bytes(range(200)))

    assert storage.read_head("file-a/object.ciphertext", 16) == bytes(range(16))
    assert storage.read_head("file-a/object.ciphertext", 1000) == bytes(range(200))


def test_read_head_reports_a_missing_object_and_refuses_bad_input(tmp_path) -> None:
    storage = _storage(tmp_path)

    with pytest.raises(StorageObjectMissingError):
        storage.read_head("file-a/absent.ciphertext", 16)
    with pytest.raises(StorageObjectError):
        storage.read_head("../escape.ciphertext", 16)
    with pytest.raises(ValueError):
        storage.read_head("file-a/object.ciphertext", 0)
