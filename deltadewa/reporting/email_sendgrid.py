"""SendGrid delivery for the weekly digest email.

Calls SendGrid's `v3 Mail Send
<https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send>`_
REST endpoint directly via ``requests`` (already a project dependency)
rather than adding the ``sendgrid`` SDK as a new one — the whole
integration is one POST.

A send failure — network error, or any non-2xx response — always raises
:class:`EmailDeliveryError`. It is never swallowed here: silent
non-delivery must be impossible to mistake for success, and the caller
(``deltadewa.reporting.weekly_report``) is what turns that exception into
a distinct, loud process exit code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"
_REQUEST_TIMEOUT_SECONDS = 10


class EmailDeliveryError(Exception):
    """Raised when SendGrid did not confirm the send was accepted."""


@dataclass(frozen=True)
class EmailMessage:
    """A single HTML email, ready to send.

    Attributes:
        subject: The email subject line.
        html_body: The full HTML document to send as the message body.
        to_addr: Recipient email address.
        from_addr: Verified sender email address (SendGrid requires the
            sending domain/address be verified on the account).

    """

    subject: str
    html_body: str
    to_addr: str
    from_addr: str


def _payload(message: EmailMessage) -> dict[str, Any]:
    return {
        "personalizations": [{"to": [{"email": message.to_addr}]}],
        "from": {"email": message.from_addr},
        "subject": message.subject,
        "content": [{"type": "text/html", "value": message.html_body}],
    }


def send_email(
    message: EmailMessage,
    *,
    api_key: str,
    session: requests.Session | None = None,
) -> None:
    """Send *message* via SendGrid. Raises on any failure to send.

    Args:
        message: The email to send.
        api_key: SendGrid API key (``SENDGRID_API_KEY`` — never
            hardcoded; the caller reads it from the environment).
        session: Optional ``requests.Session`` to use (for testing).
            Defaults to a new ``Session``.

    Raises:
        EmailDeliveryError: The request failed outright (network error),
            or SendGrid responded with anything other than its documented
            success status (``202 Accepted``).

    """
    session = session or requests.Session()
    try:
        response = session.post(
            _SENDGRID_API_URL,
            json=_payload(message),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        msg = f"SendGrid request failed: {exc}"
        raise EmailDeliveryError(msg) from exc

    if response.status_code != requests.codes.accepted:
        msg = (
            f"SendGrid rejected the send: {response.status_code} "
            f"{response.text}"
        )
        raise EmailDeliveryError(msg)
