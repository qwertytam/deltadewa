"""Tests for deltadewa.visualization.stress_charts_plotly."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from deltadewa.visualization.stress_charts_plotly import (
    STRESS_METRICS,
    plot_spot_vol_heatmap,
    plot_time_price_heatmap,
)

_SPOT_SCENARIOS = np.array([4000.0, 4500.0, 5000.0, 5500.0, 6000.0])
_VOL_SCENARIOS = np.array([0.15, 0.20, 0.25, 0.30, 0.35])
_ORIGINAL_SPOT = 5000.0
_AVG_VOL = 0.25


def _spot_vol_df() -> pd.DataFrame:
    rows = [
        {
            "spot_price": spot,
            "volatility": vol,
            "value": (spot - _ORIGINAL_SPOT) - (vol - _AVG_VOL) * 100_000,
        }
        for vol in _VOL_SCENARIOS
        for spot in _SPOT_SCENARIOS
    ]
    return pd.DataFrame(rows)


def _time_price_df() -> pd.DataFrame:
    rows = [
        {"spot_price": spot, "days_forward": days, "value": spot - days * 10}
        for days in (0, 30, 90)
        for spot in _SPOT_SCENARIOS
    ]
    return pd.DataFrame(rows)


class TestPlotSpotVolHeatmap:
    """Tests for plot_spot_vol_heatmap."""

    def test_uses_cvd_safe_colorscale_not_ryg(self) -> None:
        fig = plot_spot_vol_heatmap(
            _spot_vol_df(),
            spot_scenarios=_SPOT_SCENARIOS,
            vol_scenarios=_VOL_SCENARIOS,
            original_spot=_ORIGINAL_SPOT,
            avg_vol=_AVG_VOL,
            metric="pnl",
        )

        heatmap = fig.data[0]
        assert heatmap.colorscale is not None
        colorscale_repr = str(heatmap.colorscale).lower()
        assert "rdylgn" not in colorscale_repr

    def test_diverging_scale_centered_at_zero(self) -> None:
        fig = plot_spot_vol_heatmap(
            _spot_vol_df(),
            spot_scenarios=_SPOT_SCENARIOS,
            vol_scenarios=_VOL_SCENARIOS,
            original_spot=_ORIGINAL_SPOT,
            avg_vol=_AVG_VOL,
            metric="pnl",
        )

        assert fig.data[0].zmid == pytest.approx(0.0)

    def test_y_axis_labelled_as_absolute_level_not_bump(self) -> None:
        fig = plot_spot_vol_heatmap(
            _spot_vol_df(),
            spot_scenarios=_SPOT_SCENARIOS,
            vol_scenarios=_VOL_SCENARIOS,
            original_spot=_ORIGINAL_SPOT,
            avg_vol=_AVG_VOL,
            metric="pnl",
        )

        title = fig.layout.yaxis.title.text.lower()
        assert "level" in title
        assert "bump" not in title

    def test_marks_current_position_and_reference_lines(self) -> None:
        fig = plot_spot_vol_heatmap(
            _spot_vol_df(),
            spot_scenarios=_SPOT_SCENARIOS,
            vol_scenarios=_VOL_SCENARIOS,
            original_spot=_ORIGINAL_SPOT,
            avg_vol=_AVG_VOL,
            metric="pnl",
        )

        marker_trace = next(
            trace for trace in fig.data if trace.name == "Current position"
        )
        assert list(marker_trace.x) == [_ORIGINAL_SPOT]
        assert list(marker_trace.y) == [_AVG_VOL]
        assert fig.layout.shapes  # the hline/vline reference lines

    def test_empty_dataframe_renders_placeholder_not_raise(self) -> None:
        empty = pd.DataFrame(columns=["spot_price", "volatility", "value"])

        fig = plot_spot_vol_heatmap(
            empty,
            spot_scenarios=_SPOT_SCENARIOS,
            vol_scenarios=_VOL_SCENARIOS,
            original_spot=_ORIGINAL_SPOT,
            avg_vol=_AVG_VOL,
            metric="pnl",
        )

        assert isinstance(fig, go.Figure)
        assert fig.layout.annotations

    def test_unknown_metric_falls_back_to_pnl_label(self) -> None:
        fig = plot_spot_vol_heatmap(
            _spot_vol_df(),
            spot_scenarios=_SPOT_SCENARIOS,
            vol_scenarios=_VOL_SCENARIOS,
            original_spot=_ORIGINAL_SPOT,
            avg_vol=_AVG_VOL,
            metric="not-a-real-metric",
        )

        assert STRESS_METRICS["pnl"].label in fig.layout.title.text


class TestPlotTimePriceHeatmap:
    """Tests for plot_time_price_heatmap."""

    def test_uses_cvd_safe_colorscale_and_zmid(self) -> None:
        fig = plot_time_price_heatmap(
            _time_price_df(),
            original_spot=_ORIGINAL_SPOT,
            original_date=datetime(2026, 1, 1, tzinfo=UTC),
            metric="pnl",
        )

        heatmap = fig.data[0]
        assert "rdylgn" not in str(heatmap.colorscale).lower()
        assert heatmap.zmid == pytest.approx(0.0)

    def test_cells_carry_text_annotations(self) -> None:
        fig = plot_time_price_heatmap(
            _time_price_df(),
            original_spot=_ORIGINAL_SPOT,
            original_date=datetime(2026, 1, 1, tzinfo=UTC),
            metric="pnl",
        )

        heatmap = fig.data[0]
        assert heatmap.texttemplate == "%{text}"
        text = np.array(heatmap.text)
        assert text.shape == (
            len(_SPOT_SCENARIOS),
            3,
        )  # 3 distinct day offsets
        assert all("$" in cell for row in text for cell in row)

    def test_column_labels_show_today_and_dates(self) -> None:
        fig = plot_time_price_heatmap(
            _time_price_df(),
            original_spot=_ORIGINAL_SPOT,
            original_date=datetime(2026, 1, 1, tzinfo=UTC),
            metric="pnl",
        )

        x_labels = list(fig.data[0].x)
        assert any("Today" in label for label in x_labels)
        assert any("T+30" in label for label in x_labels)
        assert all("2026" in label for label in x_labels)

    def test_row_labels_show_percent_move_from_current(self) -> None:
        fig = plot_time_price_heatmap(
            _time_price_df(),
            original_spot=_ORIGINAL_SPOT,
            original_date=datetime(2026, 1, 1, tzinfo=UTC),
            metric="pnl",
        )

        y_labels = list(fig.data[0].y)
        assert any("~0%" in label for label in y_labels)
        assert any("+" in label for label in y_labels)
        assert any(label.count("-") >= 1 and "$" in label for label in y_labels)

    def test_empty_dataframe_renders_placeholder_not_raise(self) -> None:
        empty = pd.DataFrame(columns=["spot_price", "days_forward", "value"])

        fig = plot_time_price_heatmap(
            empty,
            original_spot=_ORIGINAL_SPOT,
            original_date=datetime(2026, 1, 1, tzinfo=UTC),
            metric="pnl",
        )

        assert isinstance(fig, go.Figure)
        assert fig.layout.annotations
