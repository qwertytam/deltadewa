"""Tests for deltadewa.analysis.ladder -- a ladder as a sized, scored unit."""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from deltadewa import constants as const
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import CrashShock, crash_convexity_pct
from deltadewa.analysis.ladder import (
    LadderSource,
    ProposedLadder,
    RungSpec,
    _allocate_contracts,
    book_convexity_by_depth,
    ladder_depth_profile,
    ladder_from_book,
    materialize_ladder,
    profile_depths,
    size_ladder,
)
from deltadewa.analysis.maturity import MaturityBuckets
from deltadewa.analysis.sizing import size_hedge
from deltadewa.constants import OptionType
from deltadewa.ips_config import (
    IpsLadderRung,
    IpsMaturitySelection,
    IpsStrikeLadder,
)
from deltadewa.portfolio.core import OptionPortfolio

from .test_convexity_agreement import _SPOT, _ips, _portfolio

#: A $50M book, so a ladder needs tens of contracts and the weight split is
#: visible (on a small book every rung rounds to one contract).
_BIG_QTY = 10_000.0
_TENOR = 1.5


def _handbook_ladder(
    source: LadderSource = LadderSource.OPERATOR,
) -> ProposedLadder:
    """35/40/25 across 20/30/40% OTM -- the handbook's example ladder."""
    return ProposedLadder(
        rungs=(
            RungSpec(20.0, _TENOR, 35.0),
            RungSpec(30.0, _TENOR, 40.0),
            RungSpec(40.0, _TENOR, 25.0),
        ),
        source=source,
    )


def _held_book(
    quantities: tuple[int, int, int] = (23, 26, 16),
) -> OptionPortfolio:
    """The §4-style book: three held rungs at 20/30/40% OTM, 18 months."""
    book = _portfolio(_BIG_QTY)
    for pct_otm, quantity in zip((20.0, 30.0, 40.0), quantities, strict=True):
        book.add_position(
            strike_price=_SPOT * (1.0 - pct_otm / 100.0),
            maturity_date=book.valuation_date
            + timedelta(days=round(_TENOR * const.DAYS_PER_YEAR)),
            quantity=quantity,
            option_type=OptionType.PUT,
        )
    return book


