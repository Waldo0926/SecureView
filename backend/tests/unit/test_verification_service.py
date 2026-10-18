from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.config import Settings
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
from app.models.email_verification_code import EmailVerificationCode
from app.services.email_service import EmailDeliveryError, OutboundEmail
from app.services.verification_service import VerificationService

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
NOW_DB = NOW.replace(tzinfo=None)
CODE_UUID = UUID("44444444-4444-4444-8444-444444444444")
CONTEXT = RequestContext(ip_address="203.0.113.10", user_agent="verification-test")


class FakeEmailService:
    def __init__(self) -> None:
        self.sent: list[OutboundEmail] = []
        self.error: Exception | None = None

    def send(self, message: OutboundEmail) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(message)


class FakeAuditService:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def append(self, **values: object) -> None:
        self.events.append(values)


@dataclass
class FakeVerificationRepository:
    users: dict[str, SimpleNamespace] = field(default_factory=dict)
    added_codes: list[EmailVerificationCode] = field(default_factory=list)
    active_code: EmailVerificationCode | None = None
    last_issued_at: datetime | None = None
    invalidated: list[tuple[str, VerificationPurpose]] = field(default_factory=list)
    throttles: dict[tuple[LoginThrottleScope, str], SimpleNamespace] = field(default_factory=dict)

    def get_user_by_email(self, email: str) -> SimpleNamespace | None:
        return self.users.get(email)

    def add_verification_code(self, code: EmailVerificationCode) -> None:
        self.added_codes.append(code)

    def get_last_verification_code_issued_at(
        self,
        *,
        email: str,
        purpose: VerificationPurpose,
    ) -> datetime | None:
        # Like the real query: the newest row for this address and purpose, whatever its status.
        issued = [
            code.created_at
            for code in self.added_codes
            if code.email == email and code.purpose == purpose
        ]
        if self.last_issued_at is not None:
            issued.append(self.last_issued_at)
        return max(issued, default=None)

    def invalidate_pending_verification_codes(
        self,
        *,
        email: str,
        purpose: VerificationPurpose,
    ) -> int:
        self.invalidated.append((email, purpose))
        return 0

    def lock_active_verification_code(
        self,
        *,
        email: str,
        purpose: VerificationPurpose,
        now: datetime,
    ) -> EmailVerificationCode | None:
        return self.active_code

    def lock_or_create_throttle(
        self,
        scope: LoginThrottleScope,
        key_hash: str,
        *,
        now: datetime,
    ) -> SimpleNamespace:
        key = (scope, key_hash)
        if key not in self.throttles:
            self.throttles[key] = SimpleNamespace(
                failed_count=0,
                window_started_at=now,
                blocked_until=None,
                updated_at=now,
            )
        return self.throttles[key]


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        APP_DEBUG=False,
        SECRET_KEY="test-secret-key-that-is-long-enough",
    )


@dataclass
class Harness:
    service: VerificationService
    repository: FakeVerificationRepository
    email: FakeEmailService
    audit: FakeAuditService


def _harness(*, code: str = "123456") -> Harness:
    repository = FakeVerificationRepository()
    email = FakeEmailService()
    audit = FakeAuditService()
    service = VerificationService(
        db=FakeDb(),  # type: ignore[arg-type]
        settings=_settings(),
        repository=repository,  # type: ignore[arg-type]
        audit_service=audit,  # type: ignore[arg-type]
        email_service=email,  # type: ignore[arg-type]
        clock=lambda: NOW,
        code_factory=lambda _length: code,
        uuid_factory=lambda: CODE_UUID,
    )
    return Harness(service, repository, email, audit)


def _active_user(email: str = "alice@example.com") -> SimpleNamespace:
    return SimpleNamespace(id=7, email=email, status=UserStatus.ACTIVE)


def _stored_code(
    harness: Harness,
    *,
    purpose: VerificationPurpose,
    email: str,
    code: str,
    max_attempts: int = 5,
) -> EmailVerificationCode:
    digest = harness.service._digest(purpose=purpose, email=email, code=code)
    return EmailVerificationCode(
        id=1,
        code_uuid=str(CODE_UUID),
        purpose=purpose,
        email=email,
        user_id=7,
        code_hash=digest,
        status=VerificationCodeStatus.PENDING,
        attempt_count=0,
        max_attempts=max_attempts,
        created_at=NOW_DB,
        expires_at=NOW_DB + timedelta(minutes=10),
    )


def _assert_only_a_dead_time_marker(harness: Harness) -> None:
    # A withheld send leaves one row so the resend interval can count it, but that row can
    # never be consumed: it is born INVALIDATED and belongs to no account.
    (marker,) = harness.repository.added_codes
    assert marker.status == VerificationCodeStatus.INVALIDATED
    assert marker.user_id is None
    assert marker.created_at == NOW_DB
    assert harness.repository.invalidated == []
    assert harness.audit.events == []


