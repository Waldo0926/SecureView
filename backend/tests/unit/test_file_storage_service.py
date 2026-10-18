from __future__ import annotations

import asyncio
from io import BytesIO
from uuid import UUID

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.config import Settings
from app.domain.errors import FileEnvelopeInvalidError, FileTooLargeError
from app.services.file_storage_service import FileStorageService, StorageObjectError

FILE_ID = UUID("11111111-1111-4111-8111-111111111111")
OBJECT_ID = UUID("22222222-2222-4222-8222-222222222222")


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        APP_DEBUG=False,
        SECRET_KEY="test-secret-key-that-is-long-enough",
        TEMP_FILE_DIR=tmp_path / "staging",
        ENCRYPTED_FILE_DIR=tmp_path / "objects",
    )


def _upload(content: bytes, media_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(
        filename="ciphertext.bin",
        file=BytesIO(content),
        headers=Headers({"content-type": media_type}),
    )


def test_storage_stages_hashes_publishes_and_streams_ciphertext(tmp_path) -> None:
    storage = FileStorageService(settings=_settings(tmp_path))
    ciphertext = b"already encrypted bytes"

    staged = asyncio.run(storage.stage_upload(_upload(ciphertext), max_size_bytes=1024))
    object_key = storage.allocate_object_key(FILE_ID, random_id=OBJECT_ID)
    storage.publish(staged, object_key)

    verified = storage.open_verified(object_key)
    assert verified.size_bytes == len(ciphertext)
    assert b"".join(verified.iter_chunks(3)) == ciphertext

    storage.delete_object(object_key)
    storage.delete_object(object_key)


def test_storage_rejects_oversized_or_non_ciphertext_uploads_without_staging_leaks(
    tmp_path,
) -> None:
    storage = FileStorageService(settings=_settings(tmp_path))

    with pytest.raises(FileTooLargeError):
        asyncio.run(storage.stage_upload(_upload(b"too large"), max_size_bytes=3))
    assert list(storage.staging_root.glob("*")) == []

    with pytest.raises(FileEnvelopeInvalidError):
        asyncio.run(storage.stage_upload(_upload(b"ciphertext", "text/plain"), max_size_bytes=99))


def test_storage_rejects_path_traversal_object_keys(tmp_path) -> None:
    storage = FileStorageService(settings=_settings(tmp_path))

    with pytest.raises(StorageObjectError):
        storage.delete_object("../outside")


def test_publish_removes_new_object_when_directory_sync_fails(tmp_path, monkeypatch) -> None:
    storage = FileStorageService(settings=_settings(tmp_path))
    staged = asyncio.run(storage.stage_upload(_upload(b"ciphertext"), max_size_bytes=99))
    object_key = storage.allocate_object_key(FILE_ID, random_id=OBJECT_ID)

    def fail_sync(_path) -> None:
        raise OSError("simulated directory sync failure")

    monkeypatch.setattr(storage, "_sync_directory", fail_sync)

    with pytest.raises(StorageObjectError):
        storage.publish(staged, object_key)

    assert not storage._object_path(object_key).exists()


def _publish(storage: FileStorageService, file_id: UUID, object_id: UUID, body: bytes) -> str:
    staged = asyncio.run(storage.stage_upload(_upload(body), max_size_bytes=1024))
    object_key = storage.allocate_object_key(file_id, random_id=object_id)
    storage.publish(staged, object_key)
    return object_key


def test_deleting_an_object_removes_its_per_file_directory(tmp_path) -> None:
    """`publish` makes one directory per file; nothing used to take it away again.

    Left alone, every file ever uploaded cost the deployment a permanent empty
    directory, and nothing but this call was in a position to remove one.
    """
    storage = FileStorageService(settings=_settings(tmp_path))
    object_key = _publish(storage, FILE_ID, OBJECT_ID, b"ciphertext")
    object_directory = (tmp_path / "objects" / str(FILE_ID)).resolve()
    assert object_directory.is_dir()

    storage.delete_object(object_key)

    assert not object_directory.exists()
    assert (tmp_path / "objects").resolve().is_dir()


def test_deleting_one_object_keeps_a_directory_that_still_holds_another(tmp_path) -> None:
    """rmdir refusing a non-empty directory is the interlock, not an error to handle."""
    storage = FileStorageService(settings=_settings(tmp_path))
    first = _publish(storage, FILE_ID, OBJECT_ID, b"first")
    second = _publish(
        storage,
        FILE_ID,
        UUID("33333333-3333-4333-8333-333333333333"),
        b"second",
    )

    storage.delete_object(first)

    object_directory = (tmp_path / "objects" / str(FILE_ID)).resolve()
    assert object_directory.is_dir()
    assert storage.open_verified(second).size_bytes == len(b"second")


def test_deleting_an_absent_object_still_prunes_and_never_raises(tmp_path) -> None:
    storage = FileStorageService(settings=_settings(tmp_path))
    object_key = _publish(storage, FILE_ID, OBJECT_ID, b"ciphertext")

    storage.delete_object(object_key)
    storage.delete_object(object_key)

    assert not (tmp_path / "objects" / str(FILE_ID)).exists()


def _stored(tmp_path, content: bytes):
    storage = FileStorageService(settings=_settings(tmp_path))
    key = f"{FILE_ID}/{OBJECT_ID}.ciphertext"
    path = storage.object_root / key
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return storage, key, path


def test_replace_object_swaps_the_bytes_and_keeps_the_damaged_copy(tmp_path) -> None:
    storage, key, path = _stored(tmp_path, b"tampered bytes")
    good = tmp_path / "good.bin"
    good.write_bytes(b"the original ciphertext")

    kept = storage.replace_object(key, good, quarantine_dir=tmp_path / "quarantine")

    assert path.read_bytes() == b"the original ciphertext"
    assert kept is not None and kept.read_bytes() == b"tampered bytes"
    assert kept.parent == tmp_path / "quarantine" and kept.stat().st_mode & 0o077 == 0
    assert [p.name for p in path.parent.iterdir()] == [path.name]  # no temporary left behind
    assert (
        storage.hash_object(key)[0] == __import__("hashlib").sha256(good.read_bytes()).hexdigest()
    )


def test_replace_object_puts_back_an_object_that_is_gone(tmp_path) -> None:
    storage, key, path = _stored(tmp_path, b"x")
    path.unlink()
    good = tmp_path / "good.bin"
    good.write_bytes(b"restored")

    assert storage.replace_object(key, good, quarantine_dir=tmp_path / "quarantine") is None
    assert path.read_bytes() == b"restored"


def test_replace_object_leaves_the_old_bytes_when_the_copy_fails(tmp_path) -> None:
    storage, key, path = _stored(tmp_path, b"still here")

    with pytest.raises(StorageObjectError):
        storage.replace_object(key, tmp_path / "does-not-exist.bin")

    assert path.read_bytes() == b"still here"
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_replace_object_refuses_a_key_outside_the_root(tmp_path) -> None:
    storage, _, _ = _stored(tmp_path, b"x")
    good = tmp_path / "good.bin"
    good.write_bytes(b"x")

    with pytest.raises(StorageObjectError):
        storage.replace_object("../escape.ciphertext", good)
