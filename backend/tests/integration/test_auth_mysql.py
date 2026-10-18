import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import Connection, Engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.auth import RequestContext
from app.domain.enums import (
    SystemRole,
    UserStatus,
    VerificationCodeStatus,
    VerificationPurpose,
)
from app.domain.errors import AuthenticationError
from app.domain.keys import (
    ClientKeyRegistration,
    EncryptedPrivateKeyBundleInput,
    KeyProtectionProfileInput,
)
from app.models.audit_chain_head import AuditChainHead
from app.models.audit_log import AuditLog
from app.models.email_verification_code import EmailVerificationCode
from app.models.encrypted_private_key_bundle import EncryptedPrivateKeyBundle
from app.models.user import User
from app.models.user_key import UserKey
from app.models.user_key_protection_profile import UserKeyProtectionProfile
from app.models.user_session import UserSession
from app.services.audit_log_service import AuditLogService
from app.services.auth_service import AuthService
from app.services.email_service import OutboundEmail

pytestmark = pytest.mark.integration

TEMPORARY_AUTH_DDL = (
    """
    CREATE TEMPORARY TABLE users (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        user_uuid CHAR(36) NOT NULL UNIQUE,
        username VARCHAR(100) COLLATE utf8mb4_unicode_ci NOT NULL UNIQUE,
        email VARCHAR(255) COLLATE utf8mb4_unicode_ci NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role ENUM('USER', 'ADMIN', 'RECOVERY_OFFICER') NOT NULL DEFAULT 'USER',
        status ENUM('ACTIVE', 'DISABLED', 'DELETED') NOT NULL DEFAULT 'ACTIVE',
        email_verified BOOLEAN NOT NULL DEFAULT FALSE,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        password_changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_login_at DATETIME NULL,
        avatar_object_key VARCHAR(500) NULL,
        avatar_content_type VARCHAR(64) NULL,
        avatar_sha256 CHAR(64) NULL,
        avatar_bytes INTEGER UNSIGNED NULL,
        avatar_updated_at DATETIME NULL,
        must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
        CONSTRAINT ck_users_avatar_shape CHECK (
            (avatar_object_key IS NULL AND avatar_content_type IS NULL
                AND avatar_sha256 IS NULL AND avatar_bytes IS NULL
                AND avatar_updated_at IS NULL)
            OR (avatar_object_key IS NOT NULL
                AND avatar_content_type IN ('image/png', 'image/jpeg')
                AND avatar_sha256 REGEXP '^[0-9a-f]{64}$'
                AND avatar_bytes BETWEEN 1 AND 524288
                AND avatar_updated_at IS NOT NULL)
        )
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TEMPORARY TABLE user_keys (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        key_uuid CHAR(36) NOT NULL UNIQUE,
        user_id BIGINT UNSIGNED NOT NULL,
        public_key_pem TEXT NOT NULL,
        algorithm VARCHAR(50) NOT NULL,
        key_size_bits SMALLINT UNSIGNED NOT NULL,
        custody_mode ENUM('LEGACY_EXTERNAL', 'CLIENT_WRAPPED') NOT NULL,
        fingerprint CHAR(64) NOT NULL UNIQUE,
        status ENUM('ACTIVE', 'REVOKED') NOT NULL DEFAULT 'ACTIVE',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        revoked_at DATETIME NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TEMPORARY TABLE user_key_protection_profiles (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL UNIQUE,
        profile_uuid CHAR(36) NOT NULL UNIQUE,
        format_version SMALLINT UNSIGNED NOT NULL,
        kdf_algorithm VARCHAR(32) NOT NULL,
        kdf_version SMALLINT UNSIGNED NOT NULL,
        kdf_salt VARBINARY(64) NOT NULL,
        kdf_memory_kib INTEGER UNSIGNED NOT NULL,
        kdf_iterations INTEGER UNSIGNED NOT NULL,
        kdf_parallelism INTEGER UNSIGNED NOT NULL,
        derived_key_length SMALLINT UNSIGNED NOT NULL,
        amk_wrapping_algorithm VARCHAR(50) NOT NULL,
        wrapped_amk VARBINARY(128) NOT NULL,
        amk_nonce VARBINARY(32) NOT NULL,
        amk_auth_tag VARBINARY(32) NOT NULL,
        aad_version SMALLINT UNSIGNED NOT NULL,
        revision INTEGER UNSIGNED NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TEMPORARY TABLE encrypted_private_key_bundles (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        bundle_uuid CHAR(36) NOT NULL UNIQUE,
        user_id BIGINT UNSIGNED NOT NULL,
        user_key_id BIGINT UNSIGNED NOT NULL UNIQUE,
        format_version SMALLINT UNSIGNED NOT NULL,
        private_key_format VARCHAR(32) NOT NULL,
        derivation_algorithm VARCHAR(32) NOT NULL,
        derivation_salt VARBINARY(64) NOT NULL,
        encryption_algorithm VARCHAR(50) NOT NULL,
        encrypted_private_key BLOB NOT NULL,
        nonce VARBINARY(32) NOT NULL,
        auth_tag VARBINARY(32) NOT NULL,
        aad_version SMALLINT UNSIGNED NOT NULL,
        ciphertext_sha256 CHAR(64) NOT NULL,
        revision INTEGER UNSIGNED NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TEMPORARY TABLE user_sessions (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        session_uuid CHAR(36) NOT NULL UNIQUE,
        user_id BIGINT UNSIGNED NOT NULL,
        access_token_hash CHAR(64) NOT NULL UNIQUE,
        status ENUM('ACTIVE', 'EXPIRED', 'REVOKED') NOT NULL DEFAULT 'ACTIVE',
        ip_address VARCHAR(45) NULL,
        user_agent TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        access_expires_at DATETIME NOT NULL,
        absolute_expires_at DATETIME NOT NULL,
        revoked_at DATETIME NULL,
        revoked_reason VARCHAR(100) NULL,
        INDEX idx_test_sessions_user_status (user_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TEMPORARY TABLE session_refresh_tokens (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        session_id BIGINT UNSIGNED NOT NULL,
        token_hash CHAR(64) NOT NULL UNIQUE,
        generation INT UNSIGNED NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME NOT NULL,
        consumed_at DATETIME NULL,
        revoked_at DATETIME NULL,
        UNIQUE KEY uq_test_refresh_generation (session_id, generation)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TEMPORARY TABLE auth_login_throttles (
        scope ENUM(
            'ACCOUNT', 'IP', 'REAUTH_ACCOUNT', 'REAUTH_IP', 'REGISTRATION_IP',
            'VERIFICATION_SEND_EMAIL', 'VERIFICATION_SEND_IP',
            'VERIFICATION_CHECK_EMAIL', 'VERIFICATION_CHECK_IP'
        ) NOT NULL,
        key_hash CHAR(64) NOT NULL,
        failed_count INT UNSIGNED NOT NULL DEFAULT 0,
        window_started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        blocked_until DATETIME NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (scope, key_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TEMPORARY TABLE email_verification_codes (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        code_uuid CHAR(36) NOT NULL UNIQUE,
        purpose ENUM('REGISTRATION', 'PASSWORD_RESET') NOT NULL,
        email VARCHAR(255) COLLATE utf8mb4_unicode_ci NOT NULL,
        user_id BIGINT UNSIGNED NULL,
        code_hash CHAR(64) NOT NULL,
        status ENUM('PENDING', 'CONSUMED', 'INVALIDATED') NOT NULL DEFAULT 'PENDING',
        attempt_count INT UNSIGNED NOT NULL DEFAULT 0,
        max_attempts INT UNSIGNED NOT NULL DEFAULT 5,
        ip_address VARCHAR(45) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME NOT NULL,
        consumed_at DATETIME NULL,
        INDEX idx_test_verification_lookup (email, purpose, status, expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TEMPORARY TABLE audit_logs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        actor_user_id BIGINT UNSIGNED NULL,
        action VARCHAR(100) NOT NULL,
        resource_type ENUM(
            'AUTH', 'USER', 'FILE', 'SHARE', 'RECOVERY', 'INTEGRITY', 'SYSTEM'
        ) NOT NULL,
        resource_id VARCHAR(100) NULL,
        target_user_id BIGINT UNSIGNED NULL,
        result ENUM('SUCCESS', 'FAIL') NOT NULL,
        ip_address VARCHAR(45) NULL,
        user_agent TEXT NULL,
        description TEXT NULL,
        metadata_json JSON NOT NULL,
        previous_hash CHAR(64) NULL,
        current_hash CHAR(64) NOT NULL,
        created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TEMPORARY TABLE audit_chain_heads (
        id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
        last_log_id BIGINT UNSIGNED NULL,
        current_hash CHAR(64) NOT NULL,
        schema_revision VARCHAR(64) NOT NULL DEFAULT '0011_must_change_password',
        updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def _create_temporary_auth_schema(connection: Connection) -> None:
    for statement in TEMPORARY_AUTH_DDL:
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql(
        "INSERT INTO audit_chain_heads "
        "(id, last_log_id, current_hash, schema_revision) "
        "VALUES (1, NULL, %s, '0011_must_change_password')",
        ("0" * 64,),
    )
    connection.commit()


def _permanent_auth_row_counts(connection: Connection) -> dict[str, int] | None:
    """Inspect through another physical connection where temporary tables are invisible."""
    table_names = ("users", "user_keys", "user_sessions", "audit_logs")
    with connection.engine.connect() as verifier:
        verifier_inspector = inspect(verifier)
        if not all(verifier_inspector.has_table(table_name) for table_name in table_names):
            return None
        return {
            table_name: int(verifier.scalar(text(f"SELECT COUNT(*) FROM `{table_name}`")) or 0)
            for table_name in table_names
        }


class _CollectingEmailService:
    """Captures outbound mail so the integration run never touches the network."""

    def __init__(self) -> None:
        self.sent: list[OutboundEmail] = []

    def send(self, message: OutboundEmail) -> None:
        self.sent.append(message)


def _client_key_material(public_key_pem: str) -> ClientKeyRegistration:
    encrypted_private_key = b"integration-client-encrypted-pkcs8" * 20
    return ClientKeyRegistration(
        key_id=UUID("11111111-1111-4111-8111-111111111111"),
        public_key_pem=public_key_pem,
        algorithm="RSA-OAEP-SHA256",
        key_size_bits=2048,
        protection=KeyProtectionProfileInput(
            profile_id=UUID("22222222-2222-4222-8222-222222222222"),
            format_version=1,
            kdf_algorithm="ARGON2ID",
            kdf_version=19,
            kdf_salt=b"s" * 16,
            kdf_memory_kib=65_536,
            kdf_iterations=3,
            kdf_parallelism=4,
            derived_key_length=32,
            amk_wrapping_algorithm="AES-256-GCM",
            wrapped_amk=b"w" * 32,
            amk_nonce=b"n" * 12,
            amk_auth_tag=b"t" * 16,
            aad_version=1,
        ),
        private_key_bundle=EncryptedPrivateKeyBundleInput(
            bundle_id=UUID("33333333-3333-4333-8333-333333333333"),
            format_version=1,
            private_key_format="PKCS8-DER",
            derivation_algorithm="HKDF-SHA256",
            derivation_salt=b"d" * 16,
            encryption_algorithm="AES-256-GCM",
            encrypted_private_key=encrypted_private_key,
            nonce=b"i" * 12,
            auth_tag=b"a" * 16,
            aad_version=1,
            ciphertext_sha256=hashlib.sha256(encrypted_private_key).hexdigest(),
        ),
    )


def test_auth_database_is_migrated_to_expected_schema(auth_mysql_engine: Engine) -> None:
    inspector = inspect(auth_mysql_engine)
    table_names = set(inspector.get_table_names())

    assert {
        "alembic_version",
        "users",
        "user_keys",
        "user_sessions",
        "session_refresh_tokens",
        "auth_login_throttles",
        "audit_chain_heads",
        "audit_logs",
        "user_key_protection_profiles",
        "encrypted_private_key_bundles",
        "files",
        "file_key_wrappings",
        "recovery_keys",
        "recovery_requests",
    } <= table_names

    with auth_mysql_engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        readiness_revision = connection.scalar(
            text("SELECT schema_revision FROM audit_chain_heads WHERE id = 1")
        )

    assert revision == "0011_must_change_password"
    assert readiness_revision == "0011_must_change_password"
    assert {
        "session_uuid",
        "access_token_hash",
        "access_expires_at",
        "absolute_expires_at",
        "revoked_reason",
    } <= {column["name"] for column in inspector.get_columns("user_sessions")}
    assert {"key_uuid", "key_size_bits", "custody_mode"} <= {
        column["name"] for column in inspector.get_columns("user_keys")
    }
    assert {"envelope_version", "aad_version", "encrypted_manifest", "revision"} <= {
        column["name"] for column in inspector.get_columns("files")
    }
    assert {"updated_at", "revision"} <= {
        column["name"] for column in inspector.get_columns("file_key_wrappings")
    }
    assert {"key_uuid", "key_size_bits"} <= {
        column["name"] for column in inspector.get_columns("recovery_keys")
    }
    assert {
        "executed_by",
        "target_user_key_id",
        "result_wrapping_id",
        "expires_at",
        "revision",
    } <= {column["name"] for column in inspector.get_columns("recovery_requests")}


def test_mysql_collation_prevents_case_variant_duplicate_email(
    auth_mysql_session: Session,
) -> None:
    first = User(
        user_uuid=str(uuid4()),
        username=f"first-{uuid4().hex}",
        email="CaseSensitiveProbe@Example.com",
        password_hash="not-a-real-password-hash",
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        email_verified=False,
    )
    second = User(
        user_uuid=str(uuid4()),
        username=f"second-{uuid4().hex}",
        email="casesensitiveprobe@example.COM",
        password_hash="not-a-real-password-hash",
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        email_verified=False,
    )
    auth_mysql_session.add(first)
    auth_mysql_session.flush()
    auth_mysql_session.add(second)

    with pytest.raises(IntegrityError):
        auth_mysql_session.flush()

    auth_mysql_session.rollback()


def test_mysql_collation_prevents_case_variant_duplicate_username(
    auth_mysql_session: Session,
) -> None:
    username = f"CaseSensitiveProbe-{uuid4().hex}"
    first_user_id = uuid4()
    second_user_id = uuid4()
    first = User(
        user_uuid=str(first_user_id),
        username=username,
        email=f"{first_user_id}@demo.invalid",
        password_hash="not-a-real-password-hash",
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        email_verified=False,
    )
    second = User(
        user_uuid=str(second_user_id),
        username=username.swapcase(),
        email=f"{second_user_id}@demo.invalid",
        password_hash="not-a-real-password-hash",
        role=SystemRole.USER,
        status=UserStatus.ACTIVE,
        email_verified=False,
    )
    auth_mysql_session.add(first)
    auth_mysql_session.flush()
    auth_mysql_session.add(second)

    with pytest.raises(IntegrityError):
        auth_mysql_session.flush()

    auth_mysql_session.rollback()


def test_real_auth_flow_uses_only_connection_local_temporary_tables(
    temporary_auth_mysql_connection: Connection,
) -> None:
    permanent_counts_before = _permanent_auth_row_counts(temporary_auth_mysql_connection)
    _create_temporary_auth_schema(temporary_auth_mysql_connection)
    session = Session(bind=temporary_auth_mysql_connection, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        APP_DEBUG=False,
        SECRET_KEY="integration-test-secret-key-that-is-long-enough",
        USER_RSA_KEY_SIZE=2048,
    )
    fixed_now = datetime(2026, 8, 4, 4, 0, 0, 654321, tzinfo=UTC)
    current_time = [fixed_now]
    service = AuthService(db=session, settings=settings, clock=lambda: current_time[0])
    context = RequestContext(
        ip_address="203.0.113.20",
        user_agent="mysql-auth-integration-test",
    )
    original_password = "An original high entropy passphrase!"
    replacement_password = "A replacement high entropy passphrase!"
    public_key_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )

    try:
        # Registration now requires a code that was really issued and stored,
        # so exercise the emailed-challenge round trip against MySQL too.
        service.verification.email = _CollectingEmailService()
        service.verification.code_factory = lambda _length: "246810"
        service.send_verification_code(
            purpose=VerificationPurpose.REGISTRATION,
            email="integration-user@example.com",
            context=context,
        )
        issued = session.scalars(select(EmailVerificationCode)).all()
        assert len(issued) == 1
        assert issued[0].status == VerificationCodeStatus.PENDING
        assert "246810" not in issued[0].code_hash

        registered = service.register(
            username="integration-user",
            email="integration-user@example.com",
            password=original_password,
            verification_code="246810",
            key_material=_client_key_material(public_key_pem),
            context=context,
        )
        session.expire_all()
        consumed = session.scalars(select(EmailVerificationCode)).all()
        assert consumed[0].status == VerificationCodeStatus.CONSUMED
        assert consumed[0].consumed_at is not None
        assert registered.public_key_fingerprint == service.crypto.public_key_fingerprint(
            public_key_pem
        )
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(UserKey)) == 1
        assert session.scalar(select(func.count()).select_from(UserKeyProtectionProfile)) == 1
        assert session.scalar(select(func.count()).select_from(EncryptedPrivateKeyBundle)) == 1

        logged_in = service.login(
            username="integration-user",
            password=original_password,
            context=context,
        )
        original_actor = service.authenticate_access_token(logged_in.tokens.access_token)
        assert original_actor.user_public_id == registered.user.id

        # The baseline session-token timestamps use MySQL DATETIME(0), which may
        # round the inserted fractional second; one extra second crosses the bound.
        current_time[0] += timedelta(seconds=settings.AUTH_REFRESH_MIN_INTERVAL_SECONDS + 1)
        refreshed = service.refresh(
            refresh_token=logged_in.tokens.refresh_token,
            context=context,
        )
        with pytest.raises(AuthenticationError):
            service.authenticate_access_token(logged_in.tokens.access_token)
        refreshed_actor = service.authenticate_access_token(refreshed.tokens.access_token)
        assert refreshed_actor.session_public_id == original_actor.session_public_id

        revoked = service.change_password(
            actor=refreshed_actor,
            current_password=original_password,
            new_password=replacement_password,
            context=context,
        )
        assert revoked == 1
        with pytest.raises(AuthenticationError):
            service.authenticate_access_token(refreshed.tokens.access_token)

        stored_session = session.scalar(select(UserSession))
        assert stored_session is not None
        assert stored_session.status.value == "REVOKED"
        assert stored_session.revoked_reason == "password_changed"
        # Verification send, registration, login, refresh, password change.
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 5

        # Force a database round trip: DATETIME without fsp=6 used to truncate
        # the hashed timestamp and made an otherwise intact chain unverifiable.
        session.expire_all()
        audit_logs = list(session.scalars(select(AuditLog).order_by(AuditLog.id)))
        expected_previous_hash = AuditLogService.GENESIS_HASH
        for audit_log in audit_logs:
            assert audit_log.created_at.microsecond == 654321
            assert audit_log.previous_hash == expected_previous_hash
            stored_content = service.audit.make_log_content(
                action=audit_log.action,
                actor_user_id=audit_log.actor_user_id,
                created_at=audit_log.created_at,
                description=audit_log.description,
                ip_address=audit_log.ip_address,
                metadata=audit_log.metadata_json,
                resource_id=audit_log.resource_id,
                resource_type=audit_log.resource_type,
                result=audit_log.result,
                target_user_id=audit_log.target_user_id,
                user_agent=audit_log.user_agent,
            )
            assert (
                service.audit.build_log_hash(expected_previous_hash, stored_content)
                == audit_log.current_hash
            )
            expected_previous_hash = audit_log.current_hash

        assert [audit_log.action for audit_log in audit_logs] == [
            "AUTH_VERIFICATION_CODE_SENT",
            "AUTH_REGISTERED",
            "AUTH_LOGIN_SUCCEEDED",
            "AUTH_SESSION_REFRESHED",
            "AUTH_PASSWORD_CHANGED",
        ]
        # An event without metadata must round trip as an empty object, not SQL NULL.
        registered_event = next(
            audit_log for audit_log in audit_logs if audit_log.action == "AUTH_REGISTERED"
        )
        assert registered_event.metadata_json == {}
        chain_head = session.get(AuditChainHead, 1)
        assert chain_head is not None
        assert chain_head.last_log_id == audit_logs[-1].id
        assert chain_head.current_hash == expected_previous_hash
    finally:
        session.close()

    permanent_counts_after = _permanent_auth_row_counts(temporary_auth_mysql_connection)
    assert permanent_counts_after == permanent_counts_before


def test_auth_migration_guards_fail_closed_without_permanent_writes(
    temporary_auth_mysql_connection: Connection,
) -> None:
    permanent_counts_before = _permanent_auth_row_counts(temporary_auth_mysql_connection)
    temporary_auth_mysql_connection.exec_driver_sql(
        "CREATE TEMPORARY TABLE audit_logs (id BIGINT PRIMARY KEY)"
    )
    temporary_auth_mysql_connection.exec_driver_sql("INSERT INTO audit_logs (id) VALUES (1)")
    temporary_auth_mysql_connection.exec_driver_sql(
        "CREATE TEMPORARY TABLE auth_0002_audit_upgrade_guard ("
        "empty_legacy_chain TINYINT NOT NULL, "
        "CONSTRAINT ck_auth_0002_requires_empty_audit_log "
        "CHECK (empty_legacy_chain = 1)"
        ") ENGINE=InnoDB"
    )

    with pytest.raises(DBAPIError) as upgrade_guard_error:
        temporary_auth_mysql_connection.exec_driver_sql(
            "INSERT INTO auth_0002_audit_upgrade_guard (empty_legacy_chain) "
            "SELECT 0 FROM audit_logs LIMIT 1"
        )
    assert upgrade_guard_error.value.orig.args[0] == 3819
    temporary_auth_mysql_connection.rollback()

    with pytest.raises(DBAPIError) as downgrade_guard_error:
        temporary_auth_mysql_connection.exec_driver_sql(
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
            "'0002_auth_identity_sessions is irreversible; restore a backup or rebuild'"
        )
    assert downgrade_guard_error.value.orig.args[0] == 1644
    temporary_auth_mysql_connection.rollback()

    permanent_counts_after = _permanent_auth_row_counts(temporary_auth_mysql_connection)
    assert permanent_counts_after == permanent_counts_before
