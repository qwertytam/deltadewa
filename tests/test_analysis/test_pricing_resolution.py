"""The pricing-input resolver (9b): one value per input, and where it came from.

Synthetic chains only (``tests/chain_builders.py``): every contract is priced
by this repo's own engine from a known smile at a known rate and dividend
yield, so "does the resolver recover the smile at the effective r and q?" has
an exact answer. Nothing here is, or is derived from, a real payload.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from deltadewa.analysis.market_environment import DataQuality
from deltadewa.analysis.pricing_resolution import (
    EnteredInputs,
    FeedInputs,
    InputOrigin,
    LegTerms,
    ResolvedInputs,
    read_feed,
    resolve_pricing_inputs,
)
from deltadewa.constants import OptionType
from deltadewa.ips_config import (
    ChainSource,
    IpsConfig,
    IpsPricingFeed,
    load_ips_config,
)
from deltadewa.marketdata import (
    MarketDataUnavailableError,
    Observation,
    Source,
    StaticProvider,
)
from deltadewa.marketdata.chain import ChainSnapshot, parse_cboe_chain
from tests.chain_builders import (
    DECEMBER,
    DIVIDEND,
    RATE,
    SESSION,
    SPOT,
    smile,
    standard_chain,
)

_EXAMPLE_IPS = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)

#: The program date of every test: the session the chain describes.
_TODAY = SESSION
# As the program reads them: instants in the program zone, on the session day.
_NEW_YORK = ZoneInfo("America/New_York")
_NOW = datetime(2026, 11, 16, 21, 0, tzinfo=_NEW_YORK)
_FETCHED_AT = datetime(2026, 11, 16, 20, 40, tzinfo=_NEW_YORK)

#: The FRED percent that converts to exactly ``RATE`` continuously.
_FRED_PCT = 200.0 * (math.exp(RATE / 2.0) - 1.0)

_TYPED_SPOT = 4800.0
_TYPED_RATE = 0.03
_TYPED_VOL = 0.19

_DEEP = LegTerms("deep", DECEMBER, OptionType.PUT, 3500.0)
_NEAR = LegTerms("near", DECEMBER, OptionType.PUT, 4000.0)
_UNLISTED = LegTerms("unlisted", DECEMBER, OptionType.PUT, 4050.0)


def _policy(
    adopt: tuple[str, ...] = ("spot", "risk_free_rate", "volatility"),
    *,
    max_quote_age_days: int = 5,
) -> IpsPricingFeed:
    return IpsPricingFeed(
        adopt=adopt,
        rate_series="DGS1",
        chain_source=ChainSource.CBOE,
        max_quote_age_days=max_quote_age_days,
        max_spread_pct=25.0,
        override_warn_vol_points=2.0,
    )


def _entered(
    legs: tuple[LegTerms, ...] = (_DEEP, _NEAR),
    *,
    spot_pinned: bool = False,
    pinned: frozenset[str] = frozenset(),
) -> EnteredInputs:
    return EnteredInputs(
        spot=_TYPED_SPOT,
        risk_free_rate=_TYPED_RATE,
        dividend_yield=DIVIDEND,
        leg_vols={leg.position_id: _TYPED_VOL for leg in legs},
        spot_pinned=spot_pinned,
        pinned_legs=pinned,
    )


def _snapshot(*, timestamp: str | None = None) -> ChainSnapshot:
    payload = (
        standard_chain()
        if timestamp is None
        else standard_chain(timestamp=timestamp)
    )
    return parse_cboe_chain(payload)


def _chain(
    snapshot: ChainSnapshot | None = None,
    *,
    source: Source = Source.CACHED,
) -> Observation[ChainSnapshot]:
    snapshot = snapshot if snapshot is not None else _snapshot()
    return Observation(
        value=snapshot,
        source=source,
        as_of=snapshot.quoted_at,
        fetched_at=_FETCHED_AT,
    )


def _rate(
    *,
    source: Source = Source.CACHED,
    as_of: datetime = datetime(2026, 11, 13, tzinfo=UTC),
) -> Observation[float]:
    return Observation(
        value=_FRED_PCT,
        source=source,
        as_of=as_of,
        fetched_at=_FETCHED_AT,
    )


def _index(
    *,
    as_of: datetime = datetime(2026, 11, 13, tzinfo=UTC),
) -> Observation[float]:
    return Observation(
        value=4950.0,
        source=Source.CACHED,
        as_of=as_of,
        fetched_at=_FETCHED_AT,
    )


def _resolve(
    *,
    feed: FeedInputs,
    policy: IpsPricingFeed | None = None,
    entered: EnteredInputs | None = None,
    legs: tuple[LegTerms, ...] = (_DEEP, _NEAR),
    program_date: date = _TODAY,
) -> ResolvedInputs:
    return resolve_pricing_inputs(
        entered=entered if entered is not None else _entered(legs),
        legs=legs,
        policy=policy if policy is not None else _policy(),
        feed=feed,
        program_date=program_date,
        resolved_at=_NOW,
    )


def _full_feed() -> FeedInputs:
    return FeedInputs(chain=_chain(), rate=_rate(), index_spot=_index())


class TestNothingAdopted:
    """No policy, or nothing named: every input is the typed one."""

    def test_no_section_prices_on_typed_values(self) -> None:
        resolved = resolve_pricing_inputs(
            entered=_entered(),
            legs=(_DEEP, _NEAR),
            policy=None,
            feed=_full_feed(),
            program_date=_TODAY,
            resolved_at=_NOW,
        )

        assert resolved.is_identity
        assert resolved.spot.value == _TYPED_SPOT
        assert resolved.risk_free_rate.value == _TYPED_RATE
        assert {leg.value for leg in resolved.legs.values()} == {_TYPED_VOL}
        assert resolved.series == ()
        assert all(
            value.origin is InputOrigin.ENTERED
            for value in (
                resolved.spot,
                resolved.risk_free_rate,
                resolved.dividend_yield,
                *resolved.legs.values(),
            )
        )

    def test_an_empty_adopt_list_prices_on_typed_values(self) -> None:
        resolved = _resolve(feed=_full_feed(), policy=_policy(()))

        assert resolved.is_identity
        assert resolved.series == ()

    def test_an_input_not_named_stays_typed(self) -> None:
        resolved = _resolve(
            feed=_full_feed(),
            policy=_policy(("volatility",)),
        )

        assert resolved.spot.origin is InputOrigin.ENTERED
        assert resolved.spot.value == _TYPED_SPOT
        assert resolved.risk_free_rate.origin is InputOrigin.ENTERED
        assert resolved.legs["near"].origin is InputOrigin.FETCHED
        assert {use.name for use in resolved.series} == {"chain"}


class TestAdoptingAFreshFeed:
    """Rung 1: today's fetched values."""

    def test_spot_is_the_chains_own_index_level(self) -> None:
        resolved = _resolve(feed=_full_feed())

        assert resolved.spot.value == pytest.approx(SPOT)
        assert resolved.spot.origin is InputOrigin.FETCHED
        assert resolved.spot.session == SESSION
        assert resolved.spot.quality is DataQuality.CACHED
        assert resolved.session_date == SESSION

    def test_rate_is_converted_to_a_continuous_rate(self) -> None:
        resolved = _resolve(feed=_full_feed())

        assert resolved.risk_free_rate.value == pytest.approx(RATE)
        assert resolved.risk_free_rate.origin is InputOrigin.FETCHED

    def test_the_dividend_yield_is_always_typed(self) -> None:
        resolved = _resolve(feed=_full_feed())

        assert resolved.dividend_yield.origin is InputOrigin.ENTERED
        assert resolved.dividend_yield.value == DIVIDEND

    @pytest.mark.parametrize("leg", [_DEEP, _NEAR])
    def test_each_iv_is_the_smile_solved_at_the_effective_r_and_q(
        self,
        leg: LegTerms,
    ) -> None:
        resolved = _resolve(feed=_full_feed())

        value = resolved.legs[leg.position_id]
        assert value.origin is InputOrigin.FETCHED
        assert value.value == pytest.approx(smile(leg.strike), abs=2e-3)
        assert value.session == SESSION

    def test_ivs_differ_by_strike(self) -> None:
        resolved = _resolve(feed=_full_feed())

        assert resolved.legs["deep"].value > resolved.legs["near"].value

    def test_each_adopted_series_is_graded(self) -> None:
        resolved = _resolve(feed=_full_feed())

        assert {use.name: use.quality for use in resolved.series} == {
            "chain": DataQuality.CACHED,
            "rate": DataQuality.CACHED,
        }
        assert resolved.worst_series_quality is DataQuality.CACHED
        assert resolved.feed_down_since is None
        assert not resolved.is_identity


