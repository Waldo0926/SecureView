from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = BACKEND_ROOT / "scripts"


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checkpoint = _load("audit_checkpoint")


def _head() -> dict[str, object]:
    return {
        "last_log_id": 42,
        "current_hash": "a" * 64,
        "schema_revision": "0011_must_change_password",
        "updated_at": "2026-09-25T04:00:00.000000Z",
    }


def test_hmac_checkpoint_round_trip_and_tamper_detection() -> None:
    key = bytes(range(32))
    document = checkpoint.build_document(
        chain_head=_head(),
        release_sha="1" * 40,
        key=key,
        created_at=datetime(2026, 9, 25, 4, 30, tzinfo=UTC),
    )

    payload = checkpoint.verify_document(document, key)
    assert payload["audit_chain"]["last_log_id"] == 42
    assert payload["release_sha"] == "1" * 40

    document["payload"]["audit_chain"]["current_hash"] = "b" * 64
    with pytest.raises(checkpoint.CheckpointError, match="HMAC verification failed"):
        checkpoint.verify_document(document, key)


def test_local_destination_requires_explicit_drill_flag(tmp_path: Path) -> None:
    source = tmp_path / "checkpoint.json"
    source.write_text("{}\n", encoding="utf-8")

    with pytest.raises(checkpoint.CheckpointError, match="must be external"):
        checkpoint.ship(source, str(tmp_path / "dest"), allow_local=False)

    target = checkpoint.ship(source, str(tmp_path / "dest"), allow_local=True)
    assert Path(target).read_text(encoding="utf-8") == "{}\n"
    assert Path(target).stat().st_mode & 0o077 == 0


def test_hmac_key_must_be_at_least_256_bits(tmp_path: Path) -> None:
    weak = tmp_path / "weak.key"
    weak.write_text("abcd", encoding="utf-8")
    with pytest.raises(checkpoint.CheckpointError, match="256 bits"):
        checkpoint.load_hmac_key(weak)

    strong = tmp_path / "strong.key"
    strong.write_text("11" * 32 + "\n", encoding="utf-8")
    assert checkpoint.load_hmac_key(strong) == bytes.fromhex("11" * 32)


def test_serialized_checkpoint_contains_only_anchor_metadata() -> None:
    document = checkpoint.build_document(
        chain_head=_head(),
        release_sha="2" * 40,
        key=b"k" * 32,
        created_at=datetime(2026, 9, 25, 4, 30, tzinfo=UTC),
    )
    rendered = checkpoint.serialize_document(document).decode("utf-8")

    assert "current_hash" in rendered
    assert "last_log_id" in rendered
    # The schema revision is a public constant and its name may contain a word from the
    # list below (0011_must_change_password does); it is not a leaked value.
    rendered = rendered.replace(str(_head()["schema_revision"]), "")
    for forbidden in (
        "password",
        "passphrase",
        "private_key",
        "filename",
        "file_content",
        "authorization",
        "bearer",
    ):
        assert forbidden not in rendered.lower()
