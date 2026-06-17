"""Tests for deltadewa.marketdata.cboe_fred_provider."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
import requests

from deltadewa.marketdata import CboeFredProvider, MarketDataError

# ruff: noqa: S101 ANN001

_SPX_CSV = "DATE,OPEN,HIGH,LOW,CLOSE\n2026-06-15,4990,5010,4980,5000.0\n"
_VIXCLS_CSV = "DATE,VIXCLS\n2026-06-15,16.5\n"
_SKEW_CSV = "DATE,OPEN,HIGH,LOW,CLOSE\n" + "\n".join(
    f"2026-{(i % 12) + 1:02d}-01,0,0,0,{120.0 + i}" for i in range(10)
) + "\n"


def _mock_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.raise_for_status = MagicMock()
    return response


class TestCboeFredProvider:
    """Tests for CboeFredProvider."""

    def test_get_spot_fetches_and_caches(self, tmp_path) -> None:
        """Test a live fetch succeeds and writes through to the cache."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        spot = provider.get_spot("SPX")

        assert spot == 5000.0
        assert session.get.call_count == 1
        assert (tmp_path / "spot_SPX.json").exists()

    def test_get_spot_uses_cache_without_second_http_call(
        self,
        tmp_path,
    ) -> None:
        """Test that a fresh cache entry avoids a second HTTP request."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        provider.get_spot("SPX")
        provider.get_spot("SPX")

        assert session.get.call_count == 1

    def test_get_spot_falls_back_to_stale_cache_on_http_failure(
        self,
        tmp_path,
    ) -> None:
        """Test that a stale cached value is used when a live fetch fails."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            ttl=timedelta(seconds=0),
            session=session,
        )
        provider.get_spot("SPX")

        session.get.side_effect = requests.ConnectionError("offline")

        spot = provider.get_spot("SPX")

        assert spot == 5000.0

    def test_get_spot_raises_market_data_error_when_no_cache(
        self,
        tmp_path,
    ) -> None:
        """Test that a typed error is raised with no live data or cache."""
        session = MagicMock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError("offline")
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        with pytest.raises(MarketDataError):
            provider.get_spot("SPX")

    def test_get_vix_uses_fred_series(self, tmp_path) -> None:
        """Test that get_vix fetches and parses the FRED VIXCLS series."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIXCLS_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        assert provider.get_vix() == 16.5

    def test_get_vix_term_structure_returns_all_keys(self, tmp_path) -> None:
        """Test that get_vix_term_structure fetches each CBOE index."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        term_structure = provider.get_vix_term_structure()

        assert set(term_structure) == {
            "VIX9D",
            "VIX",
            "VIX3M",
            "VIX6M",
            "VIX1Y",
        }
        assert session.get.call_count == 5

    def test_get_skew_percentile_computes_rank(self, tmp_path) -> None:
        """Test that get_skew_percentile ranks the latest value in history."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SKEW_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        percentile = provider.get_skew_percentile(lookback_days=10)

        assert percentile == 1.0
