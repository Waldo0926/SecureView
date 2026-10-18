from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from app.api.body_limit import RequestBodyLimitMiddleware
from app.api.dependencies import get_auth_service
from app.domain.errors import InvalidCredentialsError
from app.main import create_app

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RejectingAuthService:
    def __init__(self) -> None:
        self.login_calls = 0

    def login(self, **values: Any):
        del values
        self.login_calls += 1
        raise InvalidCredentialsError()


def _http_scope(path: str) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }


async def _consume_body_app(scope: Scope, receive: Receive, send: Send) -> None:
    del scope
    while True:
        message = await receive()
        if message["type"] != "http.request" or not message.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def _run_streamed_request(
    *,
    path: str,
    chunks: list[bytes],
    max_body_bytes: int,
    max_upload_bytes: int,
) -> list[Message]:
    async def invoke() -> list[Message]:
        incoming = [
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks) - 1,
            }
            for index, chunk in enumerate(chunks)
        ]
        sent: list[Message] = []

        async def receive() -> Message:
            return incoming.pop(0)  # pragma: no branch - the app consumes the declared chunks

        async def send(message: Message) -> None:
            sent.append(message)

        middleware = RequestBodyLimitMiddleware(
            _consume_body_app,
            max_body_bytes=max_body_bytes,
            max_upload_bytes=max_upload_bytes,
            upload_path="/api/v1/files/upload",
        )
        await middleware(_http_scope(path), receive, send)
        return sent

    return asyncio.run(invoke())


def test_anonymous_two_megabyte_login_json_is_rejected_from_content_length() -> None:
    application = create_app()
    auth_service = RejectingAuthService()
    application.dependency_overrides[get_auth_service] = lambda: auth_service

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "username": "alice",
                "password": "not-a-real-password",
                "padding": "x" * (2 * 1024 * 1024),
            },
        )

    assert response.status_code == 413
    assert response.json()["data"]["error_code"] == "request_too_large"
    assert response.json()["message"] == "The request body is too large"
    assert response.headers["cache-control"].startswith("no-store")
    assert auth_service.login_calls == 0


def test_streamed_body_without_content_length_is_rejected_after_crossing_limit() -> None:
    sent = _run_streamed_request(
        path="/api/v1/auth/login",
        chunks=[b"12345", b"6789"],
        max_body_bytes=8,
        max_upload_bytes=16,
    )

    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    assert start["status"] == 413
    assert json.loads(body)["data"]["error_code"] == "request_too_large"


def test_upload_path_uses_upload_cap_instead_of_smaller_global_cap() -> None:
    sent = _run_streamed_request(
        path="/api/v1/files/upload",
        chunks=[b"123456", b"789012"],
        max_body_bytes=8,
        max_upload_bytes=16,
    )

    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 204


def test_normal_login_body_reaches_route_and_bodyless_reads_are_not_blocked() -> None:
    application = create_app()
    auth_service = RejectingAuthService()
    application.dependency_overrides[get_auth_service] = lambda: auth_service

    with TestClient(application) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "not-a-real-password"},
        )
        liveness = client.get("/health/live")
        download = client.post(
            f"/api/v1/files/{UUID('11111111-1111-4111-8111-111111111111')}/download"
        )

    assert login.status_code == 401
    assert login.json()["data"]["error_code"] == "invalid_credentials"
    assert auth_service.login_calls == 1
    assert liveness.status_code == 200
    assert download.status_code == 401
