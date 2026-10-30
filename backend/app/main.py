import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.body_limit import RequestBodyLimitMiddleware
from app.api.error_handlers import register_exception_handlers
from app.api.v1.router import api_router
from app.core.config import REPO_ROOT, Settings, settings
from app.core.database import (
    create_db_engine,
    create_session_factory,
)
from app.core.database import (
    engine as default_engine,
)
from app.core.observability import (
    ObservabilityMiddleware,
    ObservabilityState,
    configure_event_logger,
)
from app.core.security import PasswordManager

RELEASE_IDENTITY_FILE = REPO_ROOT / ".mcs21-release"
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{7,40}")


def resolve_commit(
    app_settings: Settings, identity_file: Path = RELEASE_IDENTITY_FILE
) -> str | None:
    """Return the running commit SHA, or None when it is not known (local development)."""
    value = app_settings.APP_COMMIT
    if not value:
        try:
            value = identity_file.read_text(encoding="utf-8")
        except OSError:
            return None
    value = value.strip().lower()
    return value if _COMMIT_PATTERN.fullmatch(value) else None


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        application.state.db_engine.dispose()


def create_app(app_settings: Settings | None = None) -> FastAPI:
    active_settings = app_settings or settings
    configure_event_logger(active_settings.LOG_LEVEL)
    observability = ObservabilityState()

    # Passing None un-mounts the route entirely, so a disabled schema is a 404 rather than a
    # 403 -- it does not confirm that the documentation is there to be found.
    docs_enabled = active_settings.APP_DOCS_ENABLED
    application = FastAPI(
        title=active_settings.APP_NAME,
        version=active_settings.APP_VERSION,
        description="Secure File Encryption and Sharing Platform API",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    application.state.settings = active_settings
    application.state.observability = observability
    application.state.db_engine = (
        default_engine
        if active_settings is settings
        else create_db_engine(
            active_settings.DATABASE_URL,
            connect_args=active_settings.DATABASE_CONNECT_ARGS,
        )
    )
    application.state.db_session_factory = create_session_factory(application.state.db_engine)
    application.state.password_manager = PasswordManager(
        max_concurrent_operations=active_settings.AUTH_PASSWORD_HASH_CONCURRENCY
    )

    application.add_middleware(
        ObservabilityMiddleware,
        state=observability,
        api_prefix=active_settings.API_PREFIX,
    )
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=active_settings.MAX_REQUEST_BODY_BYTES,
        max_upload_bytes=(
            active_settings.MAX_UPLOAD_SIZE_BYTES
            + active_settings.MAX_UPLOAD_REQUEST_OVERHEAD_BYTES
        ),
        upload_path=f"{active_settings.API_PREFIX}/files/upload",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.CORS_ORIGINS,
        allow_credentials=active_settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix=active_settings.API_PREFIX)
    register_exception_handlers(application)

    @application.get("/")
    def root():
        return {
            "success": True,
            "message": "Secure File Encryption Platform API is running",
            "docs": "/docs",
        }

    commit = resolve_commit(active_settings)

    @application.get("/health/live", tags=["Health"])
    def liveness():
        # mcs21-deploy compares this with the commit it just deployed.
        return {"status": "ok", "commit": commit}

    @application.get("/health/ready", tags=["Health"])
    def readiness():
        try:
            with application.state.db_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                revision = connection.scalar(
                    text("SELECT schema_revision FROM audit_chain_heads WHERE id = 1")
                )
        except Exception:
            observability.mark_readiness("database_unavailable")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "reason": "database_unavailable"},
            )
        if revision != active_settings.EXPECTED_SCHEMA_REVISION:
            observability.mark_readiness(
                "schema_incompatible",
                expected_schema=active_settings.EXPECTED_SCHEMA_REVISION,
                observed_schema=str(revision) if revision is not None else None,
            )
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "reason": "schema_incompatible"},
            )
        observability.mark_readiness("ready")
        return {"status": "ready"}

    @application.get("/internal/metrics", include_in_schema=False)
    def internal_metrics():
        # Production Uvicorn binds to 127.0.0.1 and nginx does not proxy /internal/.
        # This is intentionally a host-local operations surface, not a public API.
        return observability.snapshot()

    return application


app = create_app()
