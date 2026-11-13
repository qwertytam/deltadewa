"""A strike ladder as an object: rungs plus weights, sized and scored as one.

Handbook `Strike Selection
<https://qwertytam.github.io/deltadewa-handbook/part-7/strike-selection/>`_
describes a ladder as **layers of protection across several strikes** --
35/40/25 across 20/30/40% OTM -- judged on how the blend trades convexity
against carry and on how it covers the crash spectrum, not on any one rung
alone. :mod:`~deltadewa.analysis.strike_ladder` builds the *candidate
browser*: every (delta, maturity) cell sized to meet the whole crash offset
by itself (#410). This module is the other half: it composes rungs into a
weighted ladder and prepares it to be scored as a unit.

Three rules keep it from becoming a second grader:

* **Sized on the sizing workbench's target.** The offset, carry budget and
  crash basis come from :func:`~deltadewa.analysis.sizing.sizing_basis`,
  the same builder :func:`~deltadewa.analysis.sizing.size_hedge` uses, so a
  one-rung ladder reproduces ``size_hedge``'s contract count exactly and a
  ladder is comparable with a single candidate.
* **Scored by the existing graders, on a shadow book.**
  :func:`materialize_ladder` turns a sized ladder into an
  :class:`~deltadewa.portfolio.core.OptionPortfolio` holding those legs
  against the live book's underlying. The compliance strip's graders and
  ``build_scenario``'s efficiency then score it unchanged. No convexity
  formula lives here.
* **Combined figures are valuations summed, never percentages summed.** A
  ladder's combined gain is ``V_crash - V_today`` over *all* its legs
  (:func:`~deltadewa.analysis.crash_repricing.crash_convexity_pct` on the
  shadow book). The per-rung gains in :class:`DepthRow` are computed
  separately and must add up to it; a test pins that, because summing
  across strikes is exactly the reduction that can silently go wrong
  (#334).

Signs: every rung is a **long put** (``contracts >= 0``, validated), so each
rung's crash gain is non-negative and summing across rungs cannot net a
gain against a loss. A book's short or non-put legs are not rungs;
:func:`ladder_from_book` counts them in ``excluded_leg_count`` rather than
folding them in with a sign.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from deltadewa import constants as const
from deltadewa.analysis.candidate import CandidateMetrics, evaluate_candidate
from deltadewa.analysis.crash_payoff import STANDARD_SCENARIO_SHOCKS
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_convexity_pct,
    crash_hedge_value,
    hedge_value,
    partition_expired_legs,
)
from deltadewa.analysis.sizing import SizingBasis, size_from_unit, sizing_basis
from deltadewa.clock import days_between
from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.ips_config import (
        IpsConfig,
        IpsMaturitySelection,
        IpsStrikeLadder,
    )

# Decimal places a rung's ``contracts = N * weight`` is rounded to before
# the ceiling is taken. ``100 * 0.35`` is ``35.00000000000001`` in binary
# floating point; without this a clean 35 would round up to 36.
_ALLOCATION_ROUNDING_DP = 9


class LadderSource(StrEnum):
    """Where a proposed ladder's rungs and weights came from."""

    IPS = "ips"
    BOOK = "book"
    OPERATOR = "operator"


