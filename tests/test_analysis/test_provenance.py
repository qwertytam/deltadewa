"""Tests for deltadewa.analysis.provenance (Batch 3d / #367)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from deltadewa.analysis.market_environment import DataQuality, MarketEnvironment
from deltadewa.analysis.provenance import (
    Freshness,
    InputKind,
    ProvenanceLedger,
    build_provenance_ledger,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsPricingInputs
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.stamps import MarketParameterStamps
from tests.clock_helpers import days_from_today

_AS_OF_DATE = date(2026, 8, 26)
_POLICY = IpsPricingInputs(
    spot_max_age_days=1,
    volatility_max_age_days=7,
    risk_free_rate_max_age_days=30,
    dividend_yield_max_age_days=90,
)


def _make_environment(
    *,
    data_quality: DataQuality = DataQuality.LIVE,
    as_of: datetime | None = None,
) -> MarketEnvironment:
    return MarketEnvironment(
        vix=18.0,
        regime_percentile=50.0,
        regime_label=None,
        skew_index=120.0,
        skew_percentile=0.5,
        term_structure={"VIX": 18.0, "VIX3M": 19.0, "VIX6M": 20.0},
        term_shape=None,
        forward_vol_front_3m=None,
        hedge_cost_verdict=None,
        data_quality=data_quality,
        as_of=as_of,
    )


def _make_portfolio(
    *,
    stamps: MarketParameterStamps | None = None,
) -> OptionPortfolio:
    return OptionPortfolio(
        spot_price=5000.0,
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.01,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        stamps=stamps,
    )


class TestFreshnessSeverity:
    """UNKNOWN must outrank AGING — unbounded damage beats bounded damage."""

    def test_unknown_outranks_aging(self) -> None:
        environment = _make_environment(data_quality=DataQuality.LIVE)
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                # 40 days stale against a 30-day policy: AGING.
                risk_free_rate_as_of=datetime(2026, 7, 17, tzinfo=UTC),
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        # spot/dividend were never stamped at all: UNKNOWN, and must win.
        assert ledger.worst is not None
        assert ledger.worst.freshness is Freshness.UNKNOWN
        assert ledger.worst.key in {"book.spot", "book.dividend_yield"}


class TestHandEnteredGrading:
    """Each hand-entered input is graded independently, on its own band."""

    def test_never_stamped_book_inputs_are_unknown_not_fresh(self) -> None:
        """A book that predates #367 must not read as freshly confirmed."""
        environment = _make_environment()
        portfolio = _make_portfolio()  # no stamps at all

        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )

        book_entries = {
            entry.key: entry
            for entry in ledger.by_kind(InputKind.HAND_ENTERED)
            if entry.key.startswith("book.")
        }
        assert len(book_entries) == 3
        for entry in book_entries.values():
            assert entry.freshness is Freshness.UNKNOWN
            assert entry.as_of is None
            assert entry.age_days is None

    def test_stamp_within_policy_is_fresh(self) -> None:
        environment = _make_environment()
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                spot_as_of=datetime(2026, 8, 25, tzinfo=UTC),  # 1 day ago
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        spot = next(e for e in ledger.entries if e.key == "book.spot")
        assert spot.freshness is Freshness.FRESH
        assert spot.age_days == 1

    def test_stamp_past_policy_is_aging(self) -> None:
        environment = _make_environment()
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                # 5 days ago, past the 1-day spot policy.
                spot_as_of=datetime(2026, 8, 21, tzinfo=UTC),
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        spot = next(e for e in ledger.entries if e.key == "book.spot")
        assert spot.freshness is Freshness.AGING
        assert spot.age_days == 5

    def test_per_leg_iv_is_graded_independently(self) -> None:
        environment = _make_environment()
        portfolio = _make_portfolio()
        # Maturity only needs to be unexpired at add-time (#365) — the
        # provenance grading below is entirely driven by volatility_as_of
        # vs. the absolute _AS_OF_DATE, so the maturity itself is seeded
        # off the program clock rather than pinned.
        maturity = days_from_today(365)
        portfolio.add_position(
            strike_price=4500.0,
            maturity_date=maturity,
            quantity=10,
            option_type=OptionType.PUT,
            volatility_as_of=datetime(2026, 8, 25, tzinfo=UTC),  # fresh
        )
        portfolio.add_position(
            strike_price=4000.0,
            maturity_date=maturity,
            quantity=10,
            option_type=OptionType.PUT,
            volatility_as_of=datetime(2026, 8, 1, tzinfo=UTC),  # stale
        )

        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )

        leg_entries = ledger.by_kind(InputKind.HAND_ENTERED)
        legs = [e for e in leg_entries if e.key.startswith("leg.")]
        assert len(legs) == 2
        freshnesses = {e.freshness for e in legs}
        assert freshnesses == {Freshness.FRESH, Freshness.AGING}

    def test_no_positions_yields_no_leg_entries(self) -> None:
        environment = _make_environment()
        portfolio = _make_portfolio()
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        assert not any(e.key.startswith("leg.") for e in ledger.entries)


