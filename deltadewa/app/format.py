"""Pure string-formatting helpers for the Dash app.

No engine calls, no arithmetic beyond string formatting — this module
turns already-computed numbers into display strings, and interprets
already-computed decision fields into plain language. It never derives
a new number; that stays in ``analysis/``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deltadewa.analysis.roll_status import RollStatusRecord


def currency(value: float, *, decimals: int = 0) -> str:
    """Format *value* as currency, e.g. ``"$1,234,567"``.

    Args:
        value: A dollar amount.
        decimals: Number of decimal places to show. Defaults to ``0``
            (whole dollars) — the right default for large notional
            figures; pass ``decimals=2`` where cent-level precision
            matters (e.g. reproducing an engine value exactly).

    Returns:
        The formatted string, rounded to *decimals* places.

    """
    return f"${value:,.{decimals}f}"


def signed_currency(value: float) -> str:
    """Format *value* as signed whole-dollar currency.

    Args:
        value: A dollar amount. Zero renders with a leading ``+``.

    Returns:
        E.g. ``"+$45,000"`` or ``"-$12,300"``.

    """
    return f"{'+' if value >= 0 else '-'}${abs(value):,.0f}"


def percent(value: float, *, decimals: int = 1) -> str:
    """Format *value* (already a percentage number) as a percent string.

    Args:
        value: A percentage number, e.g. ``12.3`` for 12.3%, not ``0.123``.
        decimals: Number of decimal places to show.

    Returns:
        E.g. ``"12.3%"``.

    """
    return f"{value:.{decimals}f}%"


def signed_percent(value: float, *, decimals: int = 1) -> str:
    """Format *value* as a signed percent string.

    Args:
        value: A percentage number, e.g. ``12.3`` for 12.3%. Zero renders
            with a leading ``+``.
        decimals: Number of decimal places to show.

    Returns:
        E.g. ``"+12.3%"`` or ``"-4.5%"``.

    """
    return f"{value:+.{decimals}f}%"


def _round_sig_figs(value: float, sig_figs: int = 3) -> float:
    """Round *value* to *sig_figs* significant figures."""
    if value == 0:
        return 0.0
    exponent = math.floor(math.log10(abs(value)))
    factor: float = 10 ** (sig_figs - 1 - exponent)
    return round(value * factor) / factor


_COMPACT_UNITS: tuple[tuple[float, str], ...] = (
    (1_000_000_000, "B"),
    (1_000_000, "M"),
    (1_000, "K"),
)


def _compact_parts(value: float) -> tuple[float, str, int]:
    """Split *value* into a compact (scaled, suffix, decimals) triple.

    Rounds to 3 significant figures first, then picks the K/M/B unit
    from the *rounded* magnitude, not the pre-round magnitude — a value
    like 999,500 rounds to 1,000,000 and must present as ``"1.00M"``,
    not ``"1000K"``.
    """
    rounded = _round_sig_figs(value)
    magnitude = abs(rounded)
    divisor, suffix = next(
        ((d, s) for d, s in _COMPACT_UNITS if magnitude >= d),
        (1, ""),
    )
    scaled = rounded / divisor
    decimals = 0 if abs(scaled) >= 100 else (1 if abs(scaled) >= 10 else 2)
    return scaled, suffix, decimals


def compact_currency(value: float) -> str:
    """Format *value* as currency to 3 significant figures.

    Args:
        value: A dollar amount.

    Returns:
        E.g. ``"$5.23M"``, ``"$823K"``, ``"$942"``. Exact values belong
        in a ``title`` tooltip or a detail table — this is for headline
        numbers a reader should absorb at a glance, not reproduce to
        the cent.

    """
    scaled, suffix, decimals = _compact_parts(value)
    return f"${scaled:,.{decimals}f}{suffix}"


def signed_compact_currency(value: float) -> str:
    """Format *value* as signed currency to 3 significant figures.

    Args:
        value: A dollar amount. Zero renders with a leading ``+``.

    Returns:
        E.g. ``"+$5.23M"`` or ``"-$823K"``.

    """
    scaled, suffix, decimals = _compact_parts(abs(value))
    sign = "+" if value >= 0 else "-"
    return f"{sign}${scaled:,.{decimals}f}{suffix}"


def roll_verdict_reason(record: RollStatusRecord) -> str:
    """Return the plain-language reason driving ``record.verdict``.

    Matches ``record.verdict`` against the three per-trigger verdicts
    (``time_trigger``, ``convexity_trigger``, ``drift_trigger``) and
    returns that trigger's ``.reason``. When ``record.suppressed`` is
    ``True`` — or, defensively, when none of the three verdicts match
    ``record.verdict`` — this is the roll-suppression case, and a
    sentence naming the suppression explicitly is returned instead.

    Args:
        record: One position's roll status record.

    Returns:
        A one-sentence, human-readable explanation of the verdict.

    """
    if not record.suppressed:
        for trigger in (
            record.time_trigger,
            record.convexity_trigger,
            record.drift_trigger,
        ):
            if trigger.verdict == record.verdict:
                return trigger.reason

    return (
        "Strike drift alone flagged a roll, but convexity is in-band "
        "and there's no time pressure, so this is held at "
        f"{record.verdict.value}."
    )
