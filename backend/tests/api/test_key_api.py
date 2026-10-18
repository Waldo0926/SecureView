from __future__ import annotations

import base64
import hashlib
from collections.abc import Generator
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_actor, get_key_service
from app.core.config import Settings
from app.domain.auth import ActorContext
from app.domain.enums import SystemRole, UserStatus
from app.domain.errors import UserKeyNotFoundError
from app.main import create_app

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
USER_ID = UUID("11111111-1111-4111-8111-111111111111")
KEY_ID = UUID("22222222-2222-4222-8222-222222222222")
PROFILE_ID = UUID("33333333-3333-4333-8333-333333333333")
BUNDLE_ID = UUID("44444444-4444-4444-8444-444444444444")
RECIPIENT_ID = UUID("66666666-6666-4666-8666-666666666666")
RECIPIENT_KEY_ID = UUID("77777777-7777-4777-8777-777777777777")


def _actor() -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=USER_ID,
        session_id=8,
        session_public_id=UUID("55555555-5555-4555-8555-555555555555"),
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


class FakeKeyService:
    def __init__(self) -> None:
        self.requested_key_id: UUID | None = None
        self.calls: list[tuple[str, dict]] = []

    def get_owned_bundle(self, *, actor: ActorContext, key_id: UUID):
        assert actor == _actor()
        self.requested_key_id = key_id
        ciphertext = b"old-client-encrypted-private-key"
        return (
            SimpleNamespace(user_uuid=str(USER_ID)),
            SimpleNamespace(
                key_uuid=str(KEY_ID),
                algorithm="RSA-OAEP-SHA256",
                key_size_bits=3072,
                public_key_pem="-----BEGIN PUBLIC KEY-----\nopaque\n-----END PUBLIC KEY-----\n",
                fingerprint="f" * 64,
                created_at=NOW.replace(tzinfo=None),
            ),
            SimpleNamespace(
                profile_uuid=str(PROFILE_ID),
                format_version=1,
                kdf_algorithm="ARGON2ID",
                kdf_version=19,
                kdf_salt=b"s" * 16,
                kdf_memory_kib=65_536,
                kdf_iterations=3,
                kdf_parallelism=1,
                derived_key_length=32,
                amk_wrapping_algorithm="AES-256-GCM",
                wrapped_amk=b"w" * 32,
                amk_nonce=b"n" * 12,
                amk_auth_tag=b"t" * 16,
                aad_version=1,
                revision=4,
                updated_at=NOW.replace(tzinfo=None),
            ),
            SimpleNamespace(
                bundle_uuid=str(BUNDLE_ID),
                format_version=1,
                private_key_format="PKCS8-DER",
                derivation_algorithm="HKDF-SHA256",
                derivation_salt=b"d" * 16,
                encryption_algorithm="AES-256-GCM",
                encrypted_private_key=ciphertext,
                nonce=b"i" * 12,
                auth_tag=b"a" * 16,
                aad_version=1,
                ciphertext_sha256=hashlib.sha256(ciphertext).hexdigest(),
                revision=1,
                updated_at=NOW.replace(tzinfo=None),
            ),
        )

    def get_active_public_key_by_identifier(self, *, identifier: str):
        self.calls.append(("get_active_public_key_by_identifier", {"identifier": identifier}))
        if identifier not in {"recipient", "recipient@example.com"}:
            raise UserKeyNotFoundError()
        return (
            SimpleNamespace(user_uuid=str(RECIPIENT_ID)),
            SimpleNamespace(
                key_uuid=str(RECIPIENT_KEY_ID),
                algorithm="RSA-OAEP-SHA256",
                key_size_bits=3072,
                public_key_pem="-----BEGIN PUBLIC KEY-----\nrecipient\n-----END PUBLIC KEY-----\n",
                fingerprint="e" * 64,
                created_at=NOW.replace(tzinfo=None),
            ),
        )

    def get_rewrap_signing_payload(self, **values):
        self.calls.append(("get_rewrap_signing_payload", values))
        return b"p" * 32

    def rewrap_protection_profile(self, **values):
        self.calls.append(("rewrap_protection_profile", values))
        return SimpleNamespace(
            profile_uuid=str(PROFILE_ID),
            revision=5,
            updated_at=NOW.replace(tzinfo=None),
        )


