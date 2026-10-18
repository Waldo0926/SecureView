"""Real faults injected into the upload, delete, and key-custody paths (issue #58).

Nothing here makes a function raise by replacing it. Each failure is one the system can
actually meet in production, produced by the mechanism that would really cause it:

* the database connection is killed by the server at the moment of COMMIT;
* the object store refuses a write or an unlink because the path is not what it expects;
* a client sends an envelope or a signature that is malformed, truncated, or forged;
* a client acts on a revision another client has already moved past.

The assertions are about what is left behind afterwards -- rows, objects, staged bytes,
the audit chain -- because that is where a mishandled failure does its damage.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from tests.integration._concurrency_support import (
    RecoveryKeyPair,
    RegisteredUser,
    active_recovery_key,
    build_upload,
    file_service,
    integration_settings,
    register_real_user,
    request_context,
    run_upload,
    session_scope,
    sign_rsa_pss_sha256,
    upload_file,
)
from tests.integration.test_file_lifecycle_mysql import _b64

from app.domain.errors import (
    FileEnvelopeInvalidError,
    KeyBundleInvalidError,
    KeyBundleRevisionConflictError,
    ShareStateConflictError,
    StorageUnavailableError,
)
from app.domain.keys import KeyProtectionProfileInput
from app.models.audit_chain_head import AuditChainHead
from app.models.file import File
from app.models.file_access_grant import FileAccessGrant
from app.models.user_key_protection_profile import UserKeyProtectionProfile
from app.services.audit_query_service import AuditQueryService
from app.services.key_service import KeyService
from app.services.sharing_service import SharingService

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _load_reconcile():
    spec = importlib.util.spec_from_file_location(
        "reconcile_under_test", BACKEND_ROOT / "scripts" / "reconcile.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` looks its own module up in sys.modules while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _chain_head(engine: Engine) -> tuple[int | None, str | None]:
    with session_scope(engine) as session:
        head = session.scalar(select(AuditChainHead).where(AuditChainHead.id == 1))
        assert head is not None
        return head.last_log_id, head.current_hash


def _chain_is_valid(engine: Engine, admin: RegisteredUser) -> bool:
    with session_scope(engine) as session:
        return AuditQueryService(db=session).verify_chain(actor=admin.actor())["valid"] is True


def _file_row(engine: Engine, file_id) -> File | None:
    with session_scope(engine) as session:
        return session.scalar(select(File).where(File.file_uuid == str(file_id)))


def _objects(root: Path) -> list[Path]:
    objects = root / "objects"
    return sorted(objects.rglob("*.ciphertext")) if objects.is_dir() else []


def _staged(root: Path) -> list[Path]:
    staging = root / "staging"
    return sorted(staging.glob("*")) if staging.is_dir() else []


@pytest.fixture(scope="module")
def admin(auth_mysql_engine: Engine) -> RegisteredUser:
    from app.domain.enums import SystemRole

    return register_real_user(auth_mysql_engine, prefix="fault-admin", role=SystemRole.ADMIN)


@pytest.fixture
def owner(auth_mysql_engine: Engine) -> RegisteredUser:
    return register_real_user(auth_mysql_engine, prefix="fault-owner")


@pytest.fixture
def recovery(auth_mysql_engine: Engine) -> Iterator[RecoveryKeyPair]:
    with active_recovery_key(auth_mysql_engine) as pair:
        yield pair


# ---------------------------------------------------------------------------
# Storage publish / commit ordering, and what reconcile.py does about it.
# ---------------------------------------------------------------------------


def test_a_connection_killed_at_commit_leaves_no_row_and_an_orphan_reconcile_removes(
    auth_mysql_engine: Engine,
    tmp_path: Path,
    owner: RegisteredUser,
    recovery: RecoveryKeyPair,
    admin: RegisteredUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure `FileService.upload` names in its own comment, produced for real.

    The ciphertext is published before COMMIT. Here the server kills the connection the
    instant COMMIT is issued, so the client never learns the outcome. The service must not
    delete the object -- from where it stands the commit may have landed -- and MySQL must
    have rolled everything back, the flushed audit entry included. The result is exactly
    one orphaned object, which is what `scripts/reconcile.py` exists to find.
    """
    metadata, uploaded = build_upload(owner, recovery)
    head_before = _chain_head(auth_mysql_engine)

    with session_scope(auth_mysql_engine) as session:
        victim = session.connection()
        connection_id = victim.exec_driver_sql("SELECT CONNECTION_ID()").scalar_one()
        session.commit()

        # Kill at the COMMIT that would persist the file row, not at an earlier read-only
        # commit (the upload releases its connection before staging the ciphertext).
        wrote_file_row = False

        def note_file_insert(_conn, _cursor, statement, *_args) -> None:
            nonlocal wrote_file_row
            if statement.lstrip().upper().startswith("INSERT INTO FILES"):
                wrote_file_row = True

        def kill_at_commit(_conn) -> None:
            if not wrote_file_row:
                return
            with auth_mysql_engine.connect() as killer:
                killer.exec_driver_sql(f"KILL CONNECTION {int(connection_id)}")

        event.listen(victim, "before_cursor_execute", note_file_insert)
        event.listen(victim, "commit", kill_at_commit)
        with pytest.raises(DBAPIError):
            run_upload(file_service(session, tmp_path), owner, metadata, uploaded.ciphertext)

    assert _file_row(auth_mysql_engine, uploaded.file_id) is None
    assert _chain_head(auth_mysql_engine) == head_before
    assert _chain_is_valid(auth_mysql_engine, admin)
    assert _staged(tmp_path) == []
    orphans = _objects(tmp_path)
    assert len(orphans) == 1 and orphans[0].parent.name == str(uploaded.file_id)
    assert orphans[0].read_bytes() == uploaded.ciphertext

    reconcile = _load_reconcile()
    storage_settings = integration_settings(
        ENCRYPTED_FILE_DIR=tmp_path / "objects", TEMP_FILE_DIR=tmp_path / "staging"
    )
    monkeypatch.setattr(reconcile, "get_settings", lambda: storage_settings)
    monkeypatch.setattr(
        reconcile, "SessionLocal", sessionmaker(bind=auth_mysql_engine, expire_on_commit=False)
    )

    def orphan_count(report) -> int:
        return next(f.count for f in report.findings if f.what == "orphaned ciphertext objects")

    # Inside the grace window the object could still belong to an in-flight upload.
    assert (
        orphan_count(reconcile.reconcile(retain_days=30, storage_grace_minutes=60, apply=True)) == 0
    )
    assert orphans[0].exists()

    # Age it past the window, as time would.
    two_hours_ago = time.time() - 2 * 3600
    os.utime(orphans[0], (two_hours_ago, two_hours_ago))
    assert (
        orphan_count(reconcile.reconcile(retain_days=30, storage_grace_minutes=60, apply=False))
        == 1
    )
    assert orphans[0].exists(), "a report-only run deleted something"

    assert (
        orphan_count(reconcile.reconcile(retain_days=30, storage_grace_minutes=60, apply=True)) == 1
    )
    assert not orphans[0].exists()
    # Unlinking the object refreshed its directory's mtime, so the directory is inside the
    # grace again -- a retried upload under the same file_id may be about to reuse it. A
    # later run, once the directory has aged, removes it.
    assert orphans[0].parent.is_dir()
    os.utime(orphans[0].parent, (two_hours_ago, two_hours_ago))
    reconcile.reconcile(retain_days=30, storage_grace_minutes=60, apply=True)
    assert not orphans[0].parent.exists()


