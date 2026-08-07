"""Provider-agnostic SMTP delivery for the weekly digest email.

Sends via Python's stdlib ``smtplib`` + ``email.message`` rather than a
vendor SDK or REST API — switching providers (Resend, Brevo, Amazon SES,
Mailtrap, ...) is then an ``SMTP_*`` env-var change, not a code change.
Both connection modes are supported: STARTTLS (the common ``587``
convention) and implicit TLS/SMTPS (the ``465`` convention) — see
:attr:`SmtpConfig.use_implicit_tls`.

A send failure — connection error, auth failure, or the server refusing
the message — always raises :class:`EmailDeliveryError`. It is never
swallowed here: silent non-delivery must be impossible to mistake for
success, and the caller (``deltadewa.reporting.weekly_report``) is what
turns that exception into a distinct, loud process exit code.

Credentials are never included in a log message or an exception's text —
only the caught exception's own message/type is used.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage as _MimeMessage

_IMPLICIT_TLS_PORT = 465
_CONNECT_TIMEOUT_SECONDS = 10


class EmailDeliveryError(Exception):
    """Raised when the SMTP relay did not confirm the send was accepted."""


@dataclass(frozen=True)
class EmailMessage:
    """A single HTML email, ready to send.

    Attributes:
        subject: The email subject line.
        html_body: The full HTML document to send as the message body.
        to_addr: Recipient email address.
        from_addr: Sender email address (must be a verified/allowed
            sender on the relay in use).

    """

    subject: str
    html_body: str
    to_addr: str
    from_addr: str


@dataclass(frozen=True)
class SmtpConfig:
    """SMTP relay connection and auth settings.

    Read from the environment by the caller (``SMTP_HOST``, ``SMTP_PORT``,
    ``SMTP_USERNAME``, ``SMTP_PASSWORD``) — never hardcoded.

    Attributes:
        host: SMTP relay hostname.
        port: SMTP relay port. ``465`` selects implicit TLS/SMTPS; any
            other port (typically ``587``) selects plaintext-connect-then-
            STARTTLS — see :attr:`use_implicit_tls`.
        username: SMTP auth username.
        password: SMTP auth password. Never logged.

    """

    host: str
    port: int
    username: str
    password: str

    @property
    def use_implicit_tls(self) -> bool:
        """Whether to connect via implicit TLS/SMTPS instead of STARTTLS."""
        return self.port == _IMPLICIT_TLS_PORT


def _build_mime_message(message: EmailMessage) -> _MimeMessage:
    mime_message = _MimeMessage()
    mime_message["Subject"] = message.subject
    mime_message["From"] = message.from_addr
    mime_message["To"] = message.to_addr
    mime_message.set_content(
        "This email requires an HTML-capable client to view.",
    )
    mime_message.add_alternative(message.html_body, subtype="html")
    return mime_message


def _connect(config: SmtpConfig) -> smtplib.SMTP:
    if config.use_implicit_tls:
        return smtplib.SMTP_SSL(
            config.host,
            config.port,
            timeout=_CONNECT_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
    client = smtplib.SMTP(
        config.host,
        config.port,
        timeout=_CONNECT_TIMEOUT_SECONDS,
    )
    client.starttls(context=ssl.create_default_context())
    return client


def send_email(
    message: EmailMessage,
    *,
    config: SmtpConfig,
    client: smtplib.SMTP | None = None,
) -> None:
    """Send *message* via SMTP. Raises on any failure to send.

    Args:
        message: The email to send.
        config: SMTP connection/auth settings.
        client: Optional already-connected ``smtplib.SMTP`` (or
            ``SMTP_SSL``) instance to use instead of opening a real
            connection — for testing. Defaults to connecting for real
            using *config*.

    Raises:
        EmailDeliveryError: The connection, STARTTLS negotiation, login,
            or send failed for any reason (network error, auth failure,
            or the relay rejecting the message).

    """
    mime_message = _build_mime_message(message)
    try:
        smtp_client = client if client is not None else _connect(config)
        with smtp_client as smtp:
            smtp.login(config.username, config.password)
            smtp.send_message(mime_message)
    except (smtplib.SMTPException, OSError) as exc:
        msg = f"SMTP send failed: {exc}"
        raise EmailDeliveryError(msg) from exc
