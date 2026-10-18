from __future__ import annotations

import base64
import hashlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_auth_service
from app.core.config import Settings
from app.domain.auth import (
    AccountSnapshot,
    ActorContext,
    LoginResult,
    RefreshResult,
    RegistrationResult,
    RequestContext,
    SessionSnapshot,
    TokenPair,
)
from app.domain.enums import SessionStatus, SystemRole, UserStatus, VerificationPurpose
from app.domain.errors import (
    AccountIdentifierUnavailableError,
    AppError,
    AuthenticationRateLimitedError,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    VerificationCodeInvalidError,
)
from app.main import create_app

NOW = datetime(2026, 8, 4, 4, 0, tzinfo=UTC)
USER_PUBLIC_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_PUBLIC_ID = UUID("22222222-2222-4222-8222-222222222222")
KEY_ID = UUID("33333333-3333-4333-8333-333333333333")


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        id=USER_PUBLIC_ID,
        username="alice",
        email="alice@example.com",
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        email_verified=False,
        created_at=NOW,
    )


def _actor() -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=USER_PUBLIC_ID,
        session_id=9,
        session_public_id=SESSION_PUBLIC_ID,
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


class FakeAuthService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.errors: dict[str, AppError] = {}

    def _record(self, method: str, **values: Any) -> None:
        self.calls.append((method, values))
        if error := self.errors.get(method):
            raise error

    def send_verification_code(
        self,
        *,
        purpose: Any,
        email: str,
        context: RequestContext,
    ) -> None:
        self._record(
            "send_verification_code",
            purpose=purpose,
            email=email,
            context=context,
        )

    def register(
        self,
        *,
        username: str,
        email: str,
        password: str,
        verification_code: str,
        key_material: Any,
        context: RequestContext,
    ) -> RegistrationResult:
        self._record(
            "register",
            username=username,
            email=email,
            password=password,
            verification_code=verification_code,
            key_material=key_material,
            context=context,
        )
        return RegistrationResult(
            user=_account(),
            key_id=KEY_ID,
            public_key_fingerprint="f" * 64,
        )

    def reset_password(
        self,
        *,
        username: str,
        email: str,
        verification_code: str,
        new_password: str,
        context: RequestContext,
    ) -> int:
        self._record(
            "reset_password",
            username=username,
            email=email,
            verification_code=verification_code,
            new_password=new_password,
            context=context,
        )
        return 2

    def login(
        self,
        *,
        username: str,
        password: str,
        context: RequestContext,
    ) -> LoginResult:
        self._record("login", username=username, password=password, context=context)
        return LoginResult(
            user=_account(),
            tokens=TokenPair(
                session_id=SESSION_PUBLIC_ID,
                access_token="access-secret",
                refresh_token="refresh-secret",
                access_expires_at=NOW + timedelta(minutes=15),
                refresh_expires_at=NOW + timedelta(days=7),
            ),
        )

    def authenticate_access_token(self, token: str) -> ActorContext:
        self._record("authenticate_access_token", token=token)
        return _actor()

    def refresh(self, *, refresh_token: str, context: RequestContext) -> RefreshResult:
        self._record("refresh", refresh_token=refresh_token, context=context)
        return RefreshResult(
            tokens=TokenPair(
                session_id=SESSION_PUBLIC_ID,
                access_token="rotated-access-secret",
                refresh_token="rotated-refresh-secret",
                access_expires_at=NOW + timedelta(minutes=15),
                refresh_expires_at=NOW + timedelta(days=7),
            )
        )

    def get_me(self, *, actor: ActorContext) -> AccountSnapshot:
        self._record("get_me", actor=actor)
        return _account()

    def logout(self, *, actor: ActorContext, context: RequestContext) -> None:
        self._record("logout", actor=actor, context=context)

    def logout_all(self, *, actor: ActorContext, context: RequestContext) -> int:
        self._record("logout_all", actor=actor, context=context)
        return 3

    def change_password(
        self,
        *,
        actor: ActorContext,
        current_password: str,
        new_password: str,
        context: RequestContext,
    ) -> int:
        self._record(
            "change_password",
            actor=actor,
            current_password=current_password,
            new_password=new_password,
            context=context,
        )
        return 3

    def list_sessions(self, *, actor: ActorContext) -> tuple[SessionSnapshot, ...]:
        self._record("list_sessions", actor=actor)
        return (
            SessionSnapshot(
                id=SESSION_PUBLIC_ID,
                status=SessionStatus.ACTIVE,
                current=True,
                created_at=NOW - timedelta(hours=1),
                access_expires_at=NOW + timedelta(minutes=15),
                absolute_expires_at=NOW + timedelta(days=7),
                ip_address="203.0.113.10",
                user_agent="test-browser",
            ),
        )

    def revoke_session(
        self,
        *,
        actor: ActorContext,
        session_id: UUID,
        context: RequestContext,
    ) -> None:
        self._record(
            "revoke_session",
            actor=actor,
            session_id=session_id,
            context=context,
        )