def test_registration_issue_sends_code_and_stores_only_a_digest() -> None:
    harness = _harness(code="654321")

    harness.service.issue(
        purpose=VerificationPurpose.REGISTRATION,
        email="  New@Example.COM ",
        context=CONTEXT,
    )

    assert len(harness.email.sent) == 1
    message = harness.email.sent[0]
    assert message.to_address == "new@example.com"
    assert "654321" in message.text_body

    stored = harness.repository.added_codes[0]
    assert stored.email == "new@example.com"
    assert stored.purpose == VerificationPurpose.REGISTRATION
    assert stored.status == VerificationCodeStatus.PENDING
    assert stored.user_id is None
    assert stored.expires_at == NOW_DB + timedelta(minutes=10)
    # The plaintext code must never reach the row.
    assert "654321" not in repr(vars(stored))
    assert stored.code_hash != "654321"
    assert len(stored.code_hash) == 64
    assert harness.audit.events[-1]["action"] == "AUTH_VERIFICATION_CODE_SENT"


def test_registration_issue_is_silent_for_an_address_that_already_exists() -> None:
    harness = _harness()
    harness.repository.users["taken@example.com"] = _active_user("taken@example.com")

    harness.service.issue(
        purpose=VerificationPurpose.REGISTRATION,
        email="taken@example.com",
        context=CONTEXT,
    )

    # No mail and no usable code, but the send throttle was still consumed so probing
    # an existing address costs the same as probing a new one.
    assert harness.email.sent == []
    _assert_only_a_dead_time_marker(harness)
    assert any(
        scope == LoginThrottleScope.VERIFICATION_SEND_EMAIL
        for scope, _ in harness.repository.throttles
    )


def test_password_reset_issue_is_silent_for_an_unknown_address() -> None:
    harness = _harness()

    harness.service.issue(
        purpose=VerificationPurpose.PASSWORD_RESET,
        email="nobody@example.com",
        context=CONTEXT,
    )

    assert harness.email.sent == []
    _assert_only_a_dead_time_marker(harness)


def test_password_reset_issue_binds_the_code_to_the_account() -> None:
    harness = _harness()
    harness.repository.users["alice@example.com"] = _active_user()

    harness.service.issue(
        purpose=VerificationPurpose.PASSWORD_RESET,
        email="alice@example.com",
        context=CONTEXT,
    )

    stored = harness.repository.added_codes[0]
    assert stored.user_id == 7
    assert stored.purpose == VerificationPurpose.PASSWORD_RESET
    assert harness.repository.invalidated == [
        ("alice@example.com", VerificationPurpose.PASSWORD_RESET)
    ]


def test_issue_rejects_a_resend_inside_the_cooldown() -> None:
    harness = _harness()
    harness.repository.users["alice@example.com"] = _active_user()
    harness.repository.last_issued_at = NOW_DB - timedelta(seconds=10)

    with pytest.raises(AuthenticationRateLimitedError) as excinfo:
        harness.service.issue(
            purpose=VerificationPurpose.PASSWORD_RESET,
            email="alice@example.com",
            context=CONTEXT,
        )

    assert excinfo.value.headers["Retry-After"] == "50"
    assert harness.email.sent == []


@pytest.mark.parametrize(
    "purpose", [VerificationPurpose.REGISTRATION, VerificationPurpose.PASSWORD_RESET]
)
def test_a_quick_second_send_answers_the_same_whether_or_not_the_address_has_an_account(
    purpose: VerificationPurpose,
) -> None:
    # Registration sends to new addresses and reset sends to known ones, so if only the
    # sending path waited out the interval, a 200 or a 429 on the second try would say
    # which kind of address it was.
    outcomes = []
    for registered in (True, False):
        harness = _harness()
        if registered:
            harness.repository.users["alice@example.com"] = _active_user()

        harness.service.issue(purpose=purpose, email="alice@example.com", context=CONTEXT)
        with pytest.raises(AuthenticationRateLimitedError) as excinfo:
            harness.service.issue(purpose=purpose, email="alice@example.com", context=CONTEXT)

        outcomes.append(excinfo.value.headers["Retry-After"])

    assert outcomes == ["60", "60"]


def test_issue_blocks_after_the_per_email_send_limit() -> None:
    harness = _harness()
    settings = harness.service.settings

    for _ in range(settings.VERIFICATION_SEND_EMAIL_MAX_PER_WINDOW):
        # Forget the previous send so only the per-window limit is being exercised.
        harness.repository.added_codes.clear()
        harness.service.issue(
            purpose=VerificationPurpose.REGISTRATION,
            email="new@example.com",
            context=CONTEXT,
        )

    with pytest.raises(AuthenticationRateLimitedError):
        harness.service.issue(
            purpose=VerificationPurpose.REGISTRATION,
            email="new@example.com",
            context=CONTEXT,
        )


def test_issue_reports_delivery_failure_without_leaving_a_usable_code() -> None:
    harness = _harness()
    harness.email.error = EmailDeliveryError("provider down")

    with pytest.raises(EmailDeliveryFailedError):
        harness.service.issue(
            purpose=VerificationPurpose.REGISTRATION,
            email="new@example.com",
            context=CONTEXT,
        )

    # The row was staged but the caller rolls the transaction back, and no
    # success audit event was written.
    assert harness.audit.events == []


