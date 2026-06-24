"""Tests for deltadewa.analysis.crash_payoff."""

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_payoff import (
    PremiumBasis,
    _net_protective_premium,
    _premium_with_basis,
    _shock_to_multiplier,
    compute_crash_convexity,
    crash_payoff_ratio,
    crash_scenario_table,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsConvexity
from deltadewa.portfolio.core import OptionPortfolio

# ruff: noqa: S101


def _make_long_put_portfolio(
    *,
    underlying_quantity: float = 0.0,
    strike_price: float = 100.0,
    quantity: int = 10,
    spot_price: float = 100.0,
) -> OptionPortfolio:
    portfolio = OptionPortfolio(
        spot_price=spot_price,
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        underlying_quantity=underlying_quantity,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=strike_price,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=60),
        quantity=quantity,
        option_type=OptionType.PUT,
    )
    return portfolio


class TestPremiumWithBasis:
    """Tests for _premium_with_basis."""

    def test_entry_basis_when_all_positions_have_premium(self) -> None:
        """ENTRY basis when every long put has entry_premium set."""
        portfolio = _make_long_put_portfolio(quantity=10)
        pos = portfolio.positions[0]
        pos.entry_premium = 2.50

        premium, basis = _premium_with_basis(portfolio)

        assert basis == PremiumBasis.ENTRY
        expected = 2.50 * abs(pos.quantity) * pos.contract_size
        assert premium == pytest.approx(expected)

    def test_current_basis_when_any_position_lacks_premium(self) -> None:
        """CURRENT basis when at least one long put lacks entry_premium."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            risk_free_rate=0.04,
            dividend_yield=0.0,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        maturity = datetime.now(tz=UTC) + timedelta(days=60)
        for _ in range(2):
            portfolio.add_position(
                strike_price=100.0,
                maturity_date=maturity,
                quantity=5,
                option_type=OptionType.PUT,
            )
        portfolio.positions[0].entry_premium = 2.50
        # positions[1].entry_premium stays None

        _, basis = _premium_with_basis(portfolio)

        assert basis == PremiumBasis.CURRENT

    def test_empty_portfolio_returns_current_basis(self) -> None:
        """No positions -> zero premium, CURRENT basis."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        premium, basis = _premium_with_basis(portfolio)
        assert premium == pytest.approx(0.0)
        assert basis == PremiumBasis.CURRENT