@dataclass(frozen=True)
class RungSpec:
    """One proposed rung: a strike, a tenor and a weight.

    Attributes:
        pct_otm: Strike distance below spot, percent. Below 100 (the strike
            must be positive); a held in-the-money put reads negative.
        maturity_years: Time to expiry in years, > 0.
        weight: Relative share of the ladder's contract count, > 0. Only
            the ratios matter -- weights are normalised.
        contracts: A fixed size, when the rung is an *existing* holding
            (:func:`ladder_from_book`). ``None`` means the rung is sized by
            :func:`size_ladder`. A ladder is all-fixed or all-sized.

    """

    pct_otm: float
    maturity_years: float
    weight: float
    contracts: int | None = None

    def __post_init__(self) -> None:
        """Reject values that would make the ladder meaningless."""
        if not math.isfinite(self.pct_otm) or self.pct_otm >= 100.0:
            msg = f"pct_otm must be finite and < 100, got {self.pct_otm!r}"
            raise ValueError(msg)
        if not math.isfinite(self.maturity_years) or self.maturity_years <= 0:
            msg = f"maturity_years must be > 0, got {self.maturity_years!r}"
            raise ValueError(msg)
        if round(self.maturity_years * const.DAYS_PER_YEAR) < 1:
            # Priced on whole calendar days: a tenor under half a day rounds
            # to 0 and the shadow book would treat the leg as already
            # expired -- counting its premium while showing no gain.
            msg = (
                "maturity_years must be at least one calendar day, got "
                f"{self.maturity_years!r}"
            )
            raise ValueError(msg)
        if not math.isfinite(self.weight) or self.weight <= 0:
            msg = f"weight must be > 0, got {self.weight!r}"
            raise ValueError(msg)
        if self.contracts is not None and self.contracts < 0:
            # Long puts only: a negative size would be a short rung, whose
            # gain would net against the others' (#334).
            msg = f"contracts must be >= 0, got {self.contracts!r}"
            raise ValueError(msg)


@dataclass(frozen=True)
class ProposedLadder:
    """An ordered set of rungs with weights -- the object under design.

    Attributes:
        rungs: At least one rung, no two sharing a (strike, tenor) pair.
        source: Where it came from (IPS policy, the live book, the
            operator's own edit).
        excluded_leg_count: Legs of the source book that are not live long
            puts (shorts, calls, expired) and so were left out. Always 0 for an
            IPS or operator ladder.

    """

    rungs: tuple[RungSpec, ...]
    source: LadderSource
    excluded_leg_count: int = 0

    def __post_init__(self) -> None:
        """Require rungs, unique keys, and a consistent sizing mode."""
        if not self.rungs:
            msg = "a ladder needs at least one rung"
            raise ValueError(msg)
        keys = [(r.pct_otm, r.maturity_years) for r in self.rungs]
        if len(set(keys)) != len(keys):
            msg = "a ladder cannot repeat a (pct_otm, maturity_years) rung"
            raise ValueError(msg)
        fixed = [r.contracts is not None for r in self.rungs]
        if any(fixed) and not all(fixed):
            msg = "rungs must be all fixed-size or all sized, not a mix"
            raise ValueError(msg)

    @property
    def is_fixed_size(self) -> bool:
        """Whether every rung carries a held ``contracts`` count."""
        return all(r.contracts is not None for r in self.rungs)

    @property
    def normalized_weights(self) -> tuple[float, ...]:
        """Each rung's weight as a share of the total; sums to 1."""
        total = sum(r.weight for r in self.rungs)
        return tuple(r.weight / total for r in self.rungs)

    @classmethod
    def from_ips(
        cls,
        ladder: IpsStrikeLadder,
        selection: IpsMaturitySelection,
    ) -> ProposedLadder:
        """Build the program's intended ladder from the IPS.

        A rung with no ``maturity_years`` takes
        ``maturity_selection.entry_tenor_years``.
        """
        return cls(
            rungs=tuple(
                RungSpec(
                    pct_otm=rung.pct_otm,
                    maturity_years=(
                        rung.maturity_years
                        if rung.maturity_years is not None
                        else selection.entry_tenor_years
                    ),
                    weight=rung.weight_pct,
                )
                for rung in ladder.rungs
            ),
            source=LadderSource.IPS,
        )


def _partition_book(
    portfolio: OptionPortfolio,
) -> tuple[dict[tuple[float, int], int], int]:
    """Split the book into held long-put rungs and everything else.

    Returns:
        ``(held, outside)``: ``held`` maps (strike, days to expiry) to the
        contracts held; ``outside`` counts the legs that are not live long
        puts -- shorts, calls and expired legs.

    """
    live, expired = partition_expired_legs(
        portfolio.positions,
        valuation_date=portfolio.valuation_date,
    )
    held: dict[tuple[float, int], int] = {}
    outside = len(expired)
    for position in live:
        option = position.option
        if option.option_type != OptionType.PUT or position.quantity <= 0:
            outside += 1
            continue
        days = days_between(portfolio.valuation_date, option.maturity_date)
        key = (round(option.strike_price, 6), days)
        held[key] = held.get(key, 0) + position.quantity
    return held, outside