class TestTheRateAndYieldAreSolvedAt:
    """An IV and the (r, q) it was solved with are a pair."""

    def test_the_iv_is_solved_at_the_fetched_rate_when_the_rate_is_adopted(
        self,
    ) -> None:
        adopted = _resolve(feed=_full_feed())
        typed = _resolve(
            feed=_full_feed(),
            policy=_policy(("spot", "volatility")),
        )

        # Same chain, same mid: a different rate gives a different IV.
        assert adopted.legs["near"].value == pytest.approx(
            smile(4000.0),
            abs=2e-3,
        )
        assert typed.legs["near"].value != pytest.approx(
            adopted.legs["near"].value,
            abs=1e-3,
        )

    def test_a_typed_dividend_change_moves_the_solved_iv(self) -> None:
        base = _resolve(feed=_full_feed())
        moved = _resolve(
            feed=_full_feed(),
            entered=replace(_entered(), dividend_yield=DIVIDEND + 0.01),
        )

        assert moved.legs["near"].value != pytest.approx(
            base.legs["near"].value,
            abs=1e-4,
        )

    def test_a_spot_override_does_not_re_solve_the_ivs(self) -> None:
        free = _resolve(feed=_full_feed())
        pinned = _resolve(
            feed=_full_feed(),
            entered=_entered(spot_pinned=True),
        )

        assert pinned.legs["near"].value == pytest.approx(
            free.legs["near"].value,
        )


