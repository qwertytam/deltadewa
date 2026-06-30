"""Tests for deltadewa.widgets.summary module."""

from datetime import datetime
from unittest.mock import Mock

import pytest

from deltadewa import create_empty_portfolio
from deltadewa.formatters.html import format_html_metric
from deltadewa.widgets.summary import NetHedgeSummary


class TestNetHedgeSummary:
    """Test cases for NetHedgeSummary class."""

    @pytest.fixture
    def mock_portfolio(self) -> Mock:
        """Create a mock portfolio for testing."""
        portfolio = Mock()
        portfolio.spot_price = 100.0
        portfolio.valuation_date = datetime(2024, 1, 1)
        portfolio.volatility = 0.25
        portfolio.risk_free_rate = 0.05
        portfolio.dividend_yield = 0.02

        # Setup mock position for volatility stats
        pos = Mock()
        pos.option.volatility = 0.25
        pos.custom_volatility = False
        pos.position_vega.return_value = 10.0
        portfolio.positions = [pos]

        # Setup methods to return values expected by widget
        portfolio.summary_stats.return_value = {
            "total_underlying_value": 10000.0,
            "total_value": 500.0,
            "total_portfolio_value": 10500.0,
            "total_delta": 50.0,
            "net_delta": 10.0,
            "total_theta": -5.0,
            "total_vega": 20.0,
            "total_gamma": 1.5,
            "total_rho": 2.0,
            "hedge_ratio": 0.8,
            "delta_adjustment": 0.0,
            "volatility_min": 0.2,
            "volatility_max": 0.3,
            "custom_volatility_count": 0,
        }

        portfolio.calculate_pnl_at_expiry.return_value = 0.0

        # Setup risk analysis methods that analyzer will call
        portfolio.calculate_net_debit.return_value = 100.0
        portfolio.calculate_max_loss_options.return_value = {
            "max_loss": 100,
            "is_unlimited": False,
            "spot_at_max_loss": 95.0,
        }
        portfolio.calculate_max_profit_options.return_value = {
            "max_profit": 500,
            "is_unlimited": False,
            "spot_at_max_profit": 105.0,
        }
        portfolio.calculate_breakeven_points.return_value = [105.0]
        portfolio.calculate_max_loss_total.return_value = {
            "max_loss": 100,
            "is_unlimited": False,
            "spot_at_max_loss": 95.0,
        }
        portfolio.calculate_max_profit_total.return_value = {
            "max_profit": 500,
            "is_unlimited": False,
            "spot_at_max_profit": 105.0,
        }
        portfolio.run_monte_carlo_simulation.return_value = {
            "prob_profit": 0.6,
            "expected_pnl": 1.5,
        }

        portfolio.monte_carlo_results = {
            "simulated_pnls": [1.0, 2.0],
            "expected_pnl": 1.5,
            "prob_profit": 0.6,
        }

        return portfolio

    def test_initialization(self, mock_portfolio: Mock) -> None:
        """Test NetHedgeSummary can be instantiated."""
        summary = NetHedgeSummary(mock_portfolio)
        assert summary is not None
        assert summary.portfolio == mock_portfolio

    def test_attributes_exist(self, mock_portfolio: Mock) -> None:
        """Test all expected attributes are created."""
        summary = NetHedgeSummary(mock_portfolio)
        # Should have widget attributes
        assert hasattr(summary, "widget")
        assert summary.widget is not None

    def test_update_method_exists(self, mock_portfolio: Mock) -> None:
        """Test update method can be called."""
        summary = NetHedgeSummary(mock_portfolio)
        summary.update()

    def test_display_returns_widget(self, mock_portfolio: Mock) -> None:
        """Test display method returns a widget."""
        summary = NetHedgeSummary(mock_portfolio)
        widget = summary.display()
        assert widget is not None

    def test_widget_attribute(self, mock_portfolio: Mock) -> None:
        """Test widget attribute is a widget with children."""
        summary = NetHedgeSummary(mock_portfolio)
        assert hasattr(summary.widget, "children")

    def test_update_does_not_raise_for_empty_portfolio(self) -> None:
        """Test update() handles a zero-position portfolio gracefully.

        get_volatility_stats() returns {} when there are no positions;
        update() must not index "avg_volatility" unconditionally.

        The avg_volatility fallback (0.0) hits the near-zero threshold and
        renders as "- %" — NOT "0.00%". The previous assertion checked for
        "0.00%" which coincidentally matched "20.00%" (the default portfolio
        volatility shown in Min/Max Vol badges), never actually exercising the
        fallback path. This test pins the correct empty-state behaviour across
        multiple sections of the widget.
        """
        portfolio = create_empty_portfolio()

        summary = NetHedgeSummary(portfolio)

        # vol section: Vega-W.Avg Vol uses .get("avg_volatility", 0.0);
        # the exact badge should match what format_html_metric produces for 0.0.
        expected_avg_vol_badge = format_html_metric(
            "Vega-W.Avg Vol",
            0.0,
            format_type="percentage",
            is_neutral=True,
        )
        assert expected_avg_vol_badge in summary.vol_metrics_html.value

        # value section: all zero → near-zero placeholder "$ -"
        assert "Option Value" in summary.value_metrics_html.value
        assert "Total Portfolio Value" in summary.value_metrics_html.value

        # prob section: no Monte Carlo run → N/A breakeven
        assert "Breakeven Points:</strong> N/A" in summary.prob_stats_html.value
