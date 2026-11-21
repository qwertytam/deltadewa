"""Candidates are priced on the fetched smile, not the book's flat vol (9b, D3).

Synthetic chains only: every contract is priced by this repo's own engine from
a known smile and term structure at a known rate and yield, so each
interpolation rule has an exact expected answer.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pytest

from deltadewa import constants as const
from deltadewa.analysis import vol_source as vol_source_module
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.candidate import evaluate_candidate
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_convexity_pct,
    crash_hedge_value,
)
from deltadewa.analysis.ladder import (
    LadderSource,
    ProposedLadder,
    RungSpec,
    materialize_ladder,
    size_ladder,
)
from deltadewa.analysis.roll_status import roll_target_vol
from deltadewa.analysis.strike_ladder import strike_for_delta
from deltadewa.analysis.vol_source import (
    ChainVolSource,
    VolOrigin,
    VolQuote,
    vol_basis_note,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import ChainSource, IpsPricingFeed
from deltadewa.marketdata.chain import parse_cboe_chain
from deltadewa.portfolio.core import OptionPortfolio
from tests.chain_builders import (
    DECEMBER,
    DIVIDEND,
    JUNE_THURSDAY,
    RATE,
    SESSION,
    SPOT,
    engine_price,
    occ,
    payload,
    raw_contract,
    smile,
    standard_chain,
)
from tests.test_analysis.test_convexity_agreement import _SPOT, _ips, _portfolio

_FEED = IpsPricingFeed(
    adopt=("volatility",),
    rate_series="DGS1",
    chain_source=ChainSource.CBOE,
    max_quote_age_days=5,
    max_spread_pct=25.0,
    override_warn_vol_points=2.0,
)
_BOOK_VOL = 0.19
_NEAR = date(2026, 12, 18)  # on the standard chain, SPX and SPXW
_STRIKES = tuple(float(k) for k in range(3500, 5101, 100))
_TERM = {_NEAR: 0.20, JUNE_THURSDAY: 0.24, DECEMBER: 0.28}


def _source(snapshot_payload: dict | None = None) -> ChainVolSource:
    snapshot = parse_cboe_chain(
        snapshot_payload if snapshot_payload is not None else standard_chain(),
    )
    return ChainVolSource(
        snapshot,
        risk_free_rate=RATE,
        dividend_yield=DIVIDEND,
        feed=_FEED,
        program_date=SESSION,
        book_vol=_BOOK_VOL,
    )


def _term_chain(
    *,
    vols: dict[date, float] | None = None,
    dead: set[tuple[date, float]] | None = None,
) -> dict:
    """A chain with a flat-in-strike smile and a chosen term structure."""
    dead = dead or set()
    contracts = []
    for expiry, vol in (vols or _TERM).items():
        for strike in _STRIKES:
            price = engine_price(
                expiry,
                OptionType.PUT,
                strike,
                vol=vol,
                spot=SPOT,
            )
            bad = (expiry, strike) in dead
            contracts.append(
                raw_contract(
                    occ("SPX", expiry, OptionType.PUT, strike),
                    bid=0.0 if bad else round(price * 0.99, 4),
                    ask=round(price * 1.01, 4),
                    iv=vol,
                ),
            )
    return payload(contracts, spot=SPOT)


class TestOneChain:
    """The four rules, in order, with nothing extrapolated."""

    def test_a_listed_contract_is_its_own_iv(self) -> None:
        quote = _source().vol_for(
            strike=4000.0,
            maturity=DECEMBER,
            option_type=OptionType.PUT,
        )

        assert quote.origin is VolOrigin.EXACT
        assert quote.vol == pytest.approx(smile(4000.0), abs=2e-3)

    def test_between_two_listed_strikes_is_linear_in_strike(self) -> None:
        source = _source()
        low = source.vol_for(
            strike=4000.0,
            maturity=DECEMBER,
            option_type=OptionType.PUT,
        )
        high = source.vol_for(
            strike=4100.0,
            maturity=DECEMBER,
            option_type=OptionType.PUT,
        )

        quote = source.vol_for(
            strike=4025.0,
            maturity=DECEMBER,
            option_type=OptionType.PUT,
        )

        assert quote.origin is VolOrigin.BETWEEN_STRIKES
        assert quote.vol == pytest.approx(
            low.vol + 0.25 * (high.vol - low.vol),
        )

    def test_between_expiries_interpolates_total_variance(self) -> None:
        source = _source(_term_chain())
        maturity = date(2027, 3, 1)  # between 2026-12-18 and 2027-06-17
        t_near = (_NEAR - SESSION).days / 365.0
        t_far = (JUNE_THURSDAY - SESSION).days / 365.0
        t = (maturity - SESSION).days / 365.0
        w_near = _TERM[_NEAR] ** 2 * t_near
        w_far = _TERM[JUNE_THURSDAY] ** 2 * t_far
        expected = math.sqrt(
            (w_near + (t - t_near) / (t_far - t_near) * (w_far - w_near)) / t,
        )

        quote = source.vol_for(
            strike=4000.0,
            maturity=maturity,
            option_type=OptionType.PUT,
        )

        assert quote.origin is VolOrigin.BETWEEN_EXPIRIES
        assert quote.vol == pytest.approx(expected, abs=3e-3)
        assert _TERM[_NEAR] < quote.vol < _TERM[JUNE_THURSDAY]

    def test_between_expiries_and_strikes_together(self) -> None:
        quote = _source(_term_chain()).vol_for(
            strike=4025.0,
            maturity=date(2027, 3, 1),
            option_type=OptionType.PUT,
        )

        assert quote.origin is VolOrigin.BETWEEN_EXPIRIES
        assert _TERM[_NEAR] < quote.vol < _TERM[JUNE_THURSDAY]

    @pytest.mark.parametrize(
        ("strike", "maturity"),
        [
            (2000.0, DECEMBER),  # a strike below every listed one
            (6000.0, DECEMBER),  # a strike above every listed one
            (4000.0, date(2026, 11, 20)),  # an expiry before the first
            (4000.0, date(2031, 1, 1)),  # an expiry after the last
        ],
    )
    def test_outside_the_listed_range_is_the_book_vol_not_a_guess(
        self,
        strike: float,
        maturity: date,
    ) -> None:
        quote = _source(_term_chain()).vol_for(
            strike=strike,
            maturity=maturity,
            option_type=OptionType.PUT,
        )

        assert quote == VolQuote(_BOOK_VOL, VolOrigin.BOOK_FLAT)

    def test_an_unusable_contract_is_skipped_for_its_neighbours(self) -> None:
        """No bid at the listed strike: interpolate between the usable ones."""
        chain = _term_chain(dead={(DECEMBER, 4000.0)})

        quote = _source(chain).vol_for(
            strike=4000.0,
            maturity=DECEMBER,
            option_type=OptionType.PUT,
        )

        assert quote.origin is VolOrigin.BETWEEN_STRIKES
        assert quote.vol == pytest.approx(_TERM[DECEMBER], abs=3e-3)

    def test_neighbours_that_are_all_unusable_fall_back_to_the_book_vol(
        self,
    ) -> None:
        dead = {(DECEMBER, strike) for strike in _STRIKES}

        quote = _source(_term_chain(dead=dead)).vol_for(
            strike=4000.0,
            maturity=DECEMBER,
            option_type=OptionType.PUT,
        )

        assert quote.origin is VolOrigin.BOOK_FLAT

    def test_a_contract_is_solved_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[float] = []
        real = vol_source_module.read_contract

        def counting(*args: object, **kwargs: object) -> object:
            calls.append(float(kwargs["strike"]))  # type: ignore[arg-type]
            return real(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(vol_source_module, "read_contract", counting)
        source = _source()

        for _ in range(5):
            source.vol_for(
                strike=4000.0,
                maturity=DECEMBER,
                option_type=OptionType.PUT,
            )

        assert calls == [4000.0]


class TestTheBasisNote:
    """A panel says what its candidates were priced on."""

    def test_it_counts_each_origin(self) -> None:
        note = vol_basis_note(
            [
                VolQuote(0.2, VolOrigin.EXACT),
                VolQuote(0.2, VolOrigin.EXACT),
                VolQuote(0.2, VolOrigin.BETWEEN_STRIKES),
                VolQuote(0.2, VolOrigin.BOOK_FLAT),
                None,
            ],
        )

        assert note is not None
        assert "2 at a listed contract" in note
        assert "1 between listed strikes" in note
        assert "1 on the book's flat volatility" in note

    def test_an_override_alone_does_not_claim_the_chain(self) -> None:
        note = vol_basis_note(
            [
                VolQuote(0.3, VolOrigin.OVERRIDE),
                VolQuote(0.3, VolOrigin.OVERRIDE),
            ],
        )

        assert note == "Candidates are priced on the volatility you entered."

    def test_all_flat_says_nothing(self) -> None:
        assert vol_basis_note([VolQuote(0.2, VolOrigin.BOOK_FLAT)] * 3) is None
        assert vol_basis_note([]) is None


class _SmileStub:
    """A smile in strike with no chain behind it: vol rises as strike falls."""

    def vol_for(
        self,
        *,
        strike: float,
        maturity: date,
        option_type: OptionType,
    ) -> VolQuote:
        del maturity, option_type
        downside = max((_SPOT - strike) / _SPOT, 0.0)
        return VolQuote(0.18 + 0.4 * downside, VolOrigin.BETWEEN_STRIKES)


class TestThePortfolioHook:
    """candidate_vol is the one place a candidate's vol is decided."""

    def test_without_a_source_it_is_the_flat_book_vol(self) -> None:
        book = _portfolio(100.0)

        quote = book.candidate_vol(
            strike=4000.0,
            maturity=book.valuation_date + timedelta(days=200),
        )

        assert quote == VolQuote(book.volatility, VolOrigin.BOOK_FLAT)

    def test_with_a_source_it_asks_the_source_and_takes_a_datetime(
        self,
    ) -> None:
        book = _portfolio(100.0)
        book.vol_source = _SmileStub()

        quote = book.candidate_vol(
            strike=_SPOT * 0.8,
            maturity=book.valuation_date + timedelta(days=200),
        )

        assert quote.origin is VolOrigin.BETWEEN_STRIKES
        assert quote.vol == pytest.approx(0.18 + 0.4 * 0.2)


