"""Shared helpers for the multi-connection concurrency and fault-injection suites.

Unlike most of `tests/integration/`, these tests need several real, independent MySQL
connections observing the same rows at once, so they cannot use connection-local temporary
tables or a single rolled-back outer transaction. They run against the permanently migrated
schema of the disposable `_test` database, the same one `test_mysql_schema_parity.py` checks.

Registered users and their audit trail are deliberately left behind rather than deleted:
`audit_logs.actor_user_id`/`target_user_id` are `ON DELETE RESTRICT`, and deleting from the
middle of the hash chain would destroy the property it exists to provide (see
`scripts/reconcile.py`). Every identity is stamped with a fresh UUID under `example.com`
so runs never collide. Recovery keys a test registers are retired (status `REVOKED`) on the
way out rather than deleted, because file wrappings still reference them.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session
from tests.integration.test_file_lifecycle_mysql import (
    _b64,
    _file_content_aad,
    _public_pem_and_fingerprint,
    _rsa_wrap,
    _upload_part,
)

from app.core.config import Settings
from app.core.time import to_second_resolution_utc, utc_now
from app.domain.auth import ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus, VerificationPurpose
from app.domain.keys import (
    ClientKeyRegistration,
    EncryptedPrivateKeyBundleInput,
    KeyProtectionProfileInput,
)
from app.models.recovery_key import RecoveryKey
from app.models.user import User
from app.schemas.file_schema import FileUploadMetadata
from app.services.audit_log_service import AuditLogService
from app.services.auth_service import AuthService
from app.services.email_service import OutboundEmail
from app.services.file_service import FileService
from app.services.file_storage_service import FileStorageService

KEY_SIZE_BITS = 2048  # Smaller than production on purpose: every test mints fresh keys.
VERIFICATION_CODE = "135790"


def integration_settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        APP_DEBUG=False,
        SECRET_KEY="concurrency-integration-test-secret-key-32chars",
        USER_RSA_KEY_SIZE=KEY_SIZE_BITS,
        **overrides,
    )


class _DiscardingEmail:
    """The code is fixed by `code_factory`, so nothing needs to read the message."""

    def send(self, message: OutboundEmail) -> None:
        del message


def fresh_ip() -> str:
    """A random TEST-NET address, so tests do not share a per-IP throttle bucket."""
    value = uuid4().int
    return f"198.51.{value % 256}.{(value >> 8) % 254 + 1}"


def request_context(*, ip_address: str | None = None) -> RequestContext:
    return RequestContext(ip_address=ip_address or fresh_ip(), user_agent="concurrency-suite")


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """A fresh connection and session per caller -- the whole point of these tests."""
    connection = engine.connect()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        connection.close()


def race(fn: Callable[[int], Any], workers: int) -> list[Any]:
    """Run `fn(0..workers-1)` on real threads released together by a barrier.

    Each call is expected to open its own session. Exceptions are returned in place of
    results so a test can classify every outcome rather than stopping at the first.
    """
    barrier = threading.Barrier(workers)

    def released(index: int) -> Any:
        barrier.wait(timeout=30)
        try:
            return fn(index)
        except Exception as exc:
            return exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(released, range(workers)))


def outcome_names(results: Sequence[Any]) -> list[str]:
    return sorted("ok" if not isinstance(r, Exception) else type(r).__name__ for r in results)


@dataclass(frozen=True, slots=True)
class RegisteredUser:
    user_id: int
    user_uuid: UUID
    username: str
    # Kept out of repr so a failing assertion cannot print them into a test report.
    password: str = field(repr=False)
    private_key: rsa.RSAPrivateKey = field(repr=False)
    public_key_pem: str = field(repr=False)
    key_id: UUID
    profile_id: UUID
    bundle_id: UUID
    role: SystemRole

    def actor(self) -> ActorContext:
        return ActorContext(
            user_id=self.user_id,
            user_public_id=self.user_uuid,
            session_id=0,
            session_public_id=uuid4(),
            role=self.role,
            status=UserStatus.ACTIVE,
            access_token_hash="0" * 64,
        )


def _client_key_material(
    *, key_id: UUID, profile_id: UUID, bundle_id: UUID, public_key_pem: str
) -> ClientKeyRegistration:
    # The server never opens these envelopes, so fixed stand-in bytes of the right shape
    # are enough; the RSA key pair, which the server does use, is real.
    encrypted_private_key = b"concurrency-suite-encrypted-pkcs8-stand-in" * 5
    return ClientKeyRegistration(
        key_id=key_id,
        public_key_pem=public_key_pem,
        algorithm="RSA-OAEP-SHA256",
        key_size_bits=KEY_SIZE_BITS,
        protection=KeyProtectionProfileInput(
            profile_id=profile_id,
            format_version=1,
            kdf_algorithm="ARGON2ID",
            kdf_version=19,
            kdf_salt=b"s" * 16,
            kdf_memory_kib=65_536,
            kdf_iterations=3,
            kdf_parallelism=4,
            derived_key_length=32,
            amk_wrapping_algorithm="AES-256-GCM",
            wrapped_amk=b"w" * 32,
            amk_nonce=b"n" * 12,
            amk_auth_tag=b"t" * 16,
            aad_version=1,
        ),
        private_key_bundle=EncryptedPrivateKeyBundleInput(
            bundle_id=bundle_id,
            format_version=1,
            private_key_format="PKCS8-DER",
            derivation_algorithm="HKDF-SHA256",
            derivation_salt=b"d" * 16,
            encryption_algorithm="AES-256-GCM",
            encrypted_private_key=encrypted_private_key,
            nonce=b"i" * 12,
            auth_tag=b"a" * 16,
            aad_version=1,
            ciphertext_sha256=hashlib.sha256(encrypted_private_key).hexdigest(),
        ),
    )


def register_real_user(
    engine: Engine, *, prefix: str, role: SystemRole = SystemRole.USER
) -> RegisteredUser:
    """Commit a real account through the same `AuthService.register` the API calls."""
    username = f"{prefix}-{uuid4().hex[:16]}"
    email = f"{username}@example.com"
    password = f"Pw!{uuid4().hex}"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE_BITS)
    public_key_pem, _fingerprint = _public_pem_and_fingerprint(private_key)
    key_id, profile_id, bundle_id = uuid4(), uuid4(), uuid4()

    with session_scope(engine) as session:
        service = AuthService(db=session, settings=integration_settings())
        service.verification.email = _DiscardingEmail()
        service.verification.code_factory = lambda _length: VERIFICATION_CODE
        # Registration is throttled per source IP; a fresh one keeps repeated local runs
        # from exhausting a shared bucket.
        context = request_context()
        service.send_verification_code(
            purpose=VerificationPurpose.REGISTRATION, email=email, context=context
        )
        service.register(
            username=username,
            email=email,
            password=password,
            verification_code=VERIFICATION_CODE,
            key_material=_client_key_material(
                key_id=key_id,
                profile_id=profile_id,
                bundle_id=bundle_id,
                public_key_pem=public_key_pem,
            ),
            context=context,
        )
        if role is not SystemRole.USER:
            # There is no API that grants a role, by design; an operator does it in SQL.
            session.execute(update(User).where(User.username == username).values(role=role))
            session.commit()
        row = session.scalar(select(User).where(User.username == username))
        assert row is not None
        return RegisteredUser(
            user_id=row.id,
            user_uuid=UUID(str(row.user_uuid)),
            username=username,
            password=password,
            private_key=private_key,
            public_key_pem=public_key_pem,
            key_id=key_id,
            profile_id=profile_id,
            bundle_id=bundle_id,
            role=role,
        )


def sign_rsa_pss_sha256(private_key: rsa.RSAPrivateKey, message: bytes) -> bytes:
    # Must match CryptoService.verify_rsa_pss_sha256_signature's fixed salt length.
    return private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256.digest_size),
        hashes.SHA256(),
    )


def rsa_unwrap(private_key: rsa.RSAPrivateKey, wrapped: bytes) -> bytes:
    return private_key.decrypt(
        wrapped,
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )


def rsa_wrap(public_key_pem: str, dek: bytes) -> bytes:
    return _rsa_wrap(public_key_pem, dek)


@dataclass(frozen=True, slots=True)
class RecoveryKeyPair:
    key_id: UUID
    private_key: rsa.RSAPrivateKey = field(repr=False)
    public_key_pem: str = field(repr=False)


@contextmanager
def active_recovery_key(engine: Engine) -> Iterator[RecoveryKeyPair]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE_BITS)
    pem, fingerprint = _public_pem_and_fingerprint(private_key)
    key_id = uuid4()
    with session_scope(engine) as session:
        session.add(
            RecoveryKey(
                key_uuid=str(key_id),
                public_key_pem=pem,
                algorithm="RSA-OAEP-SHA256",
                key_size_bits=KEY_SIZE_BITS,
                fingerprint=fingerprint,
                status="ACTIVE",
            )
        )
        session.commit()
    try:
        yield RecoveryKeyPair(key_id=key_id, private_key=private_key, public_key_pem=pem)
    finally:
        with session_scope(engine) as session:
            session.execute(
                update(RecoveryKey)
                .where(RecoveryKey.key_uuid == str(key_id))
                .values(status="REVOKED", revoked_at=to_second_resolution_utc(utc_now()))
            )
            session.commit()


def file_service(session: Session, storage_root: Path) -> FileService:
    settings = integration_settings(
        ENCRYPTED_FILE_DIR=storage_root / "objects",
        TEMP_FILE_DIR=storage_root / "staging",
    )
    return FileService(
        db=session,
        settings=settings,
        storage=FileStorageService(settings=settings),
        audit_service=AuditLogService(session),
    )


@dataclass(frozen=True, slots=True)
class UploadedFile:
    file_id: UUID
    dek: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)


def build_upload(
    owner: RegisteredUser,
    recovery: RecoveryKeyPair,
    plaintext: bytes = b"synthetic fixture bytes, not a real document",
) -> tuple[FileUploadMetadata, UploadedFile]:
    """Encrypt exactly as the browser does, wrapping the DEK to the owner and recovery."""
    file_id = uuid4()
    dek = AESGCM.generate_key(bit_length=256)
    nonce = uuid4().bytes[:12]
    aad = _file_content_aad(
        file_id=file_id,
        filename="fixture.bin",
        plaintext_size=len(plaintext),
        mime="application/octet-stream",
    )
    sealed = AESGCM(dek).encrypt(nonce, plaintext, aad)
    ciphertext, auth_tag = sealed[:-16], sealed[-16:]
    metadata = FileUploadMetadata(
        file_id=file_id,
        original_filename="fixture.bin",
        plaintext_size=len(plaintext),
        mime_type="application/octet-stream",
        nonce=_b64(nonce),
        auth_tag=_b64(auth_tag),
        owner_key_id=owner.key_id,
        wrapped_file_key=_b64(rsa_wrap(owner.public_key_pem, dek)),
        recovery_key_id=recovery.key_id,
        recovery_wrapped_file_key=_b64(rsa_wrap(recovery.public_key_pem, dek)),
    )
    return metadata, UploadedFile(file_id=file_id, dek=dek, ciphertext=ciphertext)


def run_upload(
    service: FileService,
    owner: RegisteredUser,
    metadata: FileUploadMetadata,
    ciphertext: bytes,
) -> None:
    asyncio.run(
        service.upload(
            actor=owner.actor(),
            metadata=metadata,
            ciphertext=_upload_part(ciphertext),
            context=request_context(),
        )
    )


def upload_file(
    engine: Engine, storage_root: Path, owner: RegisteredUser, recovery: RecoveryKeyPair
) -> UploadedFile:
    metadata, uploaded = build_upload(owner, recovery)
    with session_scope(engine) as session:
        run_upload(file_service(session, storage_root), owner, metadata, uploaded.ciphertext)
    return uploaded
