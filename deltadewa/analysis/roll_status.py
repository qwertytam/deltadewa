"""Per-tranche roll status evaluation driven by ips.yaml thresholds.

Combines existing health metrics (crash convexity) with new entry-tracking
data (``OptionPosition.entry_spot``/``entry_date``) to produce a
HOLD/MONITOR/REVIEW/ROLL verdict for every position in a portfolio.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from deltadewa import constants as const
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.constants import OptionType
from deltadewa.valuation import OptionValuation

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


class RollVerdict(StrEnum):
    """Per-tranche roll recommendation, in increasing order of urgency."""

    HOLD = "HOLD"
    MONITOR = "MONITOR"
    REVIEW = "REVIEW"
    ROLL = "ROLL"


_SEVERITY: dict[RollVerdict, int] = {
    RollVerdict.HOLD: 0,
    RollVerdict.MONITOR: 1,
    RollVerdict.REVIEW: 2,
    RollVerdict.ROLL: 3,
}


@dataclass(frozen=True)
class MoneynessDrift:
    """%OTM at entry vs now, and the drift between them.

    %OTM is signed so positive always means "out of the money": for a
    CALL, ``(strike - spot) / spot * 100``; for a PUT,
    ``(spot - strike) / spot * 100``.
    """

    entry_otm_pct: float | None
    current_otm_pct: float
    drift_pct: float | None


@dataclass(frozen=True)
class RollStatusRecord:
    """One row of the roll status table — one option tranche."""

    position: OptionPosition
    moneyness: MoneynessDrift
    days_to_maturity: int
    roll_window_days: int
    crash_convexity_pct: float
    convexity_target_min_pct: float
    convexity_target_max_pct: float
    verdict: RollVerdict
    estimated_roll_up_cost: float | None


def _otm_pct(option_type: OptionType, spot: float, strike: float) -> float:
    if option_type == OptionType.CALL:
        return (strike - spot) / spot * 100
    return (spot - strike) / spot * 100


def compute_moneyness_drift(
    position: OptionPosition,
    current_spot: float,
) -> MoneynessDrift:
    """Compute %OTM at entry vs now for *position*.

    Returns ``entry_otm_pct=None`` and ``drift_pct=None`` when the position
    has no recorded ``entry_spot`` (e.g. imported from a file predating
    entry tracking).
    """
    current_otm_pct = _otm_pct(
        position.option.option_type,
        current_spot,
        position.option.strike_price,
    )

    if position.entry_spot is None:
        return MoneynessDrift(
            entry_otm_pct=None,
            current_otm_pct=current_otm_pct,
            drift_pct=None,
        )

    entry_otm_pct = _otm_pct(
        position.option.option_type,
        position.entry_spot,
        position.option.strike_price,
    )
    return MoneynessDrift(
        entry_otm_pct=entry_otm_pct,
        current_otm_pct=current_otm_pct,
        drift_pct=current_otm_pct - entry_otm_pct,
    )


def estimate_roll_up_cost(
    position: OptionPosition,
    new_strike: float,
    vol: float,
) -> float:
    """Estimate the cash cost of rolling *position* to *new_strike*.

    Prices a same-maturity option at *new_strike* using *vol* and the
    position's current spot/rate/dividend/valuation date (i.e.
    ``position.option``'s current market snapshot), and returns
    ``(new_price - current_price) * quantity * contract_size``. Positive
    means the roll costs money; negative means it's a credit.
    """
    new_option = OptionValuation(
        spot_price=position.option.spot_price,
        strike_price=new_strike,
        maturity_date=position.option.maturity_date,
        volatility=vol,
        risk_free_rate=position.option.risk_free_rate,
        dividend_yield=position.option.dividend_yield,
        option_type=position.option.option_type,
        valuation_date=position.option.valuation_date,
        exercise_style=position.exercise_style,
    )
    multiplier = position.quantity * position.contract_size
    return (new_option.price() - position.option.price()) * multiplier


def _time_trigger_verdict(
    days_to_maturity: int,
    roll_window_days: float,
    review_buffer: float,
) -> RollVerdict:
    if days_to_maturity <= roll_window_days:
        return RollVerdict.ROLL
    if days_to_maturity <= roll_window_days * review_buffer:
        return RollVerdict.REVIEW
    return RollVerdict.HOLD


def _convexity_trigger_verdict(
    crash_convexity_pct: float,
    target_min_pct: float,
    target_max_pct: float,
) -> RollVerdict:
    if crash_convexity_pct < target_min_pct:
        return RollVerdict.ROLL
    if crash_convexity_pct > target_max_pct:
        return RollVerdict.MONITOR
    return RollVerdict.HOLD


def _strike_drift_trigger_verdict(
    drift_pct: float | None,
    max_otm_drift_pct: float,
    review_fraction: float,
) -> RollVerdict:
    if drift_pct is None:
        return RollVerdict.HOLD
    abs_drift = abs(drift_pct)
    if abs_drift > max_otm_drift_pct:
        return RollVerdict.ROLL
    if abs_drift > max_otm_drift_pct * review_fraction:
        return RollVerdict.REVIEW
    return RollVerdict.HOLD


def new_strike_for_entry_otm(
    option_type: OptionType,
    current_spot: float,
    entry_otm_pct: float,
) -> float:
    """Return the strike that restores entry OTM% at *current_spot*.

    Args:
        option_type: PUT or CALL.
        current_spot: Current underlying spot price.
        entry_otm_pct: Percent OTM recorded at position entry (positive).

    Returns:
        Strike price that places the option at *entry_otm_pct* OTM from
        *current_spot*.

    """
    if option_type == OptionType.CALL:
        return current_spot * (1 + entry_otm_pct / 100)
    return current_spot * (1 - entry_otm_pct / 100)


def evaluate_roll_status(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    current_spot: float | None = None,
) -> list[RollStatusRecord]:
    """Evaluate roll status for every position in *portfolio*.

    Args:
        portfolio: Live OptionPortfolio to evaluate.
        ips_config: Hedge program policy (see deltadewa.ips_config).
        current_spot: Spot price to evaluate against. Defaults to
            portfolio.spot_price.

    Returns:
        One RollStatusRecord per position, in portfolio.positions order.

    """
    if current_spot is None:
        current_spot = portfolio.spot_price

    triggers = ips_config.triggers
    convexity = ips_config.convexity
    roll_window_days = triggers.roll_time_months * const.CALENDAR_DAYS_PER_MONTH

    analyzer = PortfolioAnalyzer(portfolio)
    # Source the whole crash basis from the IPS so the roll trigger's convexity
    # matches the health gauge / scenario table exactly; passing spot-only
    # (vol_shock=0) understated convexity and biased the roll toward firing.
    # The band below is read straight off `convexity` — pricing and policy
    # travel separately by design.
    crash_convexity_pct = analyzer.calculate_crash_convexity_pct(
        CrashShock.from_ips(convexity),
    )

    # Measure DTE against the portfolio's (what-if) valuation date, not the
    # wall clock, so moving the valuation date moves every roll verdict.
    as_of = portfolio.valuation_date
    records: list[RollStatusRecord] = []

    for position in portfolio.positions:
        days_to_maturity = (position.option.maturity_date - as_of).days

        time_verdict = _time_trigger_verdict(
            days_to_maturity,
            roll_window_days,
            triggers.roll_review_buffer,
        )
        convexity_verdict = _convexity_trigger_verdict(
            crash_convexity_pct,
            convexity.target_min_pct,
            convexity.target_max_pct,
        )
        moneyness = compute_moneyness_drift(position, current_spot)
        drift_verdict = _strike_drift_trigger_verdict(
            moneyness.drift_pct,
            triggers.strike_drift_max_otm_pct,
            triggers.strike_drift_review_fraction,
        )

        verdict = max(
            (time_verdict, convexity_verdict, drift_verdict),
            key=lambda v: _SEVERITY[v],
        )

        # Gamma/theta nuance: a put that has moved nearer the money is
        # gaining convexity on its own. If there's no time pressure and
        # crash convexity is still within target, don't force a roll that
        # was only triggered by strike drift.
        if (  # pylint: disable=too-many-boolean-expressions  # six independent roll-suppression guards; decomposing would obscure the policy
            verdict == RollVerdict.ROLL
            and position.option.option_type == OptionType.PUT
            and time_verdict != RollVerdict.ROLL
            and moneyness.drift_pct is not None
            and moneyness.drift_pct < 0
            and convexity_verdict == RollVerdict.HOLD
        ):
            verdict = RollVerdict.MONITOR

        estimated_roll_up_cost = None
        if (
            verdict in (RollVerdict.REVIEW, RollVerdict.ROLL)
            and moneyness.entry_otm_pct is not None
        ):
            new_strike = new_strike_for_entry_otm(
                position.option.option_type,
                current_spot,
                moneyness.entry_otm_pct,
            )
            estimated_roll_up_cost = estimate_roll_up_cost(
                position,
                new_strike,
                position.option.volatility,
            )

        records.append(
            RollStatusRecord(
                position=position,
                moneyness=moneyness,
                days_to_maturity=days_to_maturity,
                roll_window_days=int(roll_window_days),
                crash_convexity_pct=crash_convexity_pct,
                convexity_target_min_pct=convexity.target_min_pct,
                convexity_target_max_pct=convexity.target_max_pct,
                verdict=verdict,
                estimated_roll_up_cost=estimated_roll_up_cost,
            ),
        )

    return records
