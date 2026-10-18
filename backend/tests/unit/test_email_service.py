from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from app.core.config import Settings
from app.services.email_service import EmailDeliveryError, EmailService, OutboundEmail


def _settings(**overrides: Any) -> Settings:
    base = {
        "_env_file": None,
        "APP_ENV": "test",
        "APP_DEBUG": False,
        "SECRET_KEY": "test-secret-key-that-is-long-enough",
    }
    base.update(overrides)
    return Settings(**base)


def _message() -> OutboundEmail:
    return OutboundEmail(
        to_address="alice@example.com",
        subject="Your code",
        text_body="Verification code: 123456",
        html_body="<p>123456</p>",
    )


class _Response:
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_resend_sets_an_explicit_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resend's edge answers 403 to urllib's default "Python-urllib/x.y" agent.

    That failure only appears against the live provider, so pin the header here.
    """
    captured: dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, **_: object) -> _Response:
        captured["headers"] = dict(request.headers)
        captured["url"] = request.full_url
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    service = EmailService(_settings(EMAIL_PROVIDER="resend", RESEND_API_KEY="re_test_key"))
    service.send(_message())

    # urllib title-cases header names it stores on the request.
    agent = captured["headers"].get("User-agent") or captured["headers"].get("User-Agent")
    assert agent is not None
    assert "urllib" not in agent.lower()
    assert agent.startswith("SecureView/")


def test_resend_authorises_with_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, **_: object) -> _Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode())
        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    service = EmailService(
        _settings(
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="re_test_key",
            EMAIL_FROM_ADDRESS="no-reply@secureview.tech",
            EMAIL_FROM_NAME="SecureView",
        )
    )
    service.send(_message())

    authorization = captured["headers"].get("Authorization")
    assert authorization == "Bearer re_test_key"
    assert captured["body"]["from"] == "SecureView <no-reply@secureview.tech>"
    assert captured["body"]["to"] == ["alice@example.com"]


def test_resend_http_error_reports_the_status_without_the_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 403 must be diagnosable, but the body can echo the recipient."""

    class _ErrorBody:
        @staticmethod
        def read() -> bytes:
            return json.dumps(
                {"name": "validation_error", "message": "alice@example.com is not allowed"}
            ).encode()

    def fake_urlopen(*_: object, **__: object) -> _Response:
        raise urllib.error.HTTPError(
            url="https://api.resend.com/emails",
            code=403,
            msg="Forbidden",
            hdrs=None,  # type: ignore[arg-type]
            fp=_ErrorBody(),  # type: ignore[arg-type]
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    service = EmailService(_settings(EMAIL_PROVIDER="resend", RESEND_API_KEY="re_test_key"))
    with caplog.at_level("ERROR"), pytest.raises(EmailDeliveryError, match="403"):
        service.send(_message())

    logged = caplog.text
    assert "validation_error" in logged
    assert "alice@example.com" not in logged


def test_console_provider_never_reaches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object, **__: object) -> None:
        raise AssertionError("console delivery must not open a connection")

    monkeypatch.setattr(urllib.request, "urlopen", explode)

    EmailService(_settings(EMAIL_PROVIDER="console")).send(_message())
