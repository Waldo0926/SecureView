from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from app.api.responses import AUTH_NO_STORE_HEADERS

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class _BodyLimitExceeded(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Bound request bodies before JSON parsing or multipart spooling can exhaust resources."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_upload_bytes: int,
        upload_path: str,
        max_body_bytes: int,
    ) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        if max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_upload_bytes = max_upload_bytes
        self.upload_path = upload_path.rstrip("/") or "/"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_upload = self._is_upload(scope)
        max_bytes = self.max_upload_bytes if is_upload else self.max_body_bytes
        content_length = self._content_length(scope)
        if content_length is not None and content_length > max_bytes:
            await self._reject(scope, receive, send, is_upload=is_upload)
            return

        consumed = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > max_bytes:
                    raise _BodyLimitExceeded
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _BodyLimitExceeded:
            if response_started:  # pragma: no cover - multipart is parsed before routing
                raise
            await self._reject(scope, receive, send, is_upload=is_upload)

    def _is_upload(self, scope: Scope) -> bool:
        path = (scope.get("path") or "/").rstrip("/") or "/"
        return path == self.upload_path

    def _content_length(self, scope: Scope) -> int | None:
        for raw_name, raw_value in scope.get("headers", ()):
            if raw_name.lower() != b"content-length":
                continue
            try:
                value = int(raw_value)
            except ValueError:
                return None
            return max(value, 0)
        return None

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        is_upload: bool,
    ) -> None:
        response = JSONResponse(
            status_code=413,
            headers=AUTH_NO_STORE_HEADERS,
            content={
                "success": False,
                "status": "fail",
                "message": (
                    "The encrypted upload request is too large"
                    if is_upload
                    else "The request body is too large"
                ),
                "data": {"error_code": "request_too_large", "details": None},
                "description": None,
                "code": 413,
            },
        )
        await response(scope=scope, receive=receive, send=send)
