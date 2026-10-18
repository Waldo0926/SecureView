from __future__ import annotations

import hmac
import math
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_auth_throttle_key
from app.core.time import to_second_resolution_utc, utc_now
from app.domain.auth import RequestContext
from app.domain.enums import (
    LoginThrottleScope,
    UserStatus,
    VerificationCodeStatus,
    VerificationPurpose,
)
from app.domain.errors import (
    AuthenticationRateLimitedError,
    EmailDeliveryFailedError,
    VerificationCodeInvalidError,
)
from app.models.auth_login_throttle import AuthLoginThrottle
from app.models.email_verification_code import EmailVerificationCode
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.services.audit_log_service import AuditLogService
from app.services.email_service import EmailDeliveryError, EmailService, OutboundEmail

_PURPOSE_SUBJECTS: dict[VerificationPurpose, str] = {
    VerificationPurpose.REGISTRATION: "Your SecureView registration code",
    VerificationPurpose.PASSWORD_RESET: "Your SecureView password reset code",
}

_PURPOSE_INTROS: dict[VerificationPurpose, str] = {
    VerificationPurpose.REGISTRATION: ("Use this code to finish creating your SecureView account."),
    VerificationPurpose.PASSWORD_RESET: ("Use this code to reset your SecureView password."),
}


