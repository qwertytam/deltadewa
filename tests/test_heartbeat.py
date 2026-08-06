"""Tests for deltadewa.heartbeat."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
import requests

from deltadewa.heartbeat import ping


class TestPingUnconfigured:
    """A None/empty URL is a silent, logged no-op — not an error."""

    def test_none_url_skips_without_calling_session(self) -> None:
        session = MagicMock(spec=requests.Session)

        ping(None, label="refresh", session=session)

        session.get.assert_not_called()

    def test_empty_url_skips_without_calling_session(self) -> None:
        session = MagicMock(spec=requests.Session)

        ping("", label="refresh", session=session)

        session.get.assert_not_called()

    def test_none_url_logs_info(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        session = MagicMock(spec=requests.Session)
        with caplog.at_level(logging.INFO):
            ping(None, label="refresh", session=session)

        assert "not configured" in caplog.text


class TestPingConfigured:
    """A configured URL is GETed; a confirmed 2xx response is success."""

    def test_gets_the_configured_url(self) -> None:
        session = MagicMock(spec=requests.Session)
        response = MagicMock()
        response.raise_for_status = MagicMock()
        session.get.return_value = response

        ping("https://hc-ping.com/abc123", label="digest", session=session)

        session.get.assert_called_once()
        args, kwargs = session.get.call_args
        assert args[0] == "https://hc-ping.com/abc123"
        assert "timeout" in kwargs

    def test_success_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        session = MagicMock(spec=requests.Session)
        response = MagicMock()
        response.raise_for_status = MagicMock()
        session.get.return_value = response

        with caplog.at_level(logging.INFO):
            ping("https://hc-ping.com/abc123", label="digest", session=session)

        assert "heartbeat ping sent" in caplog.text


class TestPingFailureNeverRaises:
    """A failed ping is logged as a warning, never propagated."""

    def test_network_error_does_not_raise(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        session = MagicMock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError("offline")

        with caplog.at_level(logging.WARNING):
            ping("https://hc-ping.com/abc123", label="refresh", session=session)

        assert "heartbeat ping failed" in caplog.text

    def test_non_2xx_response_does_not_raise(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        session = MagicMock(spec=requests.Session)
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error",
        )
        session.get.return_value = response

        with caplog.at_level(logging.WARNING):
            ping("https://hc-ping.com/abc123", label="refresh", session=session)

        assert "heartbeat ping failed" in caplog.text
