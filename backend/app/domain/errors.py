from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar


class AppError(Exception):
    """Expected application failure that is safe to translate at the API edge."""

    code: ClassVar[str] = "application_error"
    public_message: ClassVar[str] = "The request could not be completed"
    default_headers: ClassVar[Mapping[str, str]] = {}

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.message = message or self.public_message
        self.details = details
        self.headers = {**self.default_headers, **(headers or {})}
        super().__init__(self.message)


class AuthenticationError(AppError):
    code = "authentication_required"
    public_message = "Authentication is required"
    default_headers: ClassVar[Mapping[str, str]] = {"WWW-Authenticate": "Bearer"}


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    public_message = "Invalid username or password"


class InvalidRefreshTokenError(AuthenticationError):
    code = "invalid_refresh_token"
    public_message = "The refresh token is invalid or expired"


class AuthorizationError(AppError):
    code = "access_denied"
    public_message = "You do not have permission to perform this action"


class PasswordChangeRequiredError(AuthorizationError):
    """An administrator reset this account's password, and the holder has not replaced it yet.

    The temporary password was seen by the administrator and travelled by hand, so until the
    holder chooses their own the session can do only what replacing it takes.
    """

    code = "password_change_required"
    public_message = "Choose a new login password before continuing"


class ResourceNotFoundError(AppError):
    code = "resource_not_found"
    public_message = "The requested resource was not found"


class ConflictError(AppError):
    code = "conflict"
    public_message = "The request conflicts with the current resource state"


class AccountIdentifierUnavailableError(ConflictError):
    code = "account_identifier_unavailable"
    public_message = "The username is unavailable"


class LastAdministratorError(ConflictError):
    """The change would leave the platform with no active administrator.

    Nothing in the application can appoint one, so the only way back would be an edit in the
    database.
    """

    code = "last_admin"
    public_message = (
        "This is the only active administrator account; another administrator must be active first"
    )


class InputError(AppError):
    code = "invalid_input"
    public_message = "The request input is invalid"


class PasswordUnchangedError(InputError):
    code = "password_unchanged"
    public_message = "The new password must be different from the current password"


class WeakPasswordError(InputError):
    code = "weak_password"
    public_message = "The password does not meet the security requirements"


class InvalidCurrentPasswordError(InputError):
    code = "invalid_current_password"
    public_message = "The current password is invalid"


class VerificationCodeInvalidError(InputError):
    code = "invalid_verification_code"
    public_message = "The verification code is incorrect or has expired"


class VerificationCodeRequiredError(InputError):
    code = "verification_code_required"
    public_message = "Request and enter an email verification code first"


class EmailDeliveryFailedError(AppError):
    code = "email_delivery_failed"
    public_message = "The verification email could not be sent; please try again later"


class SessionNotFoundError(ResourceNotFoundError):
    code = "session_not_found"
    public_message = "The requested session was not found"


class FileResourceNotFoundError(ResourceNotFoundError):
    code = "file_not_found"
    public_message = "The requested file was not found"


class FileFolderNotFoundError(ResourceNotFoundError):
    code = "file_folder_not_found"
    public_message = "The requested file folder was not found"


class FileFolderNameConflictError(ConflictError):
    code = "file_folder_name_conflict"
    public_message = "You already have a file folder with this name"


class UserKeyNotFoundError(ResourceNotFoundError):
    code = "user_key_not_found"
    public_message = "The requested encryption key was not found"


class KeyProtectionProfileNotFoundError(ResourceNotFoundError):
    code = "key_protection_profile_not_found"
    public_message = "The account key-protection profile was not found"


class RecoveryRequestNotFoundError(ResourceNotFoundError):
    code = "recovery_request_not_found"
    public_message = "The requested recovery request was not found"


class KeyBundleRevisionConflictError(ConflictError):
    code = "key_bundle_revision_conflict"
    public_message = "The encrypted key bundle has changed; reload it and try again"


class KeyProtectionResetUnavailableError(ConflictError):
    """The account holds more than one key, so one private key file cannot reset it.

    Every bundle is sealed under a key derived from the single AMK. Replacing the AMK with
    only one private key in hand would leave the others permanently unopenable, and with
    them every file wrapped to those keys.
    """

    code = "key_protection_reset_unavailable"
    public_message = (
        "This account holds more than one encryption key, so a single private key file "
        "cannot reset its passphrase without making the others unopenable"
    )


class KeyBundleInvalidError(InputError):
    code = "invalid_key_bundle"
    public_message = "The encrypted key bundle is invalid"


class FileEnvelopeInvalidError(InputError):
    code = "invalid_file_envelope"
    public_message = "The encrypted file envelope is invalid"


class FileTooLargeError(InputError):
    code = "file_too_large"
    public_message = "The encrypted file exceeds the upload size limit"


class StorageQuotaExceededError(InputError):
    code = "storage_quota_exceeded"
    public_message = "This upload would take your account over its storage limit"


class UploadDailyLimitError(AppError):
    code = "upload_daily_limit"
    public_message = "You have reached the upload limit for the last 24 hours"


class ServerStorageLowError(AppError):
    code = "server_storage_low"
    public_message = "The server is low on storage and is not accepting uploads right now"


class FileStateConflictError(ConflictError):
    code = "file_state_conflict"
    public_message = "The file is not in a state that permits this action"


class ShareStateConflictError(ConflictError):
    code = "share_state_conflict"
    public_message = "The sharing state conflicts with this request"


class RecoveryStateConflictError(ConflictError):
    code = "recovery_state_conflict"
    public_message = "The recovery request is not in a state that permits this action"


class StorageUnavailableError(AppError):
    code = "storage_unavailable"
    public_message = "Encrypted file storage is temporarily unavailable"


class IntegrityVerificationError(AppError):
    code = "integrity_verification_failed"
    public_message = "The encrypted file could not be verified"


class AuthenticationRateLimitedError(AppError):
    code = "auth_rate_limited"
    public_message = "Too many authentication attempts; please try again later"

    def __init__(
        self,
        message: str | None = None,
        *,
        retry_after_seconds: int | None = None,
        details: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        response_headers = dict(headers or {})
        if retry_after_seconds is not None:
            response_headers["Retry-After"] = str(max(0, retry_after_seconds))
        super().__init__(message, details=details, headers=response_headers)


class AvatarInvalidError(InputError):
    code = "avatar_invalid"
    public_message = "The avatar must be a PNG or JPEG image"


class AvatarTooLargeError(AppError):
    code = "avatar_too_large"
    public_message = "The avatar exceeds the upload size limit"


class AvatarNotFoundError(ResourceNotFoundError):
    code = "avatar_not_found"
    public_message = "No avatar is set for this account"


class AvatarUpdateRateLimitedError(AuthenticationRateLimitedError):
    code = "avatar_rate_limited"
    public_message = "Avatar updates are temporarily limited; please try again later"
