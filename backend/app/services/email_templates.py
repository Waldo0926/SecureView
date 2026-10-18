"""Shared HTML shell for outbound mail.

Email is not the web. Layout is tables because Outlook still renders through Word; styles are
inline because Gmail strips most of a `<style>` block; there are no images because a blocked
remote image leaves a hole and a tracking pixel is not something this product should send.
Every colour is stated on the element that uses it, so a client that drops the head still
renders something deliberate.

The plain-text alternative is not a formality: some clients show it, some people prefer it,
and it is what a screen reader reaches first. Both bodies say the same thing.
"""

from __future__ import annotations

BRAND = "#006dc7"
INK = "#141414"
MUTED = "#5c5c5c"
BORDER = "#e4e4e4"
CANVAS = "#f4f6f8"
CALLOUT_BG = "#eef5fb"

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"


def _preheader(text: str) -> str:
    """The line the inbox shows next to the subject.

    Hidden in the body, then padded: without the trailing whitespace, clients pull in
    whatever markup follows and the preview reads as a fragment of the layout.
    """
    return (
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;'
        f'font-size:1px;line-height:1px;color:{CANVAS}">{text}'
        f"{'&nbsp;&zwnj;' * 60}</div>"
    )


def button(label: str, href: str) -> str:
    """A button that survives Outlook, which ignores padding on an anchor."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:28px auto 8px">'
        "<tr>"
        f'<td align="center" bgcolor="{BRAND}" style="border-radius:6px">'
        f'<a href="{href}" style="display:inline-block;padding:13px 30px;'
        f"font-family:{FONT};font-size:15px;font-weight:600;color:#ffffff;"
        f'text-decoration:none;border-radius:6px">{label}</a>'
        "</td>"
        "</tr>"
        "</table>"
    )


def callout(text: str) -> str:
    """For the one sentence the reader must not skim past."""
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:22px 0"><tr><td style="background:{CALLOUT_BG};'
        f"border-left:3px solid {BRAND};border-radius:0 6px 6px 0;padding:14px 18px;"
        f'font-family:{FONT};font-size:14px;line-height:22px;color:{INK}">{text}'
        "</td></tr></table>"
    )


def layout(*, preheader: str, heading: str, body_html: str) -> str:
    """Wrap composed content in the shell.

    `body_html` is assembled by the caller from the helpers above; nothing here escapes it,
    so callers must not interpolate user-controlled text without escaping it first.
    """
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        "</head>"
        f'<body style="margin:0;padding:0;background:{CANVAS}">'
        f"{_preheader(preheader)}"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{CANVAS};padding:28px 12px">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:560px;background:#ffffff;border:1px solid '
        f'{BORDER};border-radius:10px;overflow:hidden">'
        # Header
        "<tr>"
        f'<td style="padding:20px 32px;border-bottom:1px solid {BORDER}">'
        f'<span style="font-family:{FONT};font-size:17px;font-weight:700;'
        f'color:{BRAND};letter-spacing:-0.2px">SecureView</span>'
        "</td>"
        "</tr>"
        # Body
        "<tr>"
        '<td style="padding:30px 32px 34px">'
        f'<h1 style="margin:0 0 16px;font-family:{FONT};font-size:20px;'
        f'line-height:28px;font-weight:600;color:{INK}">{heading}</h1>'
        f"{body_html}"
        "</td>"
        "</tr>"
        # Footer
        "<tr>"
        f'<td style="padding:18px 32px;background:{CANVAS};border-top:1px solid {BORDER};'
        f'font-family:{FONT};font-size:12px;line-height:19px;color:{MUTED}">'
        "SecureView encrypts files in your browser. Neither your passphrase nor your "
        "file contents ever reach the server."
        "</td>"
        "</tr>"
        "</table>"
        "</td></tr></table>"
        "</body></html>"
    )


def paragraph(text: str) -> str:
    return (
        f'<p style="margin:0 0 14px;font-family:{FONT};font-size:15px;'
        f'line-height:24px;color:{INK}">{text}</p>'
    )


def muted_paragraph(text: str) -> str:
    return (
        f'<p style="margin:14px 0 0;font-family:{FONT};font-size:13px;'
        f'line-height:21px;color:{MUTED}">{text}</p>'
    )
