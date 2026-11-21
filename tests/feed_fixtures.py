"""A fed book for tests: a chain dated to the program's own day (9b).

``tests/chain_builders.py`` pins its session to an absolute 2026 date, which
suits the pure chain tests. A test that loads a ``ProgramState`` has a
valuation date from the program clock, so its chain has to be dated to
*that* day or every quote reads as stale, and its contracts have to expire
on the dates the held legs do. Both are derived here from
``tests/clock_helpers.py``, never from the wall clock directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from deltadewa.clock import program_now
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import (
    MarketDataUnavailableError,
    Observation,
    Source,
)
from deltadewa.marketdata.chain import (
    ChainSnapshot,
    parse_cboe_chain,
    quote_session_date,
)
from deltadewa.state import ProgramState
from tests.chain_builders import (
    DIVIDEND,
    RATE,
    SPOT,
    payload,
    priced_contract,
)
from tests.clock_helpers import days_from_today, program_date
from tests.test_app.freshness_fixtures import GradedProvider

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig
    from deltadewa.marketdata import MarketDataProvider

_NEW_YORK = ZoneInfo("America/New_York")

#: The FRED percent that converts to exactly ``RATE`` continuously.
FRED_PCT = 200.0 * (math.exp(RATE / 2.0) - 1.0)

EXAMPLE_IPS = Path(__file__).parent.parent / "config" / "ips.example.yaml"


def adopting_ips(
    tmp_path: Path,
    adopt: tuple[str, ...] = ("spot", "risk_free_rate", "volatility"),
    *,
    max_quote_age_days: int = 5,
    chain_source: str = "cboe",
) -> Path:
    """Write the example IPS with ``adopt`` set; return the file's path.

    The synthetic chains are in Cboe's format, so the chain source is
    ``cboe`` unless a test asks for ``none``.
    """
    text = EXAMPLE_IPS.read_text()
    text = text.replace("  adopt: []", f"  adopt: [{', '.join(adopt)}]", 1)
    text = text.replace(
        "  chain_source: none ",
        f"  chain_source: {chain_source} ",
        1,
    )
    text = text.replace(
        "  max_quote_age_days: 5",
        f"  max_quote_age_days: {max_quote_age_days}",
        1,
    )
    path = tmp_path / "ips.yaml"
    path.write_text(text)
    return path


def _session_close(day: datetime) -> datetime:
    """Return 20:33 New York on *day*, as an aware UTC instant."""
    local = datetime(day.year, day.month, day.day, 20, 33, 27, tzinfo=_NEW_YORK)
    return local.astimezone(UTC)


def session_stamp(day: datetime) -> str:
    """Return the payload stamp (naive UTC) of 20:33 New York on *day*."""
    return _session_close(day).strftime("%Y-%m-%d %H:%M:%S")


def fed_chain(
    expiry: date,
    strikes: tuple[float, ...],
    *,
    spot: float = SPOT,
    program_day: datetime | None = None,
) -> ChainSnapshot:
    """Return a chain dated to the program's day, listing puts on *expiry*.

    Every contract is priced by the engine from the shared smile at
    ``RATE`` and ``DIVIDEND`` as of the chain's own session (a weekend day
    is Friday's), so the IV the resolver solves back at those is the smile.
    """
    day = program_day if program_day is not None else program_date()
    session = quote_session_date(_session_close(day))
    return parse_cboe_chain(
        payload(
            [
                priced_contract(
                    "SPX",
                    expiry,
                    OptionType.PUT,
                    strike,
                    spot=spot,
                    rate=RATE,
                    dividend=DIVIDEND,
                    valuation=session,
                )
                for strike in strikes
            ],
            spot=spot,
            timestamp=session_stamp(day),
        ),
    )


@dataclass
class FedProvider(GradedProvider):
    """A provider whose every series reads like the nightly cache.

    ``StaticProvider`` returns ``STATIC`` observations with no timestamps.
    ``GradedProvider`` grades the four market-environment readings at a
    chosen ``source``; this adds the chain, the rate and the index close at
    the same ``source`` with a real as-of and fetch time, so the resolver,
    the ledger and ``/health`` grade them as they would the refresh job's
    cache.

    Attributes:
        index_close: The nightly index close, or ``None`` for none cached.
        fetched_at: When the three feed series were fetched.
        feed_source: The ``Source`` of the three feed series, when it is not
            the same as the market-environment readings' (a chain that went
            stale while VIX did not), else ``None`` for the same one.

    """

    index_close: float | None = None
    feed_source: Source | None = None
    fetched_at: datetime = field(
        default_factory=lambda: program_now(),
    )

    @property
    def _feed_source(self) -> Source:
        return self.feed_source if self.feed_source is not None else self.source

    def get_option_chain(self, underlying: str) -> Observation[ChainSnapshot]:
        """Return the registered chain as a graded observation."""
        snapshot = self.chains.get(underlying)
        if snapshot is None:
            raise MarketDataUnavailableError(f"no chain for {underlying}")
        return Observation(
            value=snapshot,
            source=self._feed_source,
            as_of=snapshot.quoted_at,
            fetched_at=self.fetched_at,
        )

    def get_rate(self, series: str) -> Observation[float]:
        """Return the registered yield as a graded observation."""
        if series not in self.rates:
            raise MarketDataUnavailableError(f"no rate for {series}")
        return Observation(
            value=self.rates[series],
            source=self._feed_source,
            as_of=self.fetched_at,
            fetched_at=self.fetched_at,
        )

    def get_spot(self, symbol: str) -> Observation[float]:
        """Return the index close, if one is registered."""
        if self.index_close is None:
            raise MarketDataUnavailableError(f"no spot for {symbol}")
        return Observation(
            value=self.index_close,
            source=self._feed_source,
            as_of=self.fetched_at,
            fetched_at=self.fetched_at,
        )


#: The typed book the feed tests start from: typed values that differ from
#: the chain's, so every adoption is visible.
TYPED_SPOT = 4800.0
TYPED_RATE = 0.03
TYPED_VOL = 0.19
STRIKES = (3500.0, 4000.0)


def leg_expiry() -> datetime:
    """Return the held legs' expiry: a year out on the program clock."""
    return days_from_today(365)