def _rewrap_payload(*, include_signature: bool = False) -> dict:
    payload = {
        "authorizing_key_id": str(KEY_ID),
        "profile_id": str(PROFILE_ID),
        "expected_revision": 4,
        "kdf_salt": base64.b64encode(b"s" * 16).decode("ascii"),
        "kdf_memory_kib": 65_536,
        "kdf_iterations": 3,
        "kdf_parallelism": 1,
        "wrapped_amk": base64.b64encode(b"w" * 32).decode("ascii"),
        "amk_nonce": base64.b64encode(b"n" * 12).decode("ascii"),
        "amk_auth_tag": base64.b64encode(b"t" * 16).decode("ascii"),
    }
    if include_signature:
        payload.update(
            {
                "authorization_algorithm": "RSA-PSS-SHA256",
                "authorization_signature": base64.b64encode(b"a" * 384).decode("ascii"),
            }
        )
    return payload


@pytest.fixture
def key_api() -> Generator[tuple[TestClient, FakeKeyService], None, None]:
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            APP_DEBUG=False,
            SECRET_KEY="test-secret-key-that-is-long-enough",
        )
    )
    service = FakeKeyService()
    application.dependency_overrides[get_current_actor] = _actor
    application.dependency_overrides[get_key_service] = lambda: service
    with TestClient(application) as client:
        yield client, service
    application.dependency_overrides.clear()


