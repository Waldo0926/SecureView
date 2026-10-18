from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.domain.errors import ConflictError, FileEnvelopeInvalidError, FileTooLargeError

_OBJECT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class StorageObjectMissingError(FileNotFoundError):
    """Internal signal that never includes the resolved host path in its message."""


class StorageObjectError(OSError):
    """Internal storage failure whose message is safe from host-path disclosure."""


@dataclass(frozen=True, slots=True)
class StagedCiphertext:
    token: UUID
    size_bytes: int
    sha256: str


@dataclass(slots=True)
class VerifiedCiphertext:
    stream: BinaryIO
    size_bytes: int
    sha256: str

    def iter_chunks(self, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        try:
            while chunk := self.stream.read(chunk_size):
                yield chunk
        finally:
            self.stream.close()


class FileStorageService:
    """Bounded local-object storage using opaque keys and atomic publication."""

    CHUNK_SIZE = 1024 * 1024
    CIPHERTEXT_MEDIA_TYPES = frozenset(
        {
            "application/octet-stream",
            "application/x-encrypted",
        }
    )

    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings
        self.staging_root = settings.TEMP_FILE_DIR.resolve(strict=False)
        self.object_root = settings.ENCRYPTED_FILE_DIR.resolve(strict=False)

    def free_bytes(self) -> int:
        """Free space on the filesystem that holds the ciphertext objects."""
        path = self.object_root
        while not path.exists() and path != path.parent:
            path = path.parent
        return shutil.disk_usage(path).free

    @staticmethod
    def allocate_object_key(file_id: UUID, *, random_id: UUID | None = None) -> str:
        suffix = random_id or uuid4()
        return f"{file_id}/{suffix}.ciphertext"

    async def stage_upload(
        self,
        upload: UploadFile,
        *,
        max_size_bytes: int,
    ) -> StagedCiphertext:
        if upload.content_type not in self.CIPHERTEXT_MEDIA_TYPES:
            raise FileEnvelopeInvalidError(
                "The file part must contain application/octet-stream ciphertext"
            )
        if max_size_bytes <= 0:  # pragma: no cover - settings invariant
            raise RuntimeError("MAX_UPLOAD_SIZE_BYTES must be positive")
        if upload.size is not None and upload.size > max_size_bytes:
            raise FileTooLargeError()

        try:
            await run_in_threadpool(self._ensure_roots)
        except OSError as exc:
            if isinstance(exc, StorageObjectError):
                raise
            raise StorageObjectError("Unable to prepare encrypted storage") from exc
        token = uuid4()
        staged_path = self._staged_path(token)
        stream = await run_in_threadpool(self._open_staged_exclusive, staged_path)
        digest = hashlib.sha256()
        total = 0
        try:
            while True:
                chunk = await upload.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size_bytes:
                    raise FileTooLargeError()
                digest.update(chunk)
                await run_in_threadpool(stream.write, chunk)
            await run_in_threadpool(self._flush_and_sync, stream)
        except Exception:
            await run_in_threadpool(stream.close)
            await run_in_threadpool(self._unlink_if_present, staged_path)
            raise
        else:
            await run_in_threadpool(stream.close)

        return StagedCiphertext(token=token, size_bytes=total, sha256=digest.hexdigest())

    def publish(self, staged: StagedCiphertext, object_key: str) -> None:
        try:
            self._ensure_roots()
            source = self._staged_path(staged.token)
            destination = self._object_path(object_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            if isinstance(exc, StorageObjectError):
                raise
            raise StorageObjectError("Unable to prepare encrypted storage") from exc
        linked = False
        try:
            # A hard-link publish is atomic and fails if the opaque destination already
            # exists, avoiding os.replace's overwrite race. Staging and object roots are
            # deliberately required to share a filesystem.
            os.link(source, destination)
            linked = True
            source.unlink()
        except FileExistsError as exc:
            raise ConflictError("The encrypted storage object already exists") from exc
        except OSError as exc:
            if linked:
                with suppress(OSError):
                    destination.unlink()
            if exc.errno == errno.EXDEV:
                raise StorageObjectError(
                    "Staging and encrypted-object directories must share a filesystem"
                ) from exc
            raise StorageObjectError("Unable to publish the encrypted storage object") from exc
        try:
            self._sync_directory(destination.parent)
        except OSError as exc:
            # Publication is not considered successful until the directory entry is
            # durable. Remove the link here while we still know it was created by this
            # call; the outer transaction can then safely discard the staged object.
            with suppress(OSError):
                destination.unlink()
            raise StorageObjectError("Unable to synchronize encrypted storage") from exc

    def discard_staged(self, staged: StagedCiphertext | None) -> None:
        if staged is not None:
            self._unlink_if_present(self._staged_path(staged.token))

    def delete_object(self, object_key: str) -> None:
        path = self._object_path(object_key)
        self._unlink_if_present(path)
        self._prune_empty_parent(path)

    def replace_object(
        self,
        object_key: str,
        source: Path,
        *,
        quarantine_dir: Path | None = None,
    ) -> Path | None:
        """Atomically put the bytes of `source` at an existing object key (file restore only).

        Objects are write-once, so this is not part of any request path: the one caller is
        `scripts/restore_file.py`, putting back a copy from an encrypted backup that was
        verified against the recorded SHA-256. The new bytes are written beside the object,
        flushed, and renamed over it, so a reader sees the old object or the new one, never
        a mixture. If the old object is still there and `quarantine_dir` is given, its bytes
        are copied there first: a tampered object is evidence, and replacing it must not
        destroy the only copy. Returns where the old bytes were kept, or None.
        """
        destination = self._object_path(object_key)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            kept: Path | None = None
            if quarantine_dir is not None and destination.is_file():
                quarantine_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                kept = quarantine_dir / f"{destination.parent.name}-{uuid4().hex}.damaged"
                shutil.copyfile(destination, kept)
                os.chmod(kept, 0o600)
            temporary = destination.with_name(f".{destination.name}.restore-{uuid4().hex}")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as out, source.open("rb") as incoming:
                    shutil.copyfileobj(incoming, out, self.CHUNK_SIZE)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, destination)
            except BaseException:
                with suppress(OSError):
                    temporary.unlink()
                raise
            self._sync_directory(destination.parent)
        except OSError as exc:
            raise StorageObjectError("Unable to replace the encrypted storage object") from exc
        return kept

    def hash_object(self, object_key: str) -> tuple[str, int]:
        verified = self.open_verified(object_key)
        try:
            return verified.sha256, verified.size_bytes
        finally:
            verified.stream.close()

    def read_head(self, object_key: str, limit: int) -> bytes:
        """Return at most `limit` leading bytes of a stored object, without hashing it.

        Only for the bounded ciphertext preview: reading a few bytes must not cost a full
        pass over a 500 MiB object, so nothing here is verified. The caller must say so.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        path = self._object_path(object_key)
        try:
            with path.open("rb") as stream:
                return stream.read(limit)
        except FileNotFoundError as exc:
            raise StorageObjectMissingError("Encrypted storage object is missing") from exc
        except OSError as exc:
            raise StorageObjectError("Unable to read the encrypted storage object") from exc

    def open_verified(self, object_key: str) -> VerifiedCiphertext:
        path = self._object_path(object_key)
        try:
            stream = path.open("rb")
        except FileNotFoundError as exc:
            raise StorageObjectMissingError("Encrypted storage object is missing") from exc
        except OSError as exc:
            raise StorageObjectError("Unable to open the encrypted storage object") from exc

        digest = hashlib.sha256()
        size = 0
        try:
            while chunk := stream.read(self.CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
            stream.seek(0)
        except OSError as exc:
            stream.close()
            raise StorageObjectError("Unable to verify the encrypted storage object") from exc
        return VerifiedCiphertext(stream=stream, size_bytes=size, sha256=digest.hexdigest())

    def _ensure_roots(self) -> None:
        try:
            self.staging_root.mkdir(parents=True, exist_ok=True)
            self.object_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageObjectError("Unable to prepare encrypted storage roots") from exc
        if not self.staging_root.is_dir() or not self.object_root.is_dir():
            raise StorageObjectError("Configured encrypted storage roots are not directories")

    def _staged_path(self, token: UUID) -> Path:
        path = (self.staging_root / f".{token}.staging").resolve(strict=False)
        self._require_within(path, self.staging_root)
        return path

    def _object_path(self, object_key: str) -> Path:
        key = PurePosixPath(object_key)
        if (
            key.is_absolute()
            or not key.parts
            or any(
                segment in {"", ".", ".."} or not _OBJECT_SEGMENT_RE.fullmatch(segment)
                for segment in key.parts
            )
        ):
            raise StorageObjectError("Invalid encrypted storage object key")
        path = self.object_root.joinpath(*key.parts).resolve(strict=False)
        self._require_within(path, self.object_root)
        return path

    @staticmethod
    def _require_within(path: Path, root: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise StorageObjectError(
                "Encrypted storage object escaped its configured root"
            ) from exc

    @staticmethod
    def _open_staged_exclusive(path: Path) -> BinaryIO:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            return os.fdopen(descriptor, "wb")
        except OSError as exc:
            raise StorageObjectError("Unable to create a staging object") from exc

    @staticmethod
    def _flush_and_sync(stream: BinaryIO) -> None:
        stream.flush()
        os.fsync(stream.fileno())

    def _prune_empty_parent(self, path: Path) -> None:
        """Remove the per-file directory once its object is gone.

        `publish` creates one directory per `file_id` and `delete_object` only unlinked
        the object inside it, so every file ever uploaded left a directory behind for the
        lifetime of the deployment. Nothing read them and nothing else could remove them.

        Best effort by design: `rmdir` refuses a non-empty directory, which is exactly the
        interlock wanted if a concurrent publish has just written a sibling. A directory
        that cannot be removed is inert, so a failure here must not turn a successful
        delete into an error.
        """
        parent = path.parent
        if parent == self.object_root:
            return
        with suppress(OSError):
            self._require_within(parent, self.object_root)
            parent.rmdir()

    @staticmethod
    def _unlink_if_present(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise StorageObjectError("Unable to remove an encrypted storage object") from exc

    @staticmethod
    def _sync_directory(path: Path) -> None:
        # Windows does not support opening directories for fsync. Atomic rename still holds;
        # directory fsync is an additional durability measure on supporting platforms.
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