class TestComputeCrashConvexity:
    """Tests for compute_crash_convexity."""

    def test_rows_match_crash_scenario_table(self) -> None:
        """compute_crash_convexity rows agree with crash_scenario_table."""
        portfolio = _make_long_put_portfolio()
        shocks = [-10.0, -25.0, -40.0]
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=0.0,
            target_max_pct=100.0,
        )

        result = compute_crash_convexity(
            portfolio, shocks=shocks, ips_convexity=ips,
        )
        legacy = crash_scenario_table(
            portfolio, shocks=shocks, ips_convexity=ips,
        )

        assert len(result.rows) == len(legacy)
        for new, old in zip(result.rows, legacy, strict=True):
            assert new.shock_pct == old.shock_pct
            assert new.hedge_pnl == pytest.approx(old.hedge_pnl)
            assert new.payoff_ratio == pytest.approx(old.payoff_ratio)
            assert new.convexity_pct == pytest.approx(old.convexity_pct)
            assert new.meets_target == old.meets_target

    def test_headline_row_set_when_ips_supplied(self) -> None:
        """headline_row matches the IPS crash_scenario_pct row."""
        portfolio = _make_long_put_portfolio()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=0.0,
            target_max_pct=100.0,
        )

        result = compute_crash_convexity(
            portfolio, shocks=[-10.0, -25.0], ips_convexity=ips,
        )

        assert result.headline_row is not None
        assert result.headline_row.shock_pct == -25.0

    def test_no_ips_convexity_yields_none_headline(self) -> None:
        """Without ips_convexity, headline_row is None."""
        portfolio = _make_long_put_portfolio()

        result = compute_crash_convexity(portfolio, shocks=[-25.0])

        assert result.headline_row is None
        assert result.ips_convexity is None

    def test_premium_basis_entry_when_entry_premiums_set(self) -> None:
        """PremiumBasis.ENTRY when all long puts have entry_premium."""
        portfolio = _make_long_put_portfolio()
        portfolio.positions[0].entry_premium = 2.50

        result = compute_crash_convexity(portfolio, shocks=[-25.0])

        assert result.premium_basis == PremiumBasis.ENTRY

    def test_premium_basis_current_fallback(self) -> None:
        """PremiumBasis.CURRENT when no entry_premium set."""
        portfolio = _make_long_put_portfolio()
        # entry_premium is None by default

        result = compute_crash_convexity(portfolio, shocks=[-25.0])

        assert result.premium_basis == PremiumBasis.CURRENT

    def test_single_pricing_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each shock is priced exactly once — no double engine pass."""
        import deltadewa.analysis.crash_payoff as _cp

        calls: list[float] = []
        original = _cp._hedge_pnl_at_shock

        def counting_hedge_pnl(
            portfolio: OptionPortfolio, shock_pct: float,
        ) -> float:
            calls.append(shock_pct)
            return original(portfolio, shock_pct)

        monkeypatch.setattr(_cp, "_hedge_pnl_at_shock", counting_hedge_pnl)

        portfolio = _make_long_put_portfolio()
        shocks = [-10.0, -25.0, -40.0]
        compute_crash_convexity(portfolio, shocks=shocks)

        assert len(calls) == len(shocks)


class TestShockToMultiplier:
    """Tests for _shock_to_multiplier."""

    def test_negative_25_pct_is_075_multiplier(self) -> None:
        """-25.0 (a 25% decline) converts to a 0.75 spot multiplier."""
        assert _shock_to_multiplier(-25.0) == pytest.approx(0.75)

    def test_zero_pct_is_identity_multiplier(self) -> None:
        """0.0 converts to a 1.0 spot multiplier (no shock)."""
        assert _shock_to_multiplier(0.0) == pytest.approx(1.0)


class TestNetProtectivePremium:
    """Tests for _net_protective_premium."""

    def test_sums_long_put_position_value(self) -> None:
        """Premium equals the long put's own position_value()."""
        portfolio = _make_long_put_portfolio()
        position = portfolio.positions[0]
        assert _net_protective_premium(portfolio) == pytest.approx(
            position.position_value(),
        )

    def test_ignores_short_calls(self) -> None:
        """A short call contributes nothing to protective premium."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            risk_free_rate=0.04,
            dividend_yield=0.0,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=60),
            quantity=-10,
            option_type=OptionType.CALL,
        )
        assert _net_protective_premium(portfolio) == 0.0

    def test_empty_portfolio_is_zero(self) -> None:
        """An empty portfolio has zero protective premium."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        assert _net_protective_premium(portfolio) == 0.0


class TestCrashPayoffRatio:
    """Tests for crash_payoff_ratio."""

    def test_known_ratio_against_portfolio_oracle(self) -> None:
        """Ratio matches the value derived from the portfolio's own methods.

        Avoids hand-deriving the QuantLib price; uses
        ``calculate_pnl_at_expiry``/``position_value`` (already tested
        elsewhere) as the oracle.
        """
        portfolio = _make_long_put_portfolio()
        position = portfolio.positions[0]
        expected_premium = position.position_value()
        crash_spot = portfolio.spot_price * 0.75
        expected_pnl = portfolio.calculate_pnl_at_expiry(
            crash_spot,
            include_underlying=False,
        )

        ratio = crash_payoff_ratio(portfolio, crash_pct=-25.0)

        assert ratio == pytest.approx(expected_pnl / expected_premium)

    def test_underlying_quantity_does_not_affect_payoff(self) -> None:
        """hedge_pnl/payoff_ratio ignore the protected book's P&L."""
        unhedged_book = _make_long_put_portfolio(underlying_quantity=0.0)
        hedged_book = _make_long_put_portfolio(underlying_quantity=5000.0)

        ratio_no_book = crash_payoff_ratio(unhedged_book, crash_pct=-25.0)
        ratio_with_book = crash_payoff_ratio(hedged_book, crash_pct=-25.0)

        assert ratio_no_book == pytest.approx(ratio_with_book)

        # But convexity_pct (net-of-underlying) does change with the book.
        analyzer_no_book = PortfolioAnalyzer(unhedged_book)
        analyzer_with_book = PortfolioAnalyzer(hedged_book)
        convexity_no_book = analyzer_no_book.calculate_crash_convexity_pct(
            crash_pct=0.75,
        )
        convexity_with_book = analyzer_with_book.calculate_crash_convexity_pct(
            crash_pct=0.75,
        )
        assert convexity_no_book == 0.0
        assert convexity_with_book != 0.0

    def test_explicit_premium_overrides_computed_premium(self) -> None:
        """An explicit premium= bypasses _net_protective_premium."""
        portfolio = _make_long_put_portfolio()
        crash_spot = portfolio.spot_price * 0.75
        expected_pnl = portfolio.calculate_pnl_at_expiry(
            crash_spot,
            include_underlying=False,
        )

        ratio = crash_payoff_ratio(portfolio, crash_pct=-25.0, premium=500.0)

        assert ratio == pytest.approx(expected_pnl / 500.0)

    def test_zero_premium_is_safe(self) -> None:
        """No long puts -> zero premium -> ratio is 0.0, no division error."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=60),
            quantity=-10,
            option_type=OptionType.CALL,
        )

        assert crash_payoff_ratio(portfolio, crash_pct=-25.0) == 0.0

    def test_negative_explicit_premium_is_safe(self) -> None:
        """A negative explicit premium also returns 0.0, not a sign flip."""
        portfolio = _make_long_put_portfolio()

        ratio = crash_payoff_ratio(portfolio, crash_pct=-25.0, premium=-1.0)

        assert ratio == 0.0

    def test_empty_portfolio_is_safe(self) -> None:
        """An empty portfolio has zero premium and zero ratio."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        assert crash_payoff_ratio(portfolio, crash_pct=-25.0) == 0.0