class VerificationService:
    """Issues and checks emailed one-time codes.

    Only a keyed digest of each code reaches the database, so reading the table
    does not reveal a pending challenge. The caller owns the transaction, except
    that a rejected attempt commits its own counter and throttle updates before
    raising so they survive the caller's rollback.
    """

    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        repository: AuthRepository | None = None,
        audit_service: AuditLogService | None = None,
        email_service: EmailService | None = None,
        clock: Callable[[], datetime] = utc_now,
        code_factory: Callable[[int], str] | None = None,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.db = db
        self.settings = settings
        self.repository = repository or AuthRepository(db)
        self.audit = audit_service or AuditLogService(db, clock=clock)
        self.email = email_service or EmailService(settings)
        self.clock = clock
        self.code_factory = code_factory or _generate_numeric_code
        self.uuid_factory = uuid_factory

    def issue(
        self,
        *,
        purpose: VerificationPurpose,
        email: str,
        context: RequestContext,
    ) -> None:
        """Send a code when the address is eligible, without revealing whether it is.

        The caller always reports the same outcome so this endpoint cannot be
        used to enumerate registered addresses.
        """
        normalized_email = email.strip().lower()
        now = self._now()

        self._consume_send_allowance(normalized_email, context, now=now)

        user = self.repository.get_user_by_email(normalized_email)
        target_user = self._eligible_user(purpose, user)
        # Checked before eligibility, and a withheld send below records its time too, so a
        # quick second request answers 429 whether or not the address has an account.
        # Checking it only on the sending path let that answer tell the two apart.
        self._enforce_resend_interval(normalized_email, purpose, now=now)
        if target_user is None and purpose == VerificationPurpose.PASSWORD_RESET:
            # No account to reset. Stop before sending, but leave the throttle
            # consumed so probing costs the same as a real request.
            self._record_withheld_send(purpose, normalized_email, context, now=now)
            return
        if target_user is not None and purpose == VerificationPurpose.REGISTRATION:
            # The address already has an account; registration cannot proceed.
            self._record_withheld_send(purpose, normalized_email, context, now=now)
            return

        self.repository.invalidate_pending_verification_codes(
            email=normalized_email,
            purpose=purpose,
        )

        code = self.code_factory(self.settings.VERIFICATION_CODE_LENGTH)
        record = EmailVerificationCode(
            code_uuid=str(self.uuid_factory()),
            purpose=purpose,
            email=normalized_email,
            user_id=target_user.id if target_user is not None else None,
            code_hash=self._digest(purpose=purpose, email=normalized_email, code=code),
            status=VerificationCodeStatus.PENDING,
            attempt_count=0,
            max_attempts=self.settings.VERIFICATION_CODE_MAX_ATTEMPTS,
            ip_address=_safe_ip(context),
            created_at=now,
            expires_at=now + timedelta(seconds=self.settings.VERIFICATION_CODE_TTL_SECONDS),
        )
        self.repository.add_verification_code(record)

        try:
            self.email.send(self._compose(purpose, normalized_email, code))
        except EmailDeliveryError as exc:
            raise EmailDeliveryFailedError() from exc

        self.audit.append(
            action="AUTH_VERIFICATION_CODE_SENT",
            result="SUCCESS",
            actor_user_id=target_user.id if target_user is not None else None,
            target_user_id=target_user.id if target_user is not None else None,
            resource_id=record.code_uuid,
            context_ip_address=_safe_ip(context),
            context_user_agent=_safe_user_agent(context),
            metadata={"purpose": purpose.value},
        )

    def consume(
        self,
        *,
        purpose: VerificationPurpose,
        email: str,
        code: str,
        context: RequestContext,
    ) -> EmailVerificationCode:
        """Verify and burn a challenge, or raise. Never reveals which check failed.

        A failed attempt is committed on its own before raising. Callers roll the
        surrounding transaction back when the challenge fails, and an attempt
        counter that disappeared with that rollback would leave a live code open
        to unlimited guessing. Success stays uncommitted so the caller can burn
        the code in the same transaction as the account change it authorises.
        """
        normalized_email = email.strip().lower()
        now = self._now()

        self._check_verification_allowed(normalized_email, context, now=now)

        record = self.repository.lock_active_verification_code(
            email=normalized_email,
            purpose=purpose,
            now=now,
        )
        if record is None:
            self._reject_attempt(normalized_email, context, now=now)

        expected = self._digest(purpose=purpose, email=normalized_email, code=code.strip())
        if not hmac.compare_digest(record.code_hash, expected):
            record.attempt_count += 1
            if record.attempt_count >= record.max_attempts:
                record.status = VerificationCodeStatus.INVALIDATED
            self._reject_attempt(normalized_email, context, now=now)

        record.status = VerificationCodeStatus.CONSUMED
        record.consumed_at = now
        return record

    def _record_withheld_send(
        self,
        purpose: VerificationPurpose,
        email: str,
        context: RequestContext,
        *,
        now: datetime,
    ) -> None:
        """Note when a send was asked for and withheld, so the resend interval counts it.

        The interval is read from the newest code row for this address and purpose. This row
        is born INVALIDATED and its digest is of a random value nobody holds, so it can never
        be consumed; it exists only to carry the time. The cleanup job removes it once it
        expires, like any other code.
        """
        self.repository.add_verification_code(
            EmailVerificationCode(
                code_uuid=str(self.uuid_factory()),
                purpose=purpose,
                email=email,
                user_id=None,
                code_hash=self._digest(purpose=purpose, email=email, code=secrets.token_hex(32)),
                status=VerificationCodeStatus.INVALIDATED,
                attempt_count=0,
                max_attempts=self.settings.VERIFICATION_CODE_MAX_ATTEMPTS,
                ip_address=_safe_ip(context),
                created_at=now,
                expires_at=now + timedelta(seconds=self.settings.VERIFICATION_CODE_TTL_SECONDS),
            )
        )

    def _reject_attempt(
        self,
        email: str,
        context: RequestContext,
        *,
        now: datetime,
    ) -> NoReturn:
        self._record_check_failure(email, context, now=now)
        self.db.commit()
        raise VerificationCodeInvalidError()

    def _eligible_user(self, purpose: VerificationPurpose, user: User | None) -> User | None:
        if user is None:
            return None
        if purpose == VerificationPurpose.PASSWORD_RESET and not _is_resettable(user):
            return None
        return user

    def _compose(
        self,
        purpose: VerificationPurpose,
        email: str,
        code: str,
    ) -> OutboundEmail:
        minutes = max(1, self.settings.VERIFICATION_CODE_TTL_SECONDS // 60)
        intro = _PURPOSE_INTROS[purpose]
        text_body = (
            f"{intro}\n\n"
            f"Verification code: {code}\n\n"
            f"The code expires in {minutes} minutes and can be used once.\n"
            "If you did not request it, no action is required and you can ignore this email.\n"
        )
        html_body = (
            "<p>"
            f"{intro}"
            "</p>"
            f'<p style="font-size:24px;letter-spacing:4px;font-weight:700">{code}</p>'
            f"<p>The code expires in {minutes} minutes and can be used once.</p>"
            "<p>If you did not request it, no action is required and you can ignore "
            "this email.</p>"
        )
        return OutboundEmail(
            to_address=email,
            subject=_PURPOSE_SUBJECTS[purpose],
            text_body=text_body,
            html_body=html_body,
        )

    def _digest(self, *, purpose: VerificationPurpose, email: str, code: str) -> str:
        return hash_auth_throttle_key(
            self.settings.SECRET_KEY,
            f"verification:{purpose.value}:{email}",
            code,
        )

    def _enforce_resend_interval(
        self,
        email: str,
        purpose: VerificationPurpose,
        *,
        now: datetime,
    ) -> None:
        last_issued_at = self.repository.get_last_verification_code_issued_at(
            email=email,
            purpose=purpose,
        )
        if last_issued_at is None:
            return
        available_at = last_issued_at + timedelta(
            seconds=self.settings.VERIFICATION_RESEND_INTERVAL_SECONDS
        )
        if available_at > now:
            retry_after = max(1, math.ceil((available_at - now).total_seconds()))
            raise AuthenticationRateLimitedError(retry_after_seconds=retry_after)

    def _consume_send_allowance(
        self,
        email: str,
        context: RequestContext,
        *,
        now: datetime,
    ) -> None:
        buckets = self._buckets(
            email,
            context,
            email_scope=LoginThrottleScope.VERIFICATION_SEND_EMAIL,
            ip_scope=LoginThrottleScope.VERIFICATION_SEND_IP,
        )
        for scope, key_hash in buckets:
            limit = (
                self.settings.VERIFICATION_SEND_EMAIL_MAX_PER_WINDOW
                if scope == LoginThrottleScope.VERIFICATION_SEND_EMAIL
                else self.settings.VERIFICATION_SEND_IP_MAX_PER_WINDOW
            )
            throttle = self.repository.lock_or_create_throttle(scope, key_hash, now=now)
            self._reset_window_if_elapsed(throttle, now=now)
            if throttle.blocked_until is not None and throttle.blocked_until > now:
                retry_after = max(
                    1,
                    math.ceil((throttle.blocked_until - now).total_seconds()),
                )
                raise AuthenticationRateLimitedError(retry_after_seconds=retry_after)
            throttle.failed_count += 1
            if throttle.failed_count >= limit:
                throttle.blocked_until = now + timedelta(
                    seconds=self.settings.VERIFICATION_THROTTLE_BLOCK_SECONDS
                )
            throttle.updated_at = now

    def _check_verification_allowed(
        self,
        email: str,
        context: RequestContext,
        *,
        now: datetime,
    ) -> None:
        buckets = self._buckets(
            email,
            context,
            email_scope=LoginThrottleScope.VERIFICATION_CHECK_EMAIL,
            ip_scope=LoginThrottleScope.VERIFICATION_CHECK_IP,
        )
        retry_after = 0
        for scope, key_hash in buckets:
            throttle = self.repository.lock_or_create_throttle(scope, key_hash, now=now)
            self._reset_window_if_elapsed(throttle, now=now)
            if throttle.blocked_until is not None and throttle.blocked_until > now:
                retry_after = max(
                    retry_after,
                    math.ceil((throttle.blocked_until - now).total_seconds()),
                )
        if retry_after:
            raise AuthenticationRateLimitedError(retry_after_seconds=max(1, retry_after))

    def _record_check_failure(
        self,
        email: str,
        context: RequestContext,
        *,
        now: datetime,
    ) -> None:
        buckets = self._buckets(
            email,
            context,
            email_scope=LoginThrottleScope.VERIFICATION_CHECK_EMAIL,
            ip_scope=LoginThrottleScope.VERIFICATION_CHECK_IP,
        )
        for scope, key_hash in buckets:
            limit = (
                self.settings.VERIFICATION_CHECK_EMAIL_MAX_FAILURES
                if scope == LoginThrottleScope.VERIFICATION_CHECK_EMAIL
                else self.settings.VERIFICATION_CHECK_IP_MAX_FAILURES
            )
            throttle = self.repository.lock_or_create_throttle(scope, key_hash, now=now)
            self._reset_window_if_elapsed(throttle, now=now)
            throttle.failed_count += 1
            if throttle.failed_count >= limit and not (
                throttle.blocked_until is not None and throttle.blocked_until > now
            ):
                throttle.blocked_until = now + timedelta(
                    seconds=self.settings.VERIFICATION_THROTTLE_BLOCK_SECONDS
                )
            throttle.updated_at = now

    def _buckets(
        self,
        email: str,
        context: RequestContext,
        *,
        email_scope: LoginThrottleScope,
        ip_scope: LoginThrottleScope,
    ) -> tuple[tuple[LoginThrottleScope, str], ...]:
        buckets: list[tuple[LoginThrottleScope, str]] = [
            (
                email_scope,
                hash_auth_throttle_key(
                    self.settings.SECRET_KEY,
                    email_scope.value,
                    email.casefold(),
                ),
            )
        ]
        ip_address = _safe_ip(context)
        if ip_address:
            buckets.append(
                (
                    ip_scope,
                    hash_auth_throttle_key(
                        self.settings.SECRET_KEY,
                        ip_scope.value,
                        ip_address,
                    ),
                )
            )
        return tuple(sorted(buckets, key=lambda item: (item[0].value, item[1])))

    def _reset_window_if_elapsed(self, throttle: AuthLoginThrottle, *, now: datetime) -> None:
        window_elapsed = now - throttle.window_started_at >= timedelta(
            seconds=self.settings.VERIFICATION_THROTTLE_WINDOW_SECONDS
        )
        active_block = throttle.blocked_until is not None and throttle.blocked_until > now
        block_elapsed = throttle.blocked_until is not None and throttle.blocked_until <= now
        if block_elapsed or (window_elapsed and not active_block):
            throttle.failed_count = 0
            throttle.window_started_at = now
            throttle.blocked_until = None
            throttle.updated_at = now

    def _now(self) -> datetime:
        return to_second_resolution_utc(self.clock())


def _generate_numeric_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def _is_resettable(user: User) -> bool:
    return UserStatus(user.status) == UserStatus.ACTIVE


def _safe_ip(context: RequestContext) -> str | None:
    if context.ip_address is None:
        return None
    return context.ip_address[:45]


def _safe_user_agent(context: RequestContext) -> str | None:
    if context.user_agent is None:
        return None
    return context.user_agent[:512]
