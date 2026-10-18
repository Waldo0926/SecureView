from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.domain.errors import AvatarInvalidError, AvatarTooLargeError

_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_OBJECT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class StoredAvatar:
    object_key: str
    content_type: str
    sha256: str
    size_bytes: int


class AvatarStorageService:
    """Local plaintext avatar objects, deliberately outside the ciphertext root."""

    CHUNK_SIZE = 64 * 1024

    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.AVATAR_DIR.resolve(strict=False)
        self.max_bytes = settings.AVATAR_MAX_BYTES

    async def store(self, upload: UploadFile, *, user_uuid: UUID) -> StoredAvatar:
        header = await upload.read(16)
        if not header:
            raise AvatarInvalidError()
        content_type = self._sniff(header)
        token = uuid4()
        object_key = f"{user_uuid}/{token}"
        path = self._resolved(object_key)
        digest = hashlib.sha256()
        digest.update(header)
        total = len(header)

        await run_in_threadpool(self.root.mkdir, parents=True, exist_ok=True)
        await run_in_threadpool(path.parent.mkdir, parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        stream = await run_in_threadpool(tmp.open, "wb")
        try:
            await run_in_threadpool(stream.write, header)
            while True:
                chunk = await upload.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_bytes:
                    raise AvatarTooLargeError()
                digest.update(chunk)
                await run_in_threadpool(stream.write, chunk)
            await run_in_threadpool(stream.flush)
        except Exception:
            await run_in_threadpool(stream.close)
            await run_in_threadpool(tmp.unlink, missing_ok=True)
            raise
        else:
            await run_in_threadpool(stream.close)

        await run_in_threadpool(tmp.replace, path)
        return StoredAvatar(
            object_key=object_key,
            content_type=content_type,
            sha256=digest.hexdigest(),
            size_bytes=total,
        )

    async def read(self, object_key: str | None) -> bytes:
        if not object_key:
            raise FileNotFoundError("avatar missing")
        path = self._resolved(object_key)
        return await run_in_threadpool(path.read_bytes)

    async def delete(self, object_key: str | None) -> None:
        if not object_key:
            return
        path = self._resolved(object_key)
        await run_in_threadpool(path.unlink, missing_ok=True)

    def delete_sync(self, object_key: str | None) -> None:
        if not object_key:
            return
        self._resolved(object_key).unlink(missing_ok=True)

    def _resolved(self, object_key: str) -> Path:
        parts = tuple(part for part in object_key.replace("\\", "/").split("/") if part)
        if len(parts) != 2 or any(not _OBJECT_SEGMENT_RE.match(part) for part in parts):
            raise ValueError("Invalid avatar object key")
        candidate = (self.root.joinpath(*parts)).resolve(strict=False)
        if self.root not in candidate.parents and candidate != self.root:
            raise ValueError("Avatar path escapes storage root")
        return candidate

    @staticmethod
    def _sniff(header: bytes) -> str:
        if header.startswith(_PNG):
            return "image/png"
        if header.startswith(_JPEG):
            return "image/jpeg"
        raise AvatarInvalidError()