class TestRungAndLadderValidation:
    """A malformed ladder fails at construction, not in a score."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"pct_otm": 100.0, "maturity_years": 1.0, "weight": 1.0},
            {"pct_otm": float("nan"), "maturity_years": 1.0, "weight": 1.0},
            {"pct_otm": 20.0, "maturity_years": 0.0, "weight": 1.0},
            {"pct_otm": 20.0, "maturity_years": 1.0, "weight": 0.0},
            {"pct_otm": 20.0, "maturity_years": 1.0, "weight": -1.0},
            {
                "pct_otm": 20.0,
                "maturity_years": 1.0,
                "weight": 1.0,
                "contracts": -3,
            },
        ],
    )
    def test_bad_rung_is_rejected(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError, match="must be"):
            RungSpec(**kwargs)  # type: ignore[arg-type]

    def test_empty_ladder_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one rung"):
            ProposedLadder(rungs=(), source=LadderSource.OPERATOR)

    def test_repeated_rung_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="repeat"):
            ProposedLadder(
                rungs=(RungSpec(20.0, 1.0, 1.0), RungSpec(20.0, 1.0, 2.0)),
                source=LadderSource.OPERATOR,
            )

    def test_mixing_fixed_and_sized_rungs_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="all fixed-size or all sized"):
            ProposedLadder(
                rungs=(
                    RungSpec(20.0, 1.0, 1.0, contracts=5),
                    RungSpec(30.0, 1.0, 1.0),
                ),
                source=LadderSource.OPERATOR,
            )

    def test_weights_normalise_to_one(self) -> None:
        weights = _handbook_ladder().normalized_weights

        assert weights == pytest.approx((0.35, 0.40, 0.25))
        assert sum(weights) == pytest.approx(1.0)

    def test_weights_are_relative_not_percent(self) -> None:
        """1:1:2 and 25:25:50 are the same ladder."""
        a = ProposedLadder(
            rungs=(
                RungSpec(20.0, 1.0, 1.0),
                RungSpec(30.0, 1.0, 1.0),
                RungSpec(40.0, 1.0, 2.0),
            ),
            source=LadderSource.OPERATOR,
        )
        b = ProposedLadder(
            rungs=(
                RungSpec(20.0, 1.0, 25.0),
                RungSpec(30.0, 1.0, 25.0),
                RungSpec(40.0, 1.0, 50.0),
            ),
            source=LadderSource.OPERATOR,
        )

        assert a.normalized_weights == pytest.approx(b.normalized_weights)


class TestFromIps:
    """The IPS ladder, with the entry tenor filling an omitted maturity."""

    def test_omitted_maturity_takes_the_entry_tenor(self) -> None:
        ips_ladder = IpsStrikeLadder(
            rungs=(
                IpsLadderRung(pct_otm=20.0, weight_pct=60.0),
                IpsLadderRung(
                    pct_otm=30.0,
                    weight_pct=40.0,
                    maturity_years=2.0,
                ),
            ),
        )

        ladder = ProposedLadder.from_ips(
            ips_ladder,
            IpsMaturitySelection(entry_tenor_years=1.25),
        )

        assert ladder.source is LadderSource.IPS
        assert [r.maturity_years for r in ladder.rungs] == [1.25, 2.0]
        assert [r.weight for r in ladder.rungs] == [60.0, 40.0]
        assert not ladder.is_fixed_size


class TestLadderFromBook:
    """The held book, read as a fixed-size ladder."""

    def test_long_puts_become_fixed_size_rungs(self) -> None:
        ladder = ladder_from_book(_held_book())

        assert ladder is not None
        assert ladder.source is LadderSource.BOOK
        assert ladder.is_fixed_size
        assert sorted(r.contracts for r in ladder.rungs if r.contracts) == [
            16,
            23,
            26,
        ]
        assert sorted(r.pct_otm for r in ladder.rungs) == pytest.approx(
            [20.0, 30.0, 40.0],
        )
        assert all(
            r.maturity_years == pytest.approx(_TENOR, abs=0.01)
            for r in ladder.rungs
        )
        assert ladder.excluded_leg_count == 0

    def test_legs_sharing_strike_and_expiry_are_one_rung(self) -> None:
        book = _held_book()
        book.add_position(
            strike_price=_SPOT * 0.8,
            maturity_date=book.valuation_date
            + timedelta(days=round(_TENOR * const.DAYS_PER_YEAR)),
            quantity=2,
            option_type=OptionType.PUT,
        )

        ladder = ladder_from_book(book)

        assert ladder is not None
        assert len(ladder.rungs) == 3
        near = max(ladder.rungs, key=lambda r: r.weight)  # 20% rung: 23 + 2
        assert near.contracts in {25, 26}

    def test_shorts_calls_and_expired_are_counted_not_netted(self) -> None:
        book = _held_book()
        maturity = book.valuation_date + timedelta(days=400)
        book.add_position(
            strike_price=_SPOT * 0.9,
            maturity_date=maturity,
            quantity=-5,
            option_type=OptionType.PUT,
        )
        book.add_position(
            strike_price=_SPOT * 1.1,
            maturity_date=maturity,
            quantity=4,
            option_type=OptionType.CALL,
        )
        book.add_position(
            strike_price=_SPOT * 0.7,
            maturity_date=book.valuation_date - timedelta(days=10),
            quantity=9,
            option_type=OptionType.PUT,
            reject_expired=False,
        )

        ladder = ladder_from_book(book)

        assert ladder is not None
        assert ladder.excluded_leg_count == 3
        # The short put did not subtract from, nor join, any rung.
        assert sum(r.contracts or 0 for r in ladder.rungs) == 23 + 26 + 16

    def test_a_book_with_no_long_put_has_no_ladder(self) -> None:
        assert ladder_from_book(_portfolio(_BIG_QTY)) is None


class TestAllocation:
    """Splitting a total across weights never falls short, never fuzzes up."""

    def test_clean_percentages_do_not_round_up_on_float_noise(self) -> None:
        """A 7% share of 100 is 7 contracts, not 8.

        ``100 * 0.07`` is ``7.000000000000001`` in binary floating point, so
        a bare ``ceil`` over-sizes the rung by a whole contract.
        """
        assert math.ceil(100 * 0.07) == 8  # the bug the guard prevents
        assert _allocate_contracts(100, (0.07, 0.93)) == (7, 93)

    def test_each_rung_rounds_up(self) -> None:
        assert _allocate_contracts(10, (0.35, 0.40, 0.25)) == (4, 4, 3)

    def test_zero_total_is_zero_everywhere(self) -> None:
        assert _allocate_contracts(0, (0.5, 0.5)) == (0, 0)


class TestSizeLadder:
    """A ladder is sized to the sizing workbench's own target."""

    def test_one_rung_ladder_is_exactly_size_hedge(self) -> None:
        ips = _ips()
        portfolio = _portfolio(_BIG_QTY)
        single = ProposedLadder(
            rungs=(RungSpec(20.0, _TENOR, 1.0),),
            source=LadderSource.OPERATOR,
        )

        sized = size_ladder(portfolio, ips, single)
        hedge = size_hedge(
            portfolio,
            ips,
            candidate_pct_otm=20.0,
            candidate_maturity_years=_TENOR,
        )

        assert sized.total_contracts == hedge.contracts_needed
        assert sized.implied_annual_carry == pytest.approx(
            hedge.implied_annual_carry,
        )
        assert sized.basis.required_crash_offset == pytest.approx(
            hedge.required_crash_offset,
        )

    def test_ladder_covers_the_offset_and_splits_by_weight(self) -> None:
        sized = size_ladder(_portfolio(_BIG_QTY), _ips(), _handbook_ladder())

        assert sized.covers_offset
        near, mid, deep = (r.contracts for r in sized.rungs)
        # Weighted 35/40/25: the middle rung holds the most contracts.
        assert mid > near > deep > 0
        assert sized.total_contracts >= near + mid + deep - 3

    def test_fixed_size_ladder_keeps_its_held_counts(self) -> None:
        held = ladder_from_book(_held_book())
        assert held is not None

        sized = size_ladder(_portfolio(_BIG_QTY), _ips(), held)

        assert sorted(r.contracts for r in sized.rungs) == [16, 23, 26]

    def test_no_underlying_raises(self) -> None:
        with pytest.raises(ValueError, match="ladder sizing requires"):
            size_ladder(_portfolio(0.0), _ips(), _handbook_ladder())


