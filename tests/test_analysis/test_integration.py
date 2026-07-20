"""Integration tests for deltadewa.analysis package."""

from datetime import UTC, datetime, timedelta

import numpy as np

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio

# pylint: disable=protected-access


class TestPortfolioAnalyzerIntegration:
    """Integration tests for full PortfolioAnalyzer with all mixins."""

    def test_full_analysis_workflow(self) -> None:
        """Test complete analysis workflow with all features."""
        # Create portfolio with positions
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.01,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        # Add diverse positions
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,  # Short call
            option_type=OptionType.CALL,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,  # Long put
            option_type=OptionType.PUT,
        )

        portfolio.add_position(
            strike_price=110.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=60),
            quantity=-1,  # Short call
            option_type=OptionType.CALL,
        )

        # Create analyzer
        analyzer = PortfolioAnalyzer(portfolio)

        # Test maturity classification
        df = portfolio.to_dataframe()
        df_with_buckets = analyzer.add_maturity_buckets(df)
        assert "maturity_bucket" in df_with_buckets.columns

        # Test carry analysis
        carry_metrics = analyzer.calculate_carry_metrics()
        assert "total_theta_daily" in carry_metrics
        assert isinstance(carry_metrics["total_theta_daily"], (int, float))

        # Test theta summary table
        theta_table = analyzer.create_theta_summary_table()
        assert not theta_table.empty

        # Test concentration analysis
        concentration = analyzer.analyze_risk_concentration()
        assert "by_strike" in concentration
        assert "by_maturity" in concentration

        # Test hedge recommendations
        hedge_actions = analyzer.calculate_hedge_actions(
            target_hedge_ratio=50.0,
        )
        assert "current_state" in hedge_actions
        assert "target_state" in hedge_actions
        assert "underlying_trade" in hedge_actions

        # Test scenario grid
        spot_scenarios = np.array([95, 100, 105])
        time_points = [datetime.now(tz=UTC)]
        scenario_result = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="pnl",
        )
        assert len(scenario_result) > 0

        # Test scenario grid with spot/vol
        vol_scenarios = np.array([0.2, 0.3, 0.4])
        spot_vol_result = analyzer.scenario_grid_spot_vol(
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            metric="pnl",
        )
        assert len(spot_vol_result) > 0

        # Test risk summary
        risk_summary = analyzer.format_risk_summary()
        assert isinstance(risk_summary, str)
        assert len(risk_summary) > 0

        # Test insights
        insights = analyzer.generate_insights()
        assert isinstance(insights, list)

    def test_all_methods_accessible(self) -> None:
        """Test that all methods from all mixins are accessible."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        # Maturity methods
        assert callable(analyzer.classify_maturity_bucket)
        assert callable(analyzer.add_maturity_buckets)

        # Carry methods
        assert callable(analyzer.calculate_carry_metrics)
        assert callable(analyzer._empty_carry_metrics)
        assert callable(analyzer.create_theta_summary_table)

        # Concentration methods
        assert callable(analyzer.analyze_risk_concentration)
        assert callable(analyzer._empty_concentration)

        # Hedge methods
        assert callable(analyzer.calculate_hedge_actions)
        assert callable(analyzer._calculate_option_alternatives)

        # Scenario methods
        assert callable(analyzer._calculate_portfolio_value_at)
        assert callable(
            analyzer._calculate_pnl_at_expiry_vectorized,
        )
        assert callable(analyzer.scenario_grid)
        assert callable(analyzer.scenario_grid_spot_vol)

        # Insights methods
        assert callable(analyzer.format_risk_summary)
        assert callable(analyzer.generate_insights)

    def test_mixin_methods_work_together(self) -> None:
        """Test that methods from different mixins work together."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        # Add positions at different maturities
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=10),
            quantity=1,
            option_type=OptionType.CALL,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=40),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        # Carry analysis uses maturity classification
        carry_metrics = analyzer.calculate_carry_metrics()
        assert "theta_by_bucket" in carry_metrics
        assert len(carry_metrics["theta_by_bucket"]) > 0

        # Concentration analysis also uses maturity classification
        concentration = analyzer.analyze_risk_concentration()
        if "delta" in concentration["by_maturity"]:
            assert len(concentration["by_maturity"]["delta"]) > 0

        # Insights use both carry and concentration
        insights = analyzer.generate_insights()
        assert isinstance(insights, list)

    def test_portfolio_analyzer_with_complex_portfolio(self) -> None:
        """Test analyzer with complex multi-position portfolio."""
        portfolio = OptionPortfolio(
            underlying_quantity=1000.0,
            spot_price=150.0,
            volatility=0.25,
            risk_free_rate=0.04,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        # Build a covered call + protective put strategy
        strikes = [140, 145, 150, 155, 160]
        maturities = [15, 30, 45, 60]

        for i, strike in enumerate(strikes):
            for j, days in enumerate(maturities):
                portfolio.add_position(
                    strike_price=float(strike),
                    maturity_date=datetime.now(tz=UTC) + timedelta(days=days),
                    quantity=(-1) ** (i + j),  # Mix of long/short
                    option_type=(
                        OptionType.CALL if i % 2 == 0 else OptionType.PUT
                    ),
                )

        analyzer = PortfolioAnalyzer(portfolio)

        # All analyses should complete without errors
        carry_metrics = analyzer.calculate_carry_metrics()
        concentration = analyzer.analyze_risk_concentration()
        hedge_actions = analyzer.calculate_hedge_actions(
            target_hedge_ratio=60.0,
        )
        insights = analyzer.generate_insights()

        assert carry_metrics is not None
        assert concentration is not None
        assert hedge_actions is not None
        assert insights is not None
