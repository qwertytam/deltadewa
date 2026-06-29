"""Market environment gauge widgets for Tier-2 monitoring.

Provides :func:`build_env_gauges`, which renders a pre-computed
:class:`~deltadewa.analysis.market_environment.MarketEnvironment` as
three horizontal gauge cards using the same
:class:`~deltadewa.widgets.gauges.GaugeIndicator` component used by
:class:`~deltadewa.widgets.health_dashboard.HedgeHealthDashboard`.
"""

from __future__ import annotations

import ipywidgets as widgets

from deltadewa.analysis.market_environment import (
    DataQuality,
    MarketEnvironment,
)
from deltadewa.colours import DEFAULT_PALETTE

from .gauges import GaugeIndicator

# Breakpoints for 0-100 percentile gauges.
# Match the vol_regime config in health_dashboard.py (25 / 50 / 75).
_PCTILE_MIN: float = 25.0
_PCTILE_MID: float = 50.0
_PCTILE_MAX: float = 75.0

# Forward vol scale in annualised vol points.
# 0-12 = low / cheap-hedge contango; 25+ = elevated forward vol.
_FWD_START: float = 0.0
_FWD_END: float = 40.0
_FWD_MIN: float = 12.0
_FWD_MID: float = 18.0
_FWD_MAX: float = 25.0


def _gauge_inner_html(
    actual: float,
    start: float,
    end: float,
    min_val: float,
    mid_val: float,
    max_val: float,
    label_format: str,
    *,
    invert: bool,
) -> str:
    if invert:
        low_color = DEFAULT_PALETTE.positive
        high_color = DEFAULT_PALETTE.negative
    else:
        low_color = DEFAULT_PALETTE.negative
        high_color = DEFAULT_PALETTE.positive
    return (
        GaugeIndicator(
            start=start,
            end=end,
            min_val=min_val,
            mid_val=mid_val,
            max_val=max_val,
            actual=actual,
            low_color=low_color,
            mid_color=DEFAULT_PALETTE.yellow,
            high_color=high_color,
            orientation="horizontal",
            width=280,
            height=25,
            show_actual_label=True,
            show_minmidmax_labels=False,
            show_startend_labels=True,
            label_format=label_format,
            title=None,
        )
        .create_widget()
        .value
    )


def _unavailable_bar() -> str:
    return (
        '<div style="'
        "width:280px;height:25px;background:#e0e0e0;"
        "border-radius:5px;border:1px solid #ccc;"
        "display:flex;align-items:center;justify-content:center;"
        'font-size:14px;color:#999;font-weight:bold;">—</div>'
    )


def _card(title: str, description: str, body_html: str) -> str:
    return (
        '<div style="'
        f"background:{DEFAULT_PALETTE.very_light_grey};"
        "border-radius:8px;padding:12px;margin:8px;"
        "min-width:320px;max-width:360px;"
        'box-shadow:0 2px 4px rgba(0,0,0,0.1);">'
        '<div style="font-weight:bold;font-size:13px;'
        f'color:#333;margin-bottom:8px;">{title}</div>'
        f"{body_html}"
        '<div style="font-size:10px;color:#666;margin-top:8px;">'
        f"{description}</div>"
        "</div>"
    )


def _data_quality_banner(quality: DataQuality) -> str:
    if quality is DataQuality.STATIC:
        return (
            '<div style="font-size:11px;color:#888;'
            'margin:4px 8px 0 8px;">Static / offline data</div>'
        )
    if quality is DataQuality.UNAVAILABLE:
        return (
            '<div style="font-size:11px;color:#c00;'
            'margin:4px 8px 0 8px;">Market data unavailable</div>'
        )
    return ""


def build_env_gauges(env: MarketEnvironment) -> widgets.HTML:
    """Render Tier-2 environment gauges from a pre-computed MarketEnvironment.

    Builds three horizontal gauge cards for vol regime percentile, skew
    percentile, and 1m-3m forward vol, using the same
    :class:`~deltadewa.widgets.gauges.GaugeIndicator` component as
    :class:`~deltadewa.widgets.health_dashboard.HedgeHealthDashboard`.

    Must NOT call the market-data provider or
    :func:`~deltadewa.analysis.market_environment.assess_market_environment`
    again — consume the pre-computed *env* value object only.

    Degradation:
        ``LIVE`` — full colour gauges, no footer.
        ``STATIC`` — full colour gauges with "Static / offline data" caption.
        ``UNAVAILABLE`` — greyed «—» bars with "Market data unavailable"
        caption.

    Args:
        env: Pre-computed ``MarketEnvironment`` snapshot (reuse the
            ``_env`` variable already computed in the notebook).

    Returns:
        ``ipywidgets.HTML`` widget ready for ``display()``.

    """
    unavailable = env.data_quality is DataQuality.UNAVAILABLE

    # --- vol regime percentile (0-100) ---
    if unavailable or env.regime_percentile is None:
        regime_body = _unavailable_bar()
    else:
        regime_body = _gauge_inner_html(
            actual=env.regime_percentile,
            start=0.0,
            end=100.0,
            min_val=_PCTILE_MIN,
            mid_val=_PCTILE_MID,
            max_val=_PCTILE_MAX,
            label_format="{:.0f}",
            invert=True,
        )
    regime_card = _card(
        "Vol Regime Percentile",
        "VIX historical percentile (0 = low vol, 100 = high vol)",
        regime_body,
    )

    # --- skew percentile (provider returns 0-1; display as 0-100) ---
    if unavailable or env.skew_percentile is None:
        skew_body = _unavailable_bar()
    else:
        skew_body = _gauge_inner_html(
            actual=env.skew_percentile * 100.0,
            start=0.0,
            end=100.0,
            min_val=_PCTILE_MIN,
            mid_val=_PCTILE_MID,
            max_val=_PCTILE_MAX,
            label_format="{:.0f}",
            invert=True,
        )
    skew_card = _card(
        "Skew Percentile",
        "CBOE SKEW rank - higher = more expensive puts",
        skew_body,
    )

    # --- forward vol 1m-3m (vol points) ---
    if unavailable or env.forward_vol_front_3m is None:
        fwd_body = _unavailable_bar()
    else:
        fwd_body = _gauge_inner_html(
            actual=env.forward_vol_front_3m,
            start=_FWD_START,
            end=_FWD_END,
            min_val=_FWD_MIN,
            mid_val=_FWD_MID,
            max_val=_FWD_MAX,
            label_format="{:.1f}",
            invert=True,
        )
    fwd_card = _card(
        "Forward Vol 1m-3m",
        "Implied forward vol between VIX and VIX3M tenors (vol pts)",
        fwd_body,
    )

    row = (
        '<div style="'
        "font-family:-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,sans-serif;"
        'display:flex;flex-wrap:wrap;justify-content:flex-start;">'
        f"{regime_card}{skew_card}{fwd_card}"
        "</div>"
    )
    banner = _data_quality_banner(env.data_quality)
    return widgets.HTML(value=row + banner)
