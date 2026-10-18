"""Putting one object back from an encrypted backup set: what it accepts and what it refuses.

The sets here are built with the real envelope code and the same manifest layout
`backup_encrypted.py` writes, so the checks run against the actual formats.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
from pathlib import Path, PurePosixPath

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


envelope = _load("backup_envelope")
backup = _load("backup_encrypted")
restore_file = _load("restore_file")

MANIFEST_ID = "20261001T020000Z-3f9c2a1b"
OBJECT_KEY = "11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222.ciphertext"
ORIGINAL = b"the original ciphertext bytes " * 40
OTHER_KEY = "33333333-3333-4333-8333-333333333333/44444444-4444-4444-8444-444444444444.ciphertext"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def keypair(tmp_path_factory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return key, key.public_key()


def _build_set(
    root: Path,
    public,
    *,
    objects: dict[str, bytes],
    manifest_overrides: dict | None = None,
    manifest_id: str = MANIFEST_ID,
) -> Path:
    set_dir = root / manifest_id
    set_dir.mkdir(parents=True)
    work = root / "work"
    work.mkdir()
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w", format=tarfile.PAX_FORMAT) as tar:
        marker = (manifest_id + "\n").encode()
        info = tarfile.TarInfo("MANIFEST_ID")
        info.size = len(marker)
        tar.addfile(info, io.BytesIO(marker))
        for key, data in objects.items():
            info = tarfile.TarInfo(f"objects/{key}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    manifest = {
        "format": 1,
        "manifest_id": manifest_id,
        "objects_tar": {"sha256": _sha(tar_bytes.getvalue()), "bytes": len(tar_bytes.getvalue())},
        "objects": [{"key": k, "sha256": _sha(v), "bytes": len(v)} for k, v in objects.items()],
    }
    manifest.update(manifest_overrides or {})
    plains = {
        "objects": tar_bytes.getvalue(),
        "manifest": json.dumps(manifest).encode(),
        "db": b"-- not used by the single-file restore\n",
    }
    index = {"format": 1, "manifest_id": manifest_id, "artifacts": {}}
    for role, filename in backup.ARTIFACTS.items():
        source = work / role
        source.write_bytes(plains[role])
        envelope.encrypt_file(
            source, set_dir / filename, public, backup.envelope_context(manifest_id, role)
        )
        index["artifacts"][role] = {
            "file": filename,
            "sha256": envelope.sha256_file(set_dir / filename),
        }
    (set_dir / "index.json").write_text(json.dumps(index))
    return set_dir


def _locate(set_dir: Path, key, tmp_path: Path, **overrides):
    work = tmp_path / "locate"
    work.mkdir(exist_ok=True)
    arguments = {
        "object_key": OBJECT_KEY,
        "trusted_sha256": _sha(ORIGINAL),
        "expected_size": len(ORIGINAL),
        "work": work,
    }
    arguments.update(overrides)
    return restore_file.locate_object(set_dir, key, **arguments)


def test_the_original_bytes_come_back_from_a_matching_backup(tmp_path, keypair) -> None:
    private, public = keypair
    set_dir = _build_set(tmp_path, public, objects={OBJECT_KEY: ORIGINAL, OTHER_KEY: b"unrelated"})

    located = _locate(set_dir, private, tmp_path)

    assert located.path.read_bytes() == ORIGINAL
    assert located.sha256 == _sha(ORIGINAL) and located.manifest_id == MANIFEST_ID


def test_a_set_that_holds_other_bytes_for_the_object_is_not_used(tmp_path, keypair) -> None:
    private, public = keypair
    set_dir = _build_set(tmp_path, public, objects={OBJECT_KEY: b"already tampered when backed up"})

    with pytest.raises(restore_file.RestoreRefused, match="different bytes"):
        _locate(set_dir, private, tmp_path)


def test_a_set_taken_before_the_upload_says_to_try_a_later_one(tmp_path, keypair) -> None:
    private, public = keypair
    set_dir = _build_set(tmp_path, public, objects={OTHER_KEY: b"unrelated"})

    with pytest.raises(restore_file.RestoreRefused, match="try a later set"):
        _locate(set_dir, private, tmp_path)


def test_the_digest_that_matters_is_the_recorded_one_not_whatever_the_backup_holds(
    tmp_path, keypair
) -> None:
    """With a forged database digest the caller passes the audit-chain digest instead."""
    private, public = keypair
    set_dir = _build_set(tmp_path, public, objects={OBJECT_KEY: ORIGINAL})

    with pytest.raises(restore_file.RestoreRefused, match="different bytes"):
        _locate(set_dir, private, tmp_path, trusted_sha256=_sha(b"the attacker's replacement"))


def test_a_size_that_disagrees_with_the_record_is_refused(tmp_path, keypair) -> None:
    private, public = keypair
    set_dir = _build_set(tmp_path, public, objects={OBJECT_KEY: ORIGINAL})

    with pytest.raises(restore_file.RestoreRefused, match="different size"):
        _locate(set_dir, private, tmp_path, expected_size=len(ORIGINAL) + 1)


def test_a_tampered_backup_artifact_is_refused_before_anything_is_decrypted(
    tmp_path, keypair
) -> None:
    private, public = keypair
    set_dir = _build_set(tmp_path, public, objects={OBJECT_KEY: ORIGINAL})
    artifact = set_dir / backup.ARTIFACTS["objects"]
    data = bytearray(artifact.read_bytes())
    data[len(data) // 2] ^= 1
    artifact.write_bytes(bytes(data))

    with pytest.raises(restore_file.RestoreRefused, match=r"does not match index\.json"):
        _locate(set_dir, private, tmp_path)


def test_a_tampered_artifact_with_a_doctored_index_still_fails_authentication(
    tmp_path, keypair
) -> None:
    private, public = keypair
    set_dir = _build_set(tmp_path, public, objects={OBJECT_KEY: ORIGINAL})
    artifact = set_dir / backup.ARTIFACTS["objects"]
    data = bytearray(artifact.read_bytes())
    data[len(data) // 2] ^= 1
    artifact.write_bytes(bytes(data))
    index = json.loads((set_dir / "index.json").read_text())
    index["artifacts"]["objects"]["sha256"] = envelope.sha256_file(artifact)
    (set_dir / "index.json").write_text(json.dumps(index))

    with pytest.raises(restore_file.RestoreRefused, match="authentication failed"):
        _locate(set_dir, private, tmp_path)


def test_the_wrong_private_key_is_named(tmp_path, keypair) -> None:
    _, public = keypair
    other = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    set_dir = _build_set(tmp_path, public, objects={OBJECT_KEY: ORIGINAL})

    with pytest.raises(restore_file.RestoreRefused, match="different backup key"):
        _locate(set_dir, other, tmp_path)


def test_a_set_without_its_index_is_refused(tmp_path, keypair) -> None:
    private, public = keypair
    set_dir = _build_set(tmp_path, public, objects={OBJECT_KEY: ORIGINAL})
    (set_dir / "index.json").unlink()

    with pytest.raises(restore_file.RestoreRefused, match=r"index\.json is missing"):
        _locate(set_dir, private, tmp_path)


def test_an_archive_whose_member_is_not_the_manifest_digest_is_refused(tmp_path, keypair) -> None:
    """Manifest and archive agree on the digest the caller wants, but the bytes differ."""
    private, public = keypair
    lying = {
        "objects": [
            {"key": OBJECT_KEY, "sha256": _sha(ORIGINAL), "bytes": len(ORIGINAL)},
        ]
    }
    set_dir = _build_set(
        tmp_path,
        public,
        objects={OBJECT_KEY: b"Z" * len(ORIGINAL)},
        manifest_overrides=lying,
    )

    with pytest.raises(restore_file.RestoreRefused, match="does not match the recorded SHA-256"):
        _locate(set_dir, private, tmp_path)


# --- the nightly same-host backup, which needs no key ---------------------------------------


def _nightly(directory: Path, stamp: str, members: dict[str, bytes], *, manifest: bool = True):
    """Write mcs21-files-<stamp>.tar.gz the way deployment/server/mcs21-backup does."""
    import gzip
    import io

    archive = directory / f"mcs21-files-{stamp}.tar.gz"
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=f"./encrypted/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    archive.write_bytes(gzip.compress(raw.getvalue()))
    if manifest:
        (directory / f"mcs21-{stamp}.sha256").write_text(
            f"{_sha(b'dump')}  {directory}/mcs21-db-{stamp}.sql.gz\n"
            f"{_sha(archive.read_bytes())}  {archive}\n"
        )
    return archive


def _daily(restore_file, directory: Path, tmp_path: Path, data: bytes, **overrides):
    work = tmp_path / "work-daily"
    work.mkdir(exist_ok=True)
    values = dict(
        object_key="11111111-1111-4111-8111-111111111111/obj.ciphertext",
        data_relative_dir=PurePosixPath("encrypted"),
        trusted_sha256=_sha(data),
        expected_size=len(data),
        work=work,
    )
    values.update(overrides)
    return restore_file.locate_in_daily_backups(directory, **values)


def test_the_newest_nightly_archive_that_holds_the_original_is_used(tmp_path) -> None:
    restore_file = _load("restore_file")
    original = b"the original ciphertext"
    key = "11111111-1111-4111-8111-111111111111/obj.ciphertext"
    daily = tmp_path / "daily"
    daily.mkdir()
    _nightly(daily, "20261010T201600Z", {key: original})
    _nightly(daily, "20261011T201600Z", {key: original})

    located = _daily(restore_file, daily, tmp_path, original)

    assert located.manifest_id == "mcs21-files-20261011T201600Z.tar.gz"
    assert located.path.read_bytes() == original and located.size_bytes == len(original)


def test_an_archive_taken_after_the_tampering_is_skipped_for_an_older_good_one(tmp_path) -> None:
    restore_file = _load("restore_file")
    original, damaged = b"the original ciphertext", b"the original ciphertexT"
    key = "11111111-1111-4111-8111-111111111111/obj.ciphertext"
    daily = tmp_path / "daily"
    daily.mkdir()
    _nightly(daily, "20261010T201600Z", {key: original})
    _nightly(daily, "20261011T201600Z", {key: damaged})  # taken after the byte flip

    located = _daily(restore_file, daily, tmp_path, original)

    assert located.manifest_id == "mcs21-files-20261010T201600Z.tar.gz"
    assert located.path.read_bytes() == original


def test_an_archive_that_fails_its_own_checksum_manifest_is_not_trusted(tmp_path) -> None:
    restore_file = _load("restore_file")
    original = b"the original ciphertext"
    key = "11111111-1111-4111-8111-111111111111/obj.ciphertext"
    daily = tmp_path / "daily"
    daily.mkdir()
    _nightly(daily, "20261010T201600Z", {key: original})
    newer = _nightly(daily, "20261011T201600Z", {key: original})
    newer.write_bytes(newer.read_bytes() + b"\x00")  # the archive changed after the manifest

    located = _daily(restore_file, daily, tmp_path, original)

    assert located.manifest_id == "mcs21-files-20261010T201600Z.tar.gz"


def test_no_archive_with_the_original_is_refused_and_names_each_one(tmp_path) -> None:
    restore_file = _load("restore_file")
    original = b"the original ciphertext"
    key = "11111111-1111-4111-8111-111111111111/obj.ciphertext"
    daily = tmp_path / "daily"
    daily.mkdir()
    _nightly(daily, "20261010T201600Z", {"other/obj.ciphertext": original})
    _nightly(daily, "20261011T201600Z", {key: b"different"})

    with pytest.raises(restore_file.RestoreRefused) as refused:
        _daily(restore_file, daily, tmp_path, original)

    text = str(refused.value)
    assert "20261011T201600Z.tar.gz: holds different bytes" in text
    assert "20261010T201600Z.tar.gz: does not hold the object" in text
    assert "--backup-set" in text


def test_an_empty_nightly_directory_points_at_the_encrypted_set_flags(tmp_path) -> None:
    restore_file = _load("restore_file")
    empty = tmp_path / "daily"
    empty.mkdir()

    with pytest.raises(restore_file.RestoreRefused, match="no nightly backup archives"):
        _daily(restore_file, empty, tmp_path, b"x")


def test_the_deployment_env_is_loaded_only_when_nothing_set_it(tmp_path, monkeypatch) -> None:
    restore_file = _load("restore_file")
    env = tmp_path / "backend.env"
    env.write_text('DB_HOST=127.0.0.1\nDB_PASSWORD="quoted value"\n# comment\nSECRET_KEY=abc\n')
    for name in ("DB_HOST", "DB_PASSWORD", "SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SECRET_KEY", "already-set")

    assert restore_file.load_deployment_env(env) is True
    assert os.environ["DB_HOST"] == "127.0.0.1"
    assert os.environ["DB_PASSWORD"] == "quoted value"
    assert os.environ["SECRET_KEY"] == "already-set"  # setdefault: never overwrites
    assert restore_file.load_deployment_env(env) is False  # DB_HOST is set now


def test_the_backup_set_and_private_key_flags_go_together(capsys) -> None:
    restore_file = _load("restore_file")
    file_id = "11111111-1111-4111-8111-111111111111"

    args = restore_file.parse_args(["--file-id", file_id])
    assert args.backup_set is None and args.private_key is None and not args.apply

    with pytest.raises(SystemExit):
        restore_file.parse_args(["--file-id", file_id, "--backup-set", "/x"])
    assert "go together" in capsys.readouterr().err
