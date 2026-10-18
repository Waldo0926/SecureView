from __future__ import annotations

import base64
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_actor, get_recovery_service
from app.core.config import Settings
from app.domain.auth import ActorContext
from app.domain.enums import SystemRole, UserStatus
from app.main import create_app
from app.repositories.recovery_repository import RecoveryExecutionRecord

NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
REQUEST_ID = UUID("11111111-1111-4111-8111-111111111111")
FILE_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_ID = UUID("33333333-3333-4333-8333-333333333333")
SESSION_ID = UUID("44444444-4444-4444-8444-444444444444")
TARGET_KEY_ID = UUID("55555555-5555-4555-8555-555555555555")
RECOVERY_KEY_ID = UUID("66666666-6666-4666-8666-666666666666")


def _reviewer() -> ActorContext:
    return ActorContext(
        user_id=8,
        user_public_id=UUID("77777777-7777-4777-8777-777777777777"),
        session_id=9,
        session_public_id=SESSION_ID,
        role=SystemRole.RECOVERY_OFFICER,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


class FakeRecoveryService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_execution_package(
        self,
        *,
        actor: ActorContext,
        request_id: UUID,
    ) -> RecoveryExecutionRecord:
        self.calls.append(("get_execution_package", {"actor": actor, "request_id": request_id}))
        return RecoveryExecutionRecord(
            request=SimpleNamespace(
                request_uuid=str(REQUEST_ID),
                expires_at=NOW.replace(tzinfo=None) + timedelta(hours=1),
            ),
            file=SimpleNamespace(file_uuid=str(FILE_ID)),
            requester=SimpleNamespace(user_uuid=str(USER_ID)),
            target_key=SimpleNamespace(
                key_uuid=str(TARGET_KEY_ID),
                algorithm="RSA-OAEP-SHA256",
                key_size_bits=3072,
                public_key_pem="TARGET PUBLIC KEY",
                fingerprint="e" * 64,
            ),
            source_wrapping=SimpleNamespace(wrapped_file_key=b"r" * 384),
            recovery_key=SimpleNamespace(
                key_uuid=str(RECOVERY_KEY_ID),
                algorithm="RSA-OAEP-SHA256",
                key_size_bits=3072,
                public_key_pem="RECOVERY PUBLIC KEY",
                fingerprint="f" * 64,
            ),
        )

    def execute_request(self, **values: Any):
        self.calls.append(("execute_request", values))
        raise AssertionError("invalid DTO must not reach the service")


@pytest.fixture
def recovery_api() -> Generator[tuple[TestClient, FakeRecoveryService], None, None]:
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            APP_DEBUG=False,
            SECRET_KEY="test-secret-key-that-is-long-enough",
        )
    )
    service = FakeRecoveryService()
    application.dependency_overrides[get_current_actor] = _reviewer
    application.dependency_overrides[get_recovery_service] = lambda: service

    with TestClient(application) as client:
        yield client, service

    application.dependency_overrides.clear()


def test_execution_package_contains_only_public_keys_and_wrapped_dek(
    recovery_api: tuple[TestClient, FakeRecoveryService],
) -> None:
    client, service = recovery_api

    response = client.get(f"/api/v1/recovery/{REQUEST_ID}/execution-package")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    data = response.json()["data"]
    assert data["request_id"] == str(REQUEST_ID)
    assert data["file_id"] == str(FILE_ID)
    assert data["recovery_key"]["key_id"] == str(RECOVERY_KEY_ID)
    assert data["target_key"]["key_id"] == str(TARGET_KEY_ID)
    assert data["recovery_wrapped_file_key"] == base64.b64encode(b"r" * 384).decode("ascii")
    assert data["expires_at"] == "2026-08-12T04:00:00Z"
    assert "private" not in response.text.lower()
    assert "passphrase" not in response.text.lower()
    assert service.calls[-1][0] == "get_execution_package"


def test_execute_contract_rejects_any_recovery_private_key_field(
    recovery_api: tuple[TestClient, FakeRecoveryService],
) -> None:
    client, service = recovery_api

    response = client.post(
        f"/api/v1/recovery/{REQUEST_ID}/execute",
        json={
            "wrapped_file_key": base64.b64encode(b"w" * 384).decode("ascii"),
            "recovery_key_id": str(RECOVERY_KEY_ID),
            "target_key_id": str(TARGET_KEY_ID),
            "recovery_private_key_pem": "forbidden-secret",
        },
    )

    assert response.status_code == 422
    assert "forbidden-secret" not in response.text
    assert not service.calls