def make_provider(
    *,
    with_chain: bool = True,
    feed_source: Source | None = None,
) -> FedProvider:
    """Return a provider whose cache holds a chain listing the held legs."""
    chains = (
        {"SPX": fed_chain(leg_expiry().date(), STRIKES)} if with_chain else {}
    )
    return FedProvider(
        chains=chains,
        rates={"DGS1": FRED_PCT},
        feed_source=feed_source,
    )


def write_typed_book(tmp_path: Path, ips: Path) -> None:
    """Write a typed book to ``tmp_path`` with no feed involved."""
    state = ProgramState.load(
        tmp_path,
        ips_path=ips,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        examples_dir=tmp_path / "none",
    )
    state.update_market_conditions(
        spot_price=TYPED_SPOT,
        risk_free_rate=TYPED_RATE,
        dividend_yield=DIVIDEND,
    )
    for strike in STRIKES:
        state.add_position(
            strike_price=strike,
            maturity_date=leg_expiry(),
            quantity=10,
            option_type=OptionType.PUT,
            volatility=TYPED_VOL,
        )


def load_state(
    tmp_path: Path,
    ips: Path,
    provider: MarketDataProvider | None,
) -> ProgramState:
    """Load the typed book in ``tmp_path`` through *provider* (or none)."""

    def factory(_ips: IpsConfig | None) -> MarketDataProvider:
        assert provider is not None
        return provider

    return ProgramState.load(
        tmp_path,
        ips_path=ips,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        examples_dir=tmp_path / "none",
        market_data=factory if provider is not None else None,
    )
