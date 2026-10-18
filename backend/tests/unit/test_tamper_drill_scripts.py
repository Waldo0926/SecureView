from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import tamper_drill_attacker, tamper_drill_target


def test_target_refuses_a_non_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tamper_drill_target,
        "settings",
        SimpleNamespace(
            APP_ENV="test",
            DB_NAME="secureview_production",
            ENCRYPTED_FILE_DIR=Path("/lab/storage/objects"),
        ),
    )
    with pytest.raises(SystemExit, match="does not contain _test"):
        tamper_drill_target.require_lab()


def test_target_refuses_storage_outside_the_lab(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / ".secureview-tamper-lab"
    marker.write_text("lab", encoding="utf-8")
    monkeypatch.setattr(tamper_drill_target, "MARKER_PATH", marker)
    monkeypatch.setattr(
        tamper_drill_target,
        "settings",
        SimpleNamespace(
            APP_ENV="test",
            DB_NAME="secureview_tamper_test",
            ENCRYPTED_FILE_DIR=Path("/srv/production/objects"),
        ),
    )
    with pytest.raises(SystemExit, match="outside /lab/storage"):
        tamper_drill_target.require_lab()


def test_attacker_refuses_a_non_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DB_NAME", "secureview_tamper_test")
    with pytest.raises(SystemExit, match="Refusing non-test"):
        tamper_drill_attacker.require_lab()