def test_a_publish_failure_rolls_back_the_row_the_audit_entry_and_the_staged_bytes(
    auth_mysql_engine: Engine,
    tmp_path: Path,
    owner: RegisteredUser,
    recovery: RecoveryKeyPair,
    admin: RegisteredUser,
) -> None:
    """The object store refuses the write after the rows and audit entry are flushed.

    A regular file already occupies the path where the per-file directory must go, so the
    publish fails exactly as it would on a corrupted or misconfigured volume. By then the
    service has flushed the file row, two wrappings, the grant, and an audit entry that
    advanced the chain head; all of it must roll back, and the staged ciphertext must go.
    """
    metadata, uploaded = build_upload(owner, recovery)
    (tmp_path / "objects").mkdir(parents=True)
    (tmp_path / "objects" / str(uploaded.file_id)).write_bytes(b"not a directory")
    head_before = _chain_head(auth_mysql_engine)

    with session_scope(auth_mysql_engine) as session, pytest.raises(StorageUnavailableError):
        run_upload(file_service(session, tmp_path), owner, metadata, uploaded.ciphertext)

    assert _file_row(auth_mysql_engine, uploaded.file_id) is None
    assert _chain_head(auth_mysql_engine) == head_before
    assert _chain_is_valid(auth_mysql_engine, admin)
    assert _staged(tmp_path) == []
    assert _objects(tmp_path) == []


