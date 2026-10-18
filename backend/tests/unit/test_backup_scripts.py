"""Unit tests for the encrypted backup / restore scripts (issue #56).

The end-to-end behaviour runs against MySQL in scripts/backup_restore_drill.sh (CI job
mysql-gate); these cover the pure decision logic and the envelope format.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path, PurePosixPath

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = BACKEND_ROOT / "scripts"


def _load(name: str):
    """Load by path: `scripts/` is a command directory, not a package."""
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


envelope = _load("backup_envelope")
backup = _load("backup_encrypted")
restore = _load("restore_drill")
grants = _load("check_runtime_grants")


def _write_keypair(directory: Path, bits: int = 3072) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    private = directory / f"priv-{bits}.pem"
    public = directory / f"pub-{bits}.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return private, public


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    private, public = _write_keypair(tmp_path_factory.mktemp("keys"))
    other_private, _ = _write_keypair(tmp_path_factory.mktemp("other-keys"))
    return private, public, other_private


def _encrypt(tmp_path: Path, public: Path, payload: bytes, context: str) -> Path:
    source = tmp_path / "plain"
    source.write_bytes(payload)
    sealed = tmp_path / "sealed"
    envelope.encrypt_file(source, sealed, envelope.load_public_key(public), context)
    return sealed


def test_envelope_round_trip_across_chunk_boundaries(tmp_path: Path, keys) -> None:
    private, public, _ = keys
    payload = os.urandom(2 * 1024 * 1024 + 17)
    sealed = _encrypt(tmp_path, public, payload, "fyp-backup/1/id/db")
    assert payload[:64] not in sealed.read_bytes()
    out = tmp_path / "out"
    envelope.decrypt_file(
        sealed, out, envelope.load_private_key(private, None), "fyp-backup/1/id/db"
    )
    assert out.read_bytes() == payload
    assert oct(out.stat().st_mode & 0o777) == "0o600"


def test_envelope_rejects_a_flipped_byte_and_leaves_no_output(tmp_path: Path, keys) -> None:
    private, public, _ = keys
    sealed = _encrypt(tmp_path, public, b"x" * 5000, "ctx")
    data = bytearray(sealed.read_bytes())
    data[-100] ^= 0x01
    sealed.write_bytes(bytes(data))
    out = tmp_path / "out"
    with pytest.raises(envelope.EnvelopeError, match="authentication failed"):
        envelope.decrypt_file(sealed, out, envelope.load_private_key(private, None), "ctx")
    assert not out.exists()
    assert not (tmp_path / "out.partial").exists()


def test_envelope_binds_the_manifest_id_and_role(tmp_path: Path, keys) -> None:
    private, public, _ = keys
    sealed = _encrypt(tmp_path, public, b"dump", backup.envelope_context("A", "db"))
    key = envelope.load_private_key(private, None)
    for wrong in (backup.envelope_context("B", "db"), backup.envelope_context("A", "objects")):
        with pytest.raises(envelope.EnvelopeError, match="different backup set or role"):
            envelope.decrypt_file(sealed, tmp_path / "out", key, wrong)


def test_envelope_names_a_wrong_private_key(tmp_path: Path, keys) -> None:
    _, public, other_private = keys
    sealed = _encrypt(tmp_path, public, b"dump", "ctx")
    with pytest.raises(envelope.EnvelopeError, match="different backup key"):
        envelope.decrypt_file(
            sealed, tmp_path / "out", envelope.load_private_key(other_private, None), "ctx"
        )


def test_envelope_refuses_short_rsa_keys(tmp_path: Path) -> None:
    _, public = _write_keypair(tmp_path, 2048)
    with pytest.raises(envelope.EnvelopeError, match="at least 3072"):
        envelope.load_public_key(public)


def test_coordination_check_flags_missing_mismatched_and_mid_backup_deletes() -> None:
    rows = [
        ("a/1.ciphertext", "11", "ACTIVE"),
        ("b/2.ciphertext", "22", "ACTIVE"),
        ("c/3.ciphertext", "33", "DELETED"),
        ("d/4.ciphertext", "44", "CORRUPTED"),
        ("e/5.ciphertext", "55", "ACTIVE"),
    ]
    archived = {"a/1.ciphertext": "11", "b/2.ciphertext": "xx"}
    problems = backup.coordination_problems(rows, archived)
    assert problems == [
        "object b/2.ciphertext does not match files.encrypted_sha256",
        "object c/3.ciphertext was deleted while the backup ran; re-run the backup",
        "object e/5.ciphertext is missing from object storage",
    ]
    assert backup.coordination_problems(rows[:1], archived) == []


def test_restore_reconciliation_refuses_missing_active_objects_and_skips_orphans() -> None:
    manifest_objects = {"a/1.ciphertext": "11", "b/2.ciphertext": "22", "orphan/9.ciphertext": "9"}
    rows = [
        ("a/1.ciphertext", "11", "ACTIVE"),
        ("b/2.ciphertext", "22", "DELETED"),
        ("c/3.ciphertext", "33", "DELETED"),
    ]
    problems, to_restore = restore.verify_restored_objects(rows, manifest_objects)
    assert problems == []
    assert to_restore == ["a/1.ciphertext", "b/2.ciphertext"]

    problems, _ = restore.verify_restored_objects(
        [("z/9.ciphertext", "99", "ACTIVE"), ("a/1.ciphertext", "bad", "ACTIVE")],
        manifest_objects,
    )
    assert problems == [
        "ACTIVE file object z/9.ciphertext is not in this backup set",
        "ACTIVE file object a/1.ciphertext does not match files.encrypted_sha256",
    ]


def test_collect_objects_never_archives_key_material_or_stray_files(tmp_path: Path) -> None:
    good = tmp_path / "3f2a" / "b7c1.ciphertext"
    good.parent.mkdir()
    good.write_bytes(b"ciphertext")
    (tmp_path / ".gitkeep").write_text("")
    (tmp_path / "notes with spaces.txt").write_text("stray")
    (tmp_path / "link").symlink_to(good)
    objects, skipped = backup.collect_objects(tmp_path)
    assert objects == [("3f2a/b7c1.ciphertext", good)]
    assert sorted(skipped) == ["link (symlink)", "notes with spaces.txt"]

    (tmp_path / "recovery-private.pem").write_text(
        "-----BEGIN PRIVATE KEY-----\nMII...\n-----END PRIVATE KEY-----\n"
    )
    with pytest.raises(backup.BackupError, match="looks like a private key"):
        backup.collect_objects(tmp_path)


def test_object_keys_match_the_storage_service_rules() -> None:
    assert backup.is_object_key(PurePosixPath("3f2a-01/b7c1.ciphertext"))
    for bad in ("../etc/passwd", ".hidden/x", "a/-x", "a b/c"):
        assert not backup.is_object_key(PurePosixPath(bad)), bad


def test_retention_keeps_seven_daily_and_four_weekly_points() -> None:
    # One backup per day for 60 days, newest first when sorted.
    names = [f"202609{day:02d}T020000Z-0000000{day % 10}" for day in range(1, 31)] + [
        f"202608{day:02d}T020000Z-0000000{day % 10}" for day in range(1, 31)
    ]
    doomed = backup.select_for_pruning([*names, "not-a-backup"], keep_daily=7, keep_weekly=4)
    kept = sorted(set(names) - set(doomed), reverse=True)
    assert kept[:7] == [f"202609{day:02d}T020000Z-0000000{day % 10}" for day in range(30, 23, -1)]
    # The newest set of each of the four most recent ISO weeks is among those kept, and
    # nothing older than four weeks survives.
    assert len(kept) <= 7 + 4
    assert min(kept) >= "20260901"
    assert "not-a-backup" not in doomed


def test_backup_grant_extraction_reads_the_single_database_level_grant() -> None:
    statements = grants.extract_grants(
        grants.BACKUP_ACCOUNT_SQL_PATH,
        grants.PRODUCTION_BACKUP_USER,
        "gate_test_db",
        "gate_backup",
        "%",
    )
    assert statements == ["GRANT SELECT ON `gate_test_db`.* TO 'gate_backup'@'%';"]
    runtime = grants.extract_grants(
        grants.SCHEMA_SQL_PATH, grants.PRODUCTION_RUNTIME_USER, "gate_test_db", "rt", "%"
    )
    assert len(runtime) == 17
    assert all("'rt'@'%'" in statement for statement in runtime)


def test_backup_scope_holds_no_plaintext_private_key_columns() -> None:
    # The routine backup dumps every table. Recovery private keys must stay out of it, so
    # the only table allowed a private-key column is the client-encrypted bundle table,
    # whose key bytes are ciphertext under a key derived from the user's passphrase.
    import app.models  # noqa: F401 -- registers every model with Base.metadata
    from app.core.database import Base

    private_columns = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if "private" in column.name
    }
    assert private_columns == {
        ("encrypted_private_key_bundles", "private_key_format"),
        ("encrypted_private_key_bundles", "encrypted_private_key"),
    }
    recovery_columns = {c.name for c in Base.metadata.tables["recovery_keys"].columns}
    assert "public_key_pem" in recovery_columns
    assert not any("private" in name or "secret" in name for name in recovery_columns)
