from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import (
    get_account_deletion_service,
    get_auth_service,
    get_avatar_service,
    get_current_actor,
    get_request_context,
    get_settings,
)
from app.api.responses import AUTH_NO_STORE_HEADERS, ApiSuccessResponse, ok
from app.core.config import Settings
from app.domain.auth import ActorContext, RequestContext
from app.schemas.auth_schema import (
    AuthMeResponse,
    AuthRefreshRequest,
    AuthRefreshResponse,
    AuthSessionListResponse,
    AuthSessionResponse,
    AuthSessionRevokeResponse,
    AuthUserResponse,
    AvatarMetaResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    DeleteAccountRequest,
    DeleteAccountResponse,
    PasswordResetRequest,
    PasswordResetResponse,
    SendVerificationCodeRequest,
    SendVerificationCodeResponse,
    UserLoginRequest,
    UserLoginResponse,
    UserLogoutAllResponse,
    UserLogoutResponse,
    UserRegisterRequest,
    UserRegisterResponse,
)
from app.services.account_deletion_service import AccountDeletionService
from app.services.auth_service import AuthService
from app.services.avatar_service import AvatarService

router = APIRouter()

AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
AccountDeletionServiceDependency = Annotated[
    AccountDeletionService, Depends(get_account_deletion_service)
]
AvatarServiceDependency = Annotated[AvatarService, Depends(get_avatar_service)]
ActorDependency = Annotated[ActorContext, Depends(get_current_actor)]
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/verification-codes/send",
    response_model=ApiSuccessResponse[SendVerificationCodeResponse],
)
def send_verification_code(
    payload: SendVerificationCodeRequest,
    auth_service: AuthServiceDependency,
    settings: SettingsDependency,
    context: RequestContextDependency,
) -> JSONResponse:
    auth_service.send_verification_code(
        purpose=payload.purpose,
        email=str(payload.email),
        context=context,
    )
    response_data = SendVerificationCodeResponse(
        expires_in_seconds=settings.VERIFICATION_CODE_TTL_SECONDS,
        resend_available_in_seconds=settings.VERIFICATION_RESEND_INTERVAL_SECONDS,
    )
    # The same response is returned whether or not the address has an account,
    # so this endpoint cannot be used to enumerate registered users.
    return ok(
        message="If the address is eligible, a verification code has been sent",
        data=response_data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/register",
    response_model=ApiSuccessResponse[UserRegisterResponse],
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: UserRegisterRequest,
    auth_service: AuthServiceDependency,
    context: RequestContextDependency,
) -> JSONResponse:
    result = auth_service.register(
        username=payload.username,
        email=str(payload.email),
        password=payload.password,
        verification_code=payload.verification_code,
        key_material=payload.key_material.to_domain(),
        context=context,
    )
    response_data = UserRegisterResponse.model_validate(result)
    return ok(
        message="Registration successful",
        data=response_data,
        code=status.HTTP_201_CREATED,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/login", response_model=ApiSuccessResponse[UserLoginResponse])
def login(
    payload: UserLoginRequest,
    auth_service: AuthServiceDependency,
    context: RequestContextDependency,
) -> JSONResponse:
    result = auth_service.login(
        username=payload.username,
        password=payload.password,
        context=context,
    )
    response_data = UserLoginResponse(
        user=AuthUserResponse.model_validate(result.user),
        access_token=result.tokens.access_token,
        refresh_token=result.tokens.refresh_token,
        token_type=result.tokens.token_type,
        access_expires_at=result.tokens.access_expires_at,
        refresh_expires_at=result.tokens.refresh_expires_at,
        session_id=result.tokens.session_id,
    )
    return ok(
        message="Login successful",
        data=response_data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/refresh", response_model=ApiSuccessResponse[AuthRefreshResponse])
def refresh(
    payload: AuthRefreshRequest,
    auth_service: AuthServiceDependency,
    context: RequestContextDependency,
) -> JSONResponse:
    result = auth_service.refresh(refresh_token=payload.refresh_token, context=context)
    response_data = AuthRefreshResponse.model_validate(result.tokens)
    return ok(
        message="Session refreshed",
        data=response_data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get("/me", response_model=ApiSuccessResponse[AuthMeResponse])
def me(
    actor: ActorDependency,
    auth_service: AuthServiceDependency,
) -> JSONResponse:
    user = auth_service.get_me(actor=actor)
    response_data = AuthMeResponse(user=AuthUserResponse.model_validate(user))
    return ok(
        message="Current account retrieved",
        data=response_data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/avatar/upload",
    response_model=ApiSuccessResponse[AvatarMetaResponse],
)
async def upload_avatar(
    actor: ActorDependency,
    context: RequestContextDependency,
    service: AvatarServiceDependency,
    file: UploadFile = File(...),
) -> JSONResponse:
    """Replace the caller's profile picture with a validated PNG or JPEG."""
    meta = await service.upload(actor=actor, upload=file, context=context)
    return ok(
        message="Avatar updated",
        data=AvatarMetaResponse(
            has_avatar=meta.has_avatar,
            content_type=meta.content_type,
            updated_at=meta.updated_at,
            size_bytes=meta.size_bytes,
        ),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get("/avatar")
async def get_avatar(
    actor: ActorDependency,
    service: AvatarServiceDependency,
) -> Response:
    """Serve the caller's avatar bytes. Auth required; never cache across users."""
    payload = await service.get_bytes(actor=actor)
    headers = {
        **AUTH_NO_STORE_HEADERS,
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    }
    if payload.sha256:
        headers["ETag"] = f'"{payload.sha256}"'
    return Response(
        content=payload.body,
        media_type=payload.content_type,
        headers=headers,
    )


@router.post(
    "/avatar/delete",
    response_model=ApiSuccessResponse[AvatarMetaResponse],
)
async def delete_avatar(
    actor: ActorDependency,
    context: RequestContextDependency,
    service: AvatarServiceDependency,
) -> JSONResponse:
    meta = await service.delete(actor=actor, context=context)
    return ok(
        message="Avatar removed",
        data=AvatarMetaResponse(
            has_avatar=meta.has_avatar,
            content_type=meta.content_type,
            updated_at=meta.updated_at,
            size_bytes=meta.size_bytes,
        ),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/logout", response_model=ApiSuccessResponse[UserLogoutResponse])
def logout(
    actor: ActorDependency,
    context: RequestContextDependency,
    auth_service: AuthServiceDependency,
) -> JSONResponse:
    auth_service.logout(actor=actor, context=context)
    return ok(
        message="Logout successful",
        data=UserLogoutResponse(),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/logout-all", response_model=ApiSuccessResponse[UserLogoutAllResponse])
def logout_all(
    actor: ActorDependency,
    context: RequestContextDependency,
    auth_service: AuthServiceDependency,
) -> JSONResponse:
    revoked_sessions = auth_service.logout_all(actor=actor, context=context)
    response_data = UserLogoutAllResponse(revoked_sessions=revoked_sessions)
    return ok(
        message="All sessions logged out",
        data=response_data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post("/delete-account", response_model=ApiSuccessResponse[DeleteAccountResponse])
def delete_account(
    payload: DeleteAccountRequest,
    actor: ActorDependency,
    context: RequestContextDependency,
    service: AccountDeletionServiceDependency,
) -> JSONResponse:
    """Close the account and destroy the files it owns. Not reversible.

    Exists because a forgotten encryption passphrase cannot be recovered or reset by design,
    so starting over is the only remaining path -- and it should not require a teammate with
    database access. The password is required again on top of the live session: this is the
    one irreversible action in the application.
    """
    result = service.delete_account(
        actor=actor,
        password=payload.password,
        context=context,
    )
    return ok(
        message="Account deleted",
        data=DeleteAccountResponse(
            files_deleted=result.files_deleted,
            sessions_revoked=result.sessions_revoked,
        ),
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/change-password",
    response_model=ApiSuccessResponse[ChangePasswordResponse],
)
def change_password(
    payload: ChangePasswordRequest,
    actor: ActorDependency,
    context: RequestContextDependency,
    auth_service: AuthServiceDependency,
) -> JSONResponse:
    revoked_sessions = auth_service.change_password(
        actor=actor,
        current_password=payload.current_password,
        new_password=payload.new_password,
        context=context,
    )
    response_data = ChangePasswordResponse(revoked_sessions=revoked_sessions)
    return ok(
        message="Password changed; please log in again",
        data=response_data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/password-reset",
    response_model=ApiSuccessResponse[PasswordResetResponse],
)
def reset_password(
    payload: PasswordResetRequest,
    auth_service: AuthServiceDependency,
    context: RequestContextDependency,
) -> JSONResponse:
    revoked_sessions = auth_service.reset_password(
        username=payload.username,
        email=str(payload.email),
        verification_code=payload.verification_code,
        new_password=payload.new_password,
        context=context,
    )
    response_data = PasswordResetResponse(revoked_sessions=revoked_sessions)
    return ok(
        message="Password reset successfully; please log in with the new password",
        data=response_data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.get("/sessions", response_model=ApiSuccessResponse[AuthSessionListResponse])
def list_sessions(
    actor: ActorDependency,
    auth_service: AuthServiceDependency,
) -> JSONResponse:
    sessions = auth_service.list_sessions(actor=actor)
    response_data = AuthSessionListResponse(
        sessions=[AuthSessionResponse.model_validate(session) for session in sessions]
    )
    return ok(
        message="Sessions retrieved",
        data=response_data,
        headers=AUTH_NO_STORE_HEADERS,
    )


@router.post(
    "/sessions/{session_id}/revoke",
    response_model=ApiSuccessResponse[AuthSessionRevokeResponse],
)
def revoke_session(
    session_id: UUID,
    actor: ActorDependency,
    context: RequestContextDependency,
    auth_service: AuthServiceDependency,
) -> JSONResponse:
    auth_service.revoke_session(actor=actor, session_id=session_id, context=context)
    response_data = AuthSessionRevokeResponse(session_id=session_id)
    return ok(
        message="Session revoked",
        data=response_data,
        headers=AUTH_NO_STORE_HEADERS,
    )