class TestCandidatesUseIt:
    """Every candidate path reads the same surface."""

    def test_a_candidate_is_priced_at_its_strikes_vol(self) -> None:
        book = _portfolio(100.0)
        book.vol_source = _SmileStub()
        shock = CrashShock.from_ips(_ips().convexity)

        deep = evaluate_candidate(
            book,
            strike=_SPOT * 0.6,
            maturity_years=1.0,
            shock=shock,
        )
        near = evaluate_candidate(
            book,
            strike=_SPOT * 0.9,
            maturity_years=1.0,
            shock=shock,
        )

        assert deep.vol_quote is not None
        assert near.vol_quote is not None
        assert deep.vol_quote.vol > near.vol_quote.vol
        assert deep.vol_quote.origin is VolOrigin.BETWEEN_STRIKES

    def test_the_sizing_workbenchs_override_still_wins(self) -> None:
        book = _portfolio(100.0)
        book.vol_source = _SmileStub()
        shock = CrashShock.from_ips(_ips().convexity)

        metrics = evaluate_candidate(
            book,
            strike=_SPOT * 0.8,
            maturity_years=1.0,
            shock=shock,
            vol=0.33,
        )

        assert metrics.vol_quote == VolQuote(0.33, VolOrigin.OVERRIDE)

    def test_no_source_is_exactly_the_old_flat_pricing(self) -> None:
        book = _portfolio(100.0)
        shock = CrashShock.from_ips(_ips().convexity)

        flat = evaluate_candidate(
            book,
            strike=_SPOT * 0.8,
            maturity_years=1.0,
            shock=shock,
        )
        explicit = evaluate_candidate(
            book,
            strike=_SPOT * 0.8,
            maturity_years=1.0,
            shock=shock,
            vol=book.volatility,
        )

        assert flat.premium == pytest.approx(explicit.premium)
        assert flat.per_contract_payoff == pytest.approx(
            explicit.per_contract_payoff,
        )
        assert flat.vol_quote == VolQuote(book.volatility, VolOrigin.BOOK_FLAT)

    def test_a_delta_solve_prices_each_trial_strike_on_its_own_vol(
        self,
    ) -> None:
        book = _portfolio(100.0)
        book.vol_source = _SmileStub()

        strike = strike_for_delta(book, target_delta=0.10, maturity_years=1.0)

        assert strike is not None
        from deltadewa.analysis.candidate import build_put_valuation

        maturity = book.valuation_date + timedelta(
            days=round(1.0 * const.DAYS_PER_YEAR),
        )
        vol = book.candidate_vol(strike=strike, maturity=maturity).vol
        delta = build_put_valuation(
            book.spot_price,
            strike,
            maturity,
            vol,
            book,
        ).delta()
        assert abs(delta) == pytest.approx(0.10, abs=0.01)
        # On a flat vol the same target sits at a different strike.
        flat = strike_for_delta(
            _portfolio(100.0),
            target_delta=0.10,
            maturity_years=1.0,
        )
        assert flat is not None
        assert flat != pytest.approx(strike, abs=1.0)

    def test_a_book_leg_and_a_candidate_at_its_strike_agree(self) -> None:
        """The M1.7 guarantee, on the smile: same contract, same crash value.

        Pinned to the chain's own session date, never the wall clock: the
        chain's expiries are absolute dates.
        """
        book = OptionPortfolio(
            spot_price=SPOT,
            underlying_quantity=100.0,
            volatility=_BOOK_VOL,
            risk_free_rate=RATE,
            dividend_yield=DIVIDEND,
            valuation_date=datetime(SESSION.year, SESSION.month, SESSION.day),
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        source = _source()
        book.vol_source = source
        strike = 4000.0
        quote = source.vol_for(
            strike=strike,
            maturity=DECEMBER,
            option_type=OptionType.PUT,
        )
        assert quote.origin is VolOrigin.EXACT
        book.add_position(
            strike_price=strike,
            maturity_date=datetime(
                DECEMBER.year,
                DECEMBER.month,
                DECEMBER.day,
            ),
            quantity=7,
            option_type=OptionType.PUT,
            volatility=quote.vol,
        )
        shock = CrashShock.from_ips(_ips().convexity)

        held = crash_hedge_value(
            book,
            shock=shock,
            positions=[book.positions[0]],
        )
        candidate = evaluate_candidate(
            book,
            strike=strike,
            maturity_years=(DECEMBER - SESSION).days / const.DAYS_PER_YEAR,
            shock=shock,
        )

        assert candidate.vol_quote == quote
        assert candidate.per_contract_payoff == pytest.approx(held / 7)


class TestTheLadderShadowBook:
    """The shadow book and the per-rung figures read one surface."""

    def _ladder(self) -> ProposedLadder:
        return ProposedLadder(
            rungs=(
                RungSpec(20.0, 1.5, 35.0),
                RungSpec(30.0, 1.5, 40.0),
                RungSpec(40.0, 1.5, 25.0),
            ),
            source=LadderSource.OPERATOR,
        )

    def test_each_rung_is_held_at_the_vol_it_was_sized_at(self) -> None:
        ips = _ips()
        book = _portfolio(10_000.0)
        book.vol_source = _SmileStub()

        sized = size_ladder(book, ips, self._ladder())
        shadow = materialize_ladder(book, sized)

        rung_vols = [
            rung.metrics.vol_quote.vol
            for rung in sized.rungs
            if rung.contracts and rung.metrics.vol_quote
        ]
        assert [p.option.volatility for p in shadow.positions] == (
            pytest.approx(rung_vols)
        )
        assert len(set(rung_vols)) == len(rung_vols)

    def test_combined_convexity_is_still_the_sum_of_the_rungs(self) -> None:
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        book = _portfolio(10_000.0)
        book.vol_source = _SmileStub()
        sized = size_ladder(book, ips, self._ladder())

        shadow = materialize_ladder(book, sized)

        combined = crash_convexity_pct(shadow, shock=shock)
        total = sum(
            r.contracts * r.metrics.per_contract_convexity_pct
            for r in sized.rungs
        )
        assert combined == pytest.approx(total, rel=1e-9)

    def test_a_flat_book_still_holds_rungs_as_inheriting_the_book_vol(
        self,
    ) -> None:
        ips = _ips()
        book = _portfolio(10_000.0)
        sized = size_ladder(book, ips, self._ladder())

        shadow = materialize_ladder(book, sized)

        assert all(not p.custom_volatility for p in shadow.positions)
        assert {p.option.volatility for p in shadow.positions} == {
            book.volatility,
        }

    def test_the_shadow_book_carries_the_surface(self) -> None:
        ips = _ips()
        book = _portfolio(10_000.0)
        book.vol_source = _SmileStub()

        shadow = materialize_ladder(
            book,
            size_ladder(book, ips, self._ladder()),
        )

        assert shadow.vol_source is book.vol_source
        assert PortfolioAnalyzer(shadow) is not None


class TestRollCost:
    """A roll's new strike is priced on the surface the held leg was."""

    def _book_with_leg(self) -> OptionPortfolio:
        book = OptionPortfolio(
            spot_price=_SPOT,
            underlying_quantity=100.0,
            volatility=0.20,
            risk_free_rate=0.04,
            dividend_yield=0.015,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        book.add_position(
            strike_price=_SPOT * 0.8,
            maturity_date=book.valuation_date + timedelta(days=300),
            quantity=5,
            option_type=OptionType.PUT,
            volatility=0.27,
        )
        return book

    def test_a_smile_prices_the_new_strike_on_its_own_vol(self) -> None:
        book = self._book_with_leg()
        book.vol_source = _SmileStub()

        vol = roll_target_vol(book, book.positions[0], _SPOT * 0.9)

        assert vol == pytest.approx(0.18 + 0.4 * 0.1)

    def test_without_a_surface_it_is_the_held_legs_vol_as_before(self) -> None:
        book = self._book_with_leg()

        vol = roll_target_vol(book, book.positions[0], _SPOT * 0.9)

        assert vol == pytest.approx(0.27)

    def test_outside_the_listed_range_it_is_the_held_legs_vol(self) -> None:
        book = self._book_with_leg()

        class _Flat:
            def vol_for(self, **_kwargs: object) -> VolQuote:
                return VolQuote(0.20, VolOrigin.BOOK_FLAT)

        book.vol_source = _Flat()

        vol = roll_target_vol(book, book.positions[0], _SPOT * 0.9)

        assert vol == pytest.approx(0.27)


class TestWeeklyOnlyExpiries:
    """A contract only the weekly root lists is a listed contract."""

    def test_an_spxw_only_expiry_is_exact_not_interpolated(self) -> None:
        from tests.chain_builders import WEEKLY_ONLY

        # Near the money: a four-day put 20% out is worthless and has no bid.
        quote = _source().vol_for(
            strike=4900.0,
            maturity=WEEKLY_ONLY,
            option_type=OptionType.PUT,
        )

        assert quote.origin is VolOrigin.EXACT
        assert quote.vol == pytest.approx(smile(4900.0), abs=5e-3)


class TestRollAgreesWithCandidatesOnTheSurface:
    """Inside the listed range a roll's new strike and a candidate agree."""

    def _book(self) -> OptionPortfolio:
        book = OptionPortfolio(
            spot_price=SPOT,
            underlying_quantity=100.0,
            volatility=_BOOK_VOL,
            risk_free_rate=RATE,
            dividend_yield=DIVIDEND,
            valuation_date=datetime(SESSION.year, SESSION.month, SESSION.day),
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        book.vol_source = _source()
        book.add_position(
            strike_price=3500.0,
            maturity_date=datetime(
                DECEMBER.year,
                DECEMBER.month,
                DECEMBER.day,
            ),
            quantity=5,
            option_type=OptionType.PUT,
            volatility=0.31,
        )
        return book

    def test_a_listed_new_strike_is_the_candidates_vol(self) -> None:
        book = self._book()
        held = book.positions[0]

        roll = roll_target_vol(book, held, 4000.0)
        candidate = book.candidate_vol(
            strike=4000.0,
            maturity=held.option.maturity_date,
        )

        assert candidate.origin is VolOrigin.EXACT
        assert roll == pytest.approx(candidate.vol)

    def test_outside_the_range_a_roll_prices_on_the_held_legs_vol(self) -> None:
        """By design, and different from a fresh candidate: a roll's
        reference is the leg it replaces. Labelled, documented, pinned."""
        book = self._book()
        held = book.positions[0]

        roll = roll_target_vol(book, held, 1000.0)
        candidate = book.candidate_vol(
            strike=1000.0,
            maturity=held.option.maturity_date,
        )

        assert candidate.origin is VolOrigin.BOOK_FLAT
        assert roll == pytest.approx(0.31)
        assert candidate.vol == pytest.approx(_BOOK_VOL)

    def test_a_surface_that_raises_cannot_take_the_digest_down(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        book = self._book()

        class _Broken:
            def vol_for(self, **_kwargs: object) -> VolQuote:
                raise RuntimeError("surface fault")

        book.vol_source = _Broken()

        with caplog.at_level("ERROR"):
            vol = roll_target_vol(book, book.positions[0], 4000.0)

        assert vol == pytest.approx(0.31)
        assert "surface fault" in caplog.text
