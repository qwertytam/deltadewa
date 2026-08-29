"""Tests for deltadewa.analysis.maturity module."""

import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.maturity import (
    DEFAULT_MATURITY_BUCKETS,
    MaturityBuckets,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio
from tests.clock_helpers import days_from_today

DEFAULT = DEFAULT_MATURITY_BUCKETS
"""Shipped tail-hedge edges: 30 / 90 / 180 / 365 / 730 days."""


class TestMaturityBuckets:
    """The scheme itself: edges are the single source, labels derive."""

    def test_labels_derive_from_edges(self) -> None:
        assert MaturityBuckets(edges_days=(30, 90)).labels == (
            "0-30 days",
            "31-90 days",
            "90+ days",
        )

    def test_n_edges_give_n_plus_one_buckets(self) -> None:
        """The open-ended final bucket is always present."""
        for n in (1, 2, 5):
            edges = tuple(range(30, 30 * (n + 1), 30))
            assert len(MaturityBuckets(edges_days=edges).labels) == n + 1

    def test_shipped_default_is_tail_hedge_shaped(self) -> None:
        assert DEFAULT.labels == (
            "0-30 days",
            "31-90 days",
            "91-180 days",
            "181-365 days",
            "366-730 days",
            "730+ days",
        )

    def test_classify_lands_on_inclusive_upper_bounds(self) -> None:
        assert DEFAULT.classify(30) == "0-30 days"
        assert DEFAULT.classify(31) == "31-90 days"
        assert DEFAULT.classify(365) == "181-365 days"
        assert DEFAULT.classify(366) == "366-730 days"
        assert DEFAULT.classify(730) == "366-730 days"
        assert DEFAULT.classify(731) == "730+ days"

    def test_the_live_book_tranches_land_in_different_buckets(self) -> None:
        """#305's whole point: 310d and 493d were indistinguishable."""
        assert DEFAULT.classify(310) != DEFAULT.classify(493)

    def test_the_retired_scheme_could_not_separate_them(self) -> None:
        """Pins why the edges moved, not just that they did."""
        weeklies = MaturityBuckets(edges_days=(7, 30, 60, 90))
        assert weeklies.classify(310) == weeklies.classify(493) == "90+ days"

    def test_empty_edges_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            MaturityBuckets(edges_days=())

    def test_non_increasing_edges_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="strictly increasing"):
            MaturityBuckets(edges_days=(90, 30))

    def test_non_positive_first_edge_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            MaturityBuckets(edges_days=(0, 30))

    def test_single_edge_gives_two_buckets(self) -> None:
        """Degenerate case: the coarsest usable scheme."""
        buckets = MaturityBuckets(edges_days=(365,))
        assert buckets.labels == ("0-365 days", "365+ days")
        assert buckets.classify(400) == "365+ days"


