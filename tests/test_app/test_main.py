"""Tests for deltadewa.app.__main__ — env-configurable host/port."""

from __future__ import annotations

import pytest

from deltadewa.app.__main__ import _host_and_port


class TestHostAndPort:
    """_host_and_port() reads DELTADEWA_HOST/DELTADEWA_PORT, safely."""

    def test_defaults_to_loopback_8050(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DELTADEWA_HOST", raising=False)
        monkeypatch.delenv("DELTADEWA_PORT", raising=False)

        assert _host_and_port() == ("127.0.0.1", 8050)

    def test_reads_host_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Any non-default value proves the override is read; avoid
        # "0.0.0.0" itself so this doesn't read as a real bind (S104).
        monkeypatch.setenv("DELTADEWA_HOST", "192.0.2.1")
        monkeypatch.delenv("DELTADEWA_PORT", raising=False)

        host, _port = _host_and_port()

        assert host == "192.0.2.1"

    def test_reads_port_override_as_int(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("DELTADEWA_HOST", raising=False)
        monkeypatch.setenv("DELTADEWA_PORT", "9000")

        _host, port = _host_and_port()

        assert port == 9000
