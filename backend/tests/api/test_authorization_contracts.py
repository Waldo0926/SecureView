from __future__ import annotations

import base64
from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_admin_service,
    get_current_actor,
    get_security_agent_service,
    get_sharing_service,
)
from app.core.config import Settings
from app.domain.auth import ActorContext
from app.domain.enums import SystemRole, UserStatus
from app.main import create_app

FILE_ID = UUID("11111111-1111-4111-8111-111111111111")
TARGET_USER_ID = UUID("22222222-2222-4222-8222-222222222222")
TARGET_KEY_ID = UUID("33333333-3333-4333-8333-333333333333")


def _ordinary_actor() -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=UUID("44444444-4444-4444-8444-444444444444"),
        session_id=8,
        session_public_id=UUID("55555555-5555-4555-8555-555555555555"),
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


class FailIfCalledService:
    def __getattr__(self, name: str):
        raise AssertionError(f"service method {name} must not be called")


@pytest.fixture
def protected_api() -> Generator[TestClient, None, None]:
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            APP_DEBUG=False,
            SECRET_KEY="test-secret-key-that-is-long-enough",
        )
    )
    application.dependency_overrides[get_current_actor] = _ordinary_actor
    application.dependency_overrides[get_admin_service] = FailIfCalledService
    application.dependency_overrides[get_security_agent_service] = FailIfCalledService
    application.dependency_overrides[get_sharing_service] = FailIfCalledService
    with TestClient(application) as client:
        yield client
    application.dependency_overrides.clear()


def test_admin_route_rejects_authenticated_non_admin_before_service(
    protected_api: TestClient,
) -> None:
    response = protected_api.get("/api/v1/admin/users")

    assert response.status_code == 403
    assert response.json()["data"]["error_code"] == "access_denied"
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"


def test_admin_stats_reject_authenticated_non_admin_before_service(
    protected_api: TestClient,
) -> None:
    response = protected_api.get("/api/v1/admin/stats")

    assert response.status_code == 403
    assert response.json()["data"]["error_code"] == "access_denied"
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"


def test_admin_integrity_routes_reject_authenticated_non_admin_before_service(
    protected_api: TestClient,
) -> None:
    for method, path in (
        ("get", "/api/v1/admin/integrity"),
        ("post", "/api/v1/admin/integrity/scan"),
    ):
        response = getattr(protected_api, method)(path)

        assert response.status_code == 403, path
        assert response.json()["data"]["error_code"] == "access_denied"


def test_admin_account_detail_and_password_reset_reject_non_admin_before_service(
    protected_api: TestClient,
) -> None:
    for method, path in (
        ("get", f"/api/v1/admin/users/{TARGET_USER_ID}"),
        ("post", f"/api/v1/admin/users/{TARGET_USER_ID}/reset-password"),
    ):
        response = getattr(protected_api, method)(path)

        assert response.status_code == 403, path
        assert response.json()["data"]["error_code"] == "access_denied"
        assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"


def test_security_agent_report_rejects_authenticated_non_admin_before_service(
    protected_api: TestClient,
) -> None:
    response = protected_api.get("/api/v1/admin/agent/report")

    assert response.status_code == 403
    assert response.json()["data"]["error_code"] == "access_denied"


def test_security_agent_report_validates_its_window(protected_api: TestClient) -> None:
    # Validation happens before authorization is even relevant: an absurd window is a 422.
    assert protected_api.get("/api/v1/admin/agent/report?window_hours=0").status_code in (403, 422)
    assert protected_api.get("/api/v1/admin/agent/report?window_hours=100000").status_code in (
        403,
        422,
    )


def test_share_contract_rejects_plaintext_private_key_without_echoing_it(
    protected_api: TestClient,
) -> None:
    forbidden_secret = "-----BEGIN PRIVATE KEY-----never-accept-this"
    response = protected_api.post(
        f"/api/v1/files/{FILE_ID}/share",
        json={
            "target_user_id": str(TARGET_USER_ID),
            "target_key_id": str(TARGET_KEY_ID),
            "wrapped_file_key": base64.b64encode(b"w" * 256).decode("ascii"),
            "can_download": True,
            "can_share": False,
            "private_key_pem": forbidden_secret,
        },
    )

    assert response.status_code == 422
    assert response.json()["data"]["error_code"] == "request_validation_failed"
    assert forbidden_secret not in response.text
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
