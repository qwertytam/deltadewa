"""Tests for deltadewa.analysis.market_environment."""

from __future__ import annotations

import math

import pytest

from deltadewa.analysis.market_environment import (
    DataQuality,
    HedgeCostVerdict,
    RegimeLabel,
    TermShape,
    assess_market_environment,
    classify_vix_regime,
    forward_vol,
    term_structure_shape,
)
from deltadewa.ips_config import IpsMarketEnvironment
from deltadewa.marketdata._errors import MarketDataError

_CALM_TERM = {
    "VIX9D": 14.0,
    "VIX": 15.0,
    "VIX3M": 17.0,
    "VIX6M": 18.0,
    "VIX1Y": 19.0,
}
_INVERTED_TERM = {
    "VIX9D": 85.0,
    "VIX": 80.0,
    "VIX3M": 55.0,
    "VIX6M": 45.0,
    "VIX1Y": 40.0,
}
_NEAR_FLAT_TERM = {
    "VIX9D": 15.0,
    "VIX": 15.0,
    "VIX3M": 15.2,
    "VIX6M": 15.1,
    "VIX1Y": 15.3,
}


class _StubProvider:
    """Canned-value MarketDataProvider stand-in, no network."""

    is_live: bool = True

    def __init__(
        self,
        vix: float = 16.0,
        term: dict[str, float] | None = None,
        skew_index: float = 120.0,
        skew_percentile: float = 0.5,
    ) -> None:
        self.vix = vix
        self.term = term if term is not None else dict(_CALM_TERM)
        self.skew_index = skew_index
        self.skew_percentile = skew_percentile
        self.received_lookback_days: int | None = None

    def get_spot(self, symbol: str) -> float:
        raise NotImplementedError(symbol)

    def get_vix(self) -> float:
        return self.vix

    def get_vix_term_structure(self) -> dict[str, float]:
        return dict(self.term)

    def get_skew_index(self) -> float:
        return self.skew_index

    def get_skew_percentile(self, lookback_days: int = 252) -> float:
        self.received_lookback_days = lookback_days
        return self.skew_percentile


class _FailingProvider:
    """MarketDataProvider stand-in where every call raises."""

    is_live: bool = True

    def get_spot(self, symbol: str) -> float:
        raise MarketDataError(symbol)

    def get_vix(self) -> float:
        raise MarketDataError("vix unavailable")

    def get_vix_term_structure(self) -> dict[str, float]:
        raise MarketDataError("term structure unavailable")

    def get_skew_index(self) -> float:
        raise MarketDataError("skew unavailable")

    def get_skew_percentile(self, lookback_days: int = 252) -> float:
        _ = lookback_days
        raise MarketDataError("skew percentile unavailable")


class TestClassifyVixRegime:
    """Tests for classify_vix_regime."""

    def test_at_or_below_low_is_zero_and_low(self) -> None:
        """VIX at/below the low band is percentile 0, label LOW."""
        percentile, label = classify_vix_regime(
            12.0,
            low=0.15,
            high=0.35,
        )
        assert percentile == pytest.approx(0.0)
        assert label == RegimeLabel.LOW

    def test_at_or_above_high_is_hundred_and_high(self) -> None:
        """VIX at/above the high band is percentile 100, label HIGH."""
        percentile, label = classify_vix_regime(
            40.0,
            low=0.15,
            high=0.35,
        )
        assert percentile == pytest.approx(100.0)
        assert label == RegimeLabel.HIGH

    def test_midpoint_is_fifty_and_normal(self) -> None:
        """VIX at the band midpoint is percentile 50, label NORMAL."""
        percentile, label = classify_vix_regime(
            25.0,
            low=0.15,
            high=0.35,
        )
        assert percentile == pytest.approx(50.0)
        assert label == RegimeLabel.NORMAL

    def test_units_conversion_vix_18_against_default_bands(self) -> None:
        """get_vix()=18.0 (18%) is compared as 0.18 against (0.15, 0.35)."""
        percentile, label = classify_vix_regime(18.0)
        assert percentile == pytest.approx(15.0)
        assert label == RegimeLabel.LOW


