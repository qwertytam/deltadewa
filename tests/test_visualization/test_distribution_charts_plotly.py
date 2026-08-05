"""Tests for deltadewa.visualization.distribution_charts_plotly."""

import numpy as np
import plotly.graph_objects as go

from deltadewa.analysis.stress import (
    compute_empirical_cdf,
    compute_pnl_histogram,
)
from deltadewa.visualization.distribution_charts_plotly import (
    plot_pnl_distribution,
)

_PNLS = np.concatenate(
    [
        np.random.default_rng(0).normal(1_000.0, 5_000.0, 900),
        np.random.default_rng(1).normal(-8_000.0, 500.0, 100),
    ],
)


def _histogram_and_cdf() -> tuple[object, object]:
    histogram = compute_pnl_histogram(
        _PNLS,
        min_pnl=float(_PNLS.min()),
        max_pnl=float(_PNLS.max()),
        is_concentrated=False,
    )
    return histogram, compute_empirical_cdf(_PNLS)


class TestPlotPnlDistribution:
    """Tests for plot_pnl_distribution."""

    def test_returns_two_subplot_figure(self) -> None:
        histogram, empirical_cdf = _histogram_and_cdf()

        fig = plot_pnl_distribution(
            histogram=histogram,
            empirical_cdf=empirical_cdf,
            expected_pnl=200.0,
            median_pnl=150.0,
            var_95=-7_500.0,
            cvar_95=-8_200.0,
            max_loss=-9_000.0,
            is_concentrated=False,
            most_common_pnl=None,
            concentration_pct=0.0,
            expected_percentile=0.62,
            drift_measure="risk_neutral",
        )

        assert isinstance(fig, go.Figure)
        assert len(fig.layout.annotations) >= 2  # subplot titles
        titles = [ann.text for ann in fig.layout.annotations]
        assert any("Monte Carlo" in title for title in titles)
        assert any("CDF" in title for title in titles)

    def test_bars_colored_by_sign_using_palette_not_red_green(self) -> None:
        histogram, empirical_cdf = _histogram_and_cdf()

        fig = plot_pnl_distribution(
            histogram=histogram,
            empirical_cdf=empirical_cdf,
            expected_pnl=200.0,
            median_pnl=150.0,
            var_95=-7_500.0,
            cvar_95=-8_200.0,
            max_loss=-9_000.0,
            is_concentrated=False,
            most_common_pnl=None,
            concentration_pct=0.0,
            expected_percentile=0.62,
            drift_measure="risk_neutral",
        )

        bar_trace = fig.data[0]
        colors = set(bar_trace.marker.color)
        # Two distinct colours (loss vs profit bins), neither literal green.
        assert len(colors) >= 1
        assert not any(c.lower() in {"green", "#00ff00"} for c in colors)

    def test_expected_line_surfaces_drift_measure_label(self) -> None:
        histogram, empirical_cdf = _histogram_and_cdf()

        fig = plot_pnl_distribution(
            histogram=histogram,
            empirical_cdf=empirical_cdf,
            expected_pnl=200.0,
            median_pnl=150.0,
            var_95=-7_500.0,
            cvar_95=-8_200.0,
            max_loss=-9_000.0,
            is_concentrated=False,
            most_common_pnl=None,
            concentration_pct=0.0,
            expected_percentile=0.62,
            drift_measure="risk_neutral",
        )

        annotation_texts = " ".join(
            ann.text or "" for ann in fig.layout.annotations
        )
        assert "risk-neutral" in annotation_texts
        assert "probability of profit" not in annotation_texts.lower()

    def test_real_world_drift_measure_surfaces_too(self) -> None:
        histogram, empirical_cdf = _histogram_and_cdf()

        fig = plot_pnl_distribution(
            histogram=histogram,
            empirical_cdf=empirical_cdf,
            expected_pnl=200.0,
            median_pnl=150.0,
            var_95=-7_500.0,
            cvar_95=-8_200.0,
            max_loss=-9_000.0,
            is_concentrated=False,
            most_common_pnl=None,
            concentration_pct=0.0,
            expected_percentile=0.62,
            drift_measure="real_world",
        )

        annotation_texts = " ".join(
            ann.text or "" for ann in fig.layout.annotations
        )
        assert "real-world" in annotation_texts

    def test_concentrated_distribution_annotates_modal_outcome(self) -> None:
        histogram, empirical_cdf = _histogram_and_cdf()

        fig = plot_pnl_distribution(
            histogram=histogram,
            empirical_cdf=empirical_cdf,
            expected_pnl=200.0,
            median_pnl=150.0,
            var_95=-7_500.0,
            cvar_95=-8_200.0,
            max_loss=-9_000.0,
            is_concentrated=True,
            most_common_pnl=(0.0, 850),
            concentration_pct=85.0,
            expected_percentile=0.62,
            drift_measure="risk_neutral",
        )

        annotation_texts = " ".join(
            ann.text or "" for ann in fig.layout.annotations
        )
        assert "Most common" in annotation_texts
        assert "concentrated" in fig.layout.annotations[0].text.lower()

    def test_worst_case_line_omitted_when_no_losses(self) -> None:
        histogram, empirical_cdf = _histogram_and_cdf()

        fig = plot_pnl_distribution(
            histogram=histogram,
            empirical_cdf=empirical_cdf,
            expected_pnl=200.0,
            median_pnl=150.0,
            var_95=100.0,
            cvar_95=50.0,
            max_loss=0.0,
            is_concentrated=False,
            most_common_pnl=None,
            concentration_pct=0.0,
            expected_percentile=0.62,
            drift_measure="risk_neutral",
        )

        annotation_texts = " ".join(
            ann.text or "" for ann in fig.layout.annotations
        )
        assert "Worst case" not in annotation_texts
