"""Tests for deltadewa.marketdata._policy."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from deltadewa.ips_config import DEFAULT_DATA_TTL_MINUTES, load_ips_config
from deltadewa.marketdata import default_cache_dir, resolve_data_ttl
from deltadewa.marketdata._policy import _CACHE_DIR_ENV_VAR

_EXAMPLE_IPS_YAML = Path(__file__).parent.parent.parent / "config" / "ips.yaml"


class TestDefaultCacheDir:
    """default_cache_dir() — shared between the app and the refresh job."""

    def test_honours_env_var(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DELTADEWA_CACHE_DIR, when set, wins over the home-dir default."""
        monkeypatch.setenv(_CACHE_DIR_ENV_VAR, str(tmp_path))

        assert default_cache_dir() == tmp_path

    def test_falls_back_to_home_cache_when_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unset env var falls back to ~/.cache/deltadewa/marketdata."""
        monkeypatch.delenv(_CACHE_DIR_ENV_VAR, raising=False)

        assert default_cache_dir() == (
            Path.home() / ".cache" / "deltadewa" / "marketdata"
        )


class TestResolveDataTtl:
    """resolve_data_ttl() — the CACHED/STALE boundary comes from policy."""

    def test_none_ips_config_uses_default_minutes(self) -> None:
        """A missing ips.yaml falls back to DEFAULT_DATA_TTL_MINUTES."""
        assert resolve_data_ttl(None) == timedelta(
            minutes=DEFAULT_DATA_TTL_MINUTES,
        )

    def test_reads_market_environment_data_ttl_minutes(self) -> None:
        """A loaded ips_config's policy value is used, not the default."""
        ips_config = load_ips_config(_EXAMPLE_IPS_YAML)

        assert resolve_data_ttl(ips_config) == timedelta(
            minutes=ips_config.market_environment.data_ttl_minutes,
        )