def legs_outside_ladder(portfolio: OptionPortfolio) -> int:
    """Count the book's legs that a ladder cannot represent.

    Shorts, calls and expired legs. A ladder is long puts only, so when this
    is non-zero the live book and a ladder are not like-for-like: the book's
    figures include these legs, the ladder's cannot. Independent of whether
    the book holds any long put at all, unlike :func:`ladder_from_book`.
    """
    return _partition_book(portfolio)[1]


def ladder_from_book(portfolio: OptionPortfolio) -> ProposedLadder | None:
    """Read the live book's long puts as a fixed-size ladder.

    Legs sharing a strike and expiry are one rung. Weight and ``contracts``
    are the held quantity. Only **live, long puts** become rungs; shorts,
    calls and expired legs are counted in ``excluded_leg_count`` so the
    caller can say what was left out, never netted in with a sign. Per-leg
    volatility is not carried: a rung is repriced at the book's volatility.

    Args:
        portfolio: The live book.

    Returns:
        The held ladder, or ``None`` when the book holds no live long put.

    """
    held, excluded = _partition_book(portfolio)
    if not held:
        return None
    rungs = tuple(
        RungSpec(
            pct_otm=(portfolio.spot_price - strike)
            / portfolio.spot_price
            * 100.0,
            maturity_years=days / const.DAYS_PER_YEAR,
            weight=float(quantity),
            contracts=quantity,
        )
        for (strike, days), quantity in sorted(held.items(), reverse=True)
    )
    return ProposedLadder(
        rungs=rungs,
        source=LadderSource.BOOK,
        excluded_leg_count=excluded,
    )


@dataclass(frozen=True)
class SizedRung:
    """A rung priced and given a whole number of contracts.

    Attributes:
        spec: The rung as proposed.
        metrics: Per-contract pricing and crash economics for this rung,
            from :func:`~deltadewa.analysis.candidate.evaluate_candidate`.
        contracts: Whole contracts held on this rung.

    """

    spec: RungSpec
    metrics: CandidateMetrics
    contracts: int


@dataclass(frozen=True)
class SizedLadder:
    """A ladder priced and sized against the program's target.

    Attributes:
        ladder: The proposal this sizes.
        rungs: One :class:`SizedRung` per proposed rung, same order.
        basis: The target it was sized to (offset, budget, crash basis).
        vol: Volatility override used to price the rungs, or ``None`` for
            the portfolio's own.

    """

    ladder: ProposedLadder
    rungs: tuple[SizedRung, ...]
    basis: SizingBasis
    vol: float | None

    @property
    def total_contracts(self) -> int:
        """Contracts across all rungs."""
        return sum(r.contracts for r in self.rungs)

    @property
    def combined_crash_value(self) -> float:
        """Gross crash value of all contracts, in dollars.

        Sum of long-put values, each non-negative: the quantity sizing
        compares against ``basis.required_crash_offset``.
        """
        return sum(
            r.contracts * r.metrics.per_contract_payoff for r in self.rungs
        )

    @property
    def implied_annual_carry(self) -> float:
        """Annualised theta cost of all contracts, in dollars (positive)."""
        return sum(
            r.contracts * r.metrics.per_contract_carry for r in self.rungs
        )

    @property
    def covers_offset(self) -> bool:
        """Whether the ladder's crash value meets the required offset."""
        return self.combined_crash_value >= self.basis.required_crash_offset

    @property
    def within_budget(self) -> bool:
        """Whether the ladder's carry fits the annual carry budget."""
        return self.implied_annual_carry <= self.basis.carry_budget


def _allocate_contracts(
    total_units: int,
    weights: Sequence[float],
) -> tuple[int, ...]:
    """Split *total_units* across rungs by weight, rounding each **up**.

    Rounding every rung up (never to nearest) guarantees the split's crash
    value is at least the unrounded target, so a rounded ladder can only
    over-cover the offset, never fall short of it. The cost is that the
    split can exceed *total_units* by up to one contract per rung.
    """
    return tuple(
        math.ceil(round(total_units * weight, _ALLOCATION_ROUNDING_DP))
        for weight in weights
    )


