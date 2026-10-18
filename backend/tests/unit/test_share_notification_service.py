from __future__ import annotations

from app.core.config import Settings
from app.services.email_service import EmailDeliveryError, OutboundEmail
from app.services.share_notification_service import ShareNotificationService


class FakeEmail:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.sent: list[OutboundEmail] = []
        self.fail = fail

    def send(self, message: OutboundEmail) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append(message)


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        APP_DEBUG=False,
        SECRET_KEY="test-secret-key-that-is-long-enough",
        **overrides,
    )


def _notify(service: ShareNotificationService) -> bool:
    return service.notify_shared(
        recipient_email="admin@secureview.tech",
        recipient_username="admin",
        sender_username="waldo",
    )


def test_sends_nothing_unless_the_deployment_asked_for_it() -> None:
    # Off by default, so a deployment without working mail does not queue messages nobody
    # receives.
    email = FakeEmail()
    service = ShareNotificationService(settings=_settings(), email=email)

    assert _notify(service) is False
    assert email.sent == []


def test_names_the_sender_so_the_recipient_knows_who_to_expect() -> None:
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True), email=email
    )

    assert _notify(service) is True
    message = email.sent[0]
    assert message.to_address == "admin@secureview.tech"
    assert "waldo" in message.subject
    assert "waldo" in message.text_body


def test_tells_the_recipient_they_use_their_own_passphrase() -> None:
    # The single most confusing thing about this product for a first-time recipient.
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True), email=email
    )

    _notify(service)

    assert "your own encryption passphrase" in email.sent[0].text_body


def test_does_not_put_the_filename_in_the_email() -> None:
    # An email leaves the system's boundary entirely: third-party mailbox, indexed,
    # forwarded. Naming the sender is enough to prompt the recipient to look.
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True), email=email
    )

    _notify(service)

    body = email.sent[0].text_body + (email.sent[0].html_body or "")
    assert "pdf" not in body.lower()
    assert "filename" not in body.lower()


def test_links_to_the_site_when_one_is_configured() -> None:
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(
            SHARE_NOTIFICATION_EMAIL=True, APP_PUBLIC_URL="https://secureview.tech/"
        ),
        email=email,
    )

    _notify(service)

    # The trailing slash must not produce a doubled one.
    assert "https://secureview.tech/files" in email.sent[0].text_body


def test_says_nothing_about_a_link_when_none_is_configured() -> None:
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True), email=email
    )

    _notify(service)

    assert "http" not in email.sent[0].text_body


def test_a_delivery_failure_is_swallowed() -> None:
    # The share has already committed by the time this runs. A mail server being down must
    # not turn a successful share into a reported failure.
    email = FakeEmail(fail=EmailDeliveryError("smtp unreachable"))
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True), email=email
    )

    assert _notify(service) is False


def test_an_unexpected_error_is_swallowed_too() -> None:
    email = FakeEmail(fail=RuntimeError("something else entirely"))
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True), email=email
    )

    assert _notify(service) is False


def test_stops_sending_once_the_daily_cap_is_reached() -> None:
    # Verification codes share this allowance and are the ones that must get through: a code
    # that cannot be sent blocks registration and password reset outright, while a missed
    # share notification costs the recipient one glance at their file list.
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True, SHARE_NOTIFICATION_DAILY_CAP=3),
        email=email,
        sent_today=lambda: 3,
    )

    assert _notify(service) is False
    assert email.sent == []


def test_sends_while_under_the_cap() -> None:
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True, SHARE_NOTIFICATION_DAILY_CAP=3),
        email=email,
        sent_today=lambda: 2,
    )

    assert _notify(service) is True
    assert len(email.sent) == 1


def test_a_cap_of_zero_disables_notifications_entirely() -> None:
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True, SHARE_NOTIFICATION_DAILY_CAP=0),
        email=email,
        sent_today=lambda: 0,
    )

    assert _notify(service) is False


def test_a_failure_to_count_skips_the_email_rather_than_guessing() -> None:
    # If the count cannot be established, the safe direction is not to send: the thing being
    # protected is the delivery of verification codes.
    def explode() -> int:
        raise RuntimeError("database unavailable")

    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True),
        email=email,
        sent_today=explode,
    )

    assert _notify(service) is False
    assert email.sent == []


def test_escapes_a_username_rather_than_letting_it_become_markup() -> None:
    # Usernames are chosen by users and land in a message the platform sends on someone
    # else's behalf. Unescaped, a username is a way to put arbitrary HTML in that message.
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True), email=email
    )

    service.notify_shared(
        recipient_email="admin@secureview.tech",
        recipient_username="admin",
        sender_username="<img src=x onerror=alert(1)>",
    )

    html = email.sent[0].html_body or ""
    assert "<img" not in html
    assert "&lt;img" in html


def test_the_html_is_a_complete_document_with_a_preheader() -> None:
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True, APP_PUBLIC_URL="https://secureview.tech"),
        email=email,
    )

    _notify(service)
    html = email.sent[0].html_body or ""

    assert html.startswith("<!doctype html>")
    # The inbox preview line, and the button target.
    assert "shared an encrypted file with you on SecureView." in html
    assert 'href="https://secureview.tech/files"' in html
    # Layout is tables and inline styles; a <style> block would be stripped by Gmail.
    assert "<style" not in html


def test_the_plain_text_alternative_says_the_same_thing() -> None:
    # Some clients show it, some people prefer it, and a screen reader reaches it first.
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True, APP_PUBLIC_URL="https://secureview.tech"),
        email=email,
    )

    _notify(service)
    text = email.sent[0].text_body

    assert "waldo" in text
    assert "your own encryption passphrase" in text
    assert "https://secureview.tech/files" in text
    assert "<" not in text


def test_a_username_cannot_break_the_subject_line() -> None:
    # Usernames are only length-constrained, so newlines are reachable. They have no
    # business in a header.
    email = FakeEmail()
    service = ShareNotificationService(
        settings=_settings(SHARE_NOTIFICATION_EMAIL=True), email=email
    )

    service.notify_shared(
        recipient_email="admin@secureview.tech",
        recipient_username="admin",
        sender_username="waldo\r\nBcc: someone@elsewhere.test",
    )

    subject = email.sent[0].subject
    assert "\n" not in subject
    assert "\r" not in subject
