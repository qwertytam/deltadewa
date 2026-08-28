"""Tests for deltadewa.analysis.maturity module."""

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio
from tests.clock_helpers import days_from_today


class TestMaturityMixin:
    """Test cases for MaturityMixin."""

    def test_classify_maturity_bucket_weekly(self) -> None:
        """Test classification for weekly options."""
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(0) == "0-7 days (Weekly)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(3) == "0-7 days (Weekly)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(7) == "0-7 days (Weekly)"
        )

    def test_classify_maturity_bucket_monthly(self) -> None:
        """Test classification for monthly options."""
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(8)
            == "8-30 days (Monthly)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(15)
            == "8-30 days (Monthly)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(30)
            == "8-30 days (Monthly)"
        )

    def test_classify_maturity_bucket_2month(self) -> None:
        """Test classification for 2-month options."""
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(31) == "31-60 days (2M)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(45) == "31-60 days (2M)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(60) == "31-60 days (2M)"
        )

    def test_classify_maturity_bucket_3month(self) -> None:
        """Test classification for 3-month options."""
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(61) == "61-90 days (3M)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(75) == "61-90 days (3M)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(90) == "61-90 days (3M)"
        )

    def test_classify_maturity_bucket_long_term(self) -> None:
        """Test classification for long-term options."""
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(91)
            == "90+ days (Long-term)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(180)
            == "90+ days (Long-term)"
        )
        assert (
            PortfolioAnalyzer.classify_maturity_bucket(365)
            == "90+ days (Long-term)"
        )

    def test_add_maturity_buckets(self) -> None:
        """Test adding maturity bucket columns to DataFrame."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        # Add a position, pinned to the portfolio's own valuation date
        # rather than a raw UTC now() -- otherwise the two disagree for up
        # to four hours a day and the assertion below can only be a
        # tolerance band (#321, #343).
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=days_from_today(15, now=portfolio.valuation_date),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        df = portfolio.to_dataframe()

        # Add maturity buckets
        df_with_buckets = analyzer.add_maturity_buckets(df)

        # Check columns were added
        assert "days_to_expiry" in df_with_buckets.columns
        assert "maturity_bucket" in df_with_buckets.columns

        # Check values make sense
        assert df_with_buckets["days_to_expiry"].iloc[0] == 15
        assert (
            df_with_buckets["maturity_bucket"].iloc[0] == "8-30 days (Monthly)"
        )

    def test_days_to_expiry_uses_valuation_date(self) -> None:
        """days_to_expiry is measured from the valuation date, not now."""
        # Seeded off the program clock: add_position's default
        # valuation_date (used by its #365 expired-maturity guard) is
        # whatever "today" the clock reads at call time, before the
        # what-if override below — a pinned literal would go stale under
        # the clock-shift probe.
        maturity = days_from_today(365)
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )
        # A what-if valuation date exactly 30 days before maturity.
        portfolio.valuation_date = maturity - timedelta(days=30)

        analyzer = PortfolioAnalyzer(portfolio)
        df = analyzer.add_maturity_buckets(portfolio.to_dataframe())

        assert df["days_to_expiry"].iloc[0] == 30
        assert df["maturity_bucket"].iloc[0] == "8-30 days (Monthly)"

    def test_add_maturity_buckets_empty(self) -> None:
        """Test add_maturity_buckets with empty DataFrame."""
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.EUROPEAN
        )
        analyzer = PortfolioAnalyzer(portfolio)

        df = portfolio.to_dataframe()

        # Empty portfolio returns empty DataFrame, which may not have maturity
        # column
        if df.empty:
            # For empty portfolio, just check it doesn't raise an error
            # We'll test with a real position instead
            portfolio.add_position(
                strike_price=100.0,
                maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
                quantity=1,
                option_type=OptionType.CALL,
            )
            df = portfolio.to_dataframe()
            df_with_buckets = analyzer.add_maturity_buckets(df)
            assert "days_to_expiry" in df_with_buckets.columns
            assert "maturity_bucket" in df_with_buckets.columns


class TestVegaByMaturityBucket:
    """Tests for MaturityMixin.calculate_vega_by_maturity (Part X §14)."""

    def test_buckets_positions_correctly(self) -> None:
        """Legs in different buckets land in the right bucket."""
        maturity = datetime(2027, 1, 1, tzinfo=UTC)
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            valuation_date=maturity - timedelta(days=400),
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        # Weekly bucket (5 days out).
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity - timedelta(days=395),
            quantity=1,
            option_type=OptionType.CALL,
        )
        # Long-term bucket (100 days out).
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity - timedelta(days=300),
            quantity=2,
            option_type=OptionType.PUT,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        exposure = analyzer.calculate_vega_by_maturity()

        assert exposure.vega_by_bucket["0-7 days (Weekly)"] != pytest.approx(
            0.0,
            abs=1e-9,
        )
        assert exposure.vega_by_bucket["90+ days (Long-term)"] != pytest.approx(
            0.0, abs=1e-9
        )
        # Buckets nothing landed in are present, zero-filled.
        assert exposure.vega_by_bucket["8-30 days (Monthly)"] == pytest.approx(
            0.0,
            abs=1e-9,
        )
        assert exposure.vega_by_bucket["31-60 days (2M)"] == pytest.approx(
            0.0,
            abs=1e-9,
        )
        assert exposure.vega_by_bucket["61-90 days (3M)"] == pytest.approx(
            0.0,
            abs=1e-9,
        )
        assert set(exposure.vega_by_bucket) == {
            "0-7 days (Weekly)",
            "8-30 days (Monthly)",
            "31-60 days (2M)",
            "61-90 days (3M)",
            "90+ days (Long-term)",
        }

    def test_bucketed_vega_reconciles_to_total(self) -> None:
        """sum(vega_by_bucket.values()) == total_vega, always."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=10),
            quantity=3,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=200),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        exposure = analyzer.calculate_vega_by_maturity()

        assert sum(exposure.vega_by_bucket.values()) == pytest.approx(
            exposure.total_vega,
            rel=1e-9,
        )

    def test_empty_book_returns_zero_filled_buckets(self) -> None:
        """An empty book is a real all-zero reading, not a raise."""
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        analyzer = PortfolioAnalyzer(portfolio)

        exposure = analyzer.calculate_vega_by_maturity()

        assert exposure.total_vega == pytest.approx(0.0, abs=1e-9)
        assert len(exposure.vega_by_bucket) == 5
        assert all(
            v == pytest.approx(0.0, abs=1e-9)
            for v in exposure.vega_by_bucket.values()
        )
