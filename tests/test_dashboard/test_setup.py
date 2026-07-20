"""Tests for deltadewa.dashboard.setup."""

import datetime
from unittest.mock import MagicMock

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.dashboard.setup import (
    build_global_assumptions,
    initialize_portfolio,
    print_portfolio_summary,
    setup_dashboard,
)
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsPricing,
    IpsProgram,
    IpsTriggers,
)
from deltadewa.marketdata import StaticProvider
from deltadewa.portfolio.core import OptionPortfolio

# pylint: disable=redefined-outer-name


def _make_ips_config(
    instrument: str,
    exercise_style: ExerciseStyle,
) -> IpsConfig:
    return IpsConfig(
        program=IpsProgram(name="test program", instrument=instrument),
        pricing=IpsPricing(exercise_style=exercise_style),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=20.0),
        triggers=IpsTriggers(
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_time_months=9.0,
            rally_rebalance_pct=15.0,
            strike_drift_max_otm_pct=45.0,
        ),
        monetization=IpsMonetization(schedule=()),
    )


class TestBuildGlobalAssumptions:
    """Tests for build_global_assumptions."""

    def test_without_market_data_unchanged(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test that omitting market_data leaves seeding behaviour unchanged."""
        global_assumptions, _ = build_global_assumptions(empty_portfolio)

        assert global_assumptions.spot_price.value == empty_portfolio.spot_price
        assert global_assumptions.volatility.value == empty_portfolio.volatility

    def test_with_static_provider_seeds_values(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test that a supplied provider seeds spot and VIX-derived vol."""
        provider = StaticProvider(
            spot_prices={empty_portfolio.get_symbol(): 123.0},
            vix=20.0,
        )

        global_assumptions, _ = build_global_assumptions(
            empty_portfolio,
            market_data=provider,
        )

        assert global_assumptions.spot_price.value == 123.0
        assert global_assumptions.volatility.value == 0.20

    def test_falls_back_on_provider_error(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test fallback to portfolio values when the provider has no spot."""
        provider = StaticProvider()  # no spot price registered
        reporter = MagicMock()

        global_assumptions, _ = build_global_assumptions(
            empty_portfolio,
            market_data=provider,
            reporter=reporter,
        )

        assert global_assumptions.spot_price.value == empty_portfolio.spot_price
        assert global_assumptions.volatility.value == empty_portfolio.volatility
        reporter.warning.assert_called_once()


class TestSetupDashboard:
    """Tests for setup_dashboard."""

    def test_threads_market_data_through(
        self,
        single_position_portfolio: OptionPortfolio,
    ) -> None:
        """Test that setup_dashboard passes market_data to GlobalAssumptions."""
        # Mark as already-imported so initialize_portfolio doesn't overwrite
        # it (and its symbol) with the default portfolio.
        globals_dict = {"portfolio": single_position_portfolio}
        provider = StaticProvider(
            spot_prices={single_position_portfolio.get_symbol(): 250.0},
            vix=18.0,
        )

        context = setup_dashboard(
            single_position_portfolio,
            globals_dict=globals_dict,
            market_data=provider,
        )

        global_assumptions = context["global_assumptions"]
        assert global_assumptions.spot_price.value == 250.0
        assert global_assumptions.volatility.value == 0.18

    def test_auto_load_default_false_leaves_portfolio_empty(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test auto_load_default=False skips the demo-portfolio fallback."""
        context = setup_dashboard(
            empty_portfolio,
            globals_dict={},
            auto_load_default=False,
        )

        assert context["portfolio_imported"] is False
        assert len(empty_portfolio.positions) == 0


class TestInitializePortfolio:
    """Tests for initialize_portfolio."""

    def test_auto_load_default_false_does_not_load_demo(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test that no demo portfolio is loaded when disabled."""
        imported = initialize_portfolio(
            empty_portfolio,
            globals_dict={},
            auto_load_default=False,
        )

        assert imported is False
        assert len(empty_portfolio.positions) == 0

    def test_auto_load_default_true_loads_demo(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test the unchanged default behaviour still loads the demo."""
        imported = initialize_portfolio(empty_portfolio, globals_dict={})

        assert imported is False
        assert len(empty_portfolio.positions) > 0


class TestPrintPortfolioSummary:
    """Tests for print_portfolio_summary."""

    def test_does_not_raise_for_empty_portfolio(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test the summary survives a zero-position portfolio.

        get_volatility_stats() returns {} with no positions; the function
        must not index "avg_volatility" unconditionally.
        """
        volatility_before = empty_portfolio.volatility

        print_portfolio_summary(empty_portfolio)

        assert empty_portfolio.volatility == volatility_before


class TestSetupDashboardIpsConfig:
    """Tests for ips_config-driven default_exercise_style wiring."""

    def test_matching_instrument_sets_default_exercise_style(self) -> None:
        """Test that a matching symbol seeds default_exercise_style."""
        portfolio = OptionPortfolio(
            spot_price=5000.0,
            symbol="SPX",
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        ips = _make_ips_config("SPX", ExerciseStyle.EUROPEAN)
        globals_dict = {"portfolio": _with_position(portfolio)}

        setup_dashboard(
            portfolio,
            globals_dict=globals_dict,
            ips_config=ips,
        )
        portfolio.add_position(
            strike_price=4500.0,
            maturity_date=datetime.datetime.now(tz=datetime.UTC)
            + datetime.timedelta(days=90),
            quantity=1,
            option_type=OptionType.PUT,
        )

        assert portfolio.default_exercise_style == ExerciseStyle.EUROPEAN
        assert portfolio.positions[-1].exercise_style == ExerciseStyle.EUROPEAN

    def test_non_matching_instrument_leaves_default_american(self) -> None:
        """Test that a non-matching symbol leaves the AMERICAN default."""
        portfolio = OptionPortfolio(
            spot_price=400.0,
            symbol="SPY",
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        ips = _make_ips_config("SPX", ExerciseStyle.EUROPEAN)
        globals_dict = {"portfolio": _with_position(portfolio)}

        setup_dashboard(
            portfolio,
            globals_dict=globals_dict,
            ips_config=ips,
        )
        portfolio.add_position(
            strike_price=380.0,
            maturity_date=datetime.datetime.now(tz=datetime.UTC)
            + datetime.timedelta(days=90),
            quantity=1,
            option_type=OptionType.PUT,
        )

        assert portfolio.default_exercise_style == ExerciseStyle.AMERICAN
        assert portfolio.positions[-1].exercise_style == ExerciseStyle.AMERICAN


def _with_position(portfolio: OptionPortfolio) -> OptionPortfolio:
    """Add a position so initialize_portfolio treats it as already imported."""
    portfolio.add_position(
        strike_price=portfolio.spot_price,
        maturity_date=datetime.datetime.now(tz=datetime.UTC)
        + datetime.timedelta(days=30),
        quantity=1,
        option_type=OptionType.CALL,
    )
    return portfolio