class TestMaterialize:
    """The shadow book is the strip's input -- it must score like a book."""

    def test_held_ladder_scores_identically_to_the_book_it_came_from(
        self,
    ) -> None:
        """Round trip: book -> ladder -> shadow reads as the book does."""
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        book = _held_book()
        held = ladder_from_book(book)
        assert held is not None

        shadow = materialize_ladder(book, size_ladder(book, ips, held))

        assert crash_convexity_pct(shadow, shock=shock) == pytest.approx(
            crash_convexity_pct(book, shock=shock),
            rel=1e-9,
        )
        buckets = MaturityBuckets.from_ips(ips.maturity_buckets)
        assert PortfolioAnalyzer(shadow).calculate_carry_metrics(buckets)[
            "total_theta_annual"
        ] == pytest.approx(
            PortfolioAnalyzer(book).calculate_carry_metrics(buckets)[
                "total_theta_annual"
            ],
            rel=1e-9,
        )

    def test_combined_convexity_is_the_sum_of_per_contract_contributions(
        self,
    ) -> None:
        """#410: the *combined* figure, not any one rung's, is what's read.

        The shadow book's strip figure must equal the contracts-weighted
        sum of each rung's own per-contract figure (position value is
        linear in quantity), and must differ from every single rung's.
        """
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        portfolio = _portfolio(_BIG_QTY)
        sized = size_ladder(portfolio, ips, _handbook_ladder())

        shadow = materialize_ladder(portfolio, sized)

        combined = crash_convexity_pct(shadow, shock=shock)
        per_rung = [
            r.contracts * r.metrics.per_contract_convexity_pct
            for r in sized.rungs
        ]
        assert combined == pytest.approx(sum(per_rung), rel=1e-9)
        assert all(
            combined != pytest.approx(single, rel=1e-6) for single in per_rung
        )

    def test_live_book_is_not_mutated(self) -> None:
        book = _held_book()
        before = len(book.positions)

        materialize_ladder(book, size_ladder(book, _ips(), _handbook_ladder()))

        assert len(book.positions) == before

    def test_unsized_rung_is_omitted_from_the_shadow(self) -> None:
        ips = _ips()
        portfolio = _portfolio(_BIG_QTY)
        sized = size_ladder(portfolio, ips, _handbook_ladder())
        emptied = type(sized)(
            ladder=sized.ladder,
            rungs=(
                sized.rungs[0],
                type(sized.rungs[1])(
                    spec=sized.rungs[1].spec,
                    metrics=sized.rungs[1].metrics,
                    contracts=0,
                ),
                sized.rungs[2],
            ),
            basis=sized.basis,
            vol=sized.vol,
        )

        assert len(materialize_ladder(portfolio, emptied).positions) == 2