class TestTermStructureShape:
    """Tests for term_structure_shape."""

    def test_calm_upward_sloping_curve_is_contango(self) -> None:
        """Front below 3M below 6M, beyond tolerance, is CONTANGO."""
        assert term_structure_shape(_CALM_TERM) == TermShape.CONTANGO

    def test_inverted_crisis_curve_is_backwardation(self) -> None:
        """Front far above 3M is BACKWARDATION, regardless of 6M."""
        assert term_structure_shape(_INVERTED_TERM) == TermShape.BACKWARDATION

    def test_near_identical_levels_are_flat(self) -> None:
        """Differences within tolerance read as FLAT, not a real slope."""
        assert term_structure_shape(_NEAR_FLAT_TERM) == TermShape.FLAT


class TestForwardVol:
    """Tests for forward_vol."""

    def test_matches_hand_computed_formula(self) -> None:
        """forward_vol(VIX=15, VIX3M=18) matches the formula directly."""
        term = {"VIX": 15.0, "VIX3M": 18.0}
        s1, s2 = 15.0 / 100, 18.0 / 100
        t1, t2 = 1 / 12, 3 / 12
        expected_var = (s2**2 * t2 - s1**2 * t1) / (t2 - t1)
        expected = math.sqrt(max(expected_var, 0.0)) * 100

        assert forward_vol(term) == pytest.approx(expected)

    def test_flat_term_structure_returns_same_level(self) -> None:
        """A flat curve's forward vol equals the flat level itself."""
        term = {"VIX": 15.0, "VIX3M": 15.0}
        assert forward_vol(term) == pytest.approx(15.0)

    def test_missing_tenor_returns_none(self) -> None:
        """Without both VIX and VIX3M, there's nothing to compute."""
        assert forward_vol({"VIX": 15.0}) is None


