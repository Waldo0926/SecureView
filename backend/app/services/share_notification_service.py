from __future__ import annotations

import logging
import re
from collections.abc import Callable
from html import escape

from app.core.config import Settings
from app.services.email_service import EmailDeliveryError, EmailService, OutboundEmail
from app.services.email_templates import (
    button,
    callout,
    layout,
    muted_paragraph,
    paragraph,
)

logger = logging.getLogger(__name__)

_WHITESPACE_RUN = re.compile(r"\s+")


def _single_line(value: str) -> str:
    """Collapse anything that would break a header into ordinary spaces."""
    return _WHITESPACE_RUN.sub(" ", value).strip()


class ShareNotificationService:
    """Tell someone a file has been shared with them.

    Until this existed there was no notification of any kind: a recipient learned about a
    share only by opening the file list and noticing something new, which for a file shared
    once and never mentioned means never.

    **The filename is deliberately not in the message.** The platform's own threat model
    accepts that the server holds filenames, but an email leaves that boundary entirely --
    it sits in a third-party mailbox, gets indexed, and is forwarded. Saying who shared
    something is enough for the recipient to know to go and look; saying what it was called
    would move metadata somewhere the design never accounted for.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        email: EmailService | None = None,
        sent_today: Callable[[], int] | None = None,
    ) -> None:
        self.settings = settings
        self.email = email or EmailService(settings=settings)
        self.sent_today = sent_today

    def notify_shared(
        self, *, recipient_email: str, recipient_username: str, sender_username: str
    ) -> bool:
        """Best effort, by design.

        Called after the share has already committed. A share that succeeded must not be
        reported as failed because a mail server was unreachable, so delivery problems are
        logged and swallowed -- the file is shared either way, and the recipient will still
        find it in their list.
        """
        if not self.settings.SHARE_NOTIFICATION_EMAIL:
            return False

        # The provider's allowance is shared with verification codes, and those are the ones
        # that must get through: a code that fails to send blocks registration and password
        # reset outright, while a missed share notification costs the recipient a glance at
        # their file list. Stop well short of the ceiling rather than race for it.
        cap = self.settings.SHARE_NOTIFICATION_DAILY_CAP
        if self.sent_today is not None and cap >= 0:
            try:
                if self.sent_today() >= cap:
                    logger.info("Share notification skipped: daily cap of %s reached", cap)
                    return False
            except Exception:  # pragma: no cover - counting must never break a share
                logger.exception("Could not count today's share notifications")
                return False

        try:
            self.email.send(self._compose(recipient_email, recipient_username, sender_username))
            return True
        except EmailDeliveryError:
            logger.warning("Share notification could not be delivered", exc_info=False)
            return False
        except Exception:  # pragma: no cover - defensive: never fail a committed share
            logger.exception("Unexpected failure sending a share notification")
            return False

    def _compose(self, email: str, recipient: str, sender: str) -> OutboundEmail:
        where = self.settings.APP_PUBLIC_URL.rstrip("/")

        # Usernames are chosen by users and are interpolated into markup here. Escaping them
        # is not optional: without it a username is a way to put arbitrary HTML into a
        # message the platform sends on someone else's behalf.
        safe_sender = escape(sender)
        safe_recipient = escape(recipient)
        # A username has no character restriction beyond its length, so it can carry
        # newlines and control characters. Those have no business in a header line.
        subject_sender = _single_line(sender)

        link_line = f"\n\nOpen your files: {where}/files" if where else ""
        text_body = (
            f"Hello {recipient},\n\n"
            f"{sender} has shared an encrypted file with you on SecureView.\n\n"
            "You open it with your own encryption passphrase -- never the sender's. "
            'Look under "Shared with me" in your file list.'
            f"{link_line}\n\n"
            "If you were not expecting this, you can ignore it. Nothing has been added to "
            "your account that you have to act on.\n\n"
            "--\n"
            "SecureView encrypts files in your browser. Neither your passphrase nor your "
            "file contents ever reach the server.\n"
        )

        body = paragraph(f"Hello {safe_recipient},")
        body += paragraph(f"<strong>{safe_sender}</strong> has shared an encrypted file with you.")
        body += callout(
            "You open it with <strong>your own encryption passphrase</strong> &mdash; "
            "never the sender&rsquo;s."
        )
        if where:
            body += button("Open your files", f"{where}/files")
            body += muted_paragraph(
                "It is filed under &quot;Shared with me&quot;. If the button does not work, "
                f"go to {escape(where)}/files"
            )
        else:
            body += paragraph(
                "Sign in and look under &quot;Shared with me&quot; in your file list."
            )
        body += muted_paragraph(
            "If you were not expecting this, you can ignore it. Nothing has been added to "
            "your account that you have to act on."
        )

        return OutboundEmail(
            to_address=email,
            subject=f"{subject_sender} shared a file with you",
            text_body=text_body,
            html_body=layout(
                # Escaped: the preheader is markup like the rest of the document, and this
                # is the one place the sender's name appears before the body.
                preheader=f"{safe_sender} shared an encrypted file with you on SecureView.",
                heading="A file was shared with you",
                body_html=body,
            ),
        )
