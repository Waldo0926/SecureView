from __future__ import annotations

import math
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db_retry import run_with_deadlock_retry
from app.core.security import (
    PasswordManager,
    PasswordOperationCapacityError,
    generate_session_token,
    hash_auth_throttle_key,
    hash_session_token,
    normalize_password,
    password_manager,
    password_policy_error,
)
from app.core.time import to_api_utc, to_database_utc, to_second_resolution_utc, utc_now
from app.domain.auth import (
    AccountSnapshot,
    ActorContext,
    LoginResult,
    RefreshResult,
    RegistrationResult,
    RequestContext,
    SessionSnapshot,
    TokenPair,
)
from app.domain.enums import (
    LoginThrottleScope,
    SessionStatus,
    SystemRole,
    UserStatus,
    VerificationPurpose,
)
from app.domain.errors import (
    AccountIdentifierUnavailableError,
    AuthenticationError,
    AuthenticationRateLimitedError,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    InvalidRefreshTokenError,
    KeyBundleInvalidError,
    PasswordUnchangedError,
    SessionNotFoundError,
    VerificationCodeInvalidError,
    WeakPasswordError,
)
from app.domain.keys import ClientKeyRegistration
from app.models.auth_login_throttle import AuthLoginThrottle
from app.models.encrypted_private_key_bundle import EncryptedPrivateKeyBundle
from app.models.session_refresh_token import SessionRefreshToken
from app.models.user import User
from app.models.user_key import UserKey
from app.models.user_key_protection_profile import UserKeyProtectionProfile
from app.models.user_session import UserSession
from app.repositories.auth_repository import AuthRepository
from app.services.audit_log_service import AuditLogService
from app.services.crypto_service import CryptoService
from app.services.verification_service import VerificationService


