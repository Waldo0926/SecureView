from __future__ import annotations

import json
import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.observability import (
    ObservabilityMiddleware,
    ObservabilityState,
    configure_event_logger,
    emit_event,
    request_client_network,
)


def _request(client: tuple[str, int]) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": client,
            "server": ("127.0.0.1", 8000),
        }
    )


def test_structured_event_redacts_risky_fields(caplog) -> None:
    configure_event_logger("INFO")
    with caplog.at_level(logging.INFO, logger="secureview.events"):
        emit_event(
            "test.event",
            route_template="/api/v1/files/{file_id}",
            access_token="bearer-should-never-leak",
            password="password-should-never-leak",
            original_filename="private-name.txt",
            plaintext_content="private bytes",
            nested={"private_key_pem": "pem-secret", "safe_count": 3},
        )

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload["event"] == "test.event"
    assert payload["route_template"] == "/api/v1/files/{file_id}"
    assert payload["access_token"] == "[REDACTED]"
    assert payload["password"] == "[REDACTED]"
    assert payload["original_filename"] == "[REDACTED]"
    assert payload["plaintext_content"] == "[REDACTED]"
    assert payload["nested"]["private_key_pem"] == "[REDACTED]"
    assert payload["nested"]["safe_count"] == 3
    rendered = caplog.records[-1].getMessage()
    for forbidden in (
        "bearer-should-never-leak",
        "password-should-never-leak",
        "private-name.txt",
        "private bytes",
        "pem-secret",
    ):
        assert forbidden not in rendered


def test_client_address_is_reduced_to_a_network() -> None:
    assert request_client_network(_request(("203.0.113.42", 1234))) == "203.0.113.0/24"
    assert request_client_network(_request(("2001:db8:abcd:1234::42", 1234))) == (
        "2001:db8:abcd:1234::/64"
    )
    assert request_client_network(_request(("not-an-ip", 1234))) == "unknown"


def test_readiness_counts_transitions_not_probe_frequency() -> None:
    state = ObservabilityState()

    state.mark_readiness(
        "schema_incompatible",
        expected_schema="0011_must_change_password",
        observed_schema="0005_previous",
    )
    state.mark_readiness(
        "schema_incompatible",
        expected_schema="0011_must_change_password",
        observed_schema="0005_previous",
    )
    first = state.snapshot()
    assert first["readiness_failures_total"] == 1
    assert first["schema_mismatch_total"] == 1

    state.mark_readiness("ready")
    state.mark_readiness(
        "schema_incompatible",
        expected_schema="0011_must_change_password",
        observed_schema="0005_previous",
    )
    second = state.snapshot()
    assert second["readiness_failures_total"] == 2
    assert second["schema_mismatch_total"] == 2


def test_recovery_middleware_logs_only_route_template_and_counts_request(caplog) -> None:
    configure_event_logger("INFO")
    state = ObservabilityState()
    app = FastAPI()
    app.add_middleware(ObservabilityMiddleware, state=state, api_prefix="/api/v1")

    @app.post("/api/v1/recovery/{request_id}/approve")
    def approve(request_id: str):
        return {"request_id": request_id}

    actual_id = str(uuid4())
    with caplog.at_level(logging.INFO, logger="secureview.events"):
        response = TestClient(app).post(f"/api/v1/recovery/{actual_id}/approve")

    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) == 16
    snapshot = state.snapshot()
    assert snapshot["requests_total"] == 1
    assert snapshot["recovery_operations_total"] == 1

    event = json.loads(
        next(
            record.getMessage()
            for record in caplog.records
            if '"event":"recovery.operation"' in record.getMessage()
        )
    )
    assert event["route_template"] == "/api/v1/recovery/{request_id}/approve"
    assert actual_id not in json.dumps(event)