@pytest.fixture
def auth_api() -> Generator[tuple[TestClient, FakeAuthService], None, None]:
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            APP_DEBUG=False,
            SECRET_KEY="test-secret-key-that-is-long-enough",
        )
    )
    service = FakeAuthService()
    application.dependency_overrides[get_auth_service] = lambda: service

    with TestClient(application) as client:
        yield client, service

    application.dependency_overrides.clear()


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer access-secret", "User-Agent": "auth-contract-test"}


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _key_material_json() -> dict[str, Any]:
    ciphertext = b"client-encrypted-pkcs8" * 20
    return {
        "key_id": str(KEY_ID),
        "public_key_pem": "-----BEGIN PUBLIC KEY-----\n"
        + "A" * 200
        + "\n-----END PUBLIC KEY-----\n",
        "key_size_bits": 3072,
        "protection": {
            "profile_id": "44444444-4444-4444-8444-444444444444",
            "kdf_salt": _b64(b"s" * 16),
            "kdf_memory_kib": 65_536,
            "kdf_iterations": 3,
            "kdf_parallelism": 4,
            "wrapped_amk": _b64(b"w" * 32),
            "amk_nonce": _b64(b"n" * 12),
            "amk_auth_tag": _b64(b"t" * 16),
        },
        "private_key_bundle": {
            "bundle_id": "55555555-5555-4555-8555-555555555555",
            "derivation_salt": _b64(b"d" * 16),
            "encrypted_private_key": _b64(ciphertext),
            "nonce": _b64(b"i" * 12),
            "auth_tag": _b64(b"a" * 16),
            "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
        },
    }


