from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.domain.enums import (
    LoginThrottleScope,
    SessionStatus,
    SystemRole,
    VerificationCodeStatus,
    VerificationPurpose,
)
from app.models.auth_login_throttle import AuthLoginThrottle
from app.models.email_verification_code import EmailVerificationCode
from app.models.encrypted_private_key_bundle import EncryptedPrivateKeyBundle
from app.models.session_refresh_token import SessionRefreshToken
from app.models.user import User
from app.models.user_key import UserKey
from app.models.user_key_protection_profile import UserKeyProtectionProfile
from app.models.user_session import UserSession


class AuthRepository:
    """MySQL-backed identity persistence. Transaction ownership stays in AuthService."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def identifier_exists(self, username: str, email: str) -> bool:
        """True when either the username or the email is already taken.

        Registration checks the two separately (see `AuthService.register`) so that it can
        answer differently for each; this combined check is kept for the seed scripts.
        """
        statement = select(User.id).where(or_(User.username == username, User.email == email))
        return self.db.scalar(statement.limit(1)) is not None

    def username_exists(self, username: str) -> bool:
        return self.db.scalar(select(User.id).where(User.username == username).limit(1)) is not None

    def email_exists(self, email: str) -> bool:
        return self.db.scalar(select(User.id).where(User.email == email).limit(1)) is not None

    def get_user_by_username(self, username: str) -> User | None:
        return self.db.scalar(select(User).where(User.username == username).limit(1))

    def get_user(self, user_id: int) -> User | None:
        return self.db.scalar(
            select(User).where(User.id == user_id).execution_options(populate_existing=True)
        )

    def lock_user(self, user_id: int) -> User | None:
        return self.db.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_administrators(self) -> list[User]:
        """Every administrator row, locked in id order.

        For the changes that must not leave the platform without an active administrator.
        Each such change takes these locks first and in the same order, so two of them run
        one after the other instead of each counting the other as still active.
        """
        return list(
            self.db.scalars(
                select(User)
                .where(User.role == SystemRole.ADMIN)
                .order_by(User.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )

    def lock_key_protection_profile(self, user_id: int) -> UserKeyProtectionProfile | None:
        return self.db.scalar(
            select(UserKeyProtectionProfile)
            .where(UserKeyProtectionProfile.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def add_user(self, user: User) -> None:
        self.db.add(user)

    def add_user_key(self, user_key: UserKey) -> None:
        self.db.add(user_key)

    def add_key_protection_profile(self, profile: UserKeyProtectionProfile) -> None:
        self.db.add(profile)

    def add_private_key_bundle(self, bundle: EncryptedPrivateKeyBundle) -> None:
        self.db.add(bundle)

    def add_session(self, user_session: UserSession) -> None:
        self.db.add(user_session)

    def add_refresh_token(self, refresh_token: SessionRefreshToken) -> None:
        self.db.add(refresh_token)

    def flush(self) -> None:
        self.db.flush()

    def get_access_principal(
        self,
        access_token_hash: str,
    ) -> tuple[UserSession, User] | None:
        row = self.db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.access_token_hash == access_token_hash)
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return tuple(row)

    def lock_session(self, session_id: int) -> UserSession | None:
        return self.db.scalar(
            select(UserSession)
            .where(UserSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_session_for_user(
        self,
        user_id: int,
        session_public_id: UUID,
    ) -> UserSession | None:
        return self.db.scalar(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.session_uuid == str(session_public_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def list_sessions(self, user_id: int, *, limit: int = 100) -> list[UserSession]:
        return list(
            self.db.scalars(
                select(UserSession)
                .where(UserSession.user_id == user_id)
                .order_by(UserSession.created_at.desc(), UserSession.id.desc())
                .limit(limit)
                .execution_options(populate_existing=True)
            )
        )

    def lock_active_sessions(self, user_id: int) -> list[UserSession]:
        return list(
            self.db.scalars(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.status == SessionStatus.ACTIVE,
                )
                .order_by(UserSession.created_at.asc(), UserSession.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def lock_refresh_token(self, token_hash: str) -> SessionRefreshToken | None:
        return self.db.scalar(
            select(SessionRefreshToken)
            .where(SessionRefreshToken.token_hash == token_hash)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def get_refresh_route(self, token_hash: str) -> tuple[int, int] | None:
        row = self.db.execute(
            select(SessionRefreshToken.session_id, UserSession.user_id)
            .join(UserSession, UserSession.id == SessionRefreshToken.session_id)
            .where(SessionRefreshToken.token_hash == token_hash)
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return row[0], row[1]

    def lock_refresh_tokens_for_session(self, session_id: int) -> list[SessionRefreshToken]:
        return list(
            self.db.scalars(
                select(SessionRefreshToken)
                .where(SessionRefreshToken.session_id == session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def revoke_session_family(
        self,
        user_session: UserSession,
        *,
        now: datetime,
        reason: str,
    ) -> bool:
        changed = user_session.status == SessionStatus.ACTIVE
        if changed:
            user_session.status = SessionStatus.REVOKED
            user_session.revoked_at = now
            user_session.revoked_reason = reason

        for refresh_token in self.lock_refresh_tokens_for_session(user_session.id):
            if refresh_token.consumed_at is None and refresh_token.revoked_at is None:
                refresh_token.revoked_at = now
        return changed

    def expire_session_family(
        self,
        user_session: UserSession,
        *,
        now: datetime,
    ) -> bool:
        changed = user_session.status == SessionStatus.ACTIVE
        if changed:
            user_session.status = SessionStatus.EXPIRED
            user_session.revoked_at = now
            user_session.revoked_reason = "absolute_expiry"
        for refresh_token in self.lock_refresh_tokens_for_session(user_session.id):
            if refresh_token.consumed_at is None and refresh_token.revoked_at is None:
                refresh_token.revoked_at = now
        return changed

    def revoke_all_session_families(
        self,
        user_id: int,
        *,
        now: datetime,
        reason: str,
    ) -> int:
        sessions = self.lock_active_sessions(user_id)
        revoked = 0
        for user_session in sessions:
            if self.revoke_session_family(user_session, now=now, reason=reason):
                revoked += 1
        return revoked

    def release_identifiers(self, user: User, *, tombstone: str) -> None:
        """Free the username and email of a closed account so they can be registered again.

        `identifier_exists` does not filter by status, so leaving the original values in
        place would keep them reserved forever -- and closing the account exists precisely so
        the person can start over. The row itself stays: audit entries reference the user by
        id, and deleting it would take the history of what happened with it.

        The tombstone email keeps a real domain on purpose. A reserved TLD registers fine and
        then makes serialization fail wherever the address is read back.
        """
        user.username = f"deleted-{tombstone}"
        user.email = f"deleted+{tombstone}@secureview.tech"

    def get_blocked_until(
        self,
        buckets: tuple[tuple[LoginThrottleScope, str], ...],
        *,
        now: datetime,
    ) -> datetime | None:
        if not buckets:
            return None
        clauses = [
            (AuthLoginThrottle.scope == scope) & (AuthLoginThrottle.key_hash == key_hash)
            for scope, key_hash in buckets
        ]
        blocked_values = self.db.scalars(
            select(AuthLoginThrottle.blocked_until).where(or_(*clauses))
        )
        active_blocks = [value for value in blocked_values if value is not None and value > now]
        return max(active_blocks, default=None)

    def lock_or_create_throttle(
        self,
        scope: LoginThrottleScope,
        key_hash: str,
        *,
        now: datetime,
    ) -> AuthLoginThrottle:
        insert_statement = mysql_insert(AuthLoginThrottle).values(
            scope=scope,
            key_hash=key_hash,
            failed_count=0,
            window_started_at=now,
            blocked_until=None,
            updated_at=now,
        )
        self.db.execute(
            insert_statement.on_duplicate_key_update(
                key_hash=insert_statement.inserted.key_hash,
            )
        )
        throttle = self.db.scalar(
            select(AuthLoginThrottle)
            .where(
                AuthLoginThrottle.scope == scope,
                AuthLoginThrottle.key_hash == key_hash,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if throttle is None:  # pragma: no cover - database invariant
            raise RuntimeError("Authentication throttle row could not be locked")
        return throttle

    def add_verification_code(self, code: EmailVerificationCode) -> None:
        self.db.add(code)

    def get_user_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email).limit(1))

    def get_last_verification_code_issued_at(
        self,
        *,
        email: str,
        purpose: VerificationPurpose,
    ) -> datetime | None:
        return self.db.scalar(
            select(EmailVerificationCode.created_at)
            .where(
                EmailVerificationCode.email == email,
                EmailVerificationCode.purpose == purpose,
            )
            .order_by(EmailVerificationCode.created_at.desc())
            .limit(1)
        )

    def invalidate_pending_verification_codes(
        self,
        *,
        email: str,
        purpose: VerificationPurpose,
    ) -> int:
        result = self.db.execute(
            update(EmailVerificationCode)
            .where(
                EmailVerificationCode.email == email,
                EmailVerificationCode.purpose == purpose,
                EmailVerificationCode.status == VerificationCodeStatus.PENDING,
            )
            .values(status=VerificationCodeStatus.INVALIDATED)
        )
        return int(result.rowcount or 0)

    def lock_active_verification_code(
        self,
        *,
        email: str,
        purpose: VerificationPurpose,
        now: datetime,
    ) -> EmailVerificationCode | None:
        """Lock the newest unconsumed challenge so a concurrent submit cannot reuse it."""
        return self.db.scalar(
            select(EmailVerificationCode)
            .where(
                EmailVerificationCode.email == email,
                EmailVerificationCode.purpose == purpose,
                EmailVerificationCode.status == VerificationCodeStatus.PENDING,
                EmailVerificationCode.expires_at > now,
            )
            .order_by(EmailVerificationCode.created_at.desc(), EmailVerificationCode.id.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def clear_throttle(self, scope: LoginThrottleScope, key_hash: str) -> None:
        self.db.execute(
            delete(AuthLoginThrottle).where(
                AuthLoginThrottle.scope == scope,
                AuthLoginThrottle.key_hash == key_hash,
            )
        )
