import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.error_handlers import register_exception_handlers
from app.domain.errors import (
    AppError,
    LastAdministratorError,
    PasswordChangeRequiredError,
    ResourceNotFoundError,
)


def _test_app() -> FastAPI:
    application = FastAPI()
    register_exception_handlers(application)

    @application.get("/missing")
    def missing() -> None:
        raise ResourceNotFoundError()

    @application.post("/validated")
    def validated(secret_value: int) -> dict[str, Any]:
        return {"secret_value": secret_value}

    @application.get("/unexpected")
    def unexpected() -> None:
        raise RuntimeError("database-password=must-not-appear")

    return application


def test_application_error_has_stable_public_code() -> None:
    client = TestClient(_test_app())

    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json()["data"]["error_code"] == "resource_not_found"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (PasswordChangeRequiredError(), 403, "password_change_required"),
        (LastAdministratorError(), 409, "last_admin"),
    ],
)
def test_account_safety_refusals_keep_their_status_and_code(
    error: AppError, status: int, code: str
) -> None:
    # The frontend acts on these codes: one sends the holder to the password card, the
    # other explains why the last administrator cannot leave.
    application = FastAPI()
    register_exception_handlers(application)

    @application.get("/refused")
    def refused() -> None:
        raise error

    response = TestClient(application).get("/refused")

    assert response.status_code == status
    assert response.json()["data"]["error_code"] == code


def test_validation_error_does_not_echo_request_input() -> None:
    client = TestClient(_test_app())

    response = client.post("/validated?secret_value=do-not-echo-this")
    body = response.json()

    assert response.status_code == 422
    assert "do-not-echo-this" not in response.text
    assert body["data"]["error_code"] == "request_validation_failed"


def test_unexpected_error_does_not_log_exception_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_test_app(), raise_server_exceptions=False)
    secret = "database-password=must-not-appear"

    with caplog.at_level("ERROR", logger="secureview.events"):
        response = client.get("/unexpected")

    assert response.status_code == 500
    assert response.json()["data"]["error_code"] == "internal_error"
    assert secret not in response.text
    assert secret not in caplog.text

    event = json.loads(caplog.records[-1].getMessage())
    assert event["event"] == "application.unhandled_error"
    assert event["error_type"] == "RuntimeError"
