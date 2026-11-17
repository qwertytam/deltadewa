"""Tests for deltadewa.analysis.chain_quotes."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from deltadewa.analysis.chain_quotes import read_contract, rung_readings
from deltadewa.constants import OptionType
from deltadewa.ips_config import IpsConfig, load_ips_config
from deltadewa.marketdata.chain import (
    MatchFlag,
    parse_cboe_chain,
)
from tests.chain_builders import (
    BOTH_ROOTS,
    DECEMBER,
    DIVIDEND,
    JUNE_THURSDAY,
    RATE,
    SESSION,
    occ,
    payload,
    raw_contract,
    smile,
    standard_chain,
)

_EXAMPLE_IPS = Path(__file__).parents[2] / "config" / "ips.example.yaml"
_PROGRAM_DATE = date(2026, 11, 17)


@pytest.fixture(name="snapshot")
def _snapshot():
    return parse_cboe_chain(standard_chain())


@pytest.fixture(name="ips")
def _ips() -> IpsConfig:
    return load_ips_config(_EXAMPLE_IPS)


def _read(snapshot, **overrides):
    arguments = {
        "label": "L1",
        "expiry": DECEMBER,
        "option_type": OptionType.PUT,
        "strike": 4000.0,
        "risk_free_rate": RATE,
        "dividend_yield": DIVIDEND,
        "max_spread_pct": 25.0,
        "max_quote_age_days": 5,
        "program_date": _PROGRAM_DATE,
    }
    arguments.update(overrides)
    return read_contract(snapshot, **arguments)


class TestReadContract:
    """One contract: matched, solved at our r and q, flagged."""

    def test_clean_quote_solves_the_smile_at_the_books_r_and_q(
        self,
        snapshot,
    ) -> None:
        """The chain was priced at (RATE, DIVIDEND): solving recovers it."""
        reading = _read(snapshot)

        assert reading.usable
        assert reading.quote is not None
        assert reading.solved_iv == pytest.approx(smile(4000.0), abs=2e-3)
        assert reading.session_date == SESSION

    def test_a_different_rate_gives_a_different_iv(self, snapshot) -> None:
        """The IV is the one at the caller's r, not the vendor's."""
        at_book = _read(snapshot)
        higher = _read(snapshot, risk_free_rate=RATE + 0.01)

        assert higher.solved_iv is not None
        assert at_book.solved_iv is not None
        assert higher.solved_iv > at_book.solved_iv

    def test_unlisted_contract_is_absent_and_unusable(self, snapshot) -> None:
        """No contract, no IV."""
        reading = _read(snapshot, strike=4050.0)

        assert reading.quote is None
        assert reading.flags == frozenset({MatchFlag.ABSENT})
        assert not reading.usable

    def test_ambiguous_root_is_still_usable(self, snapshot) -> None:
        """SPX was used; the note does not block pricing."""
        reading = _read(snapshot, expiry=BOTH_ROOTS)

        assert MatchFlag.AMBIGUOUS_ROOT in reading.flags
        assert reading.usable

    def test_zero_bid_is_not_solved(self) -> None:
        """A mid built from no bid is not a price."""
        symbol = occ("SPX", DECEMBER, OptionType.PUT, 3000.0)
        chain = parse_cboe_chain(
            payload([raw_contract(symbol, bid=0.0, ask=0.4, iv=0.45)]),
        )

        reading = _read(chain, strike=3000.0)

        assert reading.flags == frozenset({MatchFlag.ZERO_BID})
        assert reading.solved_iv is None
        assert not reading.usable

    def test_wide_quote_is_flagged_and_unusable(self) -> None:
        """Wider than the policy spread: shown, not trusted."""
        symbol = occ("SPX", DECEMBER, OptionType.PUT, 3000.0)
        chain = parse_cboe_chain(
            payload([raw_contract(symbol, bid=1.0, ask=3.0, iv=0.45)]),
        )

        reading = _read(chain, strike=3000.0)

        assert MatchFlag.WIDE in reading.flags
        assert not reading.usable

    def test_mid_outside_no_arbitrage_bounds_is_no_solve(self) -> None:
        """A put quoted above its strike cannot be any volatility."""
        symbol = occ("SPX", DECEMBER, OptionType.PUT, 3000.0)
        chain = parse_cboe_chain(
            payload([raw_contract(symbol, bid=4000.0, ask=4010.0, iv=0.0)]),
        )

        reading = _read(chain, strike=3000.0)

        assert MatchFlag.NO_SOLVE in reading.flags
        assert reading.solved_iv is None

    @pytest.mark.parametrize(
        ("program_date", "stale"),
        [
            (date(2026, 11, 21), False),
            (date(2026, 11, 22), True),
        ],
    )
    def test_stale_quote_after_max_age(
        self,
        snapshot,
        program_date: date,
        stale: bool,
    ) -> None:
        """Session 11-16 + 5 days is the last day it is fresh."""
        reading = _read(snapshot, program_date=program_date)

        assert (MatchFlag.STALE_QUOTE in reading.flags) is stale
        assert reading.usable is (not stale)


class TestRungReadings:
    """The IPS ladder rungs read off the chain."""

    def test_no_ladder_gives_no_readings(self, snapshot, ips) -> None:
        """Without a ``strike_ladder`` section there is nothing to read."""
        bare = ips.__class__(**{**ips.__dict__, "strike_ladder": None})

        assert (
            rung_readings(
                snapshot,
                bare,
                bare.pricing_feed,
                risk_free_rate=RATE,
                dividend_yield=DIVIDEND,
                program_date=_PROGRAM_DATE,
            )
            == ()
        )

    def test_rungs_snap_to_listed_strike_and_nearest_expiry(
        self,
        snapshot,
        ips,
    ) -> None:
        """20/30/40% OTM of 5,000 snapped to the 100-point grid, 1.5y out."""
        readings = rung_readings(
            snapshot,
            ips,
            ips.pricing_feed,
            risk_free_rate=RATE,
            dividend_yield=DIVIDEND,
            program_date=_PROGRAM_DATE,
        )

        assert [r.quote.strike for r in readings if r.quote] == [
            4000.0,
            3500.0,
            3000.0,
        ]
        # The 2027-12-17 expiry is the closest listed SPX expiry to 1.5y.
        assert {r.quote.expiry for r in readings if r.quote} == {DECEMBER}
        assert all(r.usable for r in readings)
        assert readings[0].label.startswith("20% OTM")

    def test_no_standard_expiries_is_absent(self, ips) -> None:
        """A chain with only weeklies has no expiry near the rung's tenor."""
        symbol = occ("SPXW", JUNE_THURSDAY, OptionType.PUT, 4000.0)
        chain = parse_cboe_chain(
            payload([raw_contract(symbol, bid=10.0, ask=11.0, iv=0.3)]),
        )

        readings = rung_readings(
            chain,
            ips,
            ips.pricing_feed,
            risk_free_rate=RATE,
            dividend_yield=DIVIDEND,
            program_date=_PROGRAM_DATE,
        )

        assert len(readings) == 3
        assert all(r.flags == frozenset({MatchFlag.ABSENT}) for r in readings)
