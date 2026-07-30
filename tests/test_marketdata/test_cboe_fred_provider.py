"""Tests for deltadewa.marketdata.cboe_fred_provider."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import requests

from deltadewa.marketdata import (
    CboeFredProvider,
    MarketDataError,
    Source,
)

# Real CBOE SPX format: DATE + symbol-name column (no OHLCV).
# Dates are MM/DD/YYYY — must not be sorted as strings or December rows
# will sort after January rows of the following year.
_SPX_CSV = "DATE,SPX\n06/15/2026,5000.0\n"

# Multi-row SPX CSV with MM/DD/YYYY dates that sorts wrong lexicographically.
# 12/31/2025 (6800) sorts after 06/25/2026 (5000) in string order, so a
# correct chronological sort must pick 5000 as the latest value.
_SPX_CSV_MULTIROW = (
    "DATE,SPX\n06/25/2026,5000.0\n12/31/2025,6800.0\n01/02/2025,4500.0\n"
)

# Real CBOE VIX-family format: full OHLCV with a CLOSE column.
_VIX_CSV = "DATE,OPEN,HIGH,LOW,CLOSE\n06/15/2026,16.0,16.5,15.5,16.5\n"

# Real CBOE SKEW format: DATE + symbol-name column (no OHLCV).
_SKEW_CSV = (
    "DATE,SKEW\n"
    + "\n".join(f"{(i % 12) + 1:02d}/01/2026,{120.0 + i}" for i in range(10))
    + "\n"
)

# Real FRED format: "observation_date" (not "DATE") as the date column.
_VIXCLS_CSV = "observation_date,VIXCLS\n2026-06-15,16.5\n"

# Multi-row VIXCLS history for percentile/history tests (chronological).
_VIXCLS_CSV_MULTIROW = (
    "observation_date,VIXCLS\n"
    + "\n".join(f"2026-{(i % 12) + 1:02d}-01,{12.0 + i}" for i in range(10))
    + "\n"
)


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

        spot = provider.get_spot("SPX").value

        assert spot == pytest.approx(5000.0, rel=1e-2)
        assert session.get.call_count == 1
        assert (tmp_path / "spot_SPX.json").exists()

    def test_get_spot_spx_parses_symbol_column(self, tmp_path) -> None:
        """Test get_spot parses CBOE's DATE+SPX format (no CLOSE column)."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        spot = provider.get_spot("SPX").value

        assert spot == pytest.approx(5000.0, rel=1e-2)

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

        spot = provider.get_spot("SPX").value

        assert spot == pytest.approx(5000.0, rel=1e-2)

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

        assert provider.get_vix().value == pytest.approx(16.5, rel=1e-4)

    def test_get_vix_parses_observation_date_column(self, tmp_path) -> None:
        """Test get_vix handles FRED's observation_date column name."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIXCLS_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        vix = provider.get_vix().value

        assert vix == pytest.approx(16.5, rel=1e-4)

    def test_get_vix_term_structure_returns_all_keys(self, tmp_path) -> None:
        """Test that get_vix_term_structure fetches each CBOE VIX index."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        term_structure = provider.get_vix_term_structure().value

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

        term_structure = provider.get_vix_term_structure().value

        assert all(
            v == pytest.approx(16.5, rel=1e-4) for v in term_structure.values()
        )

    def test_get_skew_index_parses_skew_column(self, tmp_path) -> None:
        """Test get_skew_index handles CBOE's DATE+SKEW format (no CLOSE)."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SKEW_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        skew = provider.get_skew_index().value

        assert skew == pytest.approx(
            129.0, rel=1e-5
        )  # last row: i=9 → 120.0 + 9

    def test_get_spot_sorts_cboe_dates_chronologically(self, tmp_path) -> None:
        """Test MM/DD/YYYY dates are sorted chronologically, not as strings.

        12/31/2025 sorts after 06/25/2026 lexicographically, so a string sort
        would return 6800.0 instead of the true latest value 5000.0.
        """
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV_MULTIROW)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        spot = provider.get_spot("SPX").value

        assert spot == pytest.approx(5000.0, rel=1e-2)

    def test_get_skew_percentile_computes_rank(self, tmp_path) -> None:
        """Test that get_skew_percentile ranks the latest value in history."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SKEW_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        percentile = provider.get_skew_percentile(lookback_days=10).value

        assert percentile == pytest.approx(1.0, rel=1e-7)

    def test_get_vix_history_returns_last_n_closes(self, tmp_path) -> None:
        """get_vix_history returns the last-N VIXCLS closes, oldest first."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIXCLS_CSV_MULTIROW)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        history = provider.get_vix_history(lookback_days=3).value

        # Last three rows of 12.0..21.0 are 19.0, 20.0, 21.0 (chronological).
        assert history == [19.0, 20.0, 21.0]

    def test_get_vix_history_reuses_vix_cache(self, tmp_path) -> None:
        """History shares the vix_fred cache key — no second HTTP call."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIXCLS_CSV_MULTIROW)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        provider.get_vix()  # primes the vix_fred cache
        provider.get_vix_history()

        assert session.get.call_count == 1


