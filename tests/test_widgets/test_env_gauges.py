"""Tests for deltadewa.widgets.env_gauges."""

from datetime import UTC, datetime

import ipywidgets as widgets  # type: ignore[import-untyped]

from deltadewa.analysis.market_environment import (
    DataQuality,
    HedgeCostVerdict,
    MarketEnvironment,
    RegimeLabel,
    TermShape,
)
from deltadewa.widgets.env_gauges import build_env_gauges

_AS_OF = datetime(2026, 7, 24, tzinfo=UTC)


def _env(
    *,
    quality: DataQuality = DataQuality.LIVE,
    regime_percentile: float | None = 40.0,
    skew_percentile: float | None = 0.55,
    forward_vol_front_3m: float | None = 16.0,
) -> MarketEnvironment:
    """Craft a minimal MarketEnvironment for testing."""
    if quality is DataQuality.UNAVAILABLE:
        return MarketEnvironment(
            vix=None,
            regime_percentile=None,
            regime_label=None,
            skew_index=None,
            skew_percentile=None,
            term_structure=None,
            term_shape=None,
            forward_vol_front_3m=None,
            hedge_cost_verdict=None,
            data_quality=DataQuality.UNAVAILABLE,
            as_of=None,
        )
    return MarketEnvironment(
        vix=18.0,
        regime_percentile=regime_percentile,
        regime_label=RegimeLabel.NORMAL,
        skew_index=130.0,
        skew_percentile=skew_percentile,
        term_structure={
            "VIX9D": 16.0,
            "VIX": 18.0,
            "VIX3M": 20.0,
            "VIX6M": 21.0,
            "VIX1Y": 22.0,
        },
        term_shape=TermShape.CONTANGO,
        forward_vol_front_3m=forward_vol_front_3m,
        hedge_cost_verdict=HedgeCostVerdict.FAIR,
        data_quality=quality,
        as_of=_AS_OF,
    )


class TestBuildEnvGauges:
    """Tests for build_env_gauges."""

    def test_live_returns_html_widget(self) -> None:
        """LIVE data returns an ipywidgets.HTML instance."""
        result = build_env_gauges(_env(quality=DataQuality.LIVE))
        assert isinstance(result, widgets.HTML)

    def test_static_returns_html_widget(self) -> None:
        """STATIC data returns an ipywidgets.HTML instance."""
        result = build_env_gauges(_env(quality=DataQuality.STATIC))
        assert isinstance(result, widgets.HTML)

    def test_unavailable_returns_html_widget(self) -> None:
        """UNAVAILABLE data returns an ipywidgets.HTML instance."""
        result = build_env_gauges(_env(quality=DataQuality.UNAVAILABLE))
        assert isinstance(result, widgets.HTML)

    def test_live_contains_no_quality_banner(self) -> None:
        """LIVE gauge HTML contains no static/unavailable caption."""
        html = build_env_gauges(_env(quality=DataQuality.LIVE)).value
        assert "Static" not in html
        assert "unavailable" not in html.lower()

    def test_static_shows_caption(self) -> None:
        """STATIC gauge HTML contains the 'Static / offline data' caption."""
        html = build_env_gauges(_env(quality=DataQuality.STATIC)).value
        assert "Static" in html

    def test_unavailable_shows_caption(self) -> None:
        """UNAVAILABLE gauge HTML contains the 'unavailable' caption."""
        html = build_env_gauges(_env(quality=DataQuality.UNAVAILABLE)).value
        assert "unavailable" in html.lower()

    def test_unavailable_shows_dash_placeholder(self) -> None:
        """UNAVAILABLE gauges show the '—' placeholder bar."""
        html = build_env_gauges(_env(quality=DataQuality.UNAVAILABLE)).value
        assert "—" in html

    def test_live_contains_all_three_gauge_titles(self) -> None:
        """LIVE output contains all three gauge card titles."""
        html = build_env_gauges(_env(quality=DataQuality.LIVE)).value
        assert "Vol Regime" in html
        assert "Skew Percentile" in html
        assert "Forward Vol" in html

    def test_none_regime_percentile_does_not_raise(self) -> None:
        """None regime_percentile renders without raising."""
        result = build_env_gauges(
            _env(quality=DataQuality.STATIC, regime_percentile=None),
        )
        assert isinstance(result, widgets.HTML)

    def test_none_skew_percentile_does_not_raise(self) -> None:
        """None skew_percentile with STATIC quality renders without raising."""
        result = build_env_gauges(
            _env(quality=DataQuality.STATIC, skew_percentile=None),
        )
        assert isinstance(result, widgets.HTML)

    def test_none_forward_vol_does_not_raise(self) -> None:
        """None forward_vol_front_3m renders without raising."""
        result = build_env_gauges(
            _env(quality=DataQuality.STATIC, forward_vol_front_3m=None),
        )
        assert isinstance(result, widgets.HTML)

    def test_skew_percentile_scaled_to_100(self) -> None:
        """skew_percentile 0-1 is converted to 0-100 in the output."""
        html = build_env_gauges(
            _env(quality=DataQuality.LIVE, skew_percentile=0.72),
        ).value
        # GaugeIndicator label_format "{:.0f}" renders 72 (not 0 or 1)
        assert "72" in html

    def test_exported_from_widgets_package(self) -> None:
        """build_env_gauges is importable from deltadewa.widgets."""
        from deltadewa.widgets import build_env_gauges as imported

        assert imported is build_env_gauges
