"""Tests for deltadewa.reporting.email_smtp."""

from __future__ import annotations

import logging
import smtplib
from unittest.mock import MagicMock

import pytest

from deltadewa.reporting.email_smtp import (
    EmailDeliveryError,
    EmailMessage,
    SmtpConfig,
    send_email,
)

_MESSAGE = EmailMessage(
    subject="Weekly Hedge Digest — NO ACTION (2026-08-05)",
    html_body="<h1>Digest</h1>",
    to_addr="ic@example.com",
    from_addr="hedge-program@example.com",
)

_FAKE_PASSWORD = "test-smtp-password"  # ruff: ignore[hardcoded-password-string] -- placeholder, no relay

_STARTTLS_CONFIG = SmtpConfig(
    host="smtp.example.com",
    port=587,
    username="hedge-program@example.com",
    password=_FAKE_PASSWORD,
)

_IMPLICIT_TLS_CONFIG = SmtpConfig(
    host="smtp.example.com",
    port=465,
    username="hedge-program@example.com",
    password=_FAKE_PASSWORD,
)


def _client() -> MagicMock:
    client = MagicMock(spec=smtplib.SMTP)
    client.__enter__.return_value = client
    return client


class TestSmtpConfig:
    """`use_implicit_tls` is derived from the port, not a separate flag."""

    def test_port_465_selects_implicit_tls(self) -> None:
        assert _IMPLICIT_TLS_CONFIG.use_implicit_tls is True

    def test_port_587_selects_starttls(self) -> None:
        assert _STARTTLS_CONFIG.use_implicit_tls is False


class TestSendEmailSuccess:
    """A send that raises nothing is the only confirmed-success path."""

    def test_sends_without_raising(self) -> None:
        client = _client()

        send_email(_MESSAGE, config=_STARTTLS_CONFIG, client=client)

        client.login.assert_called_once_with(
            _STARTTLS_CONFIG.username,
            _STARTTLS_CONFIG.password,
        )
        client.send_message.assert_called_once()

    def test_message_is_well_formed(self) -> None:
        client = _client()

        send_email(_MESSAGE, config=_STARTTLS_CONFIG, client=client)

        (mime_message,), _ = client.send_message.call_args
        assert mime_message["Subject"] == _MESSAGE.subject
        assert mime_message["From"] == _MESSAGE.from_addr
        assert mime_message["To"] == _MESSAGE.to_addr

        html_part = mime_message.get_body(("html",))
        assert html_part is not None
        assert html_part.get_content().strip() == _MESSAGE.html_body

    def test_implicit_tls_config_also_sends(self) -> None:
        client = _client()

        send_email(_MESSAGE, config=_IMPLICIT_TLS_CONFIG, client=client)

        client.login.assert_called_once_with(
            _IMPLICIT_TLS_CONFIG.username,
            _IMPLICIT_TLS_CONFIG.password,
        )
        client.send_message.assert_called_once()


class TestSendEmailFailure:
    """Any SMTP or connection-level failure raises EmailDeliveryError."""

    def test_login_failure_raises(self) -> None:
        client = _client()
        client.login.side_effect = smtplib.SMTPAuthenticationError(
            535,
            b"bad credentials",
        )

        with pytest.raises(EmailDeliveryError, match="bad credentials"):
            send_email(_MESSAGE, config=_STARTTLS_CONFIG, client=client)

    def test_send_rejection_raises(self) -> None:
        client = _client()
        client.send_message.side_effect = smtplib.SMTPRecipientsRefused(
            {"ic@example.com": (550, b"mailbox unavailable")},
        )

        with pytest.raises(EmailDeliveryError, match="mailbox unavailable"):
            send_email(_MESSAGE, config=_STARTTLS_CONFIG, client=client)

    def test_connection_error_raises(self) -> None:
        client = _client()
        client.__enter__.side_effect = OSError("connection refused")

        with pytest.raises(EmailDeliveryError, match="connection refused"):
            send_email(_MESSAGE, config=_STARTTLS_CONFIG, client=client)

    def test_credentials_never_appear_in_log_output(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = _client()
        client.login.side_effect = smtplib.SMTPAuthenticationError(
            535,
            b"bad credentials",
        )

        with caplog.at_level(logging.DEBUG), pytest.raises(EmailDeliveryError):
            send_email(_MESSAGE, config=_STARTTLS_CONFIG, client=client)

        log_text = caplog.text
        assert _STARTTLS_CONFIG.password not in log_text

    def test_credentials_never_appear_in_exception_message(self) -> None:
        client = _client()
        client.login.side_effect = smtplib.SMTPAuthenticationError(
            535,
            b"bad credentials",
        )

        with pytest.raises(EmailDeliveryError) as exc_info:
            send_email(_MESSAGE, config=_STARTTLS_CONFIG, client=client)

        assert _STARTTLS_CONFIG.password not in str(exc_info.value)