def test_consume_burns_a_matching_code() -> None:
    harness = _harness()
    harness.repository.active_code = _stored_code(
        harness,
        purpose=VerificationPurpose.REGISTRATION,
        email="alice@example.com",
        code="123456",
    )

    record = harness.service.consume(
        purpose=VerificationPurpose.REGISTRATION,
        email="Alice@Example.com",
        code=" 123456 ",
        context=CONTEXT,
    )

    assert record.status == VerificationCodeStatus.CONSUMED
    assert record.consumed_at == NOW_DB


def test_consume_counts_a_wrong_code_and_invalidates_after_the_attempt_limit() -> None:
    harness = _harness()
    stored = _stored_code(
        harness,
        purpose=VerificationPurpose.REGISTRATION,
        email="alice@example.com",
        code="123456",
        max_attempts=2,
    )
    harness.repository.active_code = stored

    with pytest.raises(VerificationCodeInvalidError):
        harness.service.consume(
            purpose=VerificationPurpose.REGISTRATION,
            email="alice@example.com",
            code="000000",
            context=CONTEXT,
        )
    assert stored.attempt_count == 1
    assert stored.status == VerificationCodeStatus.PENDING

    with pytest.raises(VerificationCodeInvalidError):
        harness.service.consume(
            purpose=VerificationPurpose.REGISTRATION,
            email="alice@example.com",
            code="000000",
            context=CONTEXT,
        )
    assert stored.attempt_count == 2
    assert stored.status == VerificationCodeStatus.INVALIDATED


def test_consume_rejects_a_code_issued_for_a_different_purpose() -> None:
    harness = _harness()
    harness.repository.active_code = _stored_code(
        harness,
        purpose=VerificationPurpose.REGISTRATION,
        email="alice@example.com",
        code="123456",
    )

    with pytest.raises(VerificationCodeInvalidError):
        harness.service.consume(
            purpose=VerificationPurpose.PASSWORD_RESET,
            email="alice@example.com",
            code="123456",
            context=CONTEXT,
        )


def test_consume_without_an_active_code_fails_and_records_an_attempt() -> None:
    harness = _harness()

    with pytest.raises(VerificationCodeInvalidError):
        harness.service.consume(
            purpose=VerificationPurpose.REGISTRATION,
            email="alice@example.com",
            code="123456",
            context=CONTEXT,
        )

    check_buckets = {
        scope
        for scope, _ in harness.repository.throttles
        if scope
        in {
            LoginThrottleScope.VERIFICATION_CHECK_EMAIL,
            LoginThrottleScope.VERIFICATION_CHECK_IP,
        }
    }
    assert check_buckets == {
        LoginThrottleScope.VERIFICATION_CHECK_EMAIL,
        LoginThrottleScope.VERIFICATION_CHECK_IP,
    }


def test_consume_blocks_after_repeated_wrong_codes() -> None:
    harness = _harness()
    settings = harness.service.settings

    for _ in range(settings.VERIFICATION_CHECK_EMAIL_MAX_FAILURES):
        harness.repository.active_code = _stored_code(
            harness,
            purpose=VerificationPurpose.REGISTRATION,
            email="alice@example.com",
            code="123456",
        )
        with pytest.raises(VerificationCodeInvalidError):
            harness.service.consume(
                purpose=VerificationPurpose.REGISTRATION,
                email="alice@example.com",
                code="000000",
                context=CONTEXT,
            )

    harness.repository.active_code = _stored_code(
        harness,
        purpose=VerificationPurpose.REGISTRATION,
        email="alice@example.com",
        code="123456",
    )
    with pytest.raises(AuthenticationRateLimitedError):
        harness.service.consume(
            purpose=VerificationPurpose.REGISTRATION,
            email="alice@example.com",
            code="123456",
            context=CONTEXT,
        )


def test_a_rejected_attempt_is_committed_so_a_caller_rollback_cannot_undo_it() -> None:
    """A discarded attempt counter would leave a live code open to unlimited guessing."""
    harness = _harness()
    stored = _stored_code(
        harness,
        purpose=VerificationPurpose.REGISTRATION,
        email="alice@example.com",
        code="123456",
    )
    harness.repository.active_code = stored
    db = harness.service.db

    with pytest.raises(VerificationCodeInvalidError):
        harness.service.consume(
            purpose=VerificationPurpose.REGISTRATION,
            email="alice@example.com",
            code="000000",
            context=CONTEXT,
        )

    assert stored.attempt_count == 1
    assert db.commits == 1
    assert db.rollbacks == 0


def test_a_successful_consume_leaves_the_transaction_to_the_caller() -> None:
    harness = _harness()
    harness.repository.active_code = _stored_code(
        harness,
        purpose=VerificationPurpose.REGISTRATION,
        email="alice@example.com",
        code="123456",
    )

    harness.service.consume(
        purpose=VerificationPurpose.REGISTRATION,
        email="alice@example.com",
        code="123456",
        context=CONTEXT,
    )

    # Burning the code must land in the same transaction as the account change.
    assert harness.service.db.commits == 0
