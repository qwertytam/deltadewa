"""Tests for deltadewa.dashboard.monte_carlo_widget.MonteCarloStalenessWidget.

Strategy: test the staleness-detection logic without rendering any ipywidgets.
The widget constructor and check_and_warn() method may create widgets
internally; we only assert on the returned boolean and on state mutations.
"""

# ruff: noqa: S101 D101 D102 ANN001
# pylint: disable=missing-function-docstring, missing-class-docstring, protected-access

from __future__ import annotations

import datetime
from datetime import timedelta

from deltadewa.dashboard.monte_carlo_widget import MonteCarloStalenessWidget
from deltadewa.reporting.console import ConsoleReporter

UTC = datetime.UTC

# Threshold in hours used by the staleness check (mirror whatever constant the
# implementation uses; adjust if the implementation chooses a different value).
_STALE_THRESHOLD_HOURS = 1


def _widget(
    portfolio,
    num_sims=1000,
    include_underlying=True,
    reporter=None,
) -> MonteCarloStalenessWidget:
    return MonteCarloStalenessWidget(
        portfolio=portfolio,
        num_simulations=num_sims,
        include_underlying=include_underlying,
        reporter=reporter,
    )


# ===========================================================================
# Construction
# ===========================================================================


class TestMonteCarloStalenessWidgetConstruction:
    def test_constructs_with_minimal_args(
        self,
        single_position_portfolio,
    ) -> None:
        w = _widget(single_position_portfolio)
        assert w is not None

    def test_default_reporter_created_when_none(
        self,
        single_position_portfolio,
    ) -> None:
        w = _widget(single_position_portfolio)
        assert w._reporter is not None
        assert isinstance(w._reporter, ConsoleReporter)

    def test_custom_reporter_stored(
        self,
        single_position_portfolio,
        reporter,
    ) -> None:
        w = _widget(single_position_portfolio, reporter=reporter)
        assert w._reporter is reporter

    def test_num_simulations_stored(self, single_position_portfolio) -> None:
        w = _widget(single_position_portfolio, num_sims=5000)
        assert w._num_simulations == 5000

    def test_include_underlying_stored(self, single_position_portfolio) -> None:
        w = _widget(single_position_portfolio, include_underlying=False)
        assert w._include_underlying is False


# ===========================================================================
# Staleness detection
# ===========================================================================


class TestMonteCarloStalenessDetection:
    """check_and_warn() must return True when stale, False when fresh."""

    def test_no_mc_results_is_stale(self, single_position_portfolio) -> None:
        single_position_portfolio._monte_carlo_results = None
        w = _widget(single_position_portfolio)
        is_stale = w.check_and_warn()
        assert is_stale is True

    def test_fresh_timestamp_is_not_stale(
        self,
        single_position_portfolio,
    ) -> None:
        """Results computed moments ago should not be stale."""
        single_position_portfolio._monte_carlo_results = {
            "timestamp": datetime.datetime.now(tz=UTC),
            "simulated_pnls": [0.0] * 100,
            "num_simulations": 100,
        }
        w = _widget(single_position_portfolio)
        is_stale = w.check_and_warn()
        assert is_stale is False

    def test_old_timestamp_is_stale(self, single_position_portfolio) -> None:
        """Results older than the threshold should be considered stale."""
        old_ts = datetime.datetime.now(tz=UTC) - timedelta(
            hours=_STALE_THRESHOLD_HOURS + 1,
        )
        single_position_portfolio._monte_carlo_results = {
            "timestamp": old_ts,
            "simulated_pnls": [0.0] * 100,
            "num_simulations": 100,
        }
        w = _widget(single_position_portfolio)
        is_stale = w.check_and_warn()
        assert is_stale is True

    def test_missing_timestamp_key_is_stale(
        self,
        single_position_portfolio,
    ) -> None:
        """Results dict without a 'timestamp' key must be treated as stale."""
        single_position_portfolio._monte_carlo_results = {
            "simulated_pnls": [0.0] * 100,
            "num_simulations": 100,
            # no 'timestamp' key
        }
        w = _widget(single_position_portfolio)
        is_stale = w.check_and_warn()
        assert is_stale is True

    def test_portfolio_stale_flag_is_stale(
        self,
        single_position_portfolio,
    ) -> None:
        """portfolio.monte_carlo_stale == True should also trigger staleness."""
        single_position_portfolio._monte_carlo_results = {
            "timestamp": datetime.datetime.now(tz=UTC),
            "simulated_pnls": [0.0] * 100,
            "num_simulations": 100,
        }
        single_position_portfolio.monte_carlo_stale = True
        w = _widget(single_position_portfolio)
        is_stale = w.check_and_warn()
        assert is_stale is True

    def test_check_and_warn_does_not_raise_for_empty_portfolio(
        self,
        empty_portfolio,
    ) -> None:
        w = _widget(empty_portfolio)
        # Should not raise even with no positions and no MC results
        w.check_and_warn()

    def test_check_and_warn_returns_bool(
        self,
        single_position_portfolio,
    ) -> None:
        w = _widget(single_position_portfolio)
        result = w.check_and_warn()
        assert isinstance(result, bool)
