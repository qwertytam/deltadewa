"""Tests for deltadewa.visualization.crash_charts_plotly."""

import plotly.graph_objects as go

from deltadewa.visualization.crash_charts_plotly import plot_crash_value_curve


class TestPlotCrashValueCurve:
    """Tests for plot_crash_value_curve."""

    def test_returns_figure_with_two_traces(self) -> None:
        curve = [(-30.0, 500_000.0), (-20.0, 300_000.0), (0.0, 0.0)]

        fig = plot_crash_value_curve(
            curve,
            marker_pct=-25.0,
            marker_value=400_000.0,
            ips_crash_pct=-25.0,
        )

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 2

    def test_curve_trace_matches_input(self) -> None:
        curve = [(-30.0, 500_000.0), (-20.0, 300_000.0), (0.0, 0.0)]

        fig = plot_crash_value_curve(
            curve,
            marker_pct=-25.0,
            marker_value=400_000.0,
            ips_crash_pct=-25.0,
        )

        curve_trace = fig.data[0]
        assert list(curve_trace.x) == [-30.0, -20.0, 0.0]
        assert list(curve_trace.y) == [500_000.0, 300_000.0, 0.0]
        assert curve_trace.mode == "lines"

    def test_marker_trace_is_single_point(self) -> None:
        curve = [(-30.0, 500_000.0), (-20.0, 300_000.0), (0.0, 0.0)]

        fig = plot_crash_value_curve(
            curve,
            marker_pct=-25.0,
            marker_value=400_000.0,
            ips_crash_pct=-25.0,
        )

        marker_trace = fig.data[1]
        assert list(marker_trace.x) == [-25.0]
        assert list(marker_trace.y) == [400_000.0]
        assert marker_trace.mode == "markers"

    def test_empty_curve_does_not_raise(self) -> None:
        fig = plot_crash_value_curve(
            [],
            marker_pct=-25.0,
            marker_value=0.0,
            ips_crash_pct=-25.0,
        )

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 2
