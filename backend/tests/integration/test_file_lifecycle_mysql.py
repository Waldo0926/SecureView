"""The encrypted-file lifecycle against a real MySQL and a real filesystem.

`tests/unit` covers these services against fakes and `tests/api` covers the HTTP contract.
Neither can see the defects that only exist where the service, the SQL, and the object store
meet: a status column that no query will return afterwards, a timestamp the column rounds on
the way in, a directory nothing removes. Both were found by exercising this path against a
live database and neither was visible to a fake.

The layer under test is service + repository + MySQL + filesystem. Authentication is not
involved: these tests build an `ActorContext` directly rather than logging in, because the
questions here are about what the database and the object store end up holding.

Set `AUTH_TEST_DATABASE_URL` to a disposable, already-migrated database whose name carries a
distinct `_test` segment, exactly as the auth integration tests require. Without it the whole
module skips.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import UploadFile
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.core.config import Settings
from app.core.time import to_api_utc
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import (
    FileEnvelopeInvalidError,
    FileResourceNotFoundError,
    FileStateConflictError,
    IntegrityVerificationError,
)
from app.models.file import File
from app.models.file_access_grant import FileAccessGrant
from app.models.file_key_wrapping import FileKeyWrapping
from app.models.integrity_check import IntegrityCheck
from app.models.recovery_key import RecoveryKey
from app.models.user import User
from app.models.user_key import UserKey
from app.repositories.audit_repository import AuditRepository
from app.schemas.file_schema import FileUploadMetadata
from app.services.audit_log_service import AuditLogService
from app.services.file_service import FileService
from app.services.file_storage_service import FileStorageService

pytestmark = pytest.mark.integration

KEY_SIZE_BITS = 2048  # Smaller than production on purpose: these tests mint keys per run.
AAD_LABEL = b"FYP-FILE-CONTENT"


# ---------------------------------------------------------------------------
# The client half of the envelope, mirroring frontend/src/crypto/file_envelope.ts.
# Rebuilt here rather than imported because the point is to feed the server bytes a
# browser would really have produced.
# ---------------------------------------------------------------------------


def _frame(raw: bytes) -> bytes:
    return len(raw).to_bytes(4, "big") + raw


def _file_content_aad(*, file_id: UUID, filename: str, plaintext_size: int, mime: str) -> bytes:
    return b"".join(
        (
            AAD_LABEL,
            bytes([0]),
            bytes([1]),  # aad_version
            file_id.bytes,
            (1).to_bytes(4, "big"),  # envelope_version
            _frame(b"AES-256-GCM"),
            plaintext_size.to_bytes(8, "big"),
            _frame(filename.encode("utf-8")),
            _frame(mime.encode("ascii")),
        )
    )


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _rsa_wrap(public_key_pem: str, dek: bytes) -> bytes:
    public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    return public_key.encrypt(
        dek,
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )


def _public_pem_and_fingerprint(private_key: rsa.RSAPrivateKey) -> tuple[str, str]:
    public_key = private_key.public_key()
    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    fingerprint = hashlib.sha256(
        public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()
    return pem, fingerprint


@dataclass(frozen=True, slots=True)
class EncryptedUpload:
    """One file, encrypted exactly as the browser would encrypt it."""

    file_id: UUID
    plaintext: bytes
    ciphertext: bytes
    dek: bytes
    metadata: FileUploadMetadata


@dataclass(slots=True)
class LifecycleEnvironment:
    service: FileService
    storage: FileStorageService
    session: Session
    actor: ActorContext
    user_id: int
    owner_key_uuid: UUID
    owner_public_pem: str
    recovery_key_uuid: UUID
    recovery_private_key: rsa.RSAPrivateKey
    recovery_public_pem: str
    object_root: Path

    def build_upload(
        self,
        plaintext: bytes = b"chapter one, and everything after it",
        *,
        filename: str = "dissertation.pdf",
        mime: str = "application/pdf",
        declared_size: int | None = None,
    ) -> EncryptedUpload:
        file_id = uuid4()
        dek = AESGCM.generate_key(bit_length=256)
        nonce = uuid4().bytes[:12]
        size = len(plaintext) if declared_size is None else declared_size
        sealed = AESGCM(dek).encrypt(
            nonce,
            plaintext,
            _file_content_aad(file_id=file_id, filename=filename, plaintext_size=size, mime=mime),
        )
        ciphertext, auth_tag = sealed[:-16], sealed[-16:]
        metadata = FileUploadMetadata(
            file_id=file_id,
            original_filename=filename,
            plaintext_size=size,
            mime_type=mime,
            nonce=_b64(nonce),
            auth_tag=_b64(auth_tag),
            owner_key_id=self.owner_key_uuid,
            wrapped_file_key=_b64(_rsa_wrap(self.owner_public_pem, dek)),
            recovery_key_id=self.recovery_key_uuid,
            recovery_wrapped_file_key=_b64(_rsa_wrap(self.recovery_public_pem, dek)),
        )
        return EncryptedUpload(
            file_id=file_id,
            plaintext=plaintext,
            ciphertext=ciphertext,
            dek=dek,
            metadata=metadata,
        )

    def upload(self, prepared: EncryptedUpload | None = None) -> EncryptedUpload:
        prepared = prepared or self.build_upload()
        asyncio.run(
            self.service.upload(
                actor=self.actor,
                metadata=prepared.metadata,
                ciphertext=_upload_part(prepared.ciphertext),
                context=RequestContext(),
            )
        )
        return prepared

    def object_path(self, file_id: UUID) -> Path:
        key = self.session.scalar(
            select(File.storage_object_key).where(File.file_uuid == str(file_id))
        )
        assert key is not None
        return self.object_root / key

    def file_row(self, file_id: UUID) -> File:
        row = self.session.scalar(select(File).where(File.file_uuid == str(file_id)))
        assert row is not None
        self.session.refresh(row)
        return row


def _upload_part(ciphertext: bytes) -> UploadFile:
    return UploadFile(
        filename="ciphertext.bin",
        file=BytesIO(ciphertext),
        headers=Headers({"content-type": "application/octet-stream"}),
    )


@pytest.fixture
def lifecycle(auth_mysql_engine: Engine, tmp_path: Path) -> Iterator[LifecycleEnvironment]:
    """A file service wired to the disposable database and a storage root under tmp_path.

    Identity is created here rather than through registration: these tests are about what
    the file path writes, and going through enrolment would pull the whole account-key
    ceremony in without covering anything extra.
    """
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        APP_DEBUG=False,
        SECRET_KEY="integration-test-secret-key-long-enough",
        ENCRYPTED_FILE_DIR=tmp_path / "objects",
        TEMP_FILE_DIR=tmp_path / "staging",
    )
    session = Session(bind=auth_mysql_engine, expire_on_commit=False)
    suffix = uuid4().hex[:12]

    owner_private = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE_BITS)
    owner_pem, owner_fingerprint = _public_pem_and_fingerprint(owner_private)
    recovery_private = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE_BITS)
    recovery_pem, recovery_fingerprint = _public_pem_and_fingerprint(recovery_private)

    user = User(
        user_uuid=str(uuid4()),
        username=f"lifecycle-{suffix}",
        email=f"lifecycle-{suffix}@secureview.tech",
        password_hash="not-a-real-hash-these-tests-never-authenticate",
        role="USER",
        status="ACTIVE",
        email_verified=True,
    )
    session.add(user)
    session.flush()

    owner_key_uuid = uuid4()
    session.add(
        UserKey(
            key_uuid=str(owner_key_uuid),
            user_id=user.id,
            public_key_pem=owner_pem,
            algorithm="RSA-OAEP-SHA256",
            key_size_bits=KEY_SIZE_BITS,
            fingerprint=owner_fingerprint,
            status="ACTIVE",
        )
    )
    recovery_key_uuid = uuid4()
    session.add(
        RecoveryKey(
            key_uuid=str(recovery_key_uuid),
            public_key_pem=recovery_pem,
            algorithm="RSA-OAEP-SHA256",
            key_size_bits=KEY_SIZE_BITS,
            fingerprint=recovery_fingerprint,
            status="ACTIVE",
        )
    )
    session.commit()

    storage = FileStorageService(settings=settings)
    environment = LifecycleEnvironment(
        service=FileService(
            db=session,
            settings=settings,
            storage=storage,
            audit_service=AuditLogService(session),
        ),
        storage=storage,
        session=session,
        actor=ActorContext(
            user_id=user.id,
            user_public_id=UUID(user.user_uuid),
            session_id=1,
            session_public_id=uuid4(),
            role=SystemRole.USER,
            status=UserStatus.ACTIVE,
            access_token_hash="0" * 64,
        ),
        user_id=user.id,
        owner_key_uuid=owner_key_uuid,
        owner_public_pem=owner_pem,
        recovery_key_uuid=recovery_key_uuid,
        recovery_private_key=recovery_private,
        recovery_public_pem=recovery_pem,
        object_root=settings.ENCRYPTED_FILE_DIR,
    )
    try:
        yield environment
    finally:
        _clean_up(session, user_id=user.id, recovery_key_uuid=recovery_key_uuid)
        session.close()


def _clean_up(session: Session, *, user_id: int, recovery_key_uuid: UUID) -> None:
    """Remove this run's file rows, in foreign-key order.

    `audit_logs` and the identity its rows point at are left behind deliberately. The chain
    is append-only by design -- the runtime grant is `SELECT, INSERT` and nothing more --
    and deleting from the middle of a hash chain would corrupt exactly the property the
    table exists to provide.
    """
    session.rollback()
    file_ids = session.scalars(select(File.id).where(File.owner_id == user_id)).all()
    if file_ids:
        session.execute(delete(IntegrityCheck).where(IntegrityCheck.file_id.in_(file_ids)))
        session.execute(delete(FileKeyWrapping).where(FileKeyWrapping.file_id.in_(file_ids)))
        session.execute(delete(FileAccessGrant).where(FileAccessGrant.file_id.in_(file_ids)))
        session.execute(delete(File).where(File.id.in_(file_ids)))
    session.execute(delete(UserKey).where(UserKey.user_id == user_id))
    session.execute(delete(RecoveryKey).where(RecoveryKey.key_uuid == str(recovery_key_uuid)))
    session.commit()


# ---------------------------------------------------------------------------
# The happy path, end to end.
# ---------------------------------------------------------------------------


def test_upload_persists_the_ciphertext_and_its_recorded_digest(
    lifecycle: LifecycleEnvironment,
) -> None:
    uploaded = lifecycle.upload()

    row = lifecycle.file_row(uploaded.file_id)
    on_disk = lifecycle.object_path(uploaded.file_id).read_bytes()

    assert on_disk == uploaded.ciphertext
    assert row.encrypted_sha256 == hashlib.sha256(on_disk).hexdigest()
    assert row.encrypted_size_bytes == len(on_disk)
    assert row.file_size_bytes == len(uploaded.plaintext)
    assert row.status == "ACTIVE"


def test_no_plaintext_reaches_the_object_store(lifecycle: LifecycleEnvironment) -> None:
    """The one property the whole design exists to provide."""
    plaintext = b"the server must never be able to read this sentence"
    uploaded = lifecycle.upload(lifecycle.build_upload(plaintext))

    stored = b"".join(path.read_bytes() for path in lifecycle.object_root.rglob("*.ciphertext"))

    assert plaintext not in stored
    assert uploaded.ciphertext in stored


def test_download_returns_bytes_that_decrypt_to_the_original(
    lifecycle: LifecycleEnvironment,
) -> None:
    uploaded = lifecycle.upload()

    download = lifecycle.service.download(
        actor=lifecycle.actor,
        file_id=uploaded.file_id,
        context=RequestContext(),
    )
    streamed = b"".join(download.verified_ciphertext.iter_chunks())

    assert streamed == uploaded.ciphertext
    recovered = AESGCM(uploaded.dek).decrypt(
        uploaded.metadata.nonce_bytes(),
        streamed + uploaded.metadata.auth_tag_bytes(),
        _file_content_aad(
            file_id=uploaded.file_id,
            filename=uploaded.metadata.original_filename,
            plaintext_size=uploaded.metadata.plaintext_size,
            mime=uploaded.metadata.mime_type,
        ),
    )
    assert recovered == uploaded.plaintext


def test_the_recovery_wrapping_opens_the_same_file_key(
    lifecycle: LifecycleEnvironment,
) -> None:
    """The offline half of custody. Nothing else in the suite ever exercises it."""
    uploaded = lifecycle.upload()

    wrapped = lifecycle.session.scalar(
        select(FileKeyWrapping.wrapped_file_key)
        .join(File, File.id == FileKeyWrapping.file_id)
        .where(
            File.file_uuid == str(uploaded.file_id),
            FileKeyWrapping.recipient_type == "RECOVERY",
        )
    )
    unwrapped = lifecycle.recovery_private_key.decrypt(
        wrapped,
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )

    assert unwrapped == uploaded.dek


def test_an_empty_file_survives_the_whole_round_trip(
    lifecycle: LifecycleEnvironment,
) -> None:
    uploaded = lifecycle.upload(lifecycle.build_upload(b""))

    assert lifecycle.object_path(uploaded.file_id).read_bytes() == b""
    assert (
        lifecycle.service.integrity_check(
            actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
        ).status
        == "VALID"
    )


# ---------------------------------------------------------------------------
# Integrity findings and the durable status. Regressions for the CORRUPTED one-way door.
# ---------------------------------------------------------------------------


def test_a_modified_ciphertext_is_reported_and_marked_corrupted(
    lifecycle: LifecycleEnvironment,
) -> None:
    uploaded = lifecycle.upload()
    path = lifecycle.object_path(uploaded.file_id)
    damaged = bytearray(path.read_bytes())
    damaged[0] ^= 0xFF
    path.write_bytes(bytes(damaged))

    result = lifecycle.service.integrity_check(
        actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
    )

    assert result.status == "MODIFIED"
    assert lifecycle.file_row(uploaded.file_id).status == "CORRUPTED"


def test_a_corrupted_file_stays_visible_to_its_owner(
    lifecycle: LifecycleEnvironment,
) -> None:
    """Regression: `CORRUPTED` used to remove the file from every read route at once.

    The owner could not list it, read it, re-check it, or find out why it had gone. The
    row survived and nothing could name it.
    """
    uploaded = lifecycle.upload()
    path = lifecycle.object_path(uploaded.file_id)
    path.write_bytes(path.read_bytes() + b"appended")
    lifecycle.service.integrity_check(
        actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
    )
    assert lifecycle.file_row(uploaded.file_id).status == "CORRUPTED"

    listing = lifecycle.service.list_files(actor=lifecycle.actor, page=1, page_size=100)
    assert any(item.file_id == uploaded.file_id for item in listing.items)
    assert lifecycle.service.get_file(actor=lifecycle.actor, file_id=uploaded.file_id)
    assert (
        lifecycle.service.integrity_check(
            actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
        ).status
        == "MODIFIED"
    )


def test_downloading_a_modified_file_is_refused_rather_than_hidden(
    lifecycle: LifecycleEnvironment,
) -> None:
    """Visibility does not loosen download: the verification before the stream still bites."""
    uploaded = lifecycle.upload()
    path = lifecycle.object_path(uploaded.file_id)
    path.write_bytes(path.read_bytes()[:-1])

    with pytest.raises(IntegrityVerificationError):
        lifecycle.service.download(
            actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
        )


def test_a_temporarily_unreachable_object_does_not_change_the_stored_status(
    lifecycle: LifecycleEnvironment,
) -> None:
    """Regression: one MISSING result used to be permanent.

    An unmounted volume or a mistyped storage root was enough to strand a file whose
    ciphertext was completely intact, because the status never moved back.
    """
    uploaded = lifecycle.upload()
    path = lifecycle.object_path(uploaded.file_id)
    parked = path.with_suffix(".parked")
    path.rename(parked)

    result = lifecycle.service.integrity_check(
        actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
    )

    assert result.status == "MISSING"
    assert lifecycle.file_row(uploaded.file_id).status == "ACTIVE"

    parked.rename(path)
    assert (
        lifecycle.service.integrity_check(
            actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
        ).status
        == "VALID"
    )
    assert lifecycle.file_row(uploaded.file_id).status == "ACTIVE"
    assert lifecycle.service.download(
        actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
    ).ciphertext_size == len(uploaded.ciphertext)


def test_a_passing_recheck_restores_a_file_stranded_at_corrupted(
    lifecycle: LifecycleEnvironment,
) -> None:
    """Covers rows an older build already left at CORRUPTED: they heal, without a migration."""
    uploaded = lifecycle.upload()
    row = lifecycle.file_row(uploaded.file_id)
    lifecycle.session.execute(
        text("UPDATE files SET status = 'CORRUPTED' WHERE id = :id"), {"id": row.id}
    )
    lifecycle.session.commit()
    lifecycle.session.expire_all()

    result = lifecycle.service.integrity_check(
        actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
    )

    assert result.status == "VALID"
    assert lifecycle.file_row(uploaded.file_id).status == "ACTIVE"


# ---------------------------------------------------------------------------
# What the columns actually end up holding.
# ---------------------------------------------------------------------------


def test_the_returned_timestamp_is_the_one_the_column_holds(
    lifecycle: LifecycleEnvironment,
) -> None:
    """Regression: MySQL rounds a fractional value into a second-resolution DATETIME.

    The upload response carried microseconds the column could not hold, so it reported an
    instant that was never stored and every later read disagreed with it.
    """
    prepared = lifecycle.build_upload()
    returned = asyncio.run(
        lifecycle.service.upload(
            actor=lifecycle.actor,
            metadata=prepared.metadata,
            ciphertext=_upload_part(prepared.ciphertext),
            context=RequestContext(),
        )
    )

    stored = lifecycle.session.scalar(
        select(File.created_at).where(File.file_uuid == str(prepared.file_id))
    )
    assert stored.microsecond == 0
    assert returned.created_at == to_api_utc(stored)
    assert (
        lifecycle.service.get_file(actor=lifecycle.actor, file_id=prepared.file_id).created_at
        == returned.created_at
    )


def test_deleting_a_file_revokes_its_rows_and_takes_the_directory_with_it(
    lifecycle: LifecycleEnvironment,
) -> None:
    uploaded = lifecycle.upload()
    object_path = lifecycle.object_path(uploaded.file_id)
    object_directory = object_path.parent

    result = lifecycle.service.delete(
        actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
    )

    assert result.status == "DELETED"
    assert result.already_deleted is False
    row = lifecycle.file_row(uploaded.file_id)
    assert row.status == "DELETED"
    assert row.deleted_at is not None
    assert not object_path.exists()
    # Regression: the object was unlinked but its per-file directory stayed forever.
    assert not object_directory.exists()

    statuses = lifecycle.session.scalars(
        select(FileAccessGrant.status).where(FileAccessGrant.file_id == row.id)
    ).all()
    assert set(statuses) == {"REVOKED"}
    wrapping_statuses = lifecycle.session.scalars(
        select(FileKeyWrapping.status).where(FileKeyWrapping.file_id == row.id)
    ).all()
    assert set(wrapping_statuses) == {"REVOKED"}


def test_a_deleted_file_keeps_its_name_for_the_access_records(
    lifecycle: LifecycleEnvironment,
) -> None:
    # The records page used to ask for each deleted file's name and got a 404 every time. The
    # name is a column of the soft-deleted row, so one query returns it with the deleted flag.
    kept = lifecycle.upload()
    gone = lifecycle.upload()
    lifecycle.service.delete(actor=lifecycle.actor, file_id=gone.file_id, context=RequestContext())

    labels = AuditRepository(lifecycle.session).file_labels(
        [str(kept.file_id), str(gone.file_id), str(uuid4())]
    )

    assert set(labels) == {str(kept.file_id), str(gone.file_id)}
    assert labels[str(kept.file_id)][1] is False
    assert labels[str(gone.file_id)][1] is True
    assert labels[str(gone.file_id)][0] == lifecycle.file_row(gone.file_id).original_filename


def test_deleting_twice_is_idempotent_and_the_file_stays_gone(
    lifecycle: LifecycleEnvironment,
) -> None:
    uploaded = lifecycle.upload()
    lifecycle.service.delete(
        actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
    )

    again = lifecycle.service.delete(
        actor=lifecycle.actor, file_id=uploaded.file_id, context=RequestContext()
    )

    assert again.already_deleted is True
    with pytest.raises(FileResourceNotFoundError):
        lifecycle.service.get_file(actor=lifecycle.actor, file_id=uploaded.file_id)


# ---------------------------------------------------------------------------
# Failure paths must not leave the database and the object store disagreeing.
# ---------------------------------------------------------------------------


def test_a_reused_file_id_conflicts_and_leaves_no_second_object(
    lifecycle: LifecycleEnvironment,
) -> None:
    uploaded = lifecycle.upload()
    replay = lifecycle.build_upload()
    object_replace = replay.metadata.model_copy(update={"file_id": uploaded.file_id})

    with pytest.raises(FileStateConflictError):
        asyncio.run(
            lifecycle.service.upload(
                actor=lifecycle.actor,
                metadata=object_replace,
                ciphertext=_upload_part(replay.ciphertext),
                context=RequestContext(),
            )
        )

    assert _orphaned_objects(lifecycle) == []
    assert _staged_leftovers(lifecycle) == []
    assert lifecycle.object_path(uploaded.file_id).read_bytes() == uploaded.ciphertext


def test_a_rejected_envelope_leaves_nothing_behind(lifecycle: LifecycleEnvironment) -> None:
    """The ciphertext is staged before the size check, so this is a real cleanup path."""
    mismatched = lifecycle.build_upload(b"x" * 128, declared_size=127)

    with pytest.raises(FileEnvelopeInvalidError):
        asyncio.run(
            lifecycle.service.upload(
                actor=lifecycle.actor,
                metadata=mismatched.metadata,
                ciphertext=_upload_part(mismatched.ciphertext),
                context=RequestContext(),
            )
        )

    assert _staged_leftovers(lifecycle) == []
    assert _orphaned_objects(lifecycle) == []
    assert (
        lifecycle.session.scalar(select(File.id).where(File.file_uuid == str(mismatched.file_id)))
        is None
    )


def test_every_object_on_disk_is_named_by_a_row(lifecycle: LifecycleEnvironment) -> None:
    """Storage and database agree after a mixed run of successes and failures."""
    kept = lifecycle.upload()
    removed = lifecycle.upload()
    lifecycle.service.delete(
        actor=lifecycle.actor, file_id=removed.file_id, context=RequestContext()
    )

    assert _orphaned_objects(lifecycle) == []
    assert lifecycle.object_path(kept.file_id).is_file()


def _orphaned_objects(lifecycle: LifecycleEnvironment) -> list[str]:
    lifecycle.session.rollback()
    known = set(
        lifecycle.session.scalars(
            select(File.storage_object_key).where(File.status != "DELETED")
        ).all()
    )
    return sorted(
        str(path.relative_to(lifecycle.object_root))
        for path in lifecycle.object_root.rglob("*.ciphertext")
        if str(path.relative_to(lifecycle.object_root)) not in known
    )


def _staged_leftovers(lifecycle: LifecycleEnvironment) -> list[str]:
    staging_root = lifecycle.storage.staging_root
    if not staging_root.is_dir():
        return []
    return sorted(path.name for path in staging_root.glob("*.staging"))