def size_ladder(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    ladder: ProposedLadder,
    *,
    vol: float | None = None,
) -> SizedLadder:
    """Price a proposed ladder and size it to the program's target.

    A fixed-size ladder (a held book) keeps its contract counts. Otherwise
    the ladder is sized as one "ladder unit": the weighted-average
    per-contract payoff and carry go through
    :func:`~deltadewa.analysis.sizing.size_from_unit` against the same
    offset and budget :func:`~deltadewa.analysis.sizing.size_hedge` uses,
    giving the total contract count, which is then split by weight (each
    rung rounded up). A one-rung ladder is exactly ``size_hedge``.

    Sized on **gross** payoff (#436, decided 2026-11-13), like
    ``size_hedge``: the ladder's repriced crash value covers the offset, and
    its convexity, graded net of premium, reads a little under it.

    Args:
        portfolio: Live portfolio supplying market data and the underlying.
        ips_config: Policy (budget, drawdown tolerance, crash basis, beta).
        ladder: The proposal.
        vol: Volatility override for pricing the rungs.

    Returns:
        The sized ladder.

    Raises:
        ValueError: When the book has no underlying position.

    """
    basis = sizing_basis(portfolio, ips_config, purpose="ladder sizing")
    metrics = tuple(
        evaluate_candidate(
            portfolio,
            strike=portfolio.spot_price * (1.0 - rung.pct_otm / 100.0),
            maturity_years=rung.maturity_years,
            shock=basis.shock,
            vol=vol,
        )
        for rung in ladder.rungs
    )
    if ladder.is_fixed_size:
        contracts = tuple(r.contracts or 0 for r in ladder.rungs)
    else:
        weights = ladder.normalized_weights
        unit_payoff = sum(
            w * m.per_contract_payoff
            for w, m in zip(weights, metrics, strict=True)
        )
        unit_carry = sum(
            w * m.per_contract_carry
            for w, m in zip(weights, metrics, strict=True)
        )
        total_units = size_from_unit(
            basis.required_crash_offset,
            unit_payoff,
            unit_carry,
            basis.carry_budget,
        ).contracts_needed
        contracts = _allocate_contracts(total_units, weights)
    return SizedLadder(
        ladder=ladder,
        rungs=tuple(
            SizedRung(spec=spec, metrics=m, contracts=n)
            for spec, m, n in zip(ladder.rungs, metrics, contracts, strict=True)
        ),
        basis=basis,
        vol=vol,
    )


def materialize_ladder(
    portfolio: OptionPortfolio,
    sized: SizedLadder,
) -> OptionPortfolio:
    """Hold a sized ladder against the live book's underlying.

    The result is a throwaway shadow book: the live book's market inputs,
    valuation date and underlying, and only the ladder's legs (rungs sized
    to zero contracts are omitted). Every leg is priced at the book's
    volatility (or ``sized.vol``); a held leg's own entered volatility is
    not carried, so a held ladder reads exactly as the book does only where
    its legs sit at book volatility; the composer says so when they do not.

    It exists so the existing graders -- the compliance strip,
    ``build_scenario`` -- can score a proposal with no ladder-specific
    formula. Legs are added in rung order, which
    :func:`ladder_depth_profile` relies on.

    Args:
        portfolio: The live book. Never mutated.
        sized: The ladder to hold.

    Returns:
        A new portfolio holding the ladder's long puts.

    """
    shadow = OptionPortfolio(
        underlying_quantity=portfolio.underlying_quantity,
        spot_price=portfolio.spot_price,
        volatility=portfolio.volatility,
        risk_free_rate=portfolio.risk_free_rate,
        dividend_yield=portfolio.dividend_yield,
        valuation_date=portfolio.valuation_date,
        symbol=portfolio.symbol,
        default_exercise_style=portfolio.default_exercise_style,
        contract_size=portfolio.contract_size,
    )
    for rung in sized.rungs:
        if rung.contracts == 0:
            continue
        shadow.add_position(
            strike_price=rung.metrics.strike,
            maturity_date=portfolio.valuation_date
            + timedelta(
                days=round(rung.spec.maturity_years * const.DAYS_PER_YEAR),
            ),
            quantity=rung.contracts,
            option_type=OptionType.PUT,
            volatility=sized.vol,
        )
    return shadow


