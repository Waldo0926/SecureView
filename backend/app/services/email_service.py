from __future__ import annotations

import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage

from app.core.config import Settings

logger = logging.getLogger(__name__)

_USER_AGENT = "SecureView/1.0 (+https://secureview.tech)"


class EmailDeliveryError(Exception):
    """Outbound mail could not be handed to the configured provider."""


@dataclass(frozen=True, slots=True)
class OutboundEmail:
    to_address: str
    subject: str
    text_body: str
    html_body: str | None = None


class EmailService:
    """Sends transactional mail through Resend, SMTP, or a development log.

    Message bodies are treated as secrets in logs: only the provider, subject,
    and a redacted recipient are recorded, never the verification code.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, message: OutboundEmail) -> None:
        provider = self.settings.EMAIL_PROVIDER
        if provider == "console":
            self._send_console(message)
            return
        if provider == "resend":
            self._send_resend(message)
            return
        if provider == "smtp":
            self._send_smtp(message)
            return
        raise EmailDeliveryError(f"Unsupported email provider: {provider}")

    def _send_console(self, message: OutboundEmail) -> None:
        # Development-only. The body is printed so a developer without a mail
        # provider can complete the flow; production settings reject this mode.
        logger.warning(
            "Email delivery is disabled (EMAIL_PROVIDER=console). "
            "Message for %s with subject %r:\n%s",
            message.to_address,
            message.subject,
            message.text_body,
        )

    def _send_resend(self, message: OutboundEmail) -> None:
        payload: dict[str, object] = {
            "from": self._from_header(),
            "to": [message.to_address],
            "subject": message.subject,
            "text": message.text_body,
        }
        if message.html_body is not None:
            payload["html"] = message.html_body
        if self.settings.EMAIL_REPLY_TO:
            payload["reply_to"] = self.settings.EMAIL_REPLY_TO

        request = urllib.request.Request(
            self.settings.RESEND_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
                # urllib defaults to "Python-urllib/<version>", which Resend's
                # edge rejects with 403 before the request reaches the API.
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.EMAIL_TIMEOUT_SECONDS,
                context=ssl.create_default_context(),
            ) as response:
                if response.status >= 300:
                    raise EmailDeliveryError(f"Resend returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            # The body can echo the recipient, so log only the provider's error
            # name. Without it a 403 is indistinguishable from a bad key.
            logger.error(
                "Resend rejected a message with HTTP %s (%s)",
                exc.code,
                _resend_error_name(exc),
            )
            raise EmailDeliveryError(f"Resend returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.error("Resend delivery failed: %s", type(exc).__name__)
            raise EmailDeliveryError("The email provider is unreachable") from exc

    def _send_smtp(self, message: OutboundEmail) -> None:
        email_message = EmailMessage()
        email_message["Subject"] = message.subject
        email_message["From"] = self._from_header()
        email_message["To"] = message.to_address
        if self.settings.EMAIL_REPLY_TO:
            email_message["Reply-To"] = self.settings.EMAIL_REPLY_TO
        email_message.set_content(message.text_body)
        if message.html_body is not None:
            email_message.add_alternative(message.html_body, subtype="html")

        host = self.settings.SMTP_HOST
        port = self.settings.SMTP_PORT
        timeout = self.settings.EMAIL_TIMEOUT_SECONDS
        try:
            if self.settings.SMTP_USE_SSL:
                with smtplib.SMTP_SSL(
                    host,
                    port,
                    timeout=timeout,
                    context=ssl.create_default_context(),
                ) as client:
                    self._smtp_authenticate_and_send(client, email_message)
                return
            with smtplib.SMTP(host, port, timeout=timeout) as client:
                if self.settings.SMTP_USE_TLS:
                    client.starttls(context=ssl.create_default_context())
                self._smtp_authenticate_and_send(client, email_message)
        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            logger.error("SMTP delivery failed: %s", type(exc).__name__)
            raise EmailDeliveryError("The email provider is unreachable") from exc

    def _smtp_authenticate_and_send(
        self,
        client: smtplib.SMTP,
        email_message: EmailMessage,
    ) -> None:
        if self.settings.SMTP_USERNAME:
            client.login(self.settings.SMTP_USERNAME, self.settings.SMTP_PASSWORD)
        client.send_message(email_message)

    def _from_header(self) -> str:
        address = self.settings.EMAIL_FROM_ADDRESS
        display_name = self.settings.EMAIL_FROM_NAME.strip()
        if not display_name:
            return address
        local_part, _, domain = address.partition("@")
        return str(Address(display_name, local_part, domain))


def _resend_error_name(exc: urllib.error.HTTPError) -> str:
    """Return only the provider's error identifier, never the response body."""
    try:
        body = json.loads(exc.read().decode("utf-8", errors="replace"))
    except (ValueError, OSError):
        return "unparseable_error_body"
    name = body.get("name") if isinstance(body, dict) else None
    return str(name) if name else "unnamed_error"
