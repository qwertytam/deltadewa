"""Tests for deltadewa.analysis.crash_payoff."""

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_payoff import (
    PremiumBasis,
    _long_puts,
    _net_protective_premium,
    _premium_with_basis,
    _shock_to_multiplier,
    compute_crash_convexity,
    crash_payoff_ratio,
    crash_scenario_table,
)
from deltadewa.analysis.crash_repricing import crash_hedge_value
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsConvexity
from deltadewa.portfolio.core import OptionPortfolio


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
        """PAID basis when every long put has entry_premium set."""
        portfolio = _make_long_put_portfolio(quantity=10)
        pos = portfolio.positions[0]
        pos.entry_premium = 2.50

        premium, basis = _premium_with_basis(portfolio)

        assert basis == PremiumBasis.PAID
        expected = 2.50 * abs(pos.quantity) * pos.contract_size
        assert premium == pytest.approx(expected)

    def test_current_basis_when_any_position_lacks_premium(self) -> None:
        """MARK basis when at least one long put lacks entry_premium."""
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

        assert basis == PremiumBasis.MARK

    def test_empty_portfolio_returns_current_basis(self) -> None:
        """No positions -> zero premium, MARK basis."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        premium, basis = _premium_with_basis(portfolio)
        assert premium == pytest.approx(0.0)
        assert basis == PremiumBasis.MARK


class TestComputeCrashConvexity:
    """Tests for compute_crash_convexity."""

    def test_curve_has_n_points(self) -> None:
        """result.curve contains exactly n_points entries."""
        portfolio = _make_long_put_portfolio()
        result = compute_crash_convexity(
            portfolio,
            crash_vol_shock=0.0,
            shock_range=(-30.0, 0.0),
            n_points=7,
        )
        assert len(result.curve) == 7

    def test_curve_covers_shock_range(self) -> None:
        """First and last curve shock_pct equal the shock_range bounds."""
        portfolio = _make_long_put_portfolio()
        result = compute_crash_convexity(
            portfolio,
            crash_vol_shock=0.0,
            shock_range=(-40.0, 10.0),
            n_points=51,
        )
        assert result.curve[0][0] == pytest.approx(-40.0)
        assert result.curve[-1][0] == pytest.approx(10.0)

    def test_scenario_rows_sampled_from_curve(self) -> None:
        """scenario_rows hedge_pnl values match the curve at those shocks."""
        portfolio = _make_long_put_portfolio()
        result = compute_crash_convexity(
            portfolio,
            crash_vol_shock=0.0,
            shock_range=(-40.0, 10.0),
            n_points=51,
        )
        curve_dict = dict(result.curve)
        for row in result.scenario_rows:
            if row.shock_pct in curve_dict:
                assert row.hedge_pnl == pytest.approx(
                    curve_dict[row.shock_pct],
                )

    def test_ips_crash_point_in_scenario_rows(self) -> None:
        """The IPS crash_scenario_pct always appears in scenario_rows."""
        portfolio = _make_long_put_portfolio()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=0.0,
            target_max_pct=100.0,
        )
        result = compute_crash_convexity(
            portfolio,
            crash_vol_shock=ips.crash_vol_shock,
            ips_convexity=ips,
        )
        shocks_in_rows = {r.shock_pct for r in result.scenario_rows}
        assert -25.0 in shocks_in_rows

    def test_payoff_ratio_matches_manual(self) -> None:
        """payoff_ratio equals repriced_hedge_at_ips / premium_paid."""
        portfolio = _make_long_put_portfolio()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=0.0,
            target_max_pct=100.0,
        )
        result = compute_crash_convexity(
            portfolio,
            crash_vol_shock=ips.crash_vol_shock,
            ips_convexity=ips,
        )
        assert result.payoff_ratio is not None
        expected_repriced = crash_hedge_value(
            portfolio,
            crash_move=-0.25,
            vol_shock=ips.crash_vol_shock,
            positions=_long_puts(portfolio),
        )
        assert result.payoff_ratio == pytest.approx(
            expected_repriced / result.premium_paid,
        )

    def test_payoff_ratio_none_without_ips(self) -> None:
        """payoff_ratio is None when no ips_convexity is supplied."""
        portfolio = _make_long_put_portfolio()
        result = compute_crash_convexity(portfolio, crash_vol_shock=0.0)
        assert result.payoff_ratio is None
        assert result.ips_convexity is None

    def test_scenario_rows_match_crash_scenario_table(self) -> None:
        """crash_scenario_table is a thin wrapper — rows are identical."""
        portfolio = _make_long_put_portfolio()
        shocks = [-10.0, -25.0, -40.0]
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=0.0,
            target_max_pct=100.0,
        )
        result = compute_crash_convexity(
            portfolio,
            crash_vol_shock=ips.crash_vol_shock,
            ips_convexity=ips,
            scenario_shocks=shocks,
        )
        table = crash_scenario_table(
            portfolio,
            shocks=shocks,
            ips_convexity=ips,
        )
        assert result.scenario_rows == table

    def test_premium_basis_entry_when_entry_premiums_set(self) -> None:
        """PremiumBasis.PAID when all long puts have entry_premium."""
        portfolio = _make_long_put_portfolio()
        portfolio.positions[0].entry_premium = 2.50
        result = compute_crash_convexity(portfolio, crash_vol_shock=0.0)
        assert result.premium_basis == PremiumBasis.PAID

    def test_premium_basis_current_fallback(self) -> None:
        """PremiumBasis.MARK when no entry_premium set."""
        portfolio = _make_long_put_portfolio()
        result = compute_crash_convexity(portfolio, crash_vol_shock=0.0)
        assert result.premium_basis == PremiumBasis.MARK

    def test_single_pricing_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each unique shock in the combined set is repriced exactly once."""
        import deltadewa.analysis.crash_payoff as _cp

        calls: list[float] = []
        original = _cp.crash_hedge_value

        def counting_hedge_value(
            portfolio: OptionPortfolio,
            *,
            crash_move: float,
            vol_shock: float,
            skew_steepening: float = 0.0,
            positions: object = None,
        ) -> float:
            calls.append(round(crash_move * 100.0, 6))
            return original(
                portfolio,
                crash_move=crash_move,
                vol_shock=vol_shock,
                skew_steepening=skew_steepening,
                positions=positions,
            )

        monkeypatch.setattr(_cp, "crash_hedge_value", counting_hedge_value)

        portfolio = _make_long_put_portfolio()
        # n_points=11; linspace(-40,10,11) = -40,-35,...,10 (step 5).
        # Default scenario shocks -10,-20,-30,-40 are all on the grid,
        # so combined set = fine_grid only = 11 unique points.
        n = 11
        compute_crash_convexity(
            portfolio,
            crash_vol_shock=0.0,
            shock_range=(-40.0, 10.0),
            n_points=n,
        )
        assert len(calls) == n
        assert len(set(calls)) == n


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
        assert _net_protective_premium(portfolio) == pytest.approx(
            0.0, rel=1e-4
        )

    def test_empty_portfolio_is_zero(self) -> None:
        """An empty portfolio has zero protective premium."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        assert _net_protective_premium(portfolio) == pytest.approx(
            0.0, rel=1e-4
        )


class TestCrashPayoffRatio:
    """Tests for crash_payoff_ratio."""

    def test_known_ratio_against_portfolio_oracle(self) -> None:
        """Ratio matches the repriced long-put value / premium directly.

        Uses the shared crash-repricing helper as the oracle — the repriced
        hedge value of the long puts (hedge-only, spot-only vol_shock=0.0),
        over the mark-fallback premium.
        """
        portfolio = _make_long_put_portfolio()
        pos = portfolio.positions[0]
        expected_premium = pos.position_value()  # mark fallback
        expected_repriced = crash_hedge_value(
            portfolio,
            crash_move=-0.25,
            vol_shock=0.0,
            positions=_long_puts(portfolio),
        )

        ratio = crash_payoff_ratio(portfolio, crash_pct=-25.0, vol_shock=0.0)

        assert ratio == pytest.approx(expected_repriced / expected_premium)

    def test_underlying_quantity_does_not_affect_payoff(self) -> None:
        """hedge_pnl/payoff_ratio ignore the protected book's P&L."""
        unhedged_book = _make_long_put_portfolio(underlying_quantity=0.0)
        hedged_book = _make_long_put_portfolio(underlying_quantity=5000.0)

        ratio_no_book = crash_payoff_ratio(
            unhedged_book,
            crash_pct=-25.0,
            vol_shock=0.0,
        )
        ratio_with_book = crash_payoff_ratio(
            hedged_book,
            crash_pct=-25.0,
            vol_shock=0.0,
        )

        assert ratio_no_book == pytest.approx(ratio_with_book)

        # But convexity_pct (net-of-underlying) does change with the book.
        analyzer_no_book = PortfolioAnalyzer(unhedged_book)
        analyzer_with_book = PortfolioAnalyzer(hedged_book)
        convexity_no_book = analyzer_no_book.calculate_crash_convexity_pct(
            crash_scenario_pct=-25.0,
            crash_vol_shock=0.0,
            skew_steepening=0.0,
        )
        convexity_with_book = analyzer_with_book.calculate_crash_convexity_pct(
            crash_scenario_pct=-25.0,
            crash_vol_shock=0.0,
            skew_steepening=0.0,
        )
        assert convexity_no_book == pytest.approx(0.0, rel=1e-8)
        assert convexity_with_book != pytest.approx(0.0, rel=1e-8)

    def test_explicit_premium_overrides_computed_premium(self) -> None:
        """An explicit premium= bypasses _premium_with_basis."""
        portfolio = _make_long_put_portfolio()
        expected_repriced = crash_hedge_value(
            portfolio,
            crash_move=-0.25,
            vol_shock=0.0,
            positions=_long_puts(portfolio),
        )

        ratio = crash_payoff_ratio(
            portfolio,
            crash_pct=-25.0,
            vol_shock=0.0,
            premium=500.0,
        )

        assert ratio == pytest.approx(expected_repriced / 500.0)

    def test_zero_premium_is_safe(self) -> None:
        """No long puts -> zero premium -> ratio is 0.0, no division error."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=60),
            quantity=-10,
            option_type=OptionType.CALL,
        )

        assert crash_payoff_ratio(
            portfolio, crash_pct=-25.0, vol_shock=0.0
        ) == pytest.approx(0.0, rel=1e-8)

    def test_negative_explicit_premium_is_safe(self) -> None:
        """A negative explicit premium also returns 0.0, not a sign flip."""
        portfolio = _make_long_put_portfolio()

        ratio = crash_payoff_ratio(
            portfolio,
            crash_pct=-25.0,
            vol_shock=0.0,
            premium=-1.0,
        )

        assert ratio == pytest.approx(0.0, rel=1e-8)

    def test_empty_portfolio_is_safe(self) -> None:
        """An empty portfolio has zero premium and zero ratio."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        assert crash_payoff_ratio(
            portfolio, crash_pct=-25.0, vol_shock=0.0
        ) == pytest.approx(0.0, rel=1e-8)

    def test_vol_shock_is_required(self) -> None:
        """vol_shock has no default — it can't silently diverge to spot-only.

        Regression for the diverging-knobs trap: the crash scenario is always
        supplied (``crash_pct`` is required), so the vol shock must be too —
        pass ``0.0`` explicitly for a spot-only crash. Omitting it is a
        ``TypeError``, never a silent spot-only reprice.
        """
        portfolio = _make_long_put_portfolio()
        with pytest.raises(TypeError):
            crash_payoff_ratio(portfolio, crash_pct=-25.0)


