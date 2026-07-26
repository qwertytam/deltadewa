"""Tests for deltadewa.widgets.assumptions module."""

from datetime import datetime, timedelta

import pytest

from deltadewa.widgets.assumptions import GlobalAssumptions


class TestGlobalAssumptions:
    """Test cases for GlobalAssumptions class."""

    def test_initialization_defaults(self) -> None:
        """Test GlobalAssumptions can be instantiated with defaults."""
        assumptions = GlobalAssumptions()
        assert assumptions is not None
        assert assumptions.spot_price.value == pytest.approx(100.0, rel=1e-5)
        assert assumptions.volatility.value == pytest.approx(0.25, rel=1e-4)
        assert assumptions.risk_free_rate.value == pytest.approx(0.05, rel=1e-9)
        assert assumptions.dividend_yield.value == pytest.approx(0.0, rel=1e-8)

    def test_initialization_custom_values(self) -> None:
        """Test GlobalAssumptions with custom initial values."""
        val_date = datetime(2024, 1, 1)
        assumptions = GlobalAssumptions(
            spot_price=420.0,
            volatility=0.30,
            risk_free_rate=0.03,
            dividend_yield=0.02,
            valuation_date=val_date,
        )
        assert assumptions.spot_price.value == pytest.approx(420.0, rel=1e-5)
        assert assumptions.volatility.value == pytest.approx(0.30, rel=1e-8)
        assert assumptions.risk_free_rate.value == pytest.approx(0.03, rel=1e-9)
        assert assumptions.dividend_yield.value == pytest.approx(0.02, rel=1e-9)
        assert assumptions.valuation_date.value == val_date.date()

    def test_widgets_exist(self) -> None:
        """Test all expected widgets are created."""
        assumptions = GlobalAssumptions()
        assert hasattr(assumptions, "spot_price")
        assert hasattr(assumptions, "volatility")
        assert hasattr(assumptions, "risk_free_rate")
        assert hasattr(assumptions, "dividend_yield")
        assert hasattr(assumptions, "valuation_date")
        assert hasattr(assumptions, "time_horizon")
        assert hasattr(assumptions, "custom_days")
        assert hasattr(assumptions, "spot_shock_pct")
        assert hasattr(assumptions, "vol_shock_pct")
        assert hasattr(assumptions, "grid_resolution")
        assert hasattr(assumptions, "monte_carlo_num_sims")
        assert hasattr(assumptions, "monte_carlo_inc_ul")

    def test_get_days_forward_default(self) -> None:
        """Test get_days_forward returns correct value for default selection."""
        assumptions = GlobalAssumptions()
        # Default is "Today (T+180)" which is 180 days
        assert assumptions.get_days_forward() == 180

    def test_get_days_forward_custom(self) -> None:
        """Test get_days_forward returns custom days when selected."""
        assumptions = GlobalAssumptions()
        assumptions.time_horizon.value = -1  # Custom
        assumptions.custom_days.value = 45
        assert assumptions.get_days_forward() == 45

    def test_time_horizon_days_property(self) -> None:
        """Test time_horizon_days property returns object with value attribute.

        This is important for backward compatibility with code that expects an
        object with a .value attribute.
        """
        assumptions = GlobalAssumptions()
        time_horizon = assumptions.time_horizon_days
        assert hasattr(time_horizon, "value")
        assert time_horizon.value == 180  # Default selection

    def test_get_valuation_date_forward(self) -> None:
        """Test get_valuation_date_forward calculates correct future date."""
        val_date = datetime(2024, 1, 1)
        assumptions = GlobalAssumptions(valuation_date=val_date)
        assumptions.time_horizon.value = 30  # 30 days forward

        future_date = assumptions.get_valuation_date_forward()
        expected = val_date + timedelta(days=30)
        assert future_date == expected

    def test_to_dict(self) -> None:
        """Test to_dict exports all parameters correctly."""
        assumptions = GlobalAssumptions(spot_price=150.0, volatility=0.35)
        params = assumptions.to_dict()

        assert isinstance(params, dict)
        assert params["spot_price"] == pytest.approx(150.0, rel=1e-5)
        assert params["volatility"] == pytest.approx(0.35, rel=1e-4)
        assert "risk_free_rate" in params
        assert "dividend_yield" in params
        assert "valuation_date" in params
        assert "time_horizon_days" in params
        assert "spot_shock_pct" in params
        assert "vol_shock_pct" in params
        assert "grid_resolution" in params
        assert "monte_carlo_num_sims" in params
        assert "monte_carlo_inc_ul" in params

    def test_display(self) -> None:
        """Test display method returns a widget."""
        assumptions = GlobalAssumptions()
        widget = assumptions.display()
        assert widget is not None
        # Should return a VBox widget
        assert hasattr(widget, "children")

    def test_on_change_callback(self) -> None:
        """Test on_change registers and calls callbacks."""
        assumptions = GlobalAssumptions()
        call_log = []

        def callback(change) -> None:
            call_log.append(change)

        assumptions.on_change(callback)

        # Trigger a change
        assumptions.spot_price.value = 110.0

        # Callback should have been called
        assert len(call_log) > 0

    def test_custom_days_disabled_by_default(self) -> None:
        """Test custom days field is disabled when not in custom mode."""
        assumptions = GlobalAssumptions()
        assert assumptions.custom_days.disabled is True

    def test_custom_days_enabled_when_custom_selected(self) -> None:
        """Test custom days field is enabled in custom mode."""
        assumptions = GlobalAssumptions()
        assumptions.time_horizon.value = -1  # Custom
        # The observer should enable custom_days
        assert assumptions.custom_days.disabled is False
