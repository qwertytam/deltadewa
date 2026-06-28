"""Tests for deltadewa.marketdata.cboe_fred_provider."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
import requests

from deltadewa.marketdata import CboeFredProvider, MarketDataError

# Real CBOE SPX format: DATE + symbol-name column (no OHLCV).
# Dates are MM/DD/YYYY — must not be sorted as strings or December rows
# will sort after January rows of the following year.
_SPX_CSV = "DATE,SPX\n06/15/2026,5000.0\n"

# Multi-row SPX CSV with MM/DD/YYYY dates that sorts wrong lexicographically.
# 12/31/2025 (6800) sorts after 06/25/2026 (5000) in string order, so a
# correct chronological sort must pick 5000 as the latest value.
_SPX_CSV_MULTIROW = (
    "DATE,SPX\n"
    "06/25/2026,5000.0\n"
    "12/31/2025,6800.0\n"
    "01/02/2025,4500.0\n"
)

# Real CBOE VIX-family format: full OHLCV with a CLOSE column.
_VIX_CSV = "DATE,OPEN,HIGH,LOW,CLOSE\n06/15/2026,16.0,16.5,15.5,16.5\n"

# Real CBOE SKEW format: DATE + symbol-name column (no OHLCV).
_SKEW_CSV = (
    "DATE,SKEW\n"
    + "\n".join(
        f"{(i % 12) + 1:02d}/01/2026,{120.0 + i}" for i in range(10)
    )
    + "\n"
)

# Real FRED format: "observation_date" (not "DATE") as the date column.
_VIXCLS_CSV = "observation_date,VIXCLS\n2026-06-15,16.5\n"


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

    def test_get_spot_spx_parses_symbol_column(self, tmp_path) -> None:
        """Test get_spot parses CBOE's DATE+SPX format (no CLOSE column)."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        spot = provider.get_spot("SPX")

        assert spot == 5000.0

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

    def test_get_vix_parses_observation_date_column(self, tmp_path) -> None:
        """Test get_vix handles FRED's observation_date column name."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIXCLS_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        vix = provider.get_vix()

        assert vix == 16.5

    def test_get_vix_term_structure_returns_all_keys(self, tmp_path) -> None:
        """Test that get_vix_term_structure fetches each CBOE VIX index."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIX_CSV)
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

    def test_get_vix_term_structure_parses_close_column(self, tmp_path) -> None:
        """Test VIX-family symbols are parsed from the CLOSE column."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        term_structure = provider.get_vix_term_structure()

        assert all(v == 16.5 for v in term_structure.values())

    def test_get_skew_index_parses_skew_column(self, tmp_path) -> None:
        """Test get_skew_index handles CBOE's DATE+SKEW format (no CLOSE)."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SKEW_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        skew = provider.get_skew_index()

        assert skew == 129.0  # last row: i=9 → 120.0 + 9

    def test_get_spot_sorts_cboe_dates_chronologically(self, tmp_path) -> None:
        """Test MM/DD/YYYY dates are sorted chronologically, not as strings.

        12/31/2025 sorts after 06/25/2026 lexicographically, so a string sort
        would return 6800.0 instead of the true latest value 5000.0.
        """
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV_MULTIROW)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        spot = provider.get_spot("SPX")

        assert spot == 5000.0

    def test_get_skew_percentile_computes_rank(self, tmp_path) -> None:
        """Test that get_skew_percentile ranks the latest value in history."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SKEW_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        percentile = provider.get_skew_percentile(lookback_days=10)

        assert percentile == 1.0
