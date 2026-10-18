from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.time import to_api_utc, to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import FileCapability
from app.domain.errors import (
    FileEnvelopeInvalidError,
    FileFolderNameConflictError,
    FileFolderNotFoundError,
    FileResourceNotFoundError,
    FileStateConflictError,
    FileTooLargeError,
    ServerStorageLowError,
    StorageQuotaExceededError,
    StorageUnavailableError,
    UploadDailyLimitError,
)
from app.models.file import File
from app.models.file_access_grant import FileAccessGrant
from app.models.file_folder import FileFolder
from app.models.file_key_wrapping import FileKeyWrapping
from app.repositories.file_repository import FileAccessRecord, FileRepository
from app.schemas.file_schema import (
    CiphertextPreviewOut,
    FileCryptoEnvelopeOut,
    FileDeleteOut,
    FileFolderDeleteOut,
    FileFolderListOut,
    FileFolderOut,
    FileListOut,
    FileMoveOut,
    FileOut,
    FileSummaryOut,
    FileUploadMetadata,
    IntegrityCheckOut,
)
from app.services.access_control_service import AccessControlService
from app.services.audit_log_service import AuditLogService
from app.services.file_storage_service import (
    FileStorageService,
    StagedCiphertext,
    StorageObjectError,
    StorageObjectMissingError,
    VerifiedCiphertext,
)
from app.services.integrity_service import IntegrityService

# The preview is a fixed size chosen here, never by the caller, so it cannot be turned into a
# way of reading arbitrary ranges of someone else's ciphertext or of loading the server.
CIPHERTEXT_PREVIEW_BYTES = 128


@dataclass(slots=True)
class FileDownload:
    file_id: UUID
    original_filename: str
    ciphertext_size: int
    verified_ciphertext: VerifiedCiphertext


