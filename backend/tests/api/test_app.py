from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app, resolve_commit


def test_liveness_endpoint() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_liveness_reports_the_configured_commit() -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    with TestClient(create_app(Settings(_env_file=None, APP_COMMIT=sha))) as client:
        response = client.get("/health/live")

    assert response.json() == {"status": "ok", "commit": sha}


def test_commit_falls_back_to_the_release_identity_file(tmp_path: Path) -> None:
    # mcs21-deploy writes the deployed SHA to .mcs21-release at the release root.
    identity = tmp_path / ".mcs21-release"
    identity.write_text("ABCDEF0123456789abcdef0123456789abcdef01\n", encoding="utf-8")
    unset = Settings(_env_file=None)

    assert resolve_commit(unset, identity) == "abcdef0123456789abcdef0123456789abcdef01"
    assert resolve_commit(unset, tmp_path / "missing") is None


def test_commit_that_is_not_a_sha_is_not_reported(tmp_path: Path) -> None:
    identity = tmp_path / ".mcs21-release"
    identity.write_text("<script>\n", encoding="utf-8")

    assert resolve_commit(Settings(_env_file=None, APP_COMMIT="main"), identity) is None
    assert resolve_commit(Settings(_env_file=None), identity) is None


def test_openapi_schema_can_be_generated() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/auth/login" in response.json()["paths"]


def test_openapi_business_routes_only_declare_get_and_post() -> None:
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()

    declared_methods = {
        method.upper()
        for path_item in schema["paths"].values()
        for method in path_item
        if method != "parameters"
    }

    assert declared_methods <= {"GET", "POST"}
    assert schema["paths"]["/api/v1/auth/sessions/{session_id}/revoke"].keys() >= {"post"}
    assert schema["paths"]["/api/v1/files/{file_id}/delete"].keys() >= {"post"}


def test_cors_only_allows_get_and_post() -> None:
    application = create_app()
    cors_middleware = next(
        middleware for middleware in application.user_middleware if middleware.cls is CORSMiddleware
    )

    assert cors_middleware.kwargs["allow_methods"] == ["GET", "POST"]


def test_encrypted_upload_body_is_rejected_before_multipart_spooling() -> None:
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            APP_DEBUG=False,
            SECRET_KEY="test-secret-key-that-is-long-enough",
            MAX_UPLOAD_SIZE_BYTES=1,
            MAX_UPLOAD_REQUEST_OVERHEAD_BYTES=128 * 1024,
        )
    )
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/files/upload",
            content=b"x" * (128 * 1024 + 2),
            headers={
                "Content-Type": "application/octet-stream",
                "Origin": "http://localhost:5173",
            },
        )

    assert response.status_code == 413
    assert response.json()["data"]["error_code"] == "request_too_large"
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_business_routes_require_bearer_authentication() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/admin/users")

    assert response.status_code == 401
    assert response.json()["data"]["error_code"] == "authentication_required"
    assert "access_token" not in response.text


def test_application_factory_accepts_isolated_settings() -> None:
    configured = Settings(
        _env_file=None,
        APP_NAME="Architecture Test API",
        APP_VERSION="9.9.9",
        API_PREFIX="/test/v1",
        DB_NAME="auth_isolation_test",
    )

    application = create_app(configured)

    assert application.title == "Architecture Test API"
    assert application.version == "9.9.9"
    assert application.state.settings is configured
    assert application.state.db_engine.url.database == "auth_isolation_test"
    assert application.state.db_session_factory.kw["bind"] is application.state.db_engine
    assert (
        application.state.password_manager.max_concurrent_operations
        == configured.AUTH_PASSWORD_HASH_CONCURRENCY
    )
    assert "/test/v1/auth/login" in application.openapi()["paths"]
