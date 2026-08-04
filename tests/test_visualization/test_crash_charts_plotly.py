"""Tests for deltadewa.visualization.crash_charts_plotly."""

import plotly.graph_objects as go

from deltadewa.analysis.monitor_scenario import ScenarioCurvePoint
from deltadewa.visualization.crash_charts_plotly import plot_scenario_curve

_CURVE = [
    ScenarioCurvePoint(
        shock_pct=-30.0,
        shocked_spot_price=3500.0,
        hedge_value=500_000.0,
        underlying_loss=-1_500_000.0,
        net=200_000.0,
        offset_ratio=0.47,
    ),
    ScenarioCurvePoint(
        shock_pct=-0.4,
        shocked_spot_price=4980.0,
        hedge_value=100_000.0,
        underlying_loss=-20_000.0,
        net=80_000.0,
        offset_ratio=None,
    ),
    ScenarioCurvePoint(
        shock_pct=10.0,
        shocked_spot_price=5500.0,
        hedge_value=50_000.0,
        underlying_loss=750_000.0,
        net=800_000.0,
        offset_ratio=-0.07,
    ),
]


class TestPlotScenarioCurve:
    """Tests for plot_scenario_curve."""

    def test_returns_figure_with_five_traces(self) -> None:
        fig = plot_scenario_curve(
            _CURVE,
            marker_pct=-30.0,
            marker_hedge_value=500_000.0,
            ips_crash_pct=-25.0,
        )

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 5

    def test_series_assigned_to_documented_indices(self) -> None:
        fig = plot_scenario_curve(
            _CURVE,
            marker_pct=-30.0,
            marker_hedge_value=500_000.0,
            ips_crash_pct=-25.0,
        )

        xs = [point.shock_pct for point in _CURVE]
        net_trace = fig.data[0]
        hedge_value_trace = fig.data[1]
        underlying_loss_trace = fig.data[2]
        offset_ratio_trace = fig.data[3]
        marker_trace = fig.data[4]

        assert list(net_trace.x) == xs
        assert list(net_trace.y) == [point.net for point in _CURVE]
        assert net_trace.mode == "lines"

        assert list(hedge_value_trace.x) == xs
        assert list(hedge_value_trace.y) == [
            point.hedge_value for point in _CURVE
        ]

        assert list(underlying_loss_trace.x) == xs
        assert list(underlying_loss_trace.y) == [
            point.underlying_loss for point in _CURVE
        ]

        assert list(offset_ratio_trace.x) == xs
        assert list(offset_ratio_trace.y) == [
            point.offset_ratio for point in _CURVE
        ]

        assert list(marker_trace.x) == [-30.0]
        assert list(marker_trace.y) == [500_000.0]
        assert marker_trace.mode == "markers"

    def test_offset_ratio_none_produces_gap_not_spike(self) -> None:
        fig = plot_scenario_curve(
            _CURVE,
            marker_pct=-30.0,
            marker_hedge_value=500_000.0,
            ips_crash_pct=-25.0,
        )

        offset_ratio_y = list(fig.data[3].y)
        assert None in offset_ratio_y
        real_values = [value for value in offset_ratio_y if value is not None]
        assert all(abs(value) < 10.0 for value in real_values)

    def test_offset_ratio_on_secondary_axis(self) -> None:
        fig = plot_scenario_curve(
            _CURVE,
            marker_pct=-30.0,
            marker_hedge_value=500_000.0,
            ips_crash_pct=-25.0,
        )

        assert fig.data[3].yaxis == "y2"
        assert fig.layout.yaxis2.overlaying == "y"
        assert fig.layout.yaxis2.side == "right"

    def test_xaxis_ticktext_contains_percent_and_spot_price(self) -> None:
        fig = plot_scenario_curve(
            _CURVE,
            marker_pct=-30.0,
            marker_hedge_value=500_000.0,
            ips_crash_pct=-25.0,
        )

        ticktext = fig.layout.xaxis.ticktext
        assert ticktext
        assert len(ticktext) <= len(_CURVE)
        for text in ticktext:
            assert "%" in text
            assert "<br>" in text
            _, spot_part = text.split("<br>")
            assert any(char.isdigit() for char in spot_part)

    def test_yaxis_is_dollar_formatted(self) -> None:
        fig = plot_scenario_curve(
            _CURVE,
            marker_pct=-30.0,
            marker_hedge_value=500_000.0,
            ips_crash_pct=-25.0,
        )

        assert fig.layout.yaxis.tickprefix == "$"
        assert fig.layout.yaxis.tickformat

    def test_empty_curve_does_not_raise(self) -> None:
        fig = plot_scenario_curve(
            [],
            marker_pct=-25.0,
            marker_hedge_value=0.0,
            ips_crash_pct=-25.0,
        )

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 5
