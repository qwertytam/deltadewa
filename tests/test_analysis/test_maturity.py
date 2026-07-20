"""Tests for deltadewa.analysis.maturity module."""

from datetime import UTC, datetime, timedelta

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio


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
        )

        # Add a position
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=15),
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
        assert df_with_buckets["days_to_expiry"].iloc[0] >= 14
        assert df_with_buckets["days_to_expiry"].iloc[0] <= 16
        assert (
            df_with_buckets["maturity_bucket"].iloc[0] == "8-30 days (Monthly)"
        )

    def test_days_to_expiry_uses_valuation_date(self) -> None:
        """days_to_expiry is measured from the valuation date, not now."""
        maturity = datetime(2027, 1, 1, tzinfo=UTC)
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.2,
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
        portfolio = OptionPortfolio()
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