class TestMaturityMixin:
    """Test cases for MaturityMixin."""

    def test_classify_delegates_to_the_scheme(self) -> None:
        assert PortfolioAnalyzer.classify_maturity_bucket(
            45, DEFAULT
        ) == DEFAULT.classify(45)

    def test_add_maturity_buckets_adds_both_columns(self) -> None:
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=days_from_today(45),
            quantity=1,
            option_type=OptionType.CALL,
        )
        analyzer = PortfolioAnalyzer(portfolio)

        df = analyzer.add_maturity_buckets(portfolio.to_dataframe(), DEFAULT)

        assert "maturity_bucket" in df.columns
        assert "days_to_expiry" in df.columns
        assert df["days_to_expiry"].iloc[0] == 45
        assert df["maturity_bucket"].iloc[0] == "31-90 days"

    def test_days_to_expiry_uses_the_valuation_date(self) -> None:
        """#182: a what-if valuation date must move the buckets."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            valuation_date=days_from_today(0),
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=days_from_today(200),
            quantity=1,
            option_type=OptionType.CALL,
        )
        analyzer = PortfolioAnalyzer(portfolio)

        df = analyzer.add_maturity_buckets(portfolio.to_dataframe(), DEFAULT)
        assert df["days_to_expiry"].iloc[0] == 200

        portfolio.valuation_date = days_from_today(150)
        df = analyzer.add_maturity_buckets(portfolio.to_dataframe(), DEFAULT)
        assert df["days_to_expiry"].iloc[0] == 50
        assert df["maturity_bucket"].iloc[0] == "31-90 days"


class TestVegaByMaturityBucket:
    """Tests for MaturityMixin.calculate_vega_by_maturity (Part X §14)."""

    @staticmethod
    def _ladder(*days: int) -> OptionPortfolio:
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            valuation_date=days_from_today(0),
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        for offset in days:
            portfolio.add_position(
                strike_price=90.0,
                maturity_date=days_from_today(offset),
                quantity=1,
                option_type=OptionType.PUT,
            )
        return portfolio

    def test_a_leaps_ladder_spreads_across_buckets(self) -> None:
        """#305: 3/6/9/12-month rungs used to collapse into one bucket."""
        portfolio = self._ladder(90, 180, 270, 365)
        analyzer = PortfolioAnalyzer(portfolio)

        exposure = analyzer.calculate_vega_by_maturity(DEFAULT)
        non_empty = [
            label
            for label, vega in exposure.vega_by_bucket.items()
            if abs(vega) > 1e-9
        ]

        assert len(non_empty) == 3
        assert non_empty == ["31-90 days", "91-180 days", "181-365 days"]

    def test_the_retired_scheme_put_the_whole_ladder_in_one_bucket(
        self,
    ) -> None:
        """The degenerate case, pinned so a regression is visible."""
        portfolio = self._ladder(90, 180, 270, 365)
        weeklies = MaturityBuckets(edges_days=(7, 30, 60, 90))

        exposure = PortfolioAnalyzer(portfolio).calculate_vega_by_maturity(
            weeklies,
        )
        non_empty = [
            label
            for label, vega in exposure.vega_by_bucket.items()
            if abs(vega) > 1e-9
        ]

        assert non_empty == ["61-90 days", "90+ days"]

    def test_every_canonical_bucket_is_present_zero_filled(self) -> None:
        portfolio = self._ladder(200)
        exposure = PortfolioAnalyzer(portfolio).calculate_vega_by_maturity(
            DEFAULT,
        )

        assert set(exposure.vega_by_bucket) == set(DEFAULT.labels)

    def test_bucketed_vega_reconciles_to_total(self) -> None:
        """sum(vega_by_bucket.values()) == total_vega, always."""
        portfolio = self._ladder(10, 200)
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=days_from_today(400),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        exposure = PortfolioAnalyzer(portfolio).calculate_vega_by_maturity(
            DEFAULT,
        )

        assert sum(exposure.vega_by_bucket.values()) == pytest.approx(
            exposure.total_vega,
            rel=1e-9,
        )

    def test_all_positions_in_one_bucket_still_reconciles(self) -> None:
        """Degenerate case: everything in one bucket."""
        portfolio = self._ladder(200, 210, 220)
        exposure = PortfolioAnalyzer(portfolio).calculate_vega_by_maturity(
            DEFAULT,
        )

        non_empty = [
            v for v in exposure.vega_by_bucket.values() if abs(v) > 1e-9
        ]
        assert len(non_empty) == 1
        assert sum(exposure.vega_by_bucket.values()) == pytest.approx(
            exposure.total_vega,
            rel=1e-9,
        )

    def test_empty_book_returns_zero_filled_buckets(self) -> None:
        """Degenerate case: an empty book is a real all-zero reading."""
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        exposure = PortfolioAnalyzer(portfolio).calculate_vega_by_maturity(
            DEFAULT,
        )

        assert exposure.total_vega == pytest.approx(0.0, abs=1e-9)
        assert set(exposure.vega_by_bucket) == set(DEFAULT.labels)
        assert all(
            v == pytest.approx(0.0, abs=1e-9)
            for v in exposure.vega_by_bucket.values()
        )
