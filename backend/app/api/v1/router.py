from fastapi import APIRouter

from app.api.v1.routers import (
    admin_router,
    audit_router,
    auth_router,
    file_router,
    key_router,
    recovery_router,
    share_router,
)

api_router = APIRouter()

api_router.include_router(
    auth_router.router,
    prefix="/auth",
    tags=["Auth"],
)
api_router.include_router(
    key_router.router,
    prefix="/keys",
    tags=["Keys"],
)
api_router.include_router(
    file_router.router,
    prefix="/files",
    tags=["Files"],
)
api_router.include_router(
    share_router.router,
    prefix="/files",
    tags=["Sharing"],
)
api_router.include_router(
    audit_router.router,
    prefix="/audit-logs",
    tags=["Audit Logs"],
)
api_router.include_router(
    recovery_router.router,
    prefix="/recovery",
    tags=["Recovery"],
)
api_router.include_router(
    admin_router.router,
    prefix="/admin",
    tags=["Admin"],
)