class TestDepthProfile:
    """Gain by depth: rung by rung, and the whole ladder."""

    def test_rung_gains_sum_to_the_independently_priced_combined_gain(
        self,
    ) -> None:
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        portfolio = _portfolio(_BIG_QTY)
        sized = size_ladder(portfolio, ips, _handbook_ladder())
        shadow = materialize_ladder(portfolio, sized)

        rows = ladder_depth_profile(
            shadow,
            sized,
            shock=shock,
            depths=profile_depths(shock),
        )

        assert len(rows) == 5
        for row in rows:
            assert sum(row.rung_gains) == pytest.approx(
                row.combined_gain,
                rel=1e-9,
            )
            # Long puts: no rung's gain is negative, so a sum cannot net a
            # loss against a gain.
            assert all(g >= 0.0 for g in row.rung_gains)

    def test_only_the_ips_depth_is_flagged_and_it_matches_the_strip(
        self,
    ) -> None:
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        portfolio = _portfolio(_BIG_QTY)
        sized = size_ladder(portfolio, ips, _handbook_ladder())
        shadow = materialize_ladder(portfolio, sized)

        rows = ladder_depth_profile(
            shadow,
            sized,
            shock=shock,
            depths=profile_depths(shock),
        )

        flagged = [r for r in rows if r.is_ips_depth]
        assert [r.shock_pct for r in flagged] == [-25.0]
        assert flagged[0].combined_pct_of_book == pytest.approx(
            crash_convexity_pct(shadow, shock=shock),
            rel=1e-9,
        )

    def test_deeper_rungs_pay_later(self) -> None:
        """The handbook's "How the Payoff Changes": near strikes first."""
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        portfolio = _portfolio(_BIG_QTY)
        sized = size_ladder(portfolio, ips, _handbook_ladder())
        shadow = materialize_ladder(portfolio, sized)

        rows = {
            r.shock_pct: r
            for r in ladder_depth_profile(
                shadow,
                sized,
                shock=shock,
                depths=profile_depths(shock),
            )
        }

        mild = rows[-10.0]
        severe = rows[-40.0]
        # At -10% the near rung carries more of the gain than the deep one;
        # by -40% the deep rung has caught up in share.
        assert mild.rung_gains[0] > mild.rung_gains[2]
        assert (
            severe.rung_gains[2] / severe.combined_gain
            > mild.rung_gains[2] / mild.combined_gain
        )

    def test_depths_are_the_handbooks_plus_the_ips_depth(self) -> None:
        shock = CrashShock.from_ips(_ips().convexity)

        assert profile_depths(shock) == (-10.0, -20.0, -25.0, -30.0, -40.0)

    def test_mismatched_shadow_is_rejected(self) -> None:
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        portfolio = _portfolio(_BIG_QTY)
        sized = size_ladder(portfolio, ips, _handbook_ladder())

        with pytest.raises(ValueError, match="non-empty rungs"):
            ladder_depth_profile(
                _portfolio(_BIG_QTY),
                sized,
                shock=shock,
                depths=(-25.0,),
            )

    def test_baseline_column_is_the_strips_figure_per_depth(self) -> None:
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        book = _held_book()

        baseline = book_convexity_by_depth(
            book,
            shock=shock,
            depths=(-10.0, -25.0),
        )

        assert baseline == pytest.approx(
            (
                crash_convexity_pct(book, shock=shock.at_pct(-10.0)),
                crash_convexity_pct(book, shock=shock.at_pct(-25.0)),
            ),
        )


class TestSizedFiguresAgreeWithTheShadowBook:
    """The sized route and the book route are two producers; pin them equal."""

    def test_sized_carry_equals_the_shadows_theta_carry(self) -> None:
        """Rung-table carry (evaluate_candidate) == the scorecard's carry.

        Two routes: per-contract carry priced by ``evaluate_candidate``
        and summed, against ``calculate_carry_metrics`` on the shadow book.
        Equal while the program day and the portfolio's valuation date agree
        (the usual case; the boot-before-midnight-ET edge is #182's class).
        """
        ips = _ips()
        portfolio = _portfolio(_BIG_QTY)
        sized = size_ladder(portfolio, ips, _handbook_ladder())
        shadow = materialize_ladder(portfolio, sized)

        theta = PortfolioAnalyzer(shadow).calculate_carry_metrics(
            MaturityBuckets.from_ips(ips.maturity_buckets),
        )["total_theta_annual"]

        assert sized.implied_annual_carry == pytest.approx(
            abs(theta),
            rel=1e-6,
        )

    def test_covering_the_offset_reads_below_it_net_of_premium(self) -> None:
        """Pins the documented gross-vs-net gap (#410, known limitation).

        Sizing covers the offset on *gross* crash value; the convexity row
        is the gain *net of premium*. A ladder that covers the offset
        therefore reads below ``offset / book`` by the premium it paid. If
        this ever fails the sizing rule or the gauge changed, and the
        composer's caveat text needs revisiting.
        """
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        portfolio = _portfolio(_BIG_QTY)
        sized = size_ladder(portfolio, ips, _handbook_ladder())
        shadow = materialize_ladder(portfolio, sized)
        book = abs(portfolio.underlying_quantity * portfolio.spot_price)

        convexity = crash_convexity_pct(shadow, shock=shock)

        assert sized.covers_offset
        gross_pct = sized.combined_crash_value / book * 100.0
        premium_pct = (
            sum(r.contracts * r.metrics.premium for r in sized.rungs)
            / book
            * 100.0
        )
        assert convexity < gross_pct
        assert convexity == pytest.approx(gross_pct - premium_pct, rel=1e-6)