class TestCrashScenarioTable:
    """Tests for crash_scenario_table."""

    def test_empty_portfolio_rows_are_zero(self) -> None:
        """Rows for an empty portfolio have zero P&L and ratio."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        rows = crash_scenario_table(portfolio, shocks=[-10.0, -25.0])

        assert len(rows) == 2
        for row in rows:
            assert row.hedge_pnl == pytest.approx(0.0, rel=1e-8)
            assert row.payoff_ratio == pytest.approx(0.0, rel=1e-8)

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
        # The reference convexity must use the same crash vol shock the table
        # will (single-sourced from the IPS), so the -25% row matches exactly.
        vol_shock = 0.0
        analyzer = PortfolioAnalyzer(portfolio)
        convexity_25 = analyzer.calculate_crash_convexity_pct(
            crash_scenario_pct=-25.0,
            crash_vol_shock=vol_shock,
            skew_steepening=0.0,
        )
        convexity_10 = analyzer.calculate_crash_convexity_pct(
            crash_scenario_pct=-10.0,
            crash_vol_shock=vol_shock,
            skew_steepening=0.0,
        )
        assert convexity_10 != pytest.approx(convexity_25)

        # Single-point band around the -25% result: that row should meet
        # the target exactly; the -10% row, with a different convexity_pct,
        # should not.
        ips_convexity = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=convexity_25,
            target_max_pct=convexity_25,
            crash_vol_shock=vol_shock,
        )

        rows = crash_scenario_table(
            portfolio,
            shocks=[-10.0, -25.0],
            ips_convexity=ips_convexity,
        )
        by_shock = {row.shock_pct: row for row in rows}

        assert by_shock[-25.0].meets_target is True
        assert by_shock[-10.0].meets_target is False