class TestCrashScenarioTable:
    """Tests for crash_scenario_table."""

    def test_empty_portfolio_rows_are_zero(self) -> None:
        """Rows for an empty portfolio have zero P&L and ratio."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)

        rows = crash_scenario_table(portfolio, shocks=[-10.0, -25.0])

        assert len(rows) == 2
        for row in rows:
            assert row.hedge_pnl == 0.0
            assert row.payoff_ratio == 0.0

    def test_no_ips_convexity_means_no_target_met(self) -> None:
        """Without an ips_convexity band, every row's meets_target is False."""
        portfolio = _make_long_put_portfolio()

        rows = crash_scenario_table(portfolio, shocks=[-10.0, -25.0])

        assert all(row.meets_target is False for row in rows)

    def test_ips_shock_already_in_ladder_is_not_duplicated(self) -> None:
        """ips_convexity.crash_scenario_pct already in shocks -> no dup row."""
        portfolio = _make_long_put_portfolio()
        ips_convexity = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=0.0,
            target_max_pct=100.0,
        )

        rows = crash_scenario_table(
            portfolio,
            shocks=[-10.0, -25.0],
            ips_convexity=ips_convexity,
        )

        assert sorted(row.shock_pct for row in rows) == [-25.0, -10.0]
        assert len(rows) == 2

    def test_missing_ips_shock_is_added_and_ladder_sorted_mild_to_severe(
        self,
    ) -> None:
        """A crash_scenario_pct missing from shocks is added; sorted desc."""
        portfolio = _make_long_put_portfolio()
        ips_convexity = IpsConvexity(
            crash_scenario_pct=-40.0,
            target_min_pct=0.0,
            target_max_pct=100.0,
        )

        rows = crash_scenario_table(
            portfolio,
            shocks=[-10.0, -25.0],
            ips_convexity=ips_convexity,
        )

        assert [row.shock_pct for row in rows] == [-10.0, -25.0, -40.0]

    def test_meets_target_matches_inclusive_band(self) -> None:
        """meets_target is set from an inclusive target_min/max comparison."""
        # A partial hedge ratio (20 contracts vs. 5000 shares, not the
        # full 50 that would 1:1-offset the equity loss below the
        # strike and make crash P&L constant for every shock past it).
        portfolio = _make_long_put_portfolio(
            underlying_quantity=5000.0,
            strike_price=95.0,
            quantity=20,
        )
        analyzer = PortfolioAnalyzer(portfolio)
        convexity_25 = analyzer.calculate_crash_convexity_pct(crash_pct=0.75)
        convexity_10 = analyzer.calculate_crash_convexity_pct(crash_pct=0.90)
        assert convexity_10 != pytest.approx(convexity_25)

        # Single-point band around the -25% result: that row should meet
        # the target exactly; the -10% row, with a different convexity_pct,
        # should not.
        ips_convexity = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=convexity_25,
            target_max_pct=convexity_25,
        )

        rows = crash_scenario_table(
            portfolio,
            shocks=[-10.0, -25.0],
            ips_convexity=ips_convexity,
        )
        by_shock = {row.shock_pct: row for row in rows}

        assert by_shock[-25.0].meets_target is True
        assert by_shock[-10.0].meets_target is False
