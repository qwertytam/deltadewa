"""Tests for deltadewa.dashboard.session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.dashboard import session as session_module
from deltadewa.dashboard.session import SessionContext, start_session
from deltadewa.marketdata import StaticProvider
from deltadewa.portfolio.core import OptionPortfolio

# ruff: noqa: S101


class TestStartSession:
    """Tests for start_session."""

    def test_loads_ips_config_by_default(self) -> None:
        """Test that start_session loads ips.yaml without a live network."""
        ctx = start_session(globals_dict={})

        assert isinstance(ctx, SessionContext)
        assert ctx.ips_config is not None
        assert ctx.ips_config.program.instrument == "SPX"
        assert isinstance(ctx.market_data, StaticProvider)

    def test_default_exercise_style_is_european_for_spx_symbol(self) -> None:
        """Test default_exercise_style is seeded from ips.pricing for SPX."""
        spx_portfolio = OptionPortfolio(spot_price=5000.0, symbol="SPX")
        spx_portfolio.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=90),
            quantity=1,
            option_type=OptionType.PUT,
        )

        ctx = start_session(globals_dict={"portfolio": spx_portfolio})

        assert ctx.portfolio is spx_portfolio
        assert ctx.portfolio.default_exercise_style == ExerciseStyle.EUROPEAN

    def test_global_assumptions_wired_from_setup_dashboard(self) -> None:
        """Test global_assumptions reflects setup_dashboard's portfolio."""
        ctx = start_session(globals_dict={})

        assert (
            ctx.global_assumptions.spot_price.value == ctx.portfolio.spot_price
        )
        assert (
            ctx.global_assumptions.volatility.value == ctx.portfolio.volatility
        )

    def test_role_is_stored_without_conditional_behaviour(self) -> None:
        """Test role is stored verbatim with no behavioural change."""
        combined_ctx = start_session(globals_dict={}, role="combined")
        other_ctx = start_session(globals_dict={}, role="hedge-only")

        assert combined_ctx.role == "combined"
        assert other_ctx.role == "hedge-only"

    def test_default_market_data_makes_no_network_calls(self) -> None:
        """Test the default path seeds a StaticProvider, not a live one."""
        # Pass an already-imported portfolio so its symbol is stable across
        # setup_dashboard (no default-portfolio swap), letting the seeded
        # StaticProvider resolve it directly with no fallback needed.
        spx_portfolio = OptionPortfolio(spot_price=5000.0, symbol="SPX")
        spx_portfolio.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=90),
            quantity=1,
            option_type=OptionType.PUT,
        )

        ctx = start_session(globals_dict={"portfolio": spx_portfolio})

        assert isinstance(ctx.market_data, StaticProvider)
        assert ctx.market_data.get_spot(ctx.portfolio.get_symbol()) == (
            ctx.portfolio.spot_price
        )

    def test_default_path_never_constructs_cboe_fred_provider(self) -> None:
        """Test use_live_market_data=False never touches the live transport.

        Patches CboeFredProvider itself (the only thing in this module that
        can make an HTTP call) and asserts it's never constructed — i.e. no
        HTTP is attempted — when the default offline path is used.

        Patches the module object directly (rather than by string path) so
        this stays correct even if another test reloads
        ``deltadewa.dashboard.session`` elsewhere in the same process.
        """
        with patch.object(
            session_module,
            "CboeFredProvider",
        ) as mock_cboe_fred_provider:
            ctx = start_session(globals_dict={}, use_live_market_data=False)

        mock_cboe_fred_provider.assert_not_called()
        assert isinstance(ctx.market_data, StaticProvider)

    def test_live_market_data_flag_constructs_cboe_fred_provider(self) -> None:
        """Test use_live_market_data=True does construct the live provider."""
        with patch.object(
            session_module,
            "CboeFredProvider",
        ) as mock_cboe_fred_provider:
            ctx = start_session(globals_dict={}, use_live_market_data=True)

        mock_cboe_fred_provider.assert_called_once_with()
        assert ctx.market_data is mock_cboe_fred_provider.return_value
