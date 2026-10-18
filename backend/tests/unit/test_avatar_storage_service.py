from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import UploadFile

from app.core.config import Settings
from app.domain.errors import AvatarInvalidError, AvatarTooLargeError
from app.services.avatar_storage_service import AvatarStorageService

# Minimal valid PNG / JPEG magic for sniffing.
_MINI_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
_MINI_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        APP_DEBUG=False,
        SECRET_KEY="test-secret-key-that-is-long-enough",
        AVATAR_DIR=tmp_path / "avatars",
        AVATAR_MAX_BYTES=64,
        AVATAR_MIN_INTERVAL_SECONDS=0,
    )


def test_store_accepts_png_and_isolates_under_user(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage = AvatarStorageService(settings=settings)
    user_uuid = uuid4()
    upload = UploadFile(filename="a.png", file=BytesIO(_MINI_PNG))

    stored = asyncio.run(storage.store(upload, user_uuid=user_uuid))

    assert stored.content_type == "image/png"
    assert stored.size_bytes == len(_MINI_PNG)
    assert stored.object_key.startswith(f"{user_uuid}/")
    body = asyncio.run(storage.read(stored.object_key))
    assert body == _MINI_PNG


def test_store_rejects_non_image(tmp_path: Path) -> None:
    storage = AvatarStorageService(settings=_settings(tmp_path))
    upload = UploadFile(filename="x.bin", file=BytesIO(b"not-an-image"))
    with pytest.raises(AvatarInvalidError):
        asyncio.run(storage.store(upload, user_uuid=uuid4()))


def test_store_rejects_oversized(tmp_path: Path) -> None:
    storage = AvatarStorageService(settings=_settings(tmp_path))
    upload = UploadFile(filename="big.jpg", file=BytesIO(_MINI_JPEG + b"x" * 100))
    with pytest.raises(AvatarTooLargeError):
        asyncio.run(storage.store(upload, user_uuid=uuid4()))


def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = AvatarStorageService(settings=_settings(tmp_path))
    user_uuid = uuid4()
    upload = UploadFile(filename="a.png", file=BytesIO(_MINI_PNG))
    stored = asyncio.run(storage.store(upload, user_uuid=user_uuid))
    asyncio.run(storage.delete(stored.object_key))
    asyncio.run(storage.delete(stored.object_key))
    with pytest.raises(FileNotFoundError):
        asyncio.run(storage.read(stored.object_key))