def test_a_failed_unlink_after_delete_is_reported_and_a_retry_finishes_the_job(
    auth_mysql_engine: Engine,
    tmp_path: Path,
    owner: RegisteredUser,
    recovery: RecoveryKeyPair,
) -> None:
    """The soft delete is durable before cleanup; a cleanup failure must not undo it.

    The object is swapped for a non-empty directory of the same name, which no unlink can
    remove. The caller hears about it, the row still says DELETED, and once the obstacle is
    gone a plain retry removes the object and its directory.
    """
    uploaded = upload_file(auth_mysql_engine, tmp_path, owner, recovery)
    [object_path] = _objects(tmp_path)
    parked = tmp_path / "parked.ciphertext"
    object_path.rename(parked)
    object_path.mkdir()
    (object_path / "occupant").write_bytes(b"x")

    with session_scope(auth_mysql_engine) as session, pytest.raises(StorageUnavailableError):
        file_service(session, tmp_path).delete(
            actor=owner.actor(), file_id=uploaded.file_id, context=request_context()
        )

    row = _file_row(auth_mysql_engine, uploaded.file_id)
    assert row is not None and row.status == "DELETED"

    (object_path / "occupant").unlink()
    object_path.rmdir()
    parked.rename(object_path)
    with session_scope(auth_mysql_engine) as session:
        retried = file_service(session, tmp_path).delete(
            actor=owner.actor(), file_id=uploaded.file_id, context=request_context()
        )

    assert retried.already_deleted is True
    assert not object_path.exists()
    assert not object_path.parent.exists()


# ---------------------------------------------------------------------------
# Invalid envelopes are rejected before anything is kept.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "corruption",
    [
        "truncated_owner_wrapping",
        "oversized_recovery_wrapping",
        "someone_elses_key",
        "retired_recovery_key",
    ],
)
def test_a_malformed_upload_envelope_is_refused_and_leaves_nothing_behind(
    auth_mysql_engine: Engine,
    tmp_path: Path,
    owner: RegisteredUser,
    recovery: RecoveryKeyPair,
    corruption: str,
) -> None:
    metadata, uploaded = build_upload(owner, recovery)
    if corruption == "truncated_owner_wrapping":
        metadata = metadata.model_copy(
            update={"wrapped_file_key": _b64(metadata.wrapped_file_key_bytes()[:-1])}
        )
    elif corruption == "oversized_recovery_wrapping":
        metadata = metadata.model_copy(
            update={
                "recovery_wrapped_file_key": _b64(
                    metadata.recovery_wrapped_file_key_bytes() + b"\0"
                )
            }
        )
    elif corruption == "someone_elses_key":
        stranger = register_real_user(auth_mysql_engine, prefix="fault-stranger")
        metadata = metadata.model_copy(update={"owner_key_id": stranger.key_id})
    else:
        with active_recovery_key(auth_mysql_engine) as retired:
            pass  # Leaving the block revokes it.
        metadata = metadata.model_copy(update={"recovery_key_id": retired.key_id})

    with session_scope(auth_mysql_engine) as session, pytest.raises(FileEnvelopeInvalidError):
        run_upload(file_service(session, tmp_path), owner, metadata, uploaded.ciphertext)

    assert _file_row(auth_mysql_engine, uploaded.file_id) is None
    assert _staged(tmp_path) == []
    assert _objects(tmp_path) == []


def test_a_share_with_a_malformed_wrapped_key_grants_nothing(
    auth_mysql_engine: Engine,
    tmp_path: Path,
    owner: RegisteredUser,
    recovery: RecoveryKeyPair,
) -> None:
    recipient = register_real_user(auth_mysql_engine, prefix="fault-share-r")
    uploaded = upload_file(auth_mysql_engine, tmp_path, owner, recovery)
    head_before = _chain_head(auth_mysql_engine)

    with session_scope(auth_mysql_engine) as session, pytest.raises(ShareStateConflictError):
        SharingService(db=session).share(
            actor=owner.actor(),
            file_id=uploaded.file_id,
            target_user_id=recipient.user_uuid,
            target_key_id=recipient.key_id,
            wrapped_file_key=b"\x01" * 100,  # Not the 256 bytes a 2048-bit key produces.
            can_download=True,
            can_share=False,
            context=request_context(),
        )

    with session_scope(auth_mysql_engine) as session:
        grants = session.scalars(
            select(FileAccessGrant).where(FileAccessGrant.user_id == recipient.user_id)
        ).all()
    assert grants == []
    assert _chain_head(auth_mysql_engine) == head_before


# ---------------------------------------------------------------------------
# Signatures, and optimistic conflicts on the key-custody rows.
# ---------------------------------------------------------------------------


