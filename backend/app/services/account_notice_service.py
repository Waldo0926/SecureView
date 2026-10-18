from __future__ import annotations

import logging
from html import escape

from app.core.config import Settings
from app.services.email_service import EmailDeliveryError, EmailService, OutboundEmail
from app.services.email_templates import button, callout, layout, muted_paragraph, paragraph

logger = logging.getLogger(__name__)


class AccountNoticeService:
    """Tell an account holder that an administrator changed their login password.

    The message never carries the new password. The administrator hands that over in person or
    through a channel they trust; the email exists so that a reset the holder did not ask for is
    noticed, the same reason banks mail you when your password changes.
    """

    def __init__(self, *, settings: Settings, email: EmailService | None = None) -> None:
        self.settings = settings
        self.email = email or EmailService(settings=settings)

    def notify_admin_password_reset(self, *, email: str, username: str) -> bool:
        """Best effort: called after the reset has committed, so a mail failure is logged only."""
        try:
            self.email.send(self._compose(email, username))
            return True
        except EmailDeliveryError:
            logger.warning("Password reset notice could not be delivered", exc_info=False)
            return False
        except Exception:  # pragma: no cover - defensive: never fail a committed reset
            logger.exception("Unexpected failure sending a password reset notice")
            return False

    def _compose(self, email: str, username: str) -> OutboundEmail:
        where = self.settings.APP_PUBLIC_URL.rstrip("/")
        safe_username = escape(username)
        settings_line = f"\n\nChange it here after you sign in: {where}/settings" if where else ""
        text_body = (
            f"Hello {username},\n\n"
            "An administrator has reset the password you use to sign in to SecureView. "
            "Every device that was signed in has been signed out.\n\n"
            "Your encrypted files are not affected: they open with your encryption passphrase, "
            "which the administrator cannot see or change.\n\n"
            "Ask the administrator for the temporary password, sign in with it, and choose a new "
            f"one in Settings.{settings_line}\n\n"
            "If you did not ask for this, contact the SecureView team.\n"
        )
        body = paragraph(f"Hello {safe_username},")
        body += paragraph(
            "An administrator has reset the password you use to sign in to SecureView. "
            "Every device that was signed in has been signed out."
        )
        body += callout(
            "Your encrypted files are not affected: they open with your "
            "<strong>encryption passphrase</strong>, which the administrator cannot see or change."
        )
        body += paragraph(
            "Ask the administrator for the temporary password, sign in with it, and choose a "
            "new one in Settings."
        )
        if where:
            body += button("Open Settings", f"{where}/settings")
        body += muted_paragraph("If you did not ask for this, contact the SecureView team.")
        return OutboundEmail(
            to_address=email,
            subject="Your SecureView login password was reset",
            text_body=text_body,
            html_body=layout(
                preheader="An administrator reset your SecureView login password.",
                heading="Your login password was reset",
                body_html=body,
            ),
        )
