"""Plotly Monte Carlo P&L distribution chart for the Dash /design page.

Separate from :mod:`deltadewa.visualization.crash_charts_plotly` only in
subject matter -- a chart builder over already-computed numbers (a
:class:`~deltadewa.analysis.stress.PnlHistogram` and
:class:`~deltadewa.analysis.stress.EmpiricalCdf`), no portfolio, engine,
or Monte Carlo access here, matplotlib never imported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.portfolio.monte_carlo import drift_measure_label

if TYPE_CHECKING:
    from deltadewa.analysis.stress import EmpiricalCdf, PnlHistogram

_EXPECTED_COLOR = DEFAULT_PALETTE.medium_background
_VAR_COLOR = DEFAULT_PALETTE.orange
_CVAR_COLOR = DEFAULT_PALETTE.negative
_PROFIT_COLOR = DEFAULT_PALETTE.call
_LOSS_COLOR = DEFAULT_PALETTE.negative
_MEDIAN_COLOR = DEFAULT_PALETTE.medium_grey
_CDF_LINE_COLOR = DEFAULT_PALETTE.dark_background

# #332: Plotly defaults every add_vline annotation to the same vertical
# spot (the top of the axis), so with a tail-hedge book's tail statistics
# clustered together, the PDF panel's up-to-four labels reliably collide.
# Each successive annotation shifts down by this many pixels from "top" --
# staggered by *insertion order*, not by a fixed per-metric slot, since
# CVaR and worst-case are each conditionally present and any subset must
# still read correctly. The start offset is not 0: "top" (yshift=0) is
# the same row `make_subplots`' own subplot-title annotation occupies, so
# the first line needs to already clear that before staggering begins.
_PDF_ANNOTATION_YSHIFT_START = -34
_PDF_ANNOTATION_YSHIFT_STEP = -22

# #332: "bottom" (yshift=0) sits exactly on the x-axis line, on top of its
# tick labels and title -- this lifts the CDF panel's one annotation clear
# of that text while staying below the curve, which is what "bottom"
# is for.
_CDF_ANNOTATION_YSHIFT = 55


def plot_pnl_distribution(  # pylint: disable=too-many-arguments,too-many-locals
    *,
    histogram: PnlHistogram,
    empirical_cdf: EmpiricalCdf,
    expected_pnl: float,
    median_pnl: float,
    var_95: float,
    cvar_95: float,
    max_loss: float,
    is_concentrated: bool,
    most_common_pnl: tuple[float, int] | None,
    concentration_pct: float,
    expected_percentile: float,
    drift_measure: str,
) -> go.Figure:
    """Build the two-panel Monte Carlo P&L distribution chart.

    Consumes :func:`~deltadewa.analysis.stress.compute_pnl_histogram` and
    :func:`~deltadewa.analysis.stress.compute_empirical_cdf`'s output
    plus the scalar statistics from
    ``OptionPortfolioBase.run_monte_carlo_simulation``'s results dict --
    no portfolio or Monte Carlo access here, purely a chart builder over
    already-computed numbers.

    Left panel: a PDF bar histogram, bars colored by sign (loss/profit --
    already a red/blue split, not red/green, so no CVD change was needed
    there), with reference lines at the expected value, 95% VaR, 95%
    CVaR (when informative), and the worst simulated case. Right panel:
    the empirical CDF, with 5th-percentile and median crosshairs and the
    expected value's own percentile reading.

    ``drift_measure`` (``"risk_neutral"`` or ``"real_world"``) is baked
    into the expected-value trace's own label via
    :func:`~deltadewa.portfolio.monte_carlo.drift_measure_label` -- M1.3's
    requirement that a probability derived from the simulation is never
    presented as a bare "probability of profit" without naming the drift
    assumption behind it.

    Args:
        histogram: Binned P&L density from ``compute_pnl_histogram``.
        empirical_cdf: The sorted sample and its CDF from
            ``compute_empirical_cdf``.
        expected_pnl: Mean simulated P&L.
        median_pnl: Median simulated P&L.
        var_95: 95% Value at Risk (5th percentile P&L).
        cvar_95: 95% Conditional VaR (mean of the worst 5%).
        max_loss: Worst (most negative) simulated P&L; ``0`` or positive
            when no simulation lost money.
        is_concentrated: Whether the distribution is concentrated (many
            paths landing on the same rounded outcome).
        most_common_pnl: ``(value, count)`` of the modal outcome, or
            ``None``.
        concentration_pct: Percent of paths at the modal outcome.
        expected_percentile: Where ``expected_pnl`` sits on the
            empirical CDF, in ``[0, 1]`` -- from
            :func:`~deltadewa.analysis.stress.percentile_of_value`.
        drift_measure: The GBM drift measure the simulation used.

    Returns:
        A Plotly ``Figure`` with two subplots.

    """
    drift_label = drift_measure_label(drift_measure)
    pdf_title = "Monte Carlo P&L distribution" + (
        " (concentrated)" if is_concentrated else ""
    )

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=(pdf_title, "Empirical CDF"),
    )

    colors = [
        _LOSS_COLOR if center < 0 else _PROFIT_COLOR
        for center in histogram.bin_centers
    ]
    fig.add_trace(
        go.Bar(
            x=histogram.bin_centers,
            y=histogram.density,
            width=histogram.bin_width * 0.9,
            marker_color=colors,
            name="P&L density",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    # #332: staggered by insertion order (see _PDF_ANNOTATION_YSHIFT_STEP)
    # so no two of the up to four labels below land on the same row,
    # regardless of which of the two conditional ones actually render.
    next_pdf_yshift = _PDF_ANNOTATION_YSHIFT_START
    fig.add_vline(
        x=expected_pnl,
        line_dash="dash",
        line_color=_EXPECTED_COLOR,
        annotation_text=f"Expected: ${expected_pnl:,.0f}",
        annotation_position="top",
        annotation_yshift=next_pdf_yshift,
        row=1,
        col=1,
    )
    next_pdf_yshift += _PDF_ANNOTATION_YSHIFT_STEP
    fig.add_vline(
        x=var_95,
        line_dash="dash",
        line_color=_VAR_COLOR,
        annotation_text=f"95% VaR: ${var_95:,.0f}",
        annotation_position="top",
        annotation_yshift=next_pdf_yshift,
        row=1,
        col=1,
    )
    if cvar_95 < expected_pnl:
        next_pdf_yshift += _PDF_ANNOTATION_YSHIFT_STEP
        fig.add_vline(
            x=cvar_95,
            line_dash="dash",
            line_color=_CVAR_COLOR,
            annotation_text=f"95% CVaR: ${cvar_95:,.0f}",
            annotation_position="top",
            annotation_yshift=next_pdf_yshift,
            row=1,
            col=1,
        )
    if max_loss < 0:
        next_pdf_yshift += _PDF_ANNOTATION_YSHIFT_STEP
        fig.add_vline(
            x=max_loss,
            line_dash="dot",
            line_color=_CVAR_COLOR,
            annotation_text=f"Worst case: ${max_loss:,.0f}",
            annotation_position="top",
            annotation_yshift=next_pdf_yshift,
            row=1,
            col=1,
        )
    if is_concentrated and most_common_pnl is not None:
        fig.add_annotation(
            text=(
                f"Most common: ${most_common_pnl[0]:,.2f}<br>"
                f"({concentration_pct:.1f}% of scenarios)"
            ),
            xref="x domain",
            yref="y domain",
            x=0.02,
            y=0.98,
            showarrow=False,
            align="left",
            bgcolor="rgba(255, 235, 180, 0.8)",
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=empirical_cdf.sorted_pnls,
            y=empirical_cdf.cdf,
            mode="lines",
            line={"color": _CDF_LINE_COLOR, "width": 2.5},
            name="Empirical CDF",
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    fig.add_hline(
        y=0.05,
        line_dash="dash",
        line_color=_VAR_COLOR,
        row=1,
        col=2,
    )
    fig.add_vline(
        x=var_95,
        line_dash="dash",
        line_color=_VAR_COLOR,
        row=1,
        col=2,
    )
    fig.add_hline(
        y=0.50,
        line_dash="dot",
        line_color=_MEDIAN_COLOR,
        row=1,
        col=2,
    )
    fig.add_vline(
        x=median_pnl,
        line_dash="dot",
        line_color=_MEDIAN_COLOR,
        row=1,
        col=2,
    )
    fig.add_vline(
        x=expected_pnl,
        line_dash="dash",
        line_color=_EXPECTED_COLOR,
        annotation_text=(
            f"Expected (~{expected_percentile * 100:.0f}th %ile, "
            f"{drift_label} drift)"
        ),
        # #332: the CDF curve asymptotes toward 1.0 at the top of this
        # axis, so the default top placement lands the label directly on
        # the line. The bottom is empty by the same logic -- the yshift
        # lifts it clear of the x-axis's own tick labels and title,
        # which otherwise sit in that same bottom-of-plot spot.
        annotation_position="bottom",
        annotation_yshift=_CDF_ANNOTATION_YSHIFT,
        row=1,
        col=2,
    )

    fig.update_xaxes(title_text="P&L ($)", tickprefix="$", row=1, col=1)
    fig.update_yaxes(title_text="Probability density", row=1, col=1)
    fig.update_xaxes(title_text="P&L ($)", tickprefix="$", row=1, col=2)
    fig.update_yaxes(
        title_text="Cumulative probability",
        tickformat=".0%",
        row=1,
        col=2,
    )
    fig.update_layout(showlegend=False)
    return fig
