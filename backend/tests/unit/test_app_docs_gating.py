from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        APP_DEBUG=False,
        SECRET_KEY="test-secret-key-that-is-long-enough",
        **overrides,
    )


def _paths(app) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def test_docs_are_available_by_default() -> None:
    # Local development should not have to opt in; the cost of the schema is only about
    # exposing it to the internet.
    paths = _paths(create_app(_settings()))

    assert "/docs" in paths
    assert "/redoc" in paths
    assert "/openapi.json" in paths


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_disabling_docs_unmounts_the_route_entirely(path: str) -> None:
    # Un-mounted, not forbidden: a 403 would confirm the documentation is there to be found.
    paths = _paths(create_app(_settings(APP_DOCS_ENABLED=False)))

    assert path not in paths


def test_disabling_docs_leaves_the_api_itself_alone() -> None:
    # The API is mounted as a sub-application, so this has to be asked over HTTP rather than
    # read off app.routes.
    client = TestClient(create_app(_settings(APP_DOCS_ENABLED=False)))

    # 404 would mean the route is gone; anything else means it is there and merely refused
    # an empty body.
    assert client.post("/api/v1/auth/login", json={}).status_code != 404
    assert client.get("/health/live").status_code == 200
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