class TestOverrides:
    """A pin is a typed value the feed does not replace."""

    def test_a_pinned_spot_prices_on_the_typed_value_and_shows_the_fetched(
        self,
    ) -> None:
        resolved = _resolve(
            feed=_full_feed(),
            entered=_entered(spot_pinned=True),
        )

        assert resolved.spot.origin is InputOrigin.OVERRIDE
        assert resolved.spot.value == _TYPED_SPOT
        assert resolved.spot.fetched == pytest.approx(SPOT)

    def test_a_pinned_leg_prices_on_the_typed_iv_and_shows_the_fetched(
        self,
    ) -> None:
        resolved = _resolve(
            feed=_full_feed(),
            entered=_entered(pinned=frozenset({"near"})),
        )

        leg = resolved.legs["near"]
        assert leg.origin is InputOrigin.OVERRIDE
        assert leg.value == _TYPED_VOL
        assert leg.fetched == pytest.approx(smile(4000.0), abs=2e-3)
        assert resolved.legs["deep"].origin is InputOrigin.FETCHED

    def test_a_pin_on_an_input_the_policy_does_not_adopt_is_just_typed(
        self,
    ) -> None:
        resolved = _resolve(
            feed=_full_feed(),
            policy=_policy(("volatility",)),
            entered=_entered(spot_pinned=True),
        )

        assert resolved.spot.origin is InputOrigin.ENTERED


class TestWhenTheFeedFails:
    """The D8 ladder: last good, then the typed value, each labelled."""

    def test_a_stale_cache_within_the_age_limit_is_last_good(self) -> None:
        feed = FeedInputs(
            chain=_chain(source=Source.STALE),
            rate=_rate(source=Source.STALE),
            index_spot=_index(),
        )

        resolved = _resolve(feed=feed)

        assert resolved.spot.origin is InputOrigin.LAST_GOOD
        assert resolved.risk_free_rate.origin is InputOrigin.LAST_GOOD
        assert resolved.legs["near"].origin is InputOrigin.LAST_GOOD
        assert resolved.worst_series_quality is DataQuality.STALE
        assert resolved.spot.value == pytest.approx(SPOT)

    def test_a_chain_older_than_the_limit_falls_back_to_typed_values(
        self,
    ) -> None:
        feed = FeedInputs(chain=_chain(), rate=_rate(), index_spot=None)

        resolved = _resolve(
            feed=feed,
            program_date=date(2026, 11, 25),
            policy=_policy(max_quote_age_days=5),
        )

        assert resolved.spot.origin is InputOrigin.FALLBACK
        assert resolved.spot.value == _TYPED_SPOT
        assert resolved.legs["near"].origin is InputOrigin.FALLBACK
        assert resolved.legs["near"].value == _TYPED_VOL
        chain = next(use for use in resolved.series if use.name == "chain")
        assert chain.quality is DataQuality.UNAVAILABLE
        assert resolved.feed_down_since == SESSION

    def test_a_missing_chain_falls_back_and_reads_unavailable(self) -> None:
        resolved = _resolve(feed=FeedInputs(rate=_rate()))

        assert resolved.spot.origin is InputOrigin.FALLBACK
        assert resolved.legs["deep"].origin is InputOrigin.FALLBACK
        chain = next(use for use in resolved.series if use.name == "chain")
        assert chain.quality is DataQuality.UNAVAILABLE
        assert resolved.feed_down_since is None
        assert "no option chain" in resolved.legs["deep"].detail

    def test_the_index_close_backs_up_a_missing_chain_for_spot_only(
        self,
    ) -> None:
        resolved = _resolve(
            feed=FeedInputs(rate=_rate(), index_spot=_index()),
        )

        assert resolved.spot.origin is InputOrigin.FETCHED
        assert resolved.spot.value == pytest.approx(4950.0)
        assert resolved.legs["near"].origin is InputOrigin.FALLBACK

    def test_a_rate_older_than_the_limit_falls_back(self) -> None:
        feed = FeedInputs(
            chain=_chain(),
            rate=_rate(as_of=datetime(2026, 11, 1, tzinfo=UTC)),
        )

        resolved = _resolve(feed=feed)

        assert resolved.risk_free_rate.origin is InputOrigin.FALLBACK
        assert resolved.risk_free_rate.value == _TYPED_RATE
        rate = next(use for use in resolved.series if use.name == "rate")
        assert rate.quality is DataQuality.UNAVAILABLE
        assert resolved.feed_down_since == date(2026, 11, 1)

    def test_one_unusable_quote_falls_back_alone(self) -> None:
        legs = (_NEAR, _UNLISTED)

        resolved = _resolve(
            feed=_full_feed(),
            entered=_entered(legs),
            legs=legs,
        )

        assert resolved.legs["near"].origin is InputOrigin.FETCHED
        assert resolved.legs["unlisted"].origin is InputOrigin.FALLBACK
        assert resolved.legs["unlisted"].value == _TYPED_VOL
        assert "not listed" in resolved.legs["unlisted"].detail
        # The feed itself is healthy.
        assert resolved.worst_series_quality is DataQuality.CACHED

    def test_everything_falling_back_is_the_identity_view(self) -> None:
        resolved = _resolve(feed=FeedInputs())

        assert resolved.is_identity

    def test_an_expired_leg_is_left_on_its_typed_value(self) -> None:
        expired = LegTerms("old", date(2026, 11, 13), OptionType.PUT, 4000.0)

        resolved = _resolve(
            feed=_full_feed(),
            entered=_entered((expired,)),
            legs=(expired,),
        )

        assert resolved.legs["old"].origin is InputOrigin.ENTERED


