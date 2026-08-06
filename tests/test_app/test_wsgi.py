"""Tests for deltadewa.app.wsgi — provider construction wiring."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from deltadewa.app import wsgi as wsgi_module
from deltadewa.marketdata import default_cache_dir


class TestBuild:
    """_build() must wire the read-only provider correctly (M2.6)."""

    def test_provider_is_read_only_with_shared_cache_and_policy_ttl(
        self,
    ) -> None:
        """cache_dir/ttl come from the shared resolver, not bare defaults."""
        with patch.object(wsgi_module, "CboeFredProvider") as mock_provider:
            wsgi_module._build()

        mock_provider.assert_called_once()
        _, kwargs = mock_provider.call_args
        assert kwargs["read_only"] is True
        assert kwargs["cache_dir"] == default_cache_dir()
        # The shipped config/ips.yaml sets data_ttl_minutes to 2160 (36h) —
        # M2.6's daily refresh cron interval with jitter headroom — not the
        # provider's own 15-minute constructor default.
        assert kwargs["ttl"] == timedelta(minutes=2160)