class AuthService:
    """Transaction owner for local account and server-side session use cases."""

    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        repository: AuthRepository | None = None,
        audit_service: AuditLogService | None = None,
        crypto_service: CryptoService | None = None,
        verification_service: VerificationService | None = None,
        passwords: PasswordManager | None = None,
        clock: Callable[[], datetime] = utc_now,
        token_factory: Callable[[], str] = generate_session_token,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.db = db
        self.settings = settings
        self.repository = repository or AuthRepository(db)
        self.clock = clock
        self.audit = audit_service or AuditLogService(db, clock=clock)
        self.crypto = crypto_service or CryptoService()
        self.passwords = passwords or password_manager
        self.token_factory = token_factory
        self.uuid_factory = uuid_factory
        self.verification = verification_service or VerificationService(
            db=db,
            settings=settings,
            repository=self.repository,
            audit_service=self.audit,
            clock=clock,
        )

    def send_verification_code(
        self,
        *,
        purpose: VerificationPurpose,
        email: str,
        context: RequestContext,
    ) -> None:
        try:
            self.verification.issue(purpose=purpose, email=email, context=context)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def register(
        self,
        *,
        username: str,
        email: str,
        password: str,
        verification_code: str,
        key_material: ClientKeyRegistration,
        context: RequestContext,
    ) -> RegistrationResult:
        normalized_username = username.strip()
        normalized_email = email.strip().lower()
        policy_error = password_policy_error(
            password,
            context_values=(normalized_username, normalized_email),
        )
        if policy_error:
            raise WeakPasswordError(policy_error)

        self._consume_registration_attempt(context)

        try:
            # Usernames are public (sharing resolves them), so a taken one may be reported
            # outright, and reporting it before the code is consumed means the caller does
            # not have to request a new code just to pick another name.
            if self.repository.username_exists(normalized_username):
                raise AccountIdentifierUnavailableError()

            self.verification.consume(
                purpose=VerificationPurpose.REGISTRATION,
                email=normalized_email,
                code=verification_code,
                context=context,
            )

            # Whether an email has an account is not public. The send endpoint already
            # answers the same way for a registered address (and sends nothing), so a
            # valid code for a registered email should not exist; if one arrives anyway,
            # answer exactly as for a bad code rather than confirm the account exists.
            if self.repository.email_exists(normalized_email):
                raise VerificationCodeInvalidError()

            now = self._now()
            # The two key-custody tables are DATETIME(6); everything else here is
            # second-resolution. Same instant, each column at the precision it declares.
            custody_now = self._now_exact()
            password_hash = self.passwords.hash(password)
            if key_material.key_size_bits != self.settings.USER_RSA_KEY_SIZE:
                raise KeyBundleInvalidError(
                    "The RSA key size does not match the configured account key size"
                )
            try:
                self.crypto.load_rsa_public_key(
                    key_material.public_key_pem,
                    expected_key_size=key_material.key_size_bits,
                )
                public_key_fingerprint = self.crypto.public_key_fingerprint(
                    key_material.public_key_pem
                )
            except (TypeError, ValueError) as exc:
                raise KeyBundleInvalidError() from exc
            user_public_id = self.uuid_factory()

            user = User(
                user_uuid=str(user_public_id),
                username=normalized_username,
                email=normalized_email,
                password_hash=password_hash,
                role=SystemRole.USER,
                status=UserStatus.ACTIVE,
                # The address was proven by the code consumed above.
                email_verified=True,
                created_at=now,
                updated_at=now,
                password_changed_at=now,
            )
            self.repository.add_user(user)
            self.repository.flush()

            user_key = UserKey(
                key_uuid=str(key_material.key_id),
                user_id=user.id,
                public_key_pem=key_material.public_key_pem,
                algorithm=key_material.algorithm,
                key_size_bits=key_material.key_size_bits,
                custody_mode="CLIENT_WRAPPED",
                fingerprint=public_key_fingerprint,
                status="ACTIVE",
                created_at=now,
            )
            self.repository.add_user_key(user_key)
            self.repository.flush()

            protection = key_material.protection
            self.repository.add_key_protection_profile(
                UserKeyProtectionProfile(
                    user_id=user.id,
                    profile_uuid=str(protection.profile_id),
                    format_version=protection.format_version,
                    kdf_algorithm=protection.kdf_algorithm,
                    kdf_version=protection.kdf_version,
                    kdf_salt=protection.kdf_salt,
                    kdf_memory_kib=protection.kdf_memory_kib,
                    kdf_iterations=protection.kdf_iterations,
                    kdf_parallelism=protection.kdf_parallelism,
                    derived_key_length=protection.derived_key_length,
                    amk_wrapping_algorithm=protection.amk_wrapping_algorithm,
                    wrapped_amk=protection.wrapped_amk,
                    amk_nonce=protection.amk_nonce,
                    amk_auth_tag=protection.amk_auth_tag,
                    aad_version=protection.aad_version,
                    revision=1,
                    created_at=custody_now,
                    updated_at=custody_now,
                )
            )

            private_bundle = key_material.private_key_bundle
            self.repository.add_private_key_bundle(
                EncryptedPrivateKeyBundle(
                    bundle_uuid=str(private_bundle.bundle_id),
                    user_id=user.id,
                    user_key_id=user_key.id,
                    format_version=private_bundle.format_version,
                    private_key_format=private_bundle.private_key_format,
                    derivation_algorithm=private_bundle.derivation_algorithm,
                    derivation_salt=private_bundle.derivation_salt,
                    encryption_algorithm=private_bundle.encryption_algorithm,
                    encrypted_private_key=private_bundle.encrypted_private_key,
                    nonce=private_bundle.nonce,
                    auth_tag=private_bundle.auth_tag,
                    aad_version=private_bundle.aad_version,
                    ciphertext_sha256=private_bundle.ciphertext_sha256,
                    revision=1,
                    created_at=custody_now,
                    updated_at=custody_now,
                )
            )
            self.audit.append(
                action="AUTH_REGISTERED",
                result="SUCCESS",
                actor_user_id=user.id,
                target_user_id=user.id,
                resource_id=str(user_public_id),
                context_ip_address=self._safe_ip(context),
                context_user_agent=self._safe_user_agent(context),
            )
            result = RegistrationResult(
                user=self._account_snapshot(user),
                key_id=key_material.key_id,
                public_key_fingerprint=public_key_fingerprint,
            )
            self.db.commit()
            return result
        except IntegrityError as exc:
            self.db.rollback()
            # A row inserted between the checks above and this insert. Same answers as the
            # checks give, so the race cannot be used to learn what the checks hide.
            conflict = self._account_identifier_conflict(exc)
            if conflict == "username":
                raise AccountIdentifierUnavailableError() from exc
            if conflict == "email":
                raise VerificationCodeInvalidError() from exc
            raise
        except PasswordOperationCapacityError as exc:
            self.db.rollback()
            raise AuthenticationRateLimitedError(retry_after_seconds=1) from exc
        except Exception:
            self.db.rollback()
            raise

    def reset_password(
        self,
        *,
        username: str,
        email: str,
        verification_code: str,
        new_password: str,
        context: RequestContext,
    ) -> int:
        """Set a new login password after an emailed challenge.

        This never touches the client-held encryption passphrase or the stored
        key envelopes, so the account keeps access to its encrypted files.
        """
        normalized_username = username.strip()
        normalized_email = email.strip().lower()
        policy_error = password_policy_error(
            new_password,
            context_values=(normalized_username, normalized_email),
        )
        if policy_error:
            raise WeakPasswordError(policy_error)

        try:
            now = self._now()
            user = self.repository.get_user_by_username(normalized_username)
            identity_matches = (
                user is not None
                and user.email == normalized_email
                and user.status == UserStatus.ACTIVE
            )

            # Consume the challenge before deciding, so a mismatched
            # username/email pair costs an attempt instead of leaking that the
            # code itself was valid.
            self.verification.consume(
                purpose=VerificationPurpose.PASSWORD_RESET,
                email=normalized_email,
                code=verification_code,
                context=context,
            )
            if not identity_matches:
                self.db.commit()
                raise VerificationCodeInvalidError()

            replacement_hash = self.passwords.hash(new_password)
            locked_user = self.repository.lock_user(user.id)
            if locked_user is None or locked_user.status != UserStatus.ACTIVE:
                raise VerificationCodeInvalidError()

            locked_user.password_hash = replacement_hash
            locked_user.password_changed_at = now
            locked_user.updated_at = now
            # Same as change-password: a password the holder set replaces the temporary one.
            locked_user.must_change_password = False
            revoked = self.repository.revoke_all_session_families(
                locked_user.id,
                now=now,
                reason="password_reset",
            )
            self.audit.append(
                action="AUTH_PASSWORD_RESET",
                result="SUCCESS",
                actor_user_id=locked_user.id,
                target_user_id=locked_user.id,
                resource_id=str(locked_user.user_uuid),
                context_ip_address=self._safe_ip(context),
                context_user_agent=self._safe_user_agent(context),
                metadata={"revoked_sessions": revoked},
            )
            self.db.commit()
            return revoked
        except (AuthenticationRateLimitedError, VerificationCodeInvalidError):
            # A consumed-code or throttle transaction may already be committed.
            self.db.rollback()
            raise
        except PasswordOperationCapacityError as exc:
            self._reject_password_capacity_exhaustion(cause=exc)
        except Exception:
            self.db.rollback()
            raise

    def login(
        self,
        *,
        username: str,
        password: str,
        context: RequestContext,
    ) -> LoginResult:
        normalized_username = username.strip()
        buckets = self._login_buckets(normalized_username, context)
        return run_with_deadlock_retry(
            self.db,
            lambda: self._attempt_login(normalized_username, password, context, buckets),
        )

    def _attempt_login(
        self,
        normalized_username: str,
        password: str,
        context: RequestContext,
        buckets: tuple[tuple[LoginThrottleScope, str], ...],
    ) -> LoginResult:
        """One full attempt, from the throttle check to the commit.

        Two brand-new accounts signing in at the same instant can each find no existing
        session row and take MySQL's gap lock on the same, still-empty tail of
        `idx_user_sessions_user_status`; whichever loses that deadlock aborts here with an
        `OperationalError`, which `login` retries as an entirely fresh attempt (issue #139).
        """
        try:
            now = self._now()
            # Inspect persisted failures under row locks. In-flight memory use
            # is bounded independently by PasswordManager's worker-local gate.
            self._check_login_attempt_allowed(buckets, now=now)

            user = self.repository.get_user_by_username(normalized_username)
            valid_password, replacement_hash = self.passwords.verify_or_dummy(
                password,
                user.password_hash if user is not None else None,
            )
            verified_password_hash = user.password_hash if user is not None else None
            valid_account = user is not None and user.status == UserStatus.ACTIVE

            if not valid_password or not valid_account:
                self._record_login_failure(buckets, now=now)
                self.audit.append(
                    action="AUTH_LOGIN_FAILED",
                    result="FAIL",
                    actor_user_id=user.id if user is not None else None,
                    target_user_id=user.id if user is not None else None,
                    resource_id=str(user.user_uuid) if user is not None else None,
                    context_ip_address=self._safe_ip(context),
                    context_user_agent=self._safe_user_agent(context),
                    description="Invalid credentials or inactive account",
                )
                self.db.commit()
                raise InvalidCredentialsError()

            locked_user = self.repository.lock_user(user.id)
            if locked_user is None or locked_user.status != UserStatus.ACTIVE:
                self._record_login_failure(buckets, now=now)
                self.audit.append(
                    action="AUTH_LOGIN_FAILED",
                    result="FAIL",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    resource_id=str(user.user_uuid),
                    context_ip_address=self._safe_ip(context),
                    context_user_agent=self._safe_user_agent(context),
                    description="Invalid credentials or inactive account",
                )
                self.db.commit()
                raise InvalidCredentialsError()

            if locked_user.password_hash != verified_password_hash:
                valid_password, replacement_hash = self.passwords.verify_and_update(
                    password,
                    locked_user.password_hash,
                )
                if not valid_password:
                    self._record_login_failure(buckets, now=now)
                    self.audit.append(
                        action="AUTH_LOGIN_FAILED",
                        result="FAIL",
                        actor_user_id=locked_user.id,
                        target_user_id=locked_user.id,
                        resource_id=str(locked_user.user_uuid),
                        context_ip_address=self._safe_ip(context),
                        context_user_agent=self._safe_user_agent(context),
                        description="Invalid credentials or inactive account",
                    )
                    self.db.commit()
                    raise InvalidCredentialsError()

            if replacement_hash is not None:
                locked_user.password_hash = replacement_hash

            self._clear_successful_account_throttle(buckets, now=now)
            evicted_sessions = self._enforce_session_limit(locked_user.id, now=now)
            tokens = self._create_session(locked_user, context=context, now=now)
            locked_user.last_login_at = now
            locked_user.updated_at = now

            self.audit.append(
                action="AUTH_LOGIN_SUCCEEDED",
                result="SUCCESS",
                actor_user_id=locked_user.id,
                target_user_id=locked_user.id,
                resource_id=str(tokens.session_id),
                context_ip_address=self._safe_ip(context),
                context_user_agent=self._safe_user_agent(context),
                metadata={"evicted_sessions": evicted_sessions},
            )
            result = LoginResult(user=self._account_snapshot(locked_user), tokens=tokens)
            self.db.commit()
            return result
        except PasswordOperationCapacityError as exc:
            self._reject_password_capacity_exhaustion(cause=exc)
        except (InvalidCredentialsError, AuthenticationRateLimitedError):
            # A failed-login audit/throttle transaction may already be committed.
            self.db.rollback()
            raise
        except Exception:
            self.db.rollback()
            raise

    def refresh(
        self,
        *,
        refresh_token: str,
        context: RequestContext,
    ) -> RefreshResult:
        if not 32 <= len(refresh_token) <= 512:
            raise InvalidRefreshTokenError()
        token_hash = hash_session_token(refresh_token)

        try:
            now = self._now()
            refresh_route = self.repository.get_refresh_route(token_hash)
            if refresh_route is None:
                raise InvalidRefreshTokenError()
            session_id, user_id = refresh_route
            user = self.repository.lock_user(user_id)
            user_session = self.repository.lock_session(session_id)
            stored_token = self.repository.lock_refresh_token(token_hash)
            if stored_token is None or stored_token.session_id != session_id:
                raise InvalidRefreshTokenError()
            if user_session is None:  # pragma: no cover - foreign-key invariant
                raise InvalidRefreshTokenError()
            if user is None:  # pragma: no cover - foreign-key invariant
                raise InvalidRefreshTokenError()

            if stored_token.consumed_at is not None:
                self.repository.revoke_session_family(
                    user_session,
                    now=now,
                    reason="refresh_token_reuse",
                )
                self.audit.append(
                    action="AUTH_REFRESH_REPLAY_DETECTED",
                    result="FAIL",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    resource_id=str(user_session.session_uuid),
                    context_ip_address=self._safe_ip(context),
                    context_user_agent=self._safe_user_agent(context),
                )
                self.db.commit()
                raise InvalidRefreshTokenError()

            if stored_token.revoked_at is not None:
                raise InvalidRefreshTokenError()

            if user_session.status != SessionStatus.ACTIVE:
                raise InvalidRefreshTokenError()

            if user.status != UserStatus.ACTIVE:
                self.repository.revoke_session_family(
                    user_session,
                    now=now,
                    reason="account_inactive",
                )
                self.audit.append(
                    action="AUTH_REFRESH_REJECTED",
                    result="FAIL",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    resource_id=str(user_session.session_uuid),
                    context_ip_address=self._safe_ip(context),
                    context_user_agent=self._safe_user_agent(context),
                    description="Account is not active",
                )
                self.db.commit()
                raise InvalidRefreshTokenError()

            if stored_token.expires_at <= now or user_session.absolute_expires_at <= now:
                self.repository.expire_session_family(user_session, now=now)
                self.audit.append(
                    action="AUTH_SESSION_EXPIRED",
                    result="FAIL",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    resource_id=str(user_session.session_uuid),
                    context_ip_address=self._safe_ip(context),
                    context_user_agent=self._safe_user_agent(context),
                )
                self.db.commit()
                raise InvalidRefreshTokenError()

            refresh_available_at = stored_token.created_at + timedelta(
                seconds=self.settings.AUTH_REFRESH_MIN_INTERVAL_SECONDS
            )
            if refresh_available_at > now:
                retry_after = max(
                    1,
                    math.ceil((refresh_available_at - now).total_seconds()),
                )
                raise AuthenticationRateLimitedError(retry_after_seconds=retry_after)

            stored_token.consumed_at = now
            tokens = self._rotate_session(
                user_session,
                next_generation=stored_token.generation + 1,
                now=now,
            )
            user_session.ip_address = self._safe_ip(context)
            user_session.user_agent = self._safe_user_agent(context)
            user_session.updated_at = now
            self.audit.append(
                action="AUTH_SESSION_REFRESHED",
                result="SUCCESS",
                actor_user_id=user.id,
                target_user_id=user.id,
                resource_id=str(user_session.session_uuid),
                context_ip_address=self._safe_ip(context),
                context_user_agent=self._safe_user_agent(context),
                metadata={"generation": stored_token.generation + 1},
            )
            self.db.commit()
            return RefreshResult(tokens=tokens)
        except (AuthenticationRateLimitedError, InvalidRefreshTokenError):
            # Replay/expiry revocation may already be committed.
            self.db.rollback()
            raise
        except Exception:
            self.db.rollback()
            raise

    def authenticate_access_token(self, raw_token: str) -> ActorContext:
        self._validate_token_shape(raw_token)
        token_hash = hash_session_token(raw_token)
        principal = self.repository.get_access_principal(token_hash)
        if principal is None:
            raise AuthenticationError()

        user_session, user = principal
        now = self._now()
        if (
            user_session.status != SessionStatus.ACTIVE
            or user_session.access_expires_at <= now
            or user_session.absolute_expires_at <= now
            or user.status != UserStatus.ACTIVE
        ):
            raise AuthenticationError()

        return ActorContext(
            user_id=user.id,
            user_public_id=UUID(str(user.user_uuid)),
            session_id=user_session.id,
            session_public_id=UUID(str(user_session.session_uuid)),
            role=SystemRole(user.role),
            status=UserStatus(user.status),
            access_token_hash=token_hash,
            must_change_password=bool(user.must_change_password),
        )

    def get_me(self, *, actor: ActorContext) -> AccountSnapshot:
        user = self.repository.get_user(actor.user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise AuthenticationError()
        return self._account_snapshot(user)

    def logout(self, *, actor: ActorContext, context: RequestContext) -> None:
        try:
            now = self._now()
            user_session = self.repository.lock_session(actor.session_id)
            if (
                user_session is None
                or user_session.status != SessionStatus.ACTIVE
                or not secrets.compare_digest(
                    user_session.access_token_hash,
                    actor.access_token_hash,
                )
            ):
                raise AuthenticationError()

            self.repository.revoke_session_family(
                user_session,
                now=now,
                reason="logout",
            )
            self.audit.append(
                action="AUTH_LOGGED_OUT",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=actor.user_id,
                resource_id=str(actor.session_public_id),
                context_ip_address=self._safe_ip(context),
                context_user_agent=self._safe_user_agent(context),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def logout_all(self, *, actor: ActorContext, context: RequestContext) -> int:
        try:
            now = self._now()
            revoked = self.repository.revoke_all_session_families(
                actor.user_id,
                now=now,
                reason="logout_all",
            )
            self.audit.append(
                action="AUTH_ALL_SESSIONS_REVOKED",
                result="SUCCESS",
                actor_user_id=actor.user_id,
                target_user_id=actor.user_id,
                resource_id=str(actor.user_public_id),
                context_ip_address=self._safe_ip(context),
                context_user_agent=self._safe_user_agent(context),
                metadata={"revoked_sessions": revoked},
            )
            self.db.commit()
            return revoked
        except Exception:
            self.db.rollback()
            raise

    def change_password(
        self,
        *,
        actor: ActorContext,
        current_password: str,
        new_password: str,
        context: RequestContext,
    ) -> int:
        policy_error = password_policy_error(new_password)
        if policy_error:
            raise WeakPasswordError(policy_error)

        try:
            now = self._now()
            user = self.repository.get_user(actor.user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                raise AuthenticationError()

            reauthentication_buckets = self._reauthentication_buckets(user.username, context)
            self._check_login_attempt_allowed(reauthentication_buckets, now=now)

            verified_password_hash = user.password_hash
            if not self.passwords.verify(current_password, user.password_hash):
                self._record_password_change_failure(
                    user=user,
                    buckets=reauthentication_buckets,
                    context=context,
                    now=now,
                )
                raise InvalidCurrentPasswordError()

            if normalize_password(current_password) == normalize_password(new_password):
                self._clear_successful_account_throttle(
                    reauthentication_buckets,
                    now=now,
                )
                self.db.commit()
                raise PasswordUnchangedError()

            contextual_policy_error = password_policy_error(
                new_password,
                context_values=(user.username, user.email),
            )
            if contextual_policy_error:
                self._clear_successful_account_throttle(
                    reauthentication_buckets,
                    now=now,
                )
                self.db.commit()
                raise WeakPasswordError(contextual_policy_error)

            replacement_hash = self.passwords.hash(new_password)
            locked_user = self.repository.lock_user(actor.user_id)
            if locked_user is None or locked_user.status != UserStatus.ACTIVE:
                raise AuthenticationError()
            if locked_user.password_hash != verified_password_hash and not self.passwords.verify(
                current_password,
                locked_user.password_hash,
            ):
                self._record_password_change_failure(
                    user=locked_user,
                    buckets=reauthentication_buckets,
                    context=context,
                    now=now,
                )
                raise InvalidCurrentPasswordError()

            self._clear_successful_account_throttle(
                reauthentication_buckets,
                now=now,
            )
            locked_user.password_hash = replacement_hash
            locked_user.password_changed_at = now
            locked_user.updated_at = now
            # The holder chose this password, so an administrator's temporary one is gone.
            locked_user.must_change_password = False
            revoked = self.repository.revoke_all_session_families(
                locked_user.id,
                now=now,
                reason="password_changed",
            )
            self.audit.append(
                action="AUTH_PASSWORD_CHANGED",
                result="SUCCESS",
                actor_user_id=locked_user.id,
                target_user_id=locked_user.id,
                resource_id=str(locked_user.user_uuid),
                context_ip_address=self._safe_ip(context),
                context_user_agent=self._safe_user_agent(context),
                metadata={"revoked_sessions": revoked},
            )
            self.db.commit()
            return revoked
        except (
            AuthenticationRateLimitedError,
            InvalidCurrentPasswordError,
            PasswordUnchangedError,
            WeakPasswordError,
        ):
            # Invalid-current-password audit may already be committed.
            self.db.rollback()
            raise
        except PasswordOperationCapacityError as exc:
            self._reject_password_capacity_exhaustion(cause=exc)
        except Exception:
            self.db.rollback()
            raise

    def list_sessions(self, *, actor: ActorContext) -> tuple[SessionSnapshot, ...]:
        now = self._now()
        sessions = self.repository.list_sessions(actor.user_id)
        return tuple(self._session_snapshot(item, actor=actor, now=now) for item in sessions)

    def revoke_session(
        self,
        *,
        actor: ActorContext,
        session_id: UUID,
        context: RequestContext,
    ) -> None:
        try:
            now = self._now()
            user_session = self.repository.lock_session_for_user(actor.user_id, session_id)
            if user_session is None:
                raise SessionNotFoundError()

            changed = self.repository.revoke_session_family(
                user_session,
                now=now,
                reason="user_revoked",
            )
            if changed:
                self.audit.append(
                    action="AUTH_SESSION_REVOKED",
                    result="SUCCESS",
                    actor_user_id=actor.user_id,
                    target_user_id=actor.user_id,
                    resource_id=str(session_id),
                    context_ip_address=self._safe_ip(context),
                    context_user_agent=self._safe_user_agent(context),
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _create_session(
        self,
        user: User,
        *,
        context: RequestContext,
        now: datetime,
    ) -> TokenPair:
        session_public_id = self.uuid_factory()
        absolute_expires_at = now + timedelta(hours=self.settings.SESSION_ABSOLUTE_EXPIRE_HOURS)
        access_token = f"at_{self.token_factory()}"
        refresh_token = f"rt_{self.token_factory()}"
        access_expires_at = min(
            now + timedelta(minutes=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            absolute_expires_at,
        )
        refresh_expires_at = min(
            now + timedelta(days=self.settings.REFRESH_TOKEN_EXPIRE_DAYS),
            absolute_expires_at,
        )
        user_session = UserSession(
            session_uuid=str(session_public_id),
            user_id=user.id,
            access_token_hash=hash_session_token(access_token),
            status=SessionStatus.ACTIVE,
            ip_address=self._safe_ip(context),
            user_agent=self._safe_user_agent(context),
            created_at=now,
            updated_at=now,
            access_expires_at=access_expires_at,
            absolute_expires_at=absolute_expires_at,
        )
        self.repository.add_session(user_session)
        self.repository.flush()
        self.repository.add_refresh_token(
            SessionRefreshToken(
                session_id=user_session.id,
                token_hash=hash_session_token(refresh_token),
                generation=0,
                created_at=now,
                expires_at=refresh_expires_at,
            )
        )
        return TokenPair(
            session_id=session_public_id,
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=to_api_utc(access_expires_at),
            refresh_expires_at=to_api_utc(refresh_expires_at),
        )

    def _rotate_session(
        self,
        user_session: UserSession,
        *,
        next_generation: int,
        now: datetime,
    ) -> TokenPair:
        access_token = f"at_{self.token_factory()}"
        refresh_token = f"rt_{self.token_factory()}"
        access_expires_at = min(
            now + timedelta(minutes=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            user_session.absolute_expires_at,
        )
        refresh_expires_at = min(
            now + timedelta(days=self.settings.REFRESH_TOKEN_EXPIRE_DAYS),
            user_session.absolute_expires_at,
        )
        user_session.access_token_hash = hash_session_token(access_token)
        user_session.access_expires_at = access_expires_at
        self.repository.add_refresh_token(
            SessionRefreshToken(
                session_id=user_session.id,
                token_hash=hash_session_token(refresh_token),
                generation=next_generation,
                created_at=now,
                expires_at=refresh_expires_at,
            )
        )
        return TokenPair(
            session_id=UUID(str(user_session.session_uuid)),
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=to_api_utc(access_expires_at),
            refresh_expires_at=to_api_utc(refresh_expires_at),
        )

    def _enforce_session_limit(self, user_id: int, *, now: datetime) -> int:
        active_sessions = self.repository.lock_active_sessions(user_id)
        current_sessions: list[UserSession] = []
        for user_session in active_sessions:
            if user_session.absolute_expires_at <= now:
                self.repository.expire_session_family(user_session, now=now)
            else:
                current_sessions.append(user_session)

        excess = max(0, len(current_sessions) - self.settings.AUTH_MAX_ACTIVE_SESSIONS + 1)
        for user_session in current_sessions[:excess]:
            self.repository.revoke_session_family(
                user_session,
                now=now,
                reason="session_limit",
            )
        return excess

    def _check_login_attempt_allowed(
        self,
        buckets: tuple[tuple[LoginThrottleScope, str], ...],
        *,
        now: datetime,
    ) -> None:
        """Atomically inspect completed-failure blocks before verification."""
        try:
            retry_after = 0
            for scope, key_hash in sorted(
                buckets,
                key=lambda item: (item[0].value, item[1]),
            ):
                throttle = self.repository.lock_or_create_throttle(
                    scope,
                    key_hash,
                    now=now,
                )
                self._reset_login_throttle_if_elapsed(throttle, now=now)
                if throttle.blocked_until is not None and throttle.blocked_until > now:
                    retry_after = max(
                        retry_after,
                        math.ceil((throttle.blocked_until - now).total_seconds()),
                    )
                else:
                    max_failures, block_seconds = self._login_throttle_policy(scope)
                    if throttle.failed_count >= max_failures:
                        throttle.blocked_until = now + timedelta(seconds=block_seconds)
                        throttle.updated_at = now
                        retry_after = max(retry_after, block_seconds)

            if retry_after:
                self.db.commit()
                raise AuthenticationRateLimitedError(retry_after_seconds=max(1, retry_after))

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _record_login_failure(
        self,
        buckets: tuple[tuple[LoginThrottleScope, str], ...],
        *,
        now: datetime,
    ) -> None:
        for scope, key_hash in sorted(buckets, key=lambda item: (item[0].value, item[1])):
            max_failures, block_seconds = self._login_throttle_policy(scope)
            throttle = self.repository.lock_or_create_throttle(
                scope,
                key_hash,
                now=now,
            )
            self._reset_login_throttle_if_elapsed(throttle, now=now)
            throttle.failed_count += 1
            if throttle.failed_count >= max_failures and not (
                throttle.blocked_until is not None and throttle.blocked_until > now
            ):
                throttle.blocked_until = now + timedelta(seconds=block_seconds)
            throttle.updated_at = now

    def _clear_successful_account_throttle(
        self,
        buckets: tuple[tuple[LoginThrottleScope, str], ...],
        *,
        now: datetime,
    ) -> None:
        for scope, key_hash in sorted(buckets, key=lambda item: (item[0].value, item[1])):
            if scope not in {
                LoginThrottleScope.ACCOUNT,
                LoginThrottleScope.REAUTH_ACCOUNT,
            }:
                continue
            self.repository.lock_or_create_throttle(scope, key_hash, now=now)
            self.repository.clear_throttle(scope, key_hash)

    def _record_password_change_failure(
        self,
        *,
        user: User,
        buckets: tuple[tuple[LoginThrottleScope, str], ...],
        context: RequestContext,
        now: datetime,
    ) -> None:
        self.record_reauthentication_failure(
            user=user,
            buckets=buckets,
            context=context,
            now=now,
            action="AUTH_PASSWORD_CHANGE_FAILED",
            description="Current password verification failed",
        )

    # Re-entering the password while signed in (change password, delete account) shares
    # one set of throttle buckets, so guessing through one action cannot bypass the limit
    # set by the other. These three are the public face of that for other services.

    def begin_reauthentication(
        self,
        *,
        username: str,
        context: RequestContext,
        now: datetime,
    ) -> tuple[tuple[LoginThrottleScope, str], ...]:
        """Refuse with 429 while the account or IP is blocked; otherwise return the buckets.

        Commits on its own, like the login check it wraps, so the caller must not hold row
        locks it still needs across this call.
        """
        buckets = self._reauthentication_buckets(username, context)
        self._check_login_attempt_allowed(buckets, now=now)
        return buckets

    def record_reauthentication_failure(
        self,
        *,
        user: User,
        buckets: tuple[tuple[LoginThrottleScope, str], ...],
        context: RequestContext,
        now: datetime,
        action: str,
        description: str,
    ) -> None:
        """Count the failure and commit its audit event before the caller rolls back."""
        self._record_login_failure(buckets, now=now)
        self.audit.append(
            action=action,
            result="FAIL",
            actor_user_id=user.id,
            target_user_id=user.id,
            resource_id=str(user.user_uuid),
            context_ip_address=self._safe_ip(context),
            context_user_agent=self._safe_user_agent(context),
            description=description,
        )
        self.db.commit()

    def clear_reauthentication_throttle(
        self,
        *,
        buckets: tuple[tuple[LoginThrottleScope, str], ...],
        now: datetime,
    ) -> None:
        """A correct password resets the account bucket; the IP bucket keeps counting."""
        self._clear_successful_account_throttle(buckets, now=now)

    def _reject_password_capacity_exhaustion(
        self,
        *,
        cause: PasswordOperationCapacityError,
    ) -> NoReturn:
        """Release current locks and fail without recording an unverified attempt."""
        self.db.rollback()
        raise AuthenticationRateLimitedError(retry_after_seconds=1) from cause

    def _reset_login_throttle_if_elapsed(
        self,
        throttle: AuthLoginThrottle,
        *,
        now: datetime,
    ) -> None:
        window_elapsed = now - throttle.window_started_at >= timedelta(
            seconds=self.settings.AUTH_LOGIN_WINDOW_SECONDS
        )
        active_block = throttle.blocked_until is not None and throttle.blocked_until > now
        block_elapsed = throttle.blocked_until is not None and throttle.blocked_until <= now
        if block_elapsed or (window_elapsed and not active_block):
            throttle.failed_count = 0
            throttle.window_started_at = now
            throttle.blocked_until = None
            throttle.updated_at = now

    def _login_throttle_policy(self, scope: LoginThrottleScope) -> tuple[int, int]:
        if scope == LoginThrottleScope.ACCOUNT:
            return (
                self.settings.AUTH_LOGIN_ACCOUNT_MAX_FAILURES,
                self.settings.AUTH_LOGIN_ACCOUNT_BLOCK_SECONDS,
            )
        if scope == LoginThrottleScope.IP:
            return (
                self.settings.AUTH_LOGIN_IP_MAX_FAILURES,
                self.settings.AUTH_LOGIN_IP_BLOCK_SECONDS,
            )
        if scope == LoginThrottleScope.REAUTH_ACCOUNT:
            return (
                self.settings.AUTH_REAUTH_ACCOUNT_MAX_FAILURES,
                self.settings.AUTH_REAUTH_BLOCK_SECONDS,
            )
        if scope == LoginThrottleScope.REAUTH_IP:
            return (
                self.settings.AUTH_REAUTH_IP_MAX_FAILURES,
                self.settings.AUTH_REAUTH_BLOCK_SECONDS,
            )
        raise ValueError(f"Unsupported login throttle scope: {scope}")

    def _consume_registration_attempt(self, context: RequestContext) -> None:
        ip_address = self._safe_ip(context)
        if not ip_address:
            return

        scope = LoginThrottleScope.REGISTRATION_IP
        key_hash = hash_auth_throttle_key(
            self.settings.SECRET_KEY,
            scope.value,
            ip_address,
        )
        bucket = ((scope, key_hash),)
        try:
            now = self._now()
            blocked_until = self.repository.get_blocked_until(bucket, now=now)
            if blocked_until is not None:
                retry_after = max(1, math.ceil((blocked_until - now).total_seconds()))
                raise AuthenticationRateLimitedError(retry_after_seconds=retry_after)

            throttle = self.repository.lock_or_create_throttle(scope, key_hash, now=now)
            window = timedelta(seconds=self.settings.AUTH_REGISTRATION_WINDOW_SECONDS)
            active_block = throttle.blocked_until is not None and throttle.blocked_until > now
            block_elapsed = throttle.blocked_until is not None and throttle.blocked_until <= now
            if block_elapsed or (now - throttle.window_started_at >= window and not active_block):
                throttle.failed_count = 0
                throttle.window_started_at = now
                throttle.blocked_until = None
            if throttle.blocked_until is not None and throttle.blocked_until > now:
                retry_after = max(
                    1,
                    math.ceil((throttle.blocked_until - now).total_seconds()),
                )
                raise AuthenticationRateLimitedError(retry_after_seconds=retry_after)
            throttle.failed_count += 1
            if throttle.failed_count >= self.settings.AUTH_REGISTRATION_MAX_ATTEMPTS:
                throttle.blocked_until = now + timedelta(
                    seconds=self.settings.AUTH_REGISTRATION_BLOCK_SECONDS
                )
            throttle.updated_at = now
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _login_buckets(
        self,
        username: str,
        context: RequestContext,
    ) -> tuple[tuple[LoginThrottleScope, str], ...]:
        account_value = username.casefold()
        buckets: list[tuple[LoginThrottleScope, str]] = [
            (
                LoginThrottleScope.ACCOUNT,
                hash_auth_throttle_key(
                    self.settings.SECRET_KEY,
                    LoginThrottleScope.ACCOUNT.value,
                    account_value,
                ),
            )
        ]
        ip_address = self._safe_ip(context)
        if ip_address:
            buckets.append(
                (
                    LoginThrottleScope.IP,
                    hash_auth_throttle_key(
                        self.settings.SECRET_KEY,
                        LoginThrottleScope.IP.value,
                        ip_address,
                    ),
                )
            )
        return tuple(buckets)

    def _reauthentication_buckets(
        self,
        username: str,
        context: RequestContext,
    ) -> tuple[tuple[LoginThrottleScope, str], ...]:
        account_value = username.casefold()
        buckets: list[tuple[LoginThrottleScope, str]] = [
            (
                LoginThrottleScope.REAUTH_ACCOUNT,
                hash_auth_throttle_key(
                    self.settings.SECRET_KEY,
                    LoginThrottleScope.REAUTH_ACCOUNT.value,
                    account_value,
                ),
            )
        ]
        ip_address = self._safe_ip(context)
        if ip_address:
            buckets.append(
                (
                    LoginThrottleScope.REAUTH_IP,
                    hash_auth_throttle_key(
                        self.settings.SECRET_KEY,
                        LoginThrottleScope.REAUTH_IP.value,
                        ip_address,
                    ),
                )
            )
        return tuple(buckets)

    def _account_snapshot(self, user: User) -> AccountSnapshot:
        return AccountSnapshot(
            id=UUID(str(user.user_uuid)),
            username=user.username,
            email=user.email,
            role=SystemRole(user.role),
            status=UserStatus(user.status),
            email_verified=user.email_verified,
            created_at=to_api_utc(user.created_at),
            last_login_at=to_api_utc(user.last_login_at),
            has_avatar=bool(user.avatar_object_key),
            must_change_password=bool(user.must_change_password),
        )

    def _session_snapshot(
        self,
        user_session: UserSession,
        *,
        actor: ActorContext,
        now: datetime,
    ) -> SessionSnapshot:
        status = SessionStatus(user_session.status)
        if status == SessionStatus.ACTIVE and user_session.absolute_expires_at <= now:
            status = SessionStatus.EXPIRED
        return SessionSnapshot(
            id=UUID(str(user_session.session_uuid)),
            status=status,
            current=user_session.id == actor.session_id,
            created_at=to_api_utc(user_session.created_at),
            access_expires_at=to_api_utc(user_session.access_expires_at),
            absolute_expires_at=to_api_utc(user_session.absolute_expires_at),
            ip_address=user_session.ip_address,
            user_agent=user_session.user_agent,
            revoked_at=to_api_utc(user_session.revoked_at),
        )

    def _now(self) -> datetime:
        """The instant as the second-resolution DATETIME columns can hold it.

        Everything this service writes -- users, sessions, refresh tokens, throttle
        buckets -- lands in a plain `DATETIME`, which stores no fractional part and which
        MySQL *rounds* into rather than truncating. Settling the value here keeps the row
        equal to what the caller holds, and keeps a stored timestamp from landing up to
        half a second in the future. Registration is the one exception; see `_now_exact`.
        """
        return to_second_resolution_utc(self.clock())

    def _now_exact(self) -> datetime:
        """Full precision, for the `DATETIME(6)` key-custody columns only.

        `user_key_protection_profiles` and `encrypted_private_key_bundles` were declared
        with fractional seconds deliberately. Nothing signs those timestamps today, but
        reducing a column's fidelity is not a side effect this change is entitled to
        have, so the custody rows keep every digit the column was given.
        """
        return to_database_utc(self.clock())

    @staticmethod
    def _validate_token_shape(token: str) -> None:
        if not 32 <= len(token) <= 512:
            raise AuthenticationError()

    @staticmethod
    def _safe_ip(context: RequestContext) -> str | None:
        if context.ip_address is None:
            return None
        return context.ip_address[:45]

    @staticmethod
    def _safe_user_agent(context: RequestContext) -> str | None:
        if context.user_agent is None:
            return None
        return context.user_agent[:512]

    @staticmethod
    def _account_identifier_conflict(exc: IntegrityError) -> str | None:
        """Which users unique key a MySQL 1062 duplicate hit: "username", "email" or None."""
        original_args = getattr(exc.orig, "args", ())
        mysql_error_code = original_args[0] if original_args else None
        message = str(original_args[1] if len(original_args) > 1 else exc.orig).casefold()
        if mysql_error_code != 1062:
            return None
        if "uq_users_username" in message:
            return "username"
        if "uq_users_email" in message:
            return "email"
        return None
