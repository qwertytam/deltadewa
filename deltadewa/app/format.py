"""Pure string-formatting helpers for the Dash app.

No engine calls, no arithmetic beyond string formatting — this module
turns already-computed numbers into display strings, and interprets
already-computed decision fields into plain language. It never derives
a new number; that stays in ``analysis/``.
"""

from __future__ import annotations

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