class FileService:
    """Transaction owner for client-encrypted file operations."""

    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        storage: FileStorageService,
        audit_service: AuditLogService,
        repository: FileRepository | None = None,
        access_control: AccessControlService | None = None,
        integrity_service: IntegrityService | None = None,
        clock=utc_now,
        uuid_factory=uuid4,
    ) -> None:
        self.db = db
        self.settings = settings
        self.storage = storage
        self.audit = audit_service
        self.repository = repository or FileRepository(db)
        self.access = access_control or AccessControlService(
            db=db,
            settings=settings,
            storage=storage,
            audit_service=audit_service,
            repository=self.repository,
        )
        self.integrity = integrity_service or IntegrityService(
            db=db,
            settings=settings,
            storage=storage,
            audit_service=audit_service,
            repository=self.repository,
            access_control=self.access,
            clock=clock,
        )
        self.clock = clock
        self.uuid_factory = uuid_factory

    async def upload(
        self,
        *,
        actor: ActorContext,
        metadata: FileUploadMetadata,
        ciphertext: UploadFile,
        context: RequestContext,
    ) -> FileOut:
        """Check, stage, then record an encrypted upload.

        The database work runs in the thread pool, never on the event loop, and no connection
        is held while the ciphertext is staged. Before this split, an upload held a connection
        from authentication to commit while repeatedly awaiting the thread pool to write the
        staged file, and every pool thread could be waiting for a connection: at 100
        concurrent users the pool timed out and uploads failed with HTTP 500 (#140).
        """
        owner_key, recovery_key = await run_in_threadpool(self._check_upload, actor, metadata)

        staged: StagedCiphertext | None = None
        try:
            staged = await self.storage.stage_upload(
                ciphertext,
                max_size_bytes=self.settings.MAX_UPLOAD_SIZE_BYTES,
            )
        except StorageObjectError as exc:
            # No transaction is open here; rollback only resets the session's state.
            self.db.rollback()
            self._compensate(staged=staged, object_key=None)
            raise StorageUnavailableError() from exc
        except Exception:
            self.db.rollback()
            self._compensate(staged=staged, object_key=None)
            raise

        return await run_in_threadpool(
            self._record_upload, actor, metadata, context, staged, owner_key, recovery_key
        )

    def _check_upload(self, actor: ActorContext, metadata: FileUploadMetadata):
        self._validate_upload_metadata(metadata)
        owner_key = self.repository.get_active_user_key(actor.user_id, metadata.owner_key_id)
        if owner_key is None:
            raise FileEnvelopeInvalidError(
                "owner_key_id must identify one of your active public keys"
            )
        if owner_key.algorithm != metadata.key_wrapping_algorithm:
            raise FileEnvelopeInvalidError(
                "owner_key_id uses an incompatible key-wrapping algorithm"
            )
        expected_wrapped_size = getattr(owner_key, "key_size_bits", 0) // 8
        if (
            expected_wrapped_size
            and len(metadata.wrapped_file_key_bytes()) != expected_wrapped_size
        ):
            raise FileEnvelopeInvalidError("wrapped_file_key length does not match owner_key_id")
        recovery_key = self.repository.get_active_recovery_key(metadata.recovery_key_id)
        if recovery_key is None:
            raise FileEnvelopeInvalidError(
                "recovery_key_id must identify the active recovery public key"
            )
        if recovery_key.algorithm != metadata.key_wrapping_algorithm:
            raise FileEnvelopeInvalidError(
                "recovery_key_id uses an incompatible key-wrapping algorithm"
            )
        expected_recovery_wrapped_size = recovery_key.key_size_bits // 8
        if len(metadata.recovery_wrapped_file_key_bytes()) != expected_recovery_wrapped_size:
            raise FileEnvelopeInvalidError(
                "recovery_wrapped_file_key length does not match recovery_key_id"
            )
        if self.repository.file_uuid_exists(metadata.file_id):
            raise FileStateConflictError("file_id has already been used")
        self._enforce_upload_limits(actor, metadata.plaintext_size)
        # Nothing is pending; give the connection back before the request goes on to stage
        # the file, so no connection is held while the upload waits for the thread pool.
        self.repository.release_connection()
        return owner_key, recovery_key

    def _record_upload(
        self,
        actor: ActorContext,
        metadata: FileUploadMetadata,
        context: RequestContext,
        staged: StagedCiphertext,
        owner_key,
        recovery_key,
    ) -> FileOut:
        object_key: str | None = None
        published = False
        commit_attempted = False
        try:
            if staged.size_bytes != metadata.plaintext_size:
                raise FileEnvelopeInvalidError(
                    "AES-GCM ciphertext size must match plaintext_size when the tag is separate"
                )

            now = self._now()
            object_key = self.storage.allocate_object_key(
                metadata.file_id,
                random_id=self.uuid_factory(),
            )
            file_values: dict[str, object] = {
                "file_uuid": str(metadata.file_id),
                "owner_id": actor.user_id,
                "original_filename": metadata.original_filename,
                "stored_filename": f"{metadata.file_id}.ciphertext",
                "storage_object_key": object_key,
                "mime_type": metadata.mime_type,
                "file_size_bytes": metadata.plaintext_size,
                "encrypted_size_bytes": staged.size_bytes,
                "encryption_algorithm": metadata.encryption_algorithm,
                "iv": metadata.nonce_bytes(),
                "auth_tag": metadata.auth_tag_bytes(),
                "encrypted_sha256": staged.sha256,
                "status": "ACTIVE",
                "created_at": now,
                "updated_at": now,
            }
            self._set_if_mapped(file_values, File, "envelope_version", metadata.envelope_version)
            self._set_if_mapped(file_values, File, "aad_version", metadata.aad_version)
            self._set_if_mapped(file_values, File, "revision", 1)
            self._set_if_mapped(
                file_values,
                File,
                "encrypted_manifest",
                (
                    base64.b64decode(metadata.encrypted_manifest, validate=True)
                    if metadata.encrypted_manifest is not None
                    else None
                ),
            )
            file_record = File(**file_values)
            self.repository.add_file(file_record)
            self.repository.flush()

            grant_values: dict[str, object] = {
                "file_id": file_record.id,
                "user_id": actor.user_id,
                "granted_by": actor.user_id,
                "can_download": True,
                "can_share": True,
                "can_revoke": True,
                "can_manage": True,
                "status": "ACTIVE",
                "created_at": now,
            }
            self._set_if_mapped(grant_values, FileAccessGrant, "updated_at", now)
            self._set_if_mapped(grant_values, FileAccessGrant, "revision", 1)
            grant = FileAccessGrant(**grant_values)
            self.repository.add_grant(grant)

            wrapping_values: dict[str, object] = {
                "file_id": file_record.id,
                "recipient_type": "USER",
                "recipient_user_id": actor.user_id,
                "user_key_id": owner_key.id,
                "recovery_key_id": None,
                "wrapped_file_key": metadata.wrapped_file_key_bytes(),
                "wrapping_algorithm": metadata.key_wrapping_algorithm,
                "status": "ACTIVE",
                "created_at": now,
            }
            self._set_if_mapped(wrapping_values, FileKeyWrapping, "updated_at", now)
            self._set_if_mapped(wrapping_values, FileKeyWrapping, "revision", 1)
            wrapping = FileKeyWrapping(**wrapping_values)
            self.repository.add_wrapping(wrapping)

            recovery_wrapping_values: dict[str, object] = {
                "file_id": file_record.id,
                "recipient_type": "RECOVERY",
                "recipient_user_id": None,
                "user_key_id": None,
                "recovery_key_id": recovery_key.id,
                "wrapped_file_key": metadata.recovery_wrapped_file_key_bytes(),
                "wrapping_algorithm": metadata.key_wrapping_algorithm,
                "status": "ACTIVE",
                "created_at": now,
            }
            self._set_if_mapped(
                recovery_wrapping_values,
                FileKeyWrapping,
                "updated_at",
                now,
            )
            self._set_if_mapped(recovery_wrapping_values, FileKeyWrapping, "revision", 1)
            self.repository.add_wrapping(FileKeyWrapping(**recovery_wrapping_values))

            self.audit.append(
                action="FILE_UPLOADED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                resource_type="FILE",
                resource_id=str(metadata.file_id),
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={
                    "ciphertext_size": staged.size_bytes,
                    # Anchors the digest in the hash chain, so rewriting files.encrypted_sha256
                    # together with the object is still caught (see IntegrityService).
                    "ciphertext_sha256": staged.sha256,
                    "envelope_version": metadata.envelope_version,
                    "aad_version": metadata.aad_version,
                },
            )
            self.storage.publish(staged, object_key)
            published = True
            result = self._file_out(
                FileAccessRecord(
                    file=file_record,
                    grant=grant,
                    wrapping=wrapping,
                    user_key=owner_key,
                ),
                actor_user_id=actor.user_id,
            )
            # Once COMMIT has been sent, a connection failure can leave its outcome
            # ambiguous: MySQL may have committed before the acknowledgement was lost.
            # Never delete a potentially committed object's ciphertext in that state.
            # A harmless orphan is safer and can be reconciled later.
            commit_attempted = True
            self.db.commit()
            return result
        except IntegrityError as exc:
            self.db.rollback()
            self._compensate(
                staged=staged,
                object_key=object_key if published and not commit_attempted else None,
            )
            raise FileStateConflictError("file_id has already been used") from exc
        except StorageObjectError as exc:
            self.db.rollback()
            self._compensate(
                staged=staged,
                object_key=object_key if published and not commit_attempted else None,
            )
            raise StorageUnavailableError() from exc
        except Exception:
            self.db.rollback()
            self._compensate(
                staged=staged,
                object_key=object_key if published and not commit_attempted else None,
            )
            raise

    def list_files(
        self,
        *,
        actor: ActorContext,
        page: int,
        page_size: int,
        search: str | None = None,
        folder_id: UUID | None = None,
        unfiled: bool = False,
        scope: str = "all",
    ) -> FileListOut:
        # `original_filename` is a cleartext column: the server already stores it, shows it
        # back in every listing, and the client binds it into the file AAD precisely
        # because the server could otherwise rewrite it. Matching on it here therefore
        # discloses nothing the caller could not already read, and nothing about content --
        # the ciphertext and the file key stay as opaque to this query as to every other.
        normalized = search.strip() if search else None
        records, total, owned_total, shared_total = self.repository.list_active_access(
            actor.user_id,
            offset=(page - 1) * page_size,
            limit=page_size,
            search=normalized or None,
            folder_id=folder_id,
            unfiled=unfiled,
            scope=scope,
        )
        return FileListOut(
            items=[self._summary(record, actor_user_id=actor.user_id) for record in records],
            page=page,
            page_size=page_size,
            total=total,
            owned_total=owned_total,
            shared_total=shared_total,
        )

    def list_folders(self, *, actor: ActorContext) -> FileFolderListOut:
        return FileFolderListOut(
            items=[
                self._folder_out(folder, owned, shared)
                for folder, owned, shared in self.repository.list_folders(actor.user_id)
            ]
        )

    def create_folder(self, *, actor: ActorContext, name: str) -> FileFolderOut:
        folder = FileFolder(owner_id=actor.user_id, name=name)
        self.repository.add_folder(folder)
        try:
            self.repository.flush()
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise FileFolderNameConflictError() from exc
        return self._folder_out(folder, 0, 0)

    def rename_folder(self, *, actor: ActorContext, folder_id: UUID, name: str) -> FileFolderOut:
        folder = self.repository.get_owned_folder(folder_id, actor.user_id, lock=True)
        if folder is None:
            raise FileFolderNotFoundError()
        folder.name = name
        folder.updated_at = self._now()
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise FileFolderNameConflictError() from exc
        owned, shared = next(
            (
                (own, other)
                for item, own, other in self.repository.list_folders(actor.user_id)
                if item.id == folder.id
            ),
            (0, 0),
        )
        return self._folder_out(folder, owned, shared)

    def delete_folder(self, *, actor: ActorContext, folder_id: UUID) -> FileFolderDeleteOut:
        folder = self.repository.get_owned_folder(folder_id, actor.user_id, lock=True)
        if folder is None:
            raise FileFolderNotFoundError()
        files_unfiled = self.repository.delete_folder(folder)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return FileFolderDeleteOut(folder_id=folder_id, files_unfiled=files_unfiled)

    def move_file(
        self, *, actor: ActorContext, file_id: UUID, folder_id: UUID | None
    ) -> FileMoveOut:
        # The owner files the file itself; a recipient files their own grant, so two people
        # can keep the same shared file in different folders of their own.
        target = self.repository.lock_owned_file(file_id, actor.user_id)
        if target is None or target.status == "DELETED":
            target = self.repository.lock_recipient_grant(file_id, actor.user_id)
        if target is None:
            raise FileResourceNotFoundError()
        folder = None
        if folder_id is not None:
            folder = self.repository.get_owned_folder(folder_id, actor.user_id, lock=True)
            if folder is None:
                raise FileFolderNotFoundError()
        target.folder_id = folder.id if folder else None
        target.updated_at = self._now()
        if hasattr(target, "revision"):
            target.revision += 1
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return FileMoveOut(file_id=file_id, folder_id=folder_id)

    def get_file(self, *, actor: ActorContext, file_id: UUID) -> FileOut:
        record = self.access.require(
            user_id=actor.user_id,
            file_id=file_id,
            capability=FileCapability.VIEW,
        )
        return self._file_out(record, actor_user_id=actor.user_id)

    def download(
        self,
        *,
        actor: ActorContext,
        file_id: UUID,
        context: RequestContext,
    ) -> FileDownload:
        record = self.access.require(
            user_id=actor.user_id,
            file_id=file_id,
            capability=FileCapability.DOWNLOAD,
        )
        verified = self.integrity.open_verified_for_download(
            record=record,
            actor=actor,
            context=context,
        )
        return FileDownload(
            file_id=file_id,
            original_filename=record.file.original_filename,
            ciphertext_size=verified.size_bytes,
            verified_ciphertext=verified,
        )

    def ciphertext_preview(
        self,
        *,
        actor: ActorContext,
        file_id: UUID,
        context: RequestContext,
    ) -> CiphertextPreviewOut:
        """Show the first bytes of the stored ciphertext to someone allowed to download it.

        Needs the same capability as downloading the ciphertext and exposes strictly less: a
        fixed 128-byte sample plus metadata the caller already receives with the file. It is
        audited under its own action so previews never count as downloads.
        """
        record = self.access.require(
            user_id=actor.user_id,
            file_id=file_id,
            capability=FileCapability.DOWNLOAD,
        )
        try:
            sample = self.storage.read_head(
                record.file.storage_object_key, CIPHERTEXT_PREVIEW_BYTES
            )
        except (StorageObjectError, StorageObjectMissingError) as exc:
            raise StorageUnavailableError() from exc

        try:
            self.audit.append(
                action="FILE_CIPHERTEXT_PREVIEWED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                resource_type="FILE",
                resource_id=record.file.file_uuid,
                context_ip_address=context.ip_address,
                context_user_agent=context.user_agent,
                metadata={"sample_length": len(sample)},
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return CiphertextPreviewOut(
            file_id=file_id,
            encryption_algorithm=record.file.encryption_algorithm,
            plaintext_size=record.file.file_size_bytes,
            ciphertext_size=record.file.encrypted_size_bytes,
            ciphertext_sha256=record.file.encrypted_sha256,
            status=record.file.status,
            sample_offset=0,
            sample_length=len(sample),
            sample_hex=sample.hex(),
        )

    def delete(
        self,
        *,
        actor: ActorContext,
        file_id: UUID,
        context: RequestContext,
    ) -> FileDeleteOut:
        file_record = self.repository.lock_owned_file(file_id, actor.user_id)
        if file_record is None:
            raise FileResourceNotFoundError()
        already_deleted = file_record.status == "DELETED"
        object_key = file_record.storage_object_key
        if not already_deleted:
            now = self._now()
            try:
                file_record.status = "DELETED"
                file_record.deleted_at = now
                file_record.updated_at = now
                if hasattr(file_record, "revision"):
                    file_record.revision += 1
                self.repository.revoke_file_access_rows(file_record.id, revoked_at=now)
                self.audit.append(
                    action="FILE_DELETED",
                    result="SUCCESS",
                    actor_user_id=actor.user_id,
                    resource_type="FILE",
                    resource_id=str(file_id),
                    context_ip_address=context.ip_address,
                    context_user_agent=context.user_agent,
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

        # Cleanup follows the durable soft-delete. A retry sees DELETED and repeats this
        # idempotent removal if a previous process died between commit and unlink.
        try:
            self.storage.delete_object(object_key)
        except StorageObjectError as exc:
            raise StorageUnavailableError() from exc
        return FileDeleteOut(
            file_id=file_id,
            status="DELETED",
            already_deleted=already_deleted,
        )

    def integrity_check(
        self,
        *,
        actor: ActorContext,
        file_id: UUID,
        context: RequestContext,
    ) -> IntegrityCheckOut:
        return self.integrity.check(actor=actor, file_id=file_id, context=context)

    def _validate_upload_metadata(self, metadata: FileUploadMetadata) -> None:
        if metadata.plaintext_size > self.settings.MAX_UPLOAD_SIZE_BYTES:
            raise FileTooLargeError()

    @staticmethod
    def _set_if_mapped(values: dict[str, object], model: type, field: str, value: object) -> None:
        if hasattr(model, field):
            values[field] = value

    @staticmethod
    def _manifest_base64(file_record: File) -> str | None:
        manifest = getattr(file_record, "encrypted_manifest", None)
        if manifest is None:
            return None
        return base64.b64encode(bytes(manifest)).decode("ascii")

    def _summary(self, record: FileAccessRecord, *, actor_user_id: int) -> FileSummaryOut:
        owned = record.file.owner_id == actor_user_id
        return FileSummaryOut(
            file_id=UUID(record.file.file_uuid),
            original_filename=record.file.original_filename,
            plaintext_size=record.file.file_size_bytes,
            ciphertext_size=record.file.encrypted_size_bytes,
            ciphertext_sha256=record.file.encrypted_sha256,
            mime_type=record.file.mime_type,
            encryption_algorithm=record.file.encryption_algorithm,
            status=record.file.status,
            owner=owned,
            owner_username=getattr(record.file.owner, "username", None),
            folder_id=self._placement_uuid(record, owned=owned),
            created_at=to_api_utc(record.file.created_at),
            updated_at=to_api_utc(record.file.updated_at),
        )

    @staticmethod
    def _placement_uuid(record: FileAccessRecord, *, owned: bool) -> UUID | None:
        """The caller's folder for this file: the file's own if they own it, else their grant's."""
        holder = record.file if owned else record.grant
        folder = getattr(holder, "folder", None)
        return UUID(folder.folder_uuid) if folder is not None else None

    @staticmethod
    def _folder_out(folder: FileFolder, owned: int, shared: int) -> FileFolderOut:
        return FileFolderOut(
            folder_id=UUID(folder.folder_uuid),
            name=folder.name,
            file_count=owned + shared,
            owned_file_count=owned,
            shared_file_count=shared,
            created_at=to_api_utc(folder.created_at),
            updated_at=to_api_utc(folder.updated_at),
        )

    def _file_out(self, record: FileAccessRecord, *, actor_user_id: int) -> FileOut:
        summary = self._summary(record, actor_user_id=actor_user_id)
        key_uuid = getattr(record.user_key, "key_uuid", None)
        if key_uuid is None:  # pragma: no cover - migration invariant
            raise RuntimeError("The user key is missing its public key identifier")
        return FileOut(
            **summary.model_dump(),
            crypto_envelope=FileCryptoEnvelopeOut(
                encryption_algorithm=record.file.encryption_algorithm,
                envelope_version=getattr(record.file, "envelope_version", 1),
                aad_version=getattr(record.file, "aad_version", 1),
                nonce=base64.b64encode(record.file.iv).decode("ascii"),
                auth_tag=base64.b64encode(record.file.auth_tag).decode("ascii"),
                key_id=UUID(key_uuid),
                key_wrapping_algorithm=record.wrapping.wrapping_algorithm,
                wrapped_file_key=base64.b64encode(record.wrapping.wrapped_file_key).decode("ascii"),
                encrypted_manifest=self._manifest_base64(record.file),
            ),
        )

    def _compensate(
        self,
        *,
        staged: StagedCiphertext | None,
        object_key: str | None,
    ) -> None:
        try:
            if object_key is not None:
                self.storage.delete_object(object_key)
            self.storage.discard_staged(staged)
        except StorageObjectError:
            # Preserve the use-case failure. Crash/orphan reconciliation handles the rare
            # case where best-effort compensation itself cannot reach local storage.
            return

    def _enforce_upload_limits(self, actor: ActorContext, size: int) -> None:
        """Refuse an upload before any byte is stored (threat model T-D2).

        `size` is the declared plaintext size, which equals the ciphertext size and is checked
        against the bytes actually received, so it cannot be understated to slip past this.
        Two uploads racing the same quota can each pass; the overshoot is at most one file each.
        """
        settings = self.settings
        if settings.UPLOAD_MIN_FREE_DISK_BYTES and (
            self.storage.free_bytes() - size < settings.UPLOAD_MIN_FREE_DISK_BYTES
        ):
            raise ServerStorageLowError()
        if settings.USER_STORAGE_QUOTA_BYTES:
            used = self.repository.stored_bytes_for_owner(actor.user_id)
            if used + size > settings.USER_STORAGE_QUOTA_BYTES:
                raise StorageQuotaExceededError(
                    details={"used_bytes": used, "quota_bytes": settings.USER_STORAGE_QUOTA_BYTES}
                )
        if settings.USER_DAILY_UPLOAD_BYTES:
            since = self._now() - timedelta(hours=24)
            uploaded = self.repository.uploaded_bytes_since(actor.user_id, since)
            if uploaded + size > settings.USER_DAILY_UPLOAD_BYTES:
                raise UploadDailyLimitError(
                    details={
                        "uploaded_bytes": uploaded,
                        "limit_bytes": settings.USER_DAILY_UPLOAD_BYTES,
                    }
                )

    def _now(self) -> datetime:
        return to_second_resolution_utc(self.clock())