def _profile_input(user: RegisteredUser, salt: bytes) -> KeyProtectionProfileInput:
    return KeyProtectionProfileInput(
        profile_id=user.profile_id,
        format_version=1,
        kdf_algorithm="ARGON2ID",
        kdf_version=19,
        kdf_salt=salt,
        kdf_memory_kib=65_536,
        kdf_iterations=3,
        kdf_parallelism=4,
        derived_key_length=32,
        amk_wrapping_algorithm="AES-256-GCM",
        wrapped_amk=b"W" * 32,
        amk_nonce=b"N" * 12,
        amk_auth_tag=b"T" * 16,
        aad_version=1,
    )


def _revision(engine: Engine, user: RegisteredUser) -> int:
    with session_scope(engine) as session:
        revision = session.scalar(
            select(UserKeyProtectionProfile.revision).where(
                UserKeyProtectionProfile.user_id == user.user_id
            )
        )
    assert revision is not None
    return revision


def _payload(engine: Engine, user: RegisteredUser, revision: int, salt: bytes) -> bytes:
    with session_scope(engine) as session:
        payload = KeyService(
            db=session, settings=integration_settings()
        ).get_rewrap_signing_payload(
            actor=user.actor(),
            authorizing_key_id=user.key_id,
            expected_revision=revision,
            protection=_profile_input(user, salt),
        )
        session.rollback()
    return payload


def _submit(engine: Engine, user: RegisteredUser, revision: int, salt: bytes, signature: bytes):
    with session_scope(engine) as session:
        return KeyService(db=session, settings=integration_settings()).rewrap_protection_profile(
            actor=user.actor(),
            authorizing_key_id=user.key_id,
            expected_revision=revision,
            protection=_profile_input(user, salt),
            authorization_signature=signature,
            context=request_context(),
        )


@pytest.mark.parametrize("forgery", ["one_flipped_byte", "signed_by_another_key", "other_payload"])
def test_a_forged_rewrap_signature_changes_nothing(
    auth_mysql_engine: Engine, owner: RegisteredUser, forgery: str
) -> None:
    """Without proof of the private key, a stolen session cannot overwrite the envelope."""
    revision = _revision(auth_mysql_engine, owner)
    salt = uuid4().bytes
    payload = _payload(auth_mysql_engine, owner, revision, salt)
    if forgery == "one_flipped_byte":
        signature = bytearray(sign_rsa_pss_sha256(owner.private_key, payload))
        signature[len(signature) // 2] ^= 0x01
        signature = bytes(signature)
    elif forgery == "signed_by_another_key":
        other = register_real_user(auth_mysql_engine, prefix="fault-sig-other")
        signature = sign_rsa_pss_sha256(other.private_key, payload)
    else:
        # A genuine signature, but over a different salt than the one submitted.
        signature = sign_rsa_pss_sha256(
            owner.private_key, _payload(auth_mysql_engine, owner, revision, uuid4().bytes)
        )
    head_before = _chain_head(auth_mysql_engine)

    with pytest.raises(KeyBundleInvalidError):
        _submit(auth_mysql_engine, owner, revision, salt, signature)

    assert _revision(auth_mysql_engine, owner) == revision
    assert _chain_head(auth_mysql_engine) == head_before


def test_a_client_that_lost_an_optimistic_conflict_recovers_by_refetching(
    auth_mysql_engine: Engine, owner: RegisteredUser
) -> None:
    """A stale revision is refused without side effects; refetch, re-sign, and it lands."""
    start = _revision(auth_mysql_engine, owner)
    first_salt, stale_salt = uuid4().bytes, uuid4().bytes
    first_signature = sign_rsa_pss_sha256(
        owner.private_key, _payload(auth_mysql_engine, owner, start, first_salt)
    )
    stale_signature = sign_rsa_pss_sha256(
        owner.private_key, _payload(auth_mysql_engine, owner, start, stale_salt)
    )
    _submit(auth_mysql_engine, owner, start, first_salt, first_signature)

    head_before = _chain_head(auth_mysql_engine)
    with pytest.raises(KeyBundleRevisionConflictError):
        _submit(auth_mysql_engine, owner, start, stale_salt, stale_signature)
    assert _chain_head(auth_mysql_engine) == head_before

    current = _revision(auth_mysql_engine, owner)
    assert current == start + 1
    fresh_signature = sign_rsa_pss_sha256(
        owner.private_key, _payload(auth_mysql_engine, owner, current, stale_salt)
    )
    profile = _submit(auth_mysql_engine, owner, current, stale_salt, fresh_signature)
    assert profile.revision == start + 2
    assert profile.kdf_salt == stale_salt
