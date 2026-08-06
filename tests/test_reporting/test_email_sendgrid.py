"""Tests for deltadewa.reporting.email_sendgrid."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from deltadewa.reporting.email_sendgrid import (
    EmailDeliveryError,
    EmailMessage,
    send_email,
)

_MESSAGE = EmailMessage(
    subject="Weekly Hedge Digest — NO ACTION (2026-08-05)",
    html_body="<h1>Digest</h1>",
    to_addr="ic@example.com",
    from_addr="hedge-program@example.com",
)


def _session(status_code: int, text: str = "") -> MagicMock:
    session = MagicMock(spec=requests.Session)
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    session.post.return_value = response
    return session


class TestSendEmailSuccess:
    """A 202 Accepted response is the only confirmed-success path."""

    def test_202_returns_without_raising(self) -> None:
        session = _session(202)

        send_email(_MESSAGE, api_key="SG.fake", session=session)

        session.post.assert_called_once()

    def test_posts_the_right_url_and_payload(self) -> None:
        session = _session(202)

        send_email(_MESSAGE, api_key="SG.fake", session=session)

        args, kwargs = session.post.call_args
        assert args[0] == "https://api.sendgrid.com/v3/mail/send"
        payload = kwargs["json"]
        assert payload["subject"] == _MESSAGE.subject
        assert payload["from"] == {"email": _MESSAGE.from_addr}
        assert payload["personalizations"] == [
            {"to": [{"email": _MESSAGE.to_addr}]},
        ]
        assert payload["content"] == [
            {"type": "text/html", "value": _MESSAGE.html_body},
        ]

    def test_sends_the_bearer_auth_header(self) -> None:
        session = _session(202)

        send_email(_MESSAGE, api_key="SG.fake-key", session=session)

        _, kwargs = session.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer SG.fake-key"


class TestSendEmailFailure:
    """Any non-2xx response or network error raises EmailDeliveryError."""

    def test_non_2xx_response_raises(self) -> None:
        session = _session(401, text='{"errors": [{"message": "bad key"}]}')

        with pytest.raises(EmailDeliveryError, match="401"):
            send_email(_MESSAGE, api_key="SG.fake", session=session)

    def test_network_error_raises(self) -> None:
        session = MagicMock(spec=requests.Session)
        session.post.side_effect = requests.ConnectionError("offline")

        with pytest.raises(EmailDeliveryError, match="offline"):
            send_email(_MESSAGE, api_key="SG.fake", session=session)