def test_register_contract_normalizes_input_and_disables_caching(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.post(
        "/api/v1/auth/register",
        headers={"User-Agent": "auth-contract-test"},
        json={
            "username": "  alice  ",
            "email": "Alice@Example.COM",
            "password": "A strong registration passphrase!",
            "verification_code": " 123 456 ",
            "key_material": _key_material_json(),
        },
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    assert response.json()["data"]["user"]["id"] == str(USER_PUBLIC_ID)
    assert response.json()["data"]["user"]["must_change_password"] is False
    assert response.json()["data"]["key_id"] == str(KEY_ID)
    assert "private_key_pem" not in response.text
    method, values = service.calls[-1]
    assert method == "register"
    assert values["username"] == "alice"
    assert values["email"] == "alice@example.com"
    assert values["password"] == "A strong registration passphrase!"
    assert values["verification_code"] == "123456"
    assert values["context"].user_agent == "auth-contract-test"


def test_register_duplicate_identifier_uses_stable_conflict_response(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api
    service.errors["register"] = AccountIdentifierUnavailableError()
    password = "A strong registration passphrase!"

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": password,
            "verification_code": "123456",
            "key_material": _key_material_json(),
        },
    )

    assert response.status_code == 409
    assert response.json()["data"]["error_code"] == "account_identifier_unavailable"
    assert password not in response.text


def test_login_contract_returns_typed_token_response_and_disables_caching(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.post(
        "/api/v1/auth/login",
        json={"username": " alice ", "password": "login-password"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.json()["data"]["access_token"] == "access-secret"
    assert response.json()["data"]["refresh_token"] == "refresh-secret"
    assert response.json()["data"]["session_id"] == str(SESSION_PUBLIC_ID)
    assert service.calls[-1][0] == "login"
    assert service.calls[-1][1]["username"] == "alice"


def test_invalid_login_uses_generic_bearer_authentication_error(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api
    service.errors["login"] = InvalidCredentialsError()
    password = "incorrect-password"

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "unknown-user", "password": password},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["data"]["error_code"] == "invalid_credentials"
    assert password not in response.text


def test_auth_capacity_error_returns_retry_after_without_caching(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api
    service.errors["login"] = AuthenticationRateLimitedError(retry_after_seconds=1)

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "not-returned"},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert response.headers["cache-control"].startswith("no-store")
    assert response.json()["data"]["error_code"] == "auth_rate_limited"
    assert "not-returned" not in response.text


def test_refresh_contract_rotates_tokens_and_disables_caching(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "refresh-secret"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.json()["data"]["access_token"] == "rotated-access-secret"
    assert response.json()["data"]["refresh_token"] == "rotated-refresh-secret"
    assert response.json()["data"]["session_id"] == str(SESSION_PUBLIC_ID)
    assert service.calls[-1][0] == "refresh"
    assert service.calls[-1][1]["refresh_token"] == "refresh-secret"


def test_protected_auth_route_rejects_missing_bearer_token(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["data"]["error_code"] == "authentication_required"
    assert not service.calls


def test_me_resolves_bearer_token_and_returns_public_account(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.get("/api/v1/auth/me", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["data"]["user"]["email"] == "alice@example.com"
    assert "password_hash" not in response.text
    assert [call[0] for call in service.calls] == ["authenticate_access_token", "get_me"]
    assert service.calls[0][1]["token"] == "access-secret"


def test_logout_revokes_current_session_contract(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.post("/api/v1/auth/logout", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["data"] == {"logged_out": True}
    assert [call[0] for call in service.calls] == ["authenticate_access_token", "logout"]


def test_logout_all_returns_revoked_session_count(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.post("/api/v1/auth/logout-all", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["data"] == {"revoked_sessions": 3}
    assert service.calls[-1][0] == "logout_all"


def test_change_password_forwards_secrets_only_to_service_and_requires_reauthentication(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api
    current_password = "current-password"
    new_password = "A different strong passphrase!"

    response = client.post(
        "/api/v1/auth/change-password",
        headers=_auth_headers(),
        json={"current_password": current_password, "new_password": new_password},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "password_changed": True,
        "revoked_sessions": 3,
        "reauthentication_required": True,
    }
    assert current_password not in response.text
    assert new_password not in response.text
    method, values = service.calls[-1]
    assert method == "change_password"
    assert values["current_password"] == current_password
    assert values["new_password"] == new_password


def test_invalid_current_password_does_not_invalidate_the_bearer_session(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api
    service.errors["change_password"] = InvalidCurrentPasswordError()

    response = client.post(
        "/api/v1/auth/change-password",
        headers=_auth_headers(),
        json={
            "current_password": "incorrect-current-password",
            "new_password": "A different strong passphrase!",
        },
    )

    assert response.status_code == 422
    assert response.json()["data"]["error_code"] == "invalid_current_password"
    assert "www-authenticate" not in response.headers


def test_list_sessions_marks_current_session_and_returns_no_token_hashes(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.get("/api/v1/auth/sessions", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["data"]["sessions"] == [
        {
            "session_id": str(SESSION_PUBLIC_ID),
            "status": "ACTIVE",
            "current": True,
            "created_at": "2026-08-04T03:00:00Z",
            "access_expires_at": "2026-08-04T04:15:00Z",
            "absolute_expires_at": "2026-08-11T04:00:00Z",
            "ip_address": "203.0.113.10",
            "user_agent": "test-browser",
            "revoked_at": None,
        }
    ]
    assert "token_hash" not in response.text
    assert service.calls[-1][0] == "list_sessions"


def test_revoke_session_uses_public_session_id(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.post(
        f"/api/v1/auth/sessions/{SESSION_PUBLIC_ID}/revoke",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "session_id": str(SESSION_PUBLIC_ID),
        "revoked": True,
    }
    assert service.calls[-1][0] == "revoke_session"
    assert service.calls[-1][1]["session_id"] == SESSION_PUBLIC_ID


def test_send_verification_code_returns_a_uniform_response(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.post(
        "/api/v1/auth/verification-codes/send",
        json={"email": "Alice@Example.COM", "purpose": "REGISTRATION"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    body = response.json()["data"]
    assert body["code_sent"] is True
    assert body["expires_in_seconds"] > 0
    assert body["resend_available_in_seconds"] > 0
    method, values = service.calls[-1]
    assert method == "send_verification_code"
    assert values["email"] == "alice@example.com"
    assert values["purpose"] == VerificationPurpose.REGISTRATION


def test_send_verification_code_rejects_an_unknown_purpose(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, _ = auth_api

    response = client.post(
        "/api/v1/auth/verification-codes/send",
        json={"email": "alice@example.com", "purpose": "ACCOUNT_TAKEOVER"},
    )

    assert response.status_code == 422


def test_register_requires_a_verification_code(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, _ = auth_api

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "A strong registration passphrase!",
            "key_material": _key_material_json(),
        },
    )

    assert response.status_code == 422
    details = response.json()["data"]["details"]
    assert any("verification_code" in detail["location"] for detail in details)


def test_password_reset_contract_normalizes_input_and_disables_caching(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api
    new_password = "A replacement lengthy passphrase!"

    response = client.post(
        "/api/v1/auth/password-reset",
        json={
            "username": " alice ",
            "email": "Alice@Example.COM",
            "verification_code": "654321",
            "new_password": new_password,
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    body = response.json()["data"]
    assert body["password_reset"] is True
    assert body["revoked_sessions"] == 2
    assert body["key_envelopes_unchanged"] is True
    assert new_password not in response.text
    method, values = service.calls[-1]
    assert method == "reset_password"
    assert values["username"] == "alice"
    assert values["email"] == "alice@example.com"
    assert values["verification_code"] == "654321"


def test_password_reset_rejects_a_short_new_password(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api

    response = client.post(
        "/api/v1/auth/password-reset",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "verification_code": "654321",
            "new_password": "short",
        },
    )

    assert response.status_code == 422
    assert all(method != "reset_password" for method, _ in service.calls)


def test_password_reset_surfaces_an_invalid_code_without_leaking_the_reason(
    auth_api: tuple[TestClient, FakeAuthService],
) -> None:
    client, service = auth_api
    service.errors["reset_password"] = VerificationCodeInvalidError()

    response = client.post(
        "/api/v1/auth/password-reset",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "verification_code": "000000",
            "new_password": "A replacement lengthy passphrase!",
        },
    )

    assert response.status_code == 422
    assert response.json()["data"]["error_code"] == "invalid_verification_code"
