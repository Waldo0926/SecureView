from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
ENV_FILE = REPO_ROOT / ".env"

_DEVELOPMENT_SECRET_KEY = "change-this-secret-key"
_DEVELOPMENT_DB_PASSWORD = "fyp_password"
_LOCAL_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


class Settings(BaseSettings):
    APP_NAME: str = "Secure File Encryption Platform"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    # Serve /docs, /redoc and /openapi.json.
    #
    # True by default because it costs the team nothing locally and is genuinely useful
    # while building. It is turned off on the public staging host: the schema is a complete,
    # machine-readable list of every route, its parameters, and the exact shape each one
    # accepts -- which is a considerable head start to hand an anonymous visitor, and worth
    # nothing to a user of the site.
    APP_DOCS_ENABLED: bool = True
    API_PREFIX: str = "/api/v1"
    SECRET_KEY: str = Field(default=_DEVELOPMENT_SECRET_KEY, repr=False)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, gt=0)
    AUTH_REFRESH_MIN_INTERVAL_SECONDS: int = Field(default=10, ge=1, le=3600)
    SESSION_ABSOLUTE_EXPIRE_HOURS: int = Field(default=7 * 24, gt=0)
    AUTH_MAX_ACTIVE_SESSIONS: int = Field(default=10, ge=1, le=100)
    AUTH_PASSWORD_HASH_CONCURRENCY: int = Field(default=2, ge=1, le=16)
    AUTH_LOGIN_ACCOUNT_MAX_FAILURES: int = Field(default=10, ge=2, le=100)
    AUTH_LOGIN_IP_MAX_FAILURES: int = Field(default=500, ge=5, le=5000)
    AUTH_LOGIN_WINDOW_SECONDS: int = Field(default=15 * 60, ge=60)
    AUTH_LOGIN_ACCOUNT_BLOCK_SECONDS: int = Field(default=5 * 60, ge=60)
    AUTH_LOGIN_IP_BLOCK_SECONDS: int = Field(default=15 * 60, ge=60)
    AUTH_REAUTH_ACCOUNT_MAX_FAILURES: int = Field(default=5, ge=2, le=100)
    AUTH_REAUTH_IP_MAX_FAILURES: int = Field(default=200, ge=5, le=5000)
    AUTH_REAUTH_BLOCK_SECONDS: int = Field(default=5 * 60, ge=60)
    AUTH_REGISTRATION_MAX_ATTEMPTS: int = Field(default=200, ge=1, le=5000)
    AUTH_REGISTRATION_WINDOW_SECONDS: int = Field(default=60 * 60, ge=60)
    AUTH_REGISTRATION_BLOCK_SECONDS: int = Field(default=60 * 60, ge=60)
    USER_RSA_KEY_SIZE: int = Field(default=3072, ge=2048, le=4096)
    EXPECTED_SCHEMA_REVISION: str = "0011_must_change_password"

    # Emailed verification challenges for registration and password reset.
    VERIFICATION_CODE_LENGTH: int = Field(default=6, ge=6, le=10)
    VERIFICATION_CODE_TTL_SECONDS: int = Field(default=10 * 60, ge=60, le=3600)
    VERIFICATION_CODE_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=20)
    VERIFICATION_RESEND_INTERVAL_SECONDS: int = Field(default=60, ge=15, le=600)
    VERIFICATION_SEND_EMAIL_MAX_PER_WINDOW: int = Field(default=5, ge=1, le=50)
    VERIFICATION_SEND_IP_MAX_PER_WINDOW: int = Field(default=300, ge=1, le=5000)
    VERIFICATION_CHECK_EMAIL_MAX_FAILURES: int = Field(default=10, ge=1, le=100)
    VERIFICATION_CHECK_IP_MAX_FAILURES: int = Field(default=500, ge=1, le=5000)
    VERIFICATION_THROTTLE_WINDOW_SECONDS: int = Field(default=60 * 60, ge=60)
    VERIFICATION_THROTTLE_BLOCK_SECONDS: int = Field(default=15 * 60, ge=60)

    # Outbound email. "console" logs the message instead of delivering it and is
    # the only provider that may run without credentials.
    EMAIL_PROVIDER: Literal["console", "resend", "smtp"] = "console"
    EMAIL_FROM_ADDRESS: str = "no-reply@localhost"
    EMAIL_FROM_NAME: str = "SecureView"
    EMAIL_REPLY_TO: str | None = None
    EMAIL_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=60)
    # Where a notification email should send the reader. Empty means the mail simply says
    # to sign in, which is better than linking somewhere wrong.
    APP_PUBLIC_URL: str = ""
    # Tell a recipient by email that a file has been shared with them. Off by default so a
    # deployment without working mail does not queue messages nobody receives.
    SHARE_NOTIFICATION_EMAIL: bool = False
    # Share notifications must never crowd out verification codes. A code that cannot be
    # delivered blocks registration and password reset; a share notification that is not
    # delivered is an inconvenience, and the recipient still finds the file in their list.
    # This caps the nice-to-have so it can only ever consume a fraction of the day's quota.
    SHARE_NOTIFICATION_DAILY_CAP: int = Field(default=40, ge=0, le=1000)
    RESEND_API_KEY: str = Field(default="", repr=False)
    RESEND_API_URL: str = "https://api.resend.com/emails"
    SMTP_HOST: str = ""
    SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = Field(default="", repr=False)
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False

    CORS_ORIGINS: list[str] = Field(default_factory=lambda: _LOCAL_CORS_ORIGINS.copy())
    CORS_ALLOW_CREDENTIALS: bool = True
    MAX_REQUEST_BODY_BYTES: int = Field(default=1024 * 1024, gt=0, le=8 * 1024 * 1024)
    MAX_UPLOAD_SIZE_BYTES: int = Field(default=500 * 1024 * 1024, gt=0)
    MAX_UPLOAD_REQUEST_OVERHEAD_BYTES: int = Field(default=256 * 1024, ge=128 * 1024)
    # Abuse limits on uploads (threat model T-D2). 0 turns a limit off, e.g. for a capacity run.
    # Storage counts the ciphertext of files not deleted; the daily figure counts every upload in
    # the last 24 hours, deleted or not, so deleting and re-uploading does not reset it.
    USER_STORAGE_QUOTA_BYTES: int = Field(default=2 * 1024**3, ge=0)
    USER_DAILY_UPLOAD_BYTES: int = Field(default=5 * 1024**3, ge=0)
    # Refuse every upload while the storage filesystem has less than this free after the file.
    # The server is shared with other services, so a full disk must not be reachable by uploads.
    UPLOAD_MIN_FREE_DISK_BYTES: int = Field(default=2 * 1024**3, ge=0)
    LOG_LEVEL: str = "INFO"

    DB_HOST: str = "localhost"
    DB_PORT: int = Field(default=3306, ge=1, le=65535)
    DB_USER: str = "fyp_user"
    DB_PASSWORD: str = Field(default=_DEVELOPMENT_DB_PASSWORD, min_length=1, repr=False)
    DB_NAME: str = "fyp_secure_file_platform"
    DB_SSL_CA: Path | None = None
    DB_SSL_CERT: Path | None = None
    DB_SSL_KEY: Path | None = None

    ENCRYPTED_FILE_DIR: Path = Path("backend/encrypted_files")
    TEMP_FILE_DIR: Path = Path("backend/temp_files")
    # Plaintext profile pictures only. Must not share a root with ciphertext objects.
    AVATAR_DIR: Path = Path("backend/avatars")
    AVATAR_MAX_BYTES: int = Field(default=512 * 1024, gt=0, le=2 * 1024 * 1024)
    AVATAR_MIN_INTERVAL_SECONDS: int = Field(default=30, ge=0, le=3600)

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        validate_default=True,
    )

    @field_validator("APP_ENV")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("APP_ENV must not be empty")
        return normalized

    @field_validator("API_PREFIX")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("API_PREFIX must start with '/'")
        return normalized.rstrip("/") or "/"

    @field_validator("CORS_ORIGINS")
    @classmethod
    def normalize_cors_origins(cls, values: list[str]) -> list[str]:
        origins = [origin.strip().rstrip("/") for origin in values if origin.strip()]
        if len(origins) != len(set(origins)):
            raise ValueError("CORS_ORIGINS must not contain duplicates")
        return origins

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed_levels:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed_levels)}")
        return normalized

    @field_validator("DB_HOST", "DB_USER", "DB_NAME")
    @classmethod
    def validate_database_connection_name(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError(
                "database host, user, and name must be non-empty without whitespace padding"
            )
        return value

    @field_validator("USER_RSA_KEY_SIZE")
    @classmethod
    def validate_user_rsa_key_size(cls, value: int) -> int:
        if value not in {2048, 3072, 4096}:
            raise ValueError("USER_RSA_KEY_SIZE must be 2048, 3072, or 4096")
        return value

    @field_validator(
        "ENCRYPTED_FILE_DIR",
        "TEMP_FILE_DIR",
        "AVATAR_DIR",
        "DB_SSL_CA",
        "DB_SSL_CERT",
        "DB_SSL_KEY",
        mode="before",
    )
    @classmethod
    def resolve_repository_path(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path.resolve(strict=False)

    @model_validator(mode="after")
    def validate_environment_security(self) -> Settings:
        if self.CORS_ALLOW_CREDENTIALS and "*" in self.CORS_ORIGINS:
            raise ValueError("Credentialed CORS must use explicit origins")

        if self.AUTH_LOGIN_ACCOUNT_MAX_FAILURES >= self.AUTH_LOGIN_IP_MAX_FAILURES:
            raise ValueError("AUTH_LOGIN_IP_MAX_FAILURES must be greater than the account limit")

        absolute_session_minutes = self.SESSION_ABSOLUTE_EXPIRE_HOURS * 60
        if absolute_session_minutes <= self.ACCESS_TOKEN_EXPIRE_MINUTES:
            raise ValueError(
                "ACCESS_TOKEN_EXPIRE_MINUTES must be shorter than the absolute session lifetime"
            )
        if self.AUTH_REAUTH_ACCOUNT_MAX_FAILURES >= self.AUTH_REAUTH_IP_MAX_FAILURES:
            raise ValueError(
                "AUTH_REAUTH_IP_MAX_FAILURES must be greater than the reauthentication "
                "account limit"
            )
        if self.REFRESH_TOKEN_EXPIRE_DAYS * 24 > self.SESSION_ABSOLUTE_EXPIRE_HOURS:
            raise ValueError(
                "REFRESH_TOKEN_EXPIRE_DAYS must not exceed the absolute session lifetime"
            )

        if self.APP_ENV not in {"development", "test"}:
            errors: list[str] = []
            if self.APP_DEBUG:
                errors.append("APP_DEBUG must be false")
            if self.SECRET_KEY == _DEVELOPMENT_SECRET_KEY or len(self.SECRET_KEY) < 32:
                errors.append("SECRET_KEY must be a non-default value of at least 32 characters")
            if self.DB_PASSWORD == _DEVELOPMENT_DB_PASSWORD:
                errors.append("DB_PASSWORD must not use the development default")
            if self.DB_SSL_CA is None:
                errors.append("DB_SSL_CA is required for verified database TLS")
            if errors:
                raise ValueError(
                    f"Unsafe settings for APP_ENV={self.APP_ENV!r}: " + "; ".join(errors)
                )

        if self.VERIFICATION_CHECK_EMAIL_MAX_FAILURES >= self.VERIFICATION_CHECK_IP_MAX_FAILURES:
            raise ValueError(
                "VERIFICATION_CHECK_IP_MAX_FAILURES must be greater than the per-email limit"
            )
        if self.VERIFICATION_SEND_EMAIL_MAX_PER_WINDOW >= self.VERIFICATION_SEND_IP_MAX_PER_WINDOW:
            raise ValueError(
                "VERIFICATION_SEND_IP_MAX_PER_WINDOW must be greater than the per-email limit"
            )
        if self.VERIFICATION_RESEND_INTERVAL_SECONDS >= self.VERIFICATION_CODE_TTL_SECONDS:
            raise ValueError(
                "VERIFICATION_RESEND_INTERVAL_SECONDS must be shorter than the code lifetime"
            )

        email_provider_errors: list[str] = []
        if self.EMAIL_PROVIDER == "resend" and not self.RESEND_API_KEY:
            email_provider_errors.append("RESEND_API_KEY is required for EMAIL_PROVIDER=resend")
        if self.EMAIL_PROVIDER == "smtp" and not self.SMTP_HOST:
            email_provider_errors.append("SMTP_HOST is required for EMAIL_PROVIDER=smtp")
        if self.EMAIL_PROVIDER == "smtp" and self.SMTP_USE_TLS and self.SMTP_USE_SSL:
            email_provider_errors.append("SMTP_USE_TLS and SMTP_USE_SSL are mutually exclusive")
        if self.APP_ENV not in {"development", "test"} and self.EMAIL_PROVIDER == "console":
            email_provider_errors.append(
                "EMAIL_PROVIDER=console never delivers mail and is development-only"
            )
        if email_provider_errors:
            raise ValueError("Invalid email settings: " + "; ".join(email_provider_errors))

        if bool(self.DB_SSL_CERT) != bool(self.DB_SSL_KEY):
            raise ValueError("DB_SSL_CERT and DB_SSL_KEY must either both be set or both be absent")

        tls_paths = {
            "DB_SSL_CA": self.DB_SSL_CA,
            "DB_SSL_CERT": self.DB_SSL_CERT,
            "DB_SSL_KEY": self.DB_SSL_KEY,
        }
        missing_tls_files = [
            name for name, path in tls_paths.items() if path and not path.is_file()
        ]
        if missing_tls_files:
            raise ValueError(f"Database TLS files do not exist: {', '.join(missing_tls_files)}")

        return self

    @property
    def DATABASE_URL(self) -> URL:
        return URL.create(
            drivername="mysql+pymysql",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
            query={"charset": "utf8mb4"},
        )

    @property
    def DATABASE_CONNECT_ARGS(self) -> dict[str, object]:
        connect_args: dict[str, object] = {"init_command": "SET time_zone = '+00:00'"}
        if self.DB_SSL_CA is None:
            return connect_args

        connect_args.update(
            {
                "ssl_ca": str(self.DB_SSL_CA),
                "ssl_verify_cert": True,
                "ssl_verify_identity": True,
            }
        )
        if self.DB_SSL_CERT is not None and self.DB_SSL_KEY is not None:
            connect_args["ssl_cert"] = str(self.DB_SSL_CERT)
            connect_args["ssl_key"] = str(self.DB_SSL_KEY)
        return connect_args


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
