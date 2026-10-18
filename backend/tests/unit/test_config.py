from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import REPO_ROOT, Settings


def test_relative_runtime_paths_do_not_depend_on_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    configured = Settings(
        _env_file=None,
        ENCRYPTED_FILE_DIR="backend/runtime/encrypted",
        TEMP_FILE_DIR="backend/runtime/temp",
    )

    assert configured.ENCRYPTED_FILE_DIR == REPO_ROOT / "backend/runtime/encrypted"
    assert configured.TEMP_FILE_DIR == REPO_ROOT / "backend/runtime/temp"


def test_database_url_handles_reserved_password_characters() -> None:
    configured = Settings(_env_file=None, DB_PASSWORD="p@ss:/word")

    assert configured.DATABASE_URL.password == "p@ss:/word"
    assert "p%40ss%3A%2Fword" in configured.DATABASE_URL.render_as_string(hide_password=False)
    assert configured.DATABASE_CONNECT_ARGS == {"init_command": "SET time_zone = '+00:00'"}


def test_database_identity_rejects_whitespace_padding() -> None:
    with pytest.raises(ValidationError, match="without whitespace padding"):
        Settings(_env_file=None, DB_USER=" runtime ")


def test_database_tls_uses_ca_and_optional_client_identity(tmp_path: Path) -> None:
    ca_path = tmp_path / "ca.pem"
    cert_path = tmp_path / "client-cert.pem"
    key_path = tmp_path / "client-key.pem"
    ca_path.touch()
    cert_path.touch()
    key_path.touch()

    configured = Settings(
        _env_file=None,
        DB_SSL_CA=ca_path,
        DB_SSL_CERT=cert_path,
        DB_SSL_KEY=key_path,
    )

    expected_connect_args = {
        "init_command": "SET time_zone = '+00:00'",
        "ssl_ca": str(ca_path),
        "ssl_verify_cert": True,
        "ssl_verify_identity": True,
        "ssl_cert": str(cert_path),
        "ssl_key": str(key_path),
    }
    assert expected_connect_args == configured.DATABASE_CONNECT_ARGS


def test_production_requires_verified_database_tls() -> None:
    with pytest.raises(ValidationError, match="DB_SSL_CA is required"):
        Settings(
            _env_file=None,
            APP_ENV="production",
            APP_DEBUG=False,
            SECRET_KEY="a-production-secret-that-is-long-enough",
            DB_PASSWORD="a-production-database-password",
        )


def test_production_rejects_development_security_defaults() -> None:
    with pytest.raises(ValidationError, match="Unsafe settings"):
        Settings(_env_file=None, APP_ENV="production", APP_DEBUG=False)


def test_database_password_cannot_be_empty() -> None:
    with pytest.raises(ValidationError, match="at least 1 character"):
        Settings(_env_file=None, DB_PASSWORD="")


def test_settings_repr_redacts_secrets() -> None:
    configured = Settings(
        _env_file=None,
        SECRET_KEY="secret-value-that-must-not-be-rendered",
        DB_PASSWORD="database-password-that-must-not-be-rendered",
    )

    rendered = repr(configured)

    assert "secret-value-that-must-not-be-rendered" not in rendered
    assert "database-password-that-must-not-be-rendered" not in rendered


def test_auth_lifetimes_and_rsa_size_are_validated() -> None:
    with pytest.raises(ValidationError, match="shorter than the absolute session"):
        Settings(
            _env_file=None,
            ACCESS_TOKEN_EXPIRE_MINUTES=60,
            SESSION_ABSOLUTE_EXPIRE_HOURS=1,
        )

    with pytest.raises(ValidationError, match="2048, 3072, or 4096"):
        Settings(_env_file=None, USER_RSA_KEY_SIZE=2050)


def test_account_and_ip_login_limits_are_configured_independently() -> None:
    configured = Settings(_env_file=None)

    assert configured.AUTH_REFRESH_MIN_INTERVAL_SECONDS > 0
    assert configured.AUTH_PASSWORD_HASH_CONCURRENCY == 2
    assert configured.AUTH_LOGIN_ACCOUNT_MAX_FAILURES < configured.AUTH_LOGIN_IP_MAX_FAILURES
    assert configured.AUTH_LOGIN_ACCOUNT_BLOCK_SECONDS < configured.AUTH_LOGIN_IP_BLOCK_SECONDS
    assert configured.AUTH_REAUTH_ACCOUNT_MAX_FAILURES < configured.AUTH_REAUTH_IP_MAX_FAILURES

    with pytest.raises(ValidationError, match="must be greater than the account limit"):
        Settings(
            _env_file=None,
            AUTH_LOGIN_ACCOUNT_MAX_FAILURES=10,
            AUTH_LOGIN_IP_MAX_FAILURES=10,
        )

    with pytest.raises(ValidationError, match="reauthentication account limit"):
        Settings(
            _env_file=None,
            AUTH_REAUTH_ACCOUNT_MAX_FAILURES=20,
            AUTH_REAUTH_IP_MAX_FAILURES=20,
        )


def test_request_body_limit_is_positive_bounded_and_independent_from_upload_limit() -> None:
    configured = Settings(
        _env_file=None,
        MAX_REQUEST_BODY_BYTES=2 * 1024 * 1024,
        MAX_UPLOAD_SIZE_BYTES=1,
        MAX_UPLOAD_REQUEST_OVERHEAD_BYTES=128 * 1024,
    )

    assert configured.MAX_REQUEST_BODY_BYTES == 2 * 1024 * 1024

    with pytest.raises(ValidationError, match="greater than 0"):
        Settings(_env_file=None, MAX_REQUEST_BODY_BYTES=0)

    with pytest.raises(ValidationError, match="less than or equal to 8388608"):
        Settings(_env_file=None, MAX_REQUEST_BODY_BYTES=8 * 1024 * 1024 + 1)


def test_requirements_declare_every_import_the_app_needs_at_startup() -> None:
    """A dependency only present in a developer's venv still breaks a fresh deploy.

    `EmailStr` needs `email-validator`, which pydantic imports lazily. Dropping
    it from requirements.txt passed every local test and only failed in the
    release preflight, where the venv is built from this file alone.
    """
    requirements = (Path(__file__).resolve().parents[2] / "requirements.txt").read_text(
        encoding="utf-8"
    )
    declared = {
        line.split("==")[0].split("[")[0].strip().lower()
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    schema_source = (
        Path(__file__).resolve().parents[2] / "app" / "schemas" / "auth_schema.py"
    ).read_text(encoding="utf-8")
    if "EmailStr" in schema_source:
        assert "email-validator" in declared, (
            "auth_schema.py uses EmailStr, so requirements.txt must declare email-validator"
        )