def test_historical_owned_key_bundle_remains_retrievable_after_rotation(
    key_api: tuple[TestClient, FakeKeyService],
) -> None:
    client, service = key_api

    response = client.get(f"/api/v1/keys/me/{KEY_ID}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    data = response.json()["data"]
    assert data["key"]["key_id"] == str(KEY_ID)
    assert data["private_key_bundle"]["bundle_id"] == str(BUNDLE_ID)
    assert data["private_key_bundle"]["encrypted_private_key"] == base64.b64encode(
        b"old-client-encrypted-private-key"
    ).decode("ascii")
    assert "passphrase" not in response.text.lower()
    assert service.requested_key_id == KEY_ID


def test_key_addition_openapi_never_accepts_passphrase_or_plaintext_private_key(
    key_api: tuple[TestClient, FakeKeyService],
) -> None:
    client, _service = key_api

    schema = client.get("/openapi.json").json()
    addition_schema = schema["components"]["schemas"]["AddClientKeyRequest"]
    properties = addition_schema["properties"]

    assert "authorization_signature" in properties
    assert "passphrase" not in properties
    assert "private_key_pem" not in properties
    assert schema["paths"]["/api/v1/keys/add"]["post"]["security"] == [{"HTTPBearer": []}]


def test_rewrap_signing_payload_contract_returns_only_canonical_digest(
    key_api: tuple[TestClient, FakeKeyService],
) -> None:
    client, service = key_api

    response = client.post(
        "/api/v1/keys/me/rewrap/signing-payload",
        json=_rewrap_payload(),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.json()["data"] == {
        "authorization_algorithm": "RSA-PSS-SHA256",
        "authorization_payload": base64.b64encode(b"p" * 32).decode("ascii"),
    }
    name, values = service.calls[-1]
    assert name == "get_rewrap_signing_payload"
    assert values["actor"] == _actor()
    assert values["authorizing_key_id"] == KEY_ID
    assert values["expected_revision"] == 4
    assert values["protection"].wrapped_amk == b"w" * 32


def test_rewrap_contract_forwards_current_key_signature_as_bytes(
    key_api: tuple[TestClient, FakeKeyService],
) -> None:
    client, service = key_api

    response = client.post(
        "/api/v1/keys/me/rewrap",
        json=_rewrap_payload(include_signature=True),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.json()["data"] == {
        "profile_id": str(PROFILE_ID),
        "revision": 5,
        "updated_at": "2026-08-12T12:00:00Z",
    }
    name, values = service.calls[-1]
    assert name == "rewrap_protection_profile"
    assert values["actor"] == _actor()
    assert values["authorizing_key_id"] == KEY_ID
    assert values["authorization_signature"] == b"a" * 384


@pytest.mark.parametrize(
    ("path", "forbidden_field"),
    [
        ("/api/v1/keys/me/rewrap/signing-payload", "passphrase"),
        ("/api/v1/keys/me/rewrap", "private_key_pem"),
    ],
)
def test_rewrap_contract_rejects_secret_inputs_without_echoing_them(
    key_api: tuple[TestClient, FakeKeyService],
    path: str,
    forbidden_field: str,
) -> None:
    client, service = key_api
    secret = "forbidden-secret-must-not-echo"
    payload = _rewrap_payload(include_signature=path.endswith("/rewrap"))
    payload[forbidden_field] = secret

    response = client.post(path, json=payload)

    assert response.status_code == 422
    assert response.json()["data"]["error_code"] == "request_validation_failed"
    assert secret not in response.text
    assert not service.calls


def test_rewrap_openapi_requires_signature_and_exposes_no_secret_input(
    key_api: tuple[TestClient, FakeKeyService],
) -> None:
    client, _service = key_api

    schema = client.get("/openapi.json").json()
    unsigned = schema["components"]["schemas"]["RewrapKeyProtectionIn"]
    signed = schema["components"]["schemas"]["RewrapKeyProtectionRequest"]

    assert "authorization_signature" not in unsigned["properties"]
    assert "authorization_signature" in signed["properties"]
    assert "authorization_signature" in signed["required"]
    for forbidden in ("passphrase", "private_key", "private_key_pem"):
        assert forbidden not in unsigned["properties"]
        assert forbidden not in signed["properties"]
    assert schema["paths"]["/api/v1/keys/me/rewrap"]["post"]["security"] == [{"HTTPBearer": []}]
    assert schema["paths"]["/api/v1/keys/me/rewrap/signing-payload"]["post"]["security"] == [
        {"HTTPBearer": []}
    ]


def test_resolves_a_share_recipient_by_username(key_api) -> None:
    client, service = key_api

    response = client.get("/api/v1/keys/users/by-identifier/recipient/active")

    assert response.status_code == 200
    data = response.json()["data"]
    # Sharing needs all three: the contract is expressed in ids, the rewrap needs the PEM.
    assert data["user_id"] == str(RECIPIENT_ID)
    assert data["key_id"] == str(RECIPIENT_KEY_ID)
    assert data["public_key_pem"].startswith("-----BEGIN PUBLIC KEY-----")
    assert ("get_active_public_key_by_identifier", {"identifier": "recipient"}) in service.calls


def test_resolves_a_share_recipient_by_email(key_api) -> None:
    client, service = key_api

    response = client.get("/api/v1/keys/users/by-identifier/recipient%40example.com/active")

    assert response.status_code == 200
    assert (
        "get_active_public_key_by_identifier",
        {"identifier": "recipient@example.com"},
    ) in service.calls


def test_an_unknown_recipient_is_not_found(key_api) -> None:
    client, _ = key_api

    response = client.get("/api/v1/keys/users/by-identifier/nobody/active")

    assert response.status_code == 404


def test_the_identifier_route_does_not_shadow_the_user_id_route(key_api) -> None:
    # "by-identifier" sits one segment deeper than /users/{user_id}/active, so the two cannot
    # collide -- including for a username that happens to parse as a UUID.
    client, service = key_api

    client.get(f"/api/v1/keys/users/by-identifier/{RECIPIENT_ID}/active")

    assert (
        "get_active_public_key_by_identifier",
        {"identifier": str(RECIPIENT_ID)},
    ) in service.calls


def test_the_username_route_remains_as_a_compatibility_alias(key_api) -> None:
    client, service = key_api

    response = client.get("/api/v1/keys/users/by-username/recipient/active")

    assert response.status_code == 200
    assert ("get_active_public_key_by_identifier", {"identifier": "recipient"}) in service.calls