class TestMarketDataEntry:
    """The fetched market-data channel is one entry among the others."""

    def test_live_market_data_is_fresh(self) -> None:
        environment = _make_environment(
            data_quality=DataQuality.LIVE,
            as_of=datetime(2026, 8, 26, tzinfo=UTC),
        )
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                spot_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                risk_free_rate_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                dividend_yield_as_of=datetime(2026, 8, 26, tzinfo=UTC),
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        market = next(e for e in ledger.entries if e.key == "market_data")
        assert market.freshness is Freshness.FRESH
        assert market.quality is DataQuality.LIVE

    def test_unavailable_market_data_is_missing(self) -> None:
        environment = _make_environment(data_quality=DataQuality.UNAVAILABLE)
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                spot_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                risk_free_rate_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                dividend_yield_as_of=datetime(2026, 8, 26, tzinfo=UTC),
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        assert ledger.worst is not None
        assert ledger.worst.key == "market_data"
        assert ledger.worst.freshness is Freshness.MISSING
        assert ledger.needs_banner is True


class TestNeedsBanner:
    """The banner mounts only for actionable conditions, never CACHED alone."""

    def test_all_fresh_needs_no_banner(self) -> None:
        environment = _make_environment(
            data_quality=DataQuality.LIVE,
            as_of=datetime(2026, 8, 26, tzinfo=UTC),
        )
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                spot_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                risk_free_rate_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                dividend_yield_as_of=datetime(2026, 8, 26, tzinfo=UTC),
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        assert ledger.needs_banner is False

    def test_cached_market_data_alone_does_not_mount_banner(self) -> None:
        """#368: a normal CACHED read (e.g. VIX's routine FRED lag) is fine."""
        environment = _make_environment(
            data_quality=DataQuality.CACHED,
            as_of=datetime(2026, 8, 20, tzinfo=UTC),
        )
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                spot_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                risk_free_rate_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                dividend_yield_as_of=datetime(2026, 8, 26, tzinfo=UTC),
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        assert ledger.needs_banner is False

    def test_one_unconfirmed_hand_entered_input_mounts_banner(self) -> None:
        environment = _make_environment(
            data_quality=DataQuality.LIVE,
            as_of=datetime(2026, 8, 26, tzinfo=UTC),
        )
        portfolio = _make_portfolio()  # no stamps: UNKNOWN
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        assert ledger.needs_banner is True


class TestCombinedQuality:
    """The digest and /health read this without a new grade vocabulary."""

    def test_all_fresh_reports_market_data_quality(self) -> None:
        environment = _make_environment(data_quality=DataQuality.LIVE)
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                spot_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                risk_free_rate_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                dividend_yield_as_of=datetime(2026, 8, 26, tzinfo=UTC),
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        assert ledger.combined_quality is DataQuality.LIVE

    def test_stale_hand_entered_input_turns_combined_quality(self) -> None:
        """#367's acceptance: a stale hand-entered input can turn the grade."""
        environment = _make_environment(
            data_quality=DataQuality.LIVE,
            as_of=datetime(2026, 8, 26, tzinfo=UTC),
        )
        portfolio = _make_portfolio()  # UNKNOWN book inputs
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        # UNKNOWN maps to STATIC, worse than the LIVE market data alone.
        assert ledger.combined_quality is DataQuality.STATIC

    def test_market_data_worse_than_hand_entered_wins(self) -> None:
        environment = _make_environment(data_quality=DataQuality.STALE)
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                spot_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                risk_free_rate_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                dividend_yield_as_of=datetime(2026, 8, 26, tzinfo=UTC),
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        assert ledger.combined_quality is DataQuality.STALE


class TestByKind:
    def test_filters_to_requested_kind(self) -> None:
        environment = _make_environment()
        portfolio = _make_portfolio()
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )
        fetched = ledger.by_kind(InputKind.FETCHED)
        hand_entered = ledger.by_kind(InputKind.HAND_ENTERED)
        assert {e.key for e in fetched} == {"market_data"}
        assert all(e.kind is InputKind.HAND_ENTERED for e in hand_entered)
        assert len(fetched) + len(hand_entered) == len(ledger.entries)


class TestWorstOf:
    """/health's pricing_inputs object must never borrow market_data's grade."""

    def test_worst_of_hand_entered_ignores_a_worse_market_data_channel(
        self,
    ) -> None:
        environment = _make_environment(data_quality=DataQuality.UNAVAILABLE)
        portfolio = _make_portfolio(
            stamps=MarketParameterStamps(
                spot_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                risk_free_rate_as_of=datetime(2026, 8, 26, tzinfo=UTC),
                dividend_yield_as_of=datetime(2026, 8, 26, tzinfo=UTC),
            ),
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            _POLICY,
            as_of=_AS_OF_DATE,
        )

        assert ledger.worst is not None
        assert ledger.worst.key == "market_data"  # the true overall worst
        worst_hand_entered = ledger.worst_of(InputKind.HAND_ENTERED)
        assert worst_hand_entered is not None
        assert worst_hand_entered.freshness is Freshness.FRESH

    def test_worst_of_returns_none_for_an_empty_kind(self) -> None:
        """A ledger built with no hand-entered entries reports None, not a
        crash — worst_of must not assume every kind is represented.
        """
        environment = _make_environment(data_quality=DataQuality.LIVE)
        market_entry = build_provenance_ledger(
            environment,
            _make_portfolio(),
            _POLICY,
            as_of=_AS_OF_DATE,
        ).entries[0]  # the synthetic "market_data" FETCHED entry

        ledger = ProvenanceLedger(
            entries=(market_entry,),
            market_data_as_of=None,
            market_data_fetched_at=None,
            market_data_quality=DataQuality.LIVE,
            oldest_series=None,
        )

        assert ledger.worst_of(InputKind.HAND_ENTERED) is None