@dataclass(frozen=True)
class DepthRow:
    """The ladder's crash gain at one depth, rung by rung and combined.

    Attributes:
        shock_pct: Signed crash depth (e.g. ``-25.0``).
        rung_gains: ``V_crash - V_today`` for each rung's contracts, in
            :attr:`SizedLadder.rungs` order (``0.0`` for an unsized rung).
        combined_gain: ``V_crash - V_today`` over **all** legs together,
            computed directly -- not as ``sum(rung_gains)``, so the two are
            independent and a test can hold one against the other.
        combined_pct_of_book: The strip's convexity figure at this depth
            (:func:`~deltadewa.analysis.crash_repricing.crash_convexity_pct`
            on the shadow book).
        is_ips_depth: Whether this is the IPS crash depth -- the only depth
            the convexity band speaks to. Every other row is shown, never
            graded.

    """

    shock_pct: float
    rung_gains: tuple[float, ...]
    combined_gain: float
    combined_pct_of_book: float | None
    is_ips_depth: bool


def profile_depths(shock: CrashShock) -> tuple[float, ...]:
    """Return the depths a ladder is read at: the handbook's plus the IPS one.

    Ordered mild to severe, the scenario table's own order.
    """
    depths = {*STANDARD_SCENARIO_SHOCKS, round(shock.crash_scenario_pct, 6)}
    return tuple(sorted(depths, reverse=True))


def ladder_depth_profile(
    shadow: OptionPortfolio,
    sized: SizedLadder,
    *,
    shock: CrashShock,
    depths: Sequence[float],
) -> tuple[DepthRow, ...]:
    """Read a sized ladder's crash gain across depths, per rung and combined.

    Args:
        shadow: The ladder held as a book (:func:`materialize_ladder`).
        sized: The ladder that produced *shadow*.
        shock: The crash basis; each row re-aims it with ``at_pct`` so the
            vol and skew basis is identical at every depth.
        depths: Signed crash depths to read.

    Returns:
        One :class:`DepthRow` per depth, in the order given.

    Raises:
        ValueError: When *shadow* does not hold exactly the legs of
            *sized*'s non-empty rungs.

    """
    live_rungs = [i for i, r in enumerate(sized.rungs) if r.contracts > 0]
    if len(shadow.positions) != len(live_rungs):
        msg = (
            f"shadow book holds {len(shadow.positions)} legs but the ladder "
            f"has {len(live_rungs)} non-empty rungs"
        )
        raise ValueError(msg)
    legs = dict(zip(live_rungs, shadow.positions, strict=True))
    today_by_rung = {
        i: hedge_value(shadow, positions=[leg]) for i, leg in legs.items()
    }
    today_all = hedge_value(shadow)
    ips_depth = round(shock.crash_scenario_pct, 6)

    rows: list[DepthRow] = []
    for depth in depths:
        at_depth = shock.at_pct(depth)
        gains = tuple(
            (
                crash_hedge_value(shadow, shock=at_depth, positions=[legs[i]])
                - today_by_rung[i]
                if i in legs
                else 0.0
            )
            for i in range(len(sized.rungs))
        )
        rows.append(
            DepthRow(
                shock_pct=depth,
                rung_gains=gains,
                combined_gain=crash_hedge_value(shadow, shock=at_depth)
                - today_all,
                combined_pct_of_book=crash_convexity_pct(
                    shadow,
                    shock=at_depth,
                ),
                is_ips_depth=round(depth, 6) == ips_depth,
            ),
        )
    return tuple(rows)


def book_convexity_by_depth(
    portfolio: OptionPortfolio,
    *,
    shock: CrashShock,
    depths: Sequence[float],
) -> tuple[float | None, ...]:
    """Return the live book's convexity at each depth (the baseline column).

    The strip's own figure (:func:`crash_convexity_pct`) at each depth, so
    the baseline beside a proposal is the number the rest of the program
    already reports.
    """
    return tuple(
        crash_convexity_pct(portfolio, shock=shock.at_pct(depth))
        for depth in depths
    )
