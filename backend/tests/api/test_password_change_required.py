"""While an administrator's temporary password is in place, the API refuses all but a few routes.

Until this was enforced in `get_current_actor`, only the frontend guard acted on
`must_change_password`, so any other API client could keep using the account with the
password the administrator had seen.
"""

from __future__ import annotations

import re
from collections.abc import Generator
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies
from app.api.dependencies import (
    get_account_deletion_service,
    get_admin_service,
    get_audit_query_service,
    get_auth_service,
    get_avatar_service,
    get_file_service,
    get_key_service,
    get_recovery_service,
    get_security_agent_service,
    get_sharing_service,
)
from app.core.config import Settings
from app.domain.auth import AccountSnapshot, ActorContext, RequestContext
from app.domain.enums import SystemRole, UserStatus
from app.main import create_app

USER_ID = UUID("11111111-1111-4111-8111-111111111111")
PLACEHOLDER_ID = "22222222-2222-4222-8222-222222222222"
HEADERS = {"Authorization": "Bearer access-secret"}


class FakeAuthService:
    """Authenticates every token as one account whose reset marker the test controls."""

    def __init__(self) -> None:
        self.must_change_password = True
        self.calls: list[str] = []

    def _actor(self) -> ActorContext:
        return ActorContext(
            user_id=7,
            user_public_id=USER_ID,
            session_id=9,
            session_public_id=UUID("33333333-3333-4333-8333-333333333333"),
            role=SystemRole.ADMIN,
            status=UserStatus.ACTIVE,
            access_token_hash="a" * 64,
            must_change_password=self.must_change_password,
        )

    def authenticate_access_token(self, _token: str) -> ActorContext:
        return self._actor()

    def get_me(self, *, actor: ActorContext) -> AccountSnapshot:
        self.calls.append("get_me")
        return AccountSnapshot(
            id=USER_ID,
            username="alice",
            email="alice@example.com",
            role=SystemRole.ADMIN,
            status=UserStatus.ACTIVE,
            email_verified=True,
            created_at=datetime(2026, 10, 1),
            must_change_password=actor.must_change_password,
        )

    def change_password(self, *, actor, current_password, new_password, context) -> int:
        self.calls.append("change_password")
        self.must_change_password = False
        return 1

    def logout(self, *, actor: ActorContext, context: RequestContext) -> None:
        self.calls.append("logout")

    def logout_all(self, *, actor: ActorContext, context: RequestContext) -> int:
        self.calls.append("logout_all")
        return 2


class FakeFileService:
    def __init__(self) -> None:
        self.listed = 0

    def list_files(self, **values: Any):
        self.listed += 1
        return {"items": [], "page": 1, "page_size": values["page_size"], "total": 0}

    def __getattr__(self, name: str):
        raise AssertionError(f"file service method {name} must not be called")


class FailIfCalledService:
    def __getattr__(self, name: str):
        raise AssertionError(f"service method {name} must not be called")


@pytest.fixture
def api() -> Generator[tuple[TestClient, FakeAuthService, FakeFileService], None, None]:
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            APP_DEBUG=False,
            SECRET_KEY="test-secret-key-that-is-long-enough",
        )
    )
    auth = FakeAuthService()
    files = FakeFileService()
    application.dependency_overrides[get_auth_service] = lambda: auth
    application.dependency_overrides[get_file_service] = lambda: files
    for dependency in (
        get_account_deletion_service,
        get_admin_service,
        get_audit_query_service,
        get_avatar_service,
        get_key_service,
        get_recovery_service,
        get_security_agent_service,
        get_sharing_service,
    ):
        application.dependency_overrides[dependency] = FailIfCalledService
    with TestClient(application) as client:
        # Read from the application itself: `client.app` may be wrapped in middleware.
        client.openapi = application.openapi()["paths"]  # type: ignore[attr-defined]
        yield client, auth, files
    application.dependency_overrides.clear()


def _authenticated_routes(client: TestClient) -> list[tuple[str, str]]:
    """Every operation that takes a bearer session, read from the OpenAPI contract.

    `get_current_actor` is the only user of the bearer scheme, so an operation that lists it
    under `security` is one that passes through the check.
    """
    found: list[tuple[str, str]] = []
    for path, operations in client.openapi.items():  # type: ignore[attr-defined]
        for method, operation in operations.items():
            if operation.get("security"):
                found.append((method.upper(), path.removeprefix("/api/v1")))
    return found


def test_every_authenticated_route_outside_the_allow_list_is_refused(api) -> None:
    client, _auth, files = api
    routes = _authenticated_routes(client)
    refused = [key for key in routes if key not in dependencies._PASSWORD_CHANGE_ALLOWED_ROUTES]
    # The sweep must actually cover the application, not an empty list.
    assert len(refused) > 30
    assert ("POST", "/auth/delete-account") in refused
    assert ("GET", "/keys/me") in refused

    for method, template in refused:
        path = "/api/v1" + re.sub(r"\{[^}]+\}", PLACEHOLDER_ID, template)
        response = client.request(method, path, headers=HEADERS, json={})
        assert response.status_code == 403, (method, template, response.text)
        body = response.json()
        assert body["data"]["error_code"] == "password_change_required", (method, template)
    assert files.listed == 0


def test_every_allowed_route_exists(api) -> None:
    # A renamed route would otherwise drop out of the allow-list silently and lock the
    # holder out of the one card that clears the marker.
    client, _auth, _files = api
    routes = set(_authenticated_routes(client))
    assert routes >= dependencies._PASSWORD_CHANGE_ALLOWED_ROUTES


def test_files_list_and_delete_account_are_refused_with_a_stable_code(api) -> None:
    client, _auth, files = api

    listing = client.get("/api/v1/files", headers=HEADERS)
    deletion = client.post(
        "/api/v1/auth/delete-account", headers=HEADERS, json={"password": "anything-at-all"}
    )

    for response in (listing, deletion):
        assert response.status_code == 403
        body = response.json()
        assert body["data"]["error_code"] == "password_change_required"
        assert body["message"] == "Choose a new login password before continuing"
    assert files.listed == 0


def test_the_routes_needed_to_replace_the_password_still_work(api) -> None:
    client, auth, _files = api

    me = client.get("/api/v1/auth/me", headers=HEADERS)
    assert me.status_code == 200
    assert me.json()["data"]["user"]["must_change_password"] is True
    assert client.post("/api/v1/auth/logout", headers=HEADERS).status_code == 200
    assert client.post("/api/v1/auth/logout-all", headers=HEADERS).status_code == 200
    # Refresh presents the refresh token, not a session, so it never meets the check.
    assert auth.calls == ["get_me", "logout", "logout_all"]


def test_changing_the_password_clears_the_marker_and_reopens_the_api(api) -> None:
    client, auth, files = api
    assert client.get("/api/v1/files", headers=HEADERS).status_code == 403

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=HEADERS,
        json={
            "current_password": "Temporary password 1!",
            "new_password": "A completely new secure phrase!",
        },
    )

    assert changed.status_code == 200
    assert auth.must_change_password is False
    assert client.get("/api/v1/files", headers=HEADERS).status_code == 200
    assert files.listed == 1


def test_an_account_without_the_marker_is_not_affected(api) -> None:
    client, auth, files = api
    auth.must_change_password = False

    assert client.get("/api/v1/files", headers=HEADERS).status_code == 200
    assert files.listed == 1