class TestWhichTypedValuesPrice:
    """The review button stamps only typed values that are in use."""

    def test_a_fully_fed_book_has_only_the_dividend_typed(self) -> None:
        in_use = _resolve(feed=_full_feed()).typed_in_use()

        assert not in_use.spot
        assert not in_use.risk_free_rate
        assert in_use.dividend_yield
        assert in_use.legs == frozenset()

    def test_overrides_and_fallbacks_are_typed_in_use(self) -> None:
        legs = (_NEAR, _UNLISTED)
        resolved = _resolve(
            feed=_full_feed(),
            entered=_entered(
                legs,
                spot_pinned=True,
                pinned=frozenset({"near"}),
            ),
            legs=legs,
        )

        in_use = resolved.typed_in_use()
        assert in_use.spot
        assert not in_use.risk_free_rate
        assert in_use.legs == frozenset({"near", "unlisted"})


class TestReadFeed:
    """The feed is read once, and only what an adopted input needs."""

    def _provider(self) -> StaticProvider:
        return StaticProvider(
            spot_prices={"SPX": 4950.0},
            rates={"DGS1": _FRED_PCT},
            chains={"SPX": _snapshot()},
        )

    def test_no_section_reads_nothing(self) -> None:
        ips = _ips_with(None)

        feed = read_feed(self._provider(), ips)

        assert feed == FeedInputs()

    def test_only_what_an_adopted_input_needs_is_read(self) -> None:
        feed = read_feed(self._provider(), _ips_with(_policy(("volatility",))))

        assert feed.chain is not None
        assert feed.rate is None
        assert feed.index_spot is None

    def test_everything_adopted_reads_all_three(self) -> None:
        feed = read_feed(self._provider(), _ips_with(_policy()))

        assert feed.chain is not None
        assert feed.rate is not None
        assert feed.index_spot is not None

    def test_a_series_nothing_has_cached_is_none(self) -> None:
        provider = StaticProvider(spot_prices={}, rates={}, chains={})

        feed = read_feed(provider, _ips_with(_policy()))

        assert feed == FeedInputs()

    def test_the_static_provider_raises_for_a_missing_series(self) -> None:
        with pytest.raises(MarketDataUnavailableError):
            StaticProvider(chains={}).get_option_chain("SPX")


def _ips_with(policy: IpsPricingFeed | None) -> IpsConfig:
    """Return the shipped example IPS with *policy* as its ``pricing_feed``."""
    return replace(load_ips_config(_EXAMPLE_IPS), pricing_feed=policy)
