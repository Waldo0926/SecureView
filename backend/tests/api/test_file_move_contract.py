"""Moving a file into a folder, through the real route.

The bug this guards: `FileMoveIn` inherited strict validation, and FastAPI validates a request
body from the already-parsed JSON, where a UUID can only be text. Strict mode refuses text for a
UUID, so choosing any folder answered 422 "folder_id: Input should be an instance of UUID".
Unfiled (`null`) kept working, which is why it went unnoticed. Unit tests that build the model
from a `UUID` object, or from a raw JSON string, cannot see this; only the HTTP path can.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_actor, get_file_service
from app.core.config import Settings
from app.domain.auth import ActorContext
from app.domain.enums import SystemRole, UserStatus
from app.main import create_app
from app.schemas.file_schema import FileMoveOut

FILE_ID = UUID("11111111-1111-4111-8111-111111111111")
FOLDER_ID = UUID("3f2c9d1e-5b7a-4c1d-8e2f-1a2b3c4d5e6f")


def _actor() -> ActorContext:
    return ActorContext(
        user_id=7,
        user_public_id=UUID("44444444-4444-4444-8444-444444444444"),
        session_id=8,
        session_public_id=UUID("55555555-5555-4555-8555-555555555555"),
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        access_token_hash="a" * 64,
    )


class RecordingFileService:
    def __init__(self) -> None:
        self.moves: list[tuple[UUID, UUID | None]] = []

    def move_file(self, *, actor: ActorContext, file_id: UUID, folder_id: UUID | None):
        self.moves.append((file_id, folder_id))
        return FileMoveOut(file_id=file_id, folder_id=folder_id)


@pytest.fixture
def api() -> Generator[tuple[TestClient, RecordingFileService], None, None]:
    service = RecordingFileService()
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            APP_DEBUG=False,
            SECRET_KEY="test-secret-key-that-is-long-enough",
        )
    )
    application.dependency_overrides[get_current_actor] = _actor
    application.dependency_overrides[get_file_service] = lambda: service
    with TestClient(application) as client:
        yield client, service
    application.dependency_overrides.clear()


def test_moving_a_file_into_a_folder_accepts_the_folder_id_as_json_text(api) -> None:
    client, service = api

    response = client.post(f"/api/v1/files/{FILE_ID}/move", json={"folder_id": str(FOLDER_ID)})

    assert response.status_code == 200, response.text
    assert service.moves == [(FILE_ID, FOLDER_ID)]
    assert response.json()["data"]["folder_id"] == str(FOLDER_ID)


def test_moving_a_file_out_of_its_folder_still_takes_null(api) -> None:
    client, service = api

    response = client.post(f"/api/v1/files/{FILE_ID}/move", json={"folder_id": None})

    assert response.status_code == 200, response.text
    assert service.moves == [(FILE_ID, None)]


@pytest.mark.parametrize(
    "body",
    [
        {"folder_id": "not-a-uuid"},
        {"folder_id": 12345},
        {"folder_id": ""},
        {},  # the field is required: omitting it must not silently mean "unfiled"
        {"folder_id": str(FOLDER_ID), "owner_id": 1},  # unknown fields stay forbidden
    ],
)
def test_a_malformed_move_body_is_still_refused_before_the_service(api, body) -> None:
    client, service = api

    response = client.post(f"/api/v1/files/{FILE_ID}/move", json=body)

    assert response.status_code == 422
    assert service.moves == []