class TestAssessMarketEnvironment:
    """Tests for assess_market_environment."""

    def test_calm_market_is_cheap(self) -> None:
        """Low VIX + low skew + contango term -> CHEAP, data LIVE."""
        provider = _StubProvider(
            vix=18.0,
            term=_CALM_TERM,
            skew_percentile=0.20,
        )

        env = assess_market_environment(provider)

        assert env.hedge_cost_verdict == HedgeCostVerdict.CHEAP
        assert env.data_quality == DataQuality.LIVE
        assert env.regime_label == RegimeLabel.LOW
        assert env.term_shape == TermShape.CONTANGO

    def test_stressed_market_is_expensive(self) -> None:
        """High VIX + high skew + backwardation -> EXPENSIVE."""
        provider = _StubProvider(
            vix=45.0,
            term=_INVERTED_TERM,
            skew_percentile=0.85,
        )

        env = assess_market_environment(provider)

        assert env.hedge_cost_verdict == HedgeCostVerdict.EXPENSIVE
        assert env.data_quality == DataQuality.LIVE

    def test_mixed_signals_are_fair(self) -> None:
        """Low VIX but high skew (contango) doesn't meet either corner."""
        provider = _StubProvider(
            vix=18.0,
            term=_CALM_TERM,
            skew_percentile=0.85,
        )

        env = assess_market_environment(provider)

        assert env.hedge_cost_verdict == HedgeCostVerdict.FAIR

    def test_provider_failure_yields_unavailable(self) -> None:
        """Any MarketDataError degrades to all-None + UNAVAILABLE."""
        env = assess_market_environment(_FailingProvider())

        assert env.data_quality == DataQuality.UNAVAILABLE
        assert env.vix is None
        assert env.regime_percentile is None
        assert env.regime_label is None
        assert env.skew_index is None
        assert env.skew_percentile is None
        assert env.term_structure is None
        assert env.term_shape is None
        assert env.forward_vol_front_3m is None
        assert env.hedge_cost_verdict is None

    def test_ips_skew_band_changes_the_verdict(self) -> None:
        """Narrowing the IPS skew band flips a FAIR read to CHEAP.

        One place moves the consumer: the skew percentiles live only in the
        IPS ``market_environment`` policy, converted to a 0-1 fraction here.
        """
        provider = _StubProvider(
            vix=18.0,
            term=_CALM_TERM,
            skew_percentile=0.40,
        )

        default_env = assess_market_environment(provider)
        narrowed_env = assess_market_environment(
            provider,
            IpsMarketEnvironment(skew_low_pctile=45.0, skew_high_pctile=70.0),
        )

        assert default_env.hedge_cost_verdict == HedgeCostVerdict.FAIR
        assert narrowed_env.hedge_cost_verdict == HedgeCostVerdict.CHEAP

    def test_ips_regime_band_changes_the_verdict(self) -> None:
        """Narrowing the IPS vol-regime band flips a CHEAP read to FAIR."""
        provider = _StubProvider(
            vix=18.0,
            term=_CALM_TERM,
            skew_percentile=0.20,
        )

        default_env = assess_market_environment(provider)
        narrowed_env = assess_market_environment(
            provider,
            IpsMarketEnvironment(vol_regime_low=0.10, vol_regime_high=0.12),
        )

        assert default_env.hedge_cost_verdict == HedgeCostVerdict.CHEAP
        assert narrowed_env.hedge_cost_verdict == HedgeCostVerdict.FAIR
        assert narrowed_env.regime_label == RegimeLabel.HIGH

    def test_ips_term_tolerance_changes_the_shape(self) -> None:
        """The IPS term-contango tolerance moves the term-structure shape."""
        # VIX3M - VIX = 0.3 vol points; VIX6M - VIX3M = 0.2.
        term = {
            "VIX9D": 14.8,
            "VIX": 15.0,
            "VIX3M": 15.3,
            "VIX6M": 15.5,
            "VIX1Y": 15.7,
        }
        provider = _StubProvider(vix=15.0, term=term)

        # Default tolerance 0.5 > 0.3 slope -> FLAT.
        assert assess_market_environment(provider).term_shape == TermShape.FLAT
        # Tolerance 0.1 < 0.3 slope -> now reads as CONTANGO.
        tight = IpsMarketEnvironment(term_contango_tolerance=0.1)
        assert (
            assess_market_environment(provider, tight).term_shape
            == TermShape.CONTANGO
        )

    def test_skew_lookback_days_passed_through(self) -> None:
        """skew_lookback_days reaches get_skew_percentile unchanged."""
        provider = _StubProvider()

        assess_market_environment(provider, skew_lookback_days=504)

        assert provider.received_lookback_days == 504


class TestDataQualityStatic:
    """DataQuality is set via provider.is_live, not duck-typed hints."""

    def test_static_member_exists(self) -> None:
        """DataQuality.STATIC is a valid member with value 'STATIC'."""
        assert DataQuality.STATIC == "STATIC"

    def test_static_provider_yields_static_quality(self) -> None:
        """assess_market_environment returns STATIC for StaticProvider."""
        from deltadewa.marketdata import StaticProvider

        env = assess_market_environment(StaticProvider())
        assert env.data_quality == DataQuality.STATIC

    def test_live_stub_yields_live(self) -> None:
        """A provider with is_live=True returns DataQuality.LIVE."""
        env = assess_market_environment(_StubProvider())
        assert env.data_quality == DataQuality.LIVE

    def test_non_live_stub_yields_static(self) -> None:
        """A provider with is_live=False returns DataQuality.STATIC."""

        class _NonLiveStub(_StubProvider):
            is_live: bool = False

        env = assess_market_environment(_NonLiveStub())
        assert env.data_quality == DataQuality.STATIC

    def test_erroring_stub_yields_unavailable(self) -> None:
        """A provider that raises MarketDataError returns UNAVAILABLE."""
        env = assess_market_environment(_FailingProvider())
        assert env.data_quality == DataQuality.UNAVAILABLE

    def test_static_case_populates_fields(self) -> None:
        """DataQuality.STATIC does not suppress environment fields."""
        from deltadewa.marketdata import StaticProvider

        env = assess_market_environment(StaticProvider())
        assert env.vix is not None
        assert env.regime_label is not None