class TestCboeFredProviderProvenance:
    """Each fetch path must label itself for what it actually did."""

    def test_live_fetch_is_labelled_live(self, tmp_path) -> None:
        """A successful network fetch reports Source.LIVE."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        assert provider.get_spot("SPX").source is Source.LIVE

    def test_within_ttl_cache_hit_is_labelled_cached(self, tmp_path) -> None:
        """A second call inside the TTL reports CACHED, not LIVE."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        provider.get_spot("SPX")
        second = provider.get_spot("SPX")

        assert second.source is Source.CACHED
        assert session.get.call_count == 1

    def test_stale_fallback_is_labelled_stale(self, tmp_path) -> None:
        """The regression this exists to stop: a stale fallback said LIVE.

        Previously the value came back bare and the environment was stamped
        from the provider's ``is_live`` class attribute, so a cache entry
        served after a failed fetch was indistinguishable from a fresh one.
        """
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            ttl=timedelta(seconds=0),
            session=session,
        )
        provider.get_spot("SPX")
        session.get.side_effect = requests.ConnectionError("offline")

        stale = provider.get_spot("SPX")

        assert stale.source is Source.STALE
        assert stale.value == pytest.approx(5000.0, rel=1e-2)

    def test_as_of_is_the_observation_date_not_the_fetch_time(
        self,
        tmp_path,
    ) -> None:
        """A daily close is older than its download the moment it arrives.

        ``_SPX_CSV``'s only row is dated 2026-06-15. A fetch today is LIVE
        and ``fetched_at`` is now, but the datum itself is weeks old — the
        distinction a staleness banner has to show.
        """
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_SPX_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        spot = provider.get_spot("SPX")

        assert spot.as_of == datetime(2026, 6, 15, tzinfo=UTC)
        assert spot.fetched_at is not None
        assert spot.as_of < spot.fetched_at

    def test_fred_as_of_parses_iso_dates(self, tmp_path) -> None:
        """FRED writes YYYY-MM-DD; CBOE writes MM/DD/YYYY. Both parse."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIXCLS_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        assert provider.get_vix().as_of == datetime(2026, 6, 15, tzinfo=UTC)

    def test_vix_history_as_of_tracks_the_window_it_returned(
        self,
        tmp_path,
    ) -> None:
        """The as-of belongs to the last row actually returned."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIXCLS_CSV_MULTIROW)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        history = provider.get_vix_history(lookback_days=3)

        # Rows run 2026-01-01..2026-10-01; the last is the tenth.
        assert history.as_of == datetime(2026, 10, 1, tzinfo=UTC)

    def test_vix_and_history_share_provenance(self, tmp_path) -> None:
        """Sharing the vix_fred cache key must mean sharing the as-of."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIXCLS_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        vix = provider.get_vix()
        history = provider.get_vix_history()

        assert history.as_of == vix.as_of

    def test_term_structure_takes_the_worst_leg(self, tmp_path) -> None:
        """One stale leg makes the whole curve stale."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _mock_response(_VIX_CSV)
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            ttl=timedelta(seconds=0),
            session=session,
        )
        provider.get_vix_term_structure()
        session.get.side_effect = requests.ConnectionError("offline")

        term = provider.get_vix_term_structure()

        assert term.source is Source.STALE
        assert set(term.value) == {"VIX9D", "VIX", "VIX3M", "VIX6M", "VIX1Y"}
