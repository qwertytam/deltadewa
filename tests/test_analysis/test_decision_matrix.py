"""Tests for deltadewa.analysis.decision_matrix."""


from __future__ import annotations

from typing import Any

from deltadewa.analysis.decision_matrix import (
    DecisionVerdict,
    HedgeAdequacy,
    decision_matrix,
    entry_timing_tree,
)
from deltadewa.analysis.market_environment import (
    DataQuality,
    HedgeCostVerdict,
    MarketEnvironment,
    RegimeLabel,
    TermShape,
)
from deltadewa.analysis.monetization import (
    MonetizationPlan,
    MonetizationStepStatus,
)
from deltadewa.ips_config import IpsConvexity

# ── Shared helpers ────────────────────────────────────────────────────


def _make_env(**kwargs: Any) -> MarketEnvironment:
    """Return a fully-populated LIVE MarketEnvironment with overrides."""
    defaults: dict[str, Any] = {
        "vix": 18.0,
        "regime_percentile": 30.0,
        "regime_label": RegimeLabel.NORMAL,
        "skew_index": 130.0,
        "skew_percentile": 0.35,
        "term_structure": {},
        "term_shape": TermShape.FLAT,
        "forward_vol_front_3m": 19.0,
        "hedge_cost_verdict": HedgeCostVerdict.FAIR,
        "data_quality": DataQuality.LIVE,
    }
    return MarketEnvironment(**{**defaults, **kwargs})


_IPS = IpsConvexity(
    crash_scenario_pct=-20.0,
    target_min_pct=10.0,
    target_max_pct=30.0,
)


def _make_plan(*, harvest: float) -> MonetizationPlan:
    """Return a MonetizationPlan with the given value_to_harvest."""
    return MonetizationPlan(
        current_gain_pct=50.0,
        steps=[
            MonetizationStepStatus(
                gain_pct=25.0, sell_pct=25.0, triggered=True,
            ),
        ],
        recommended_cumulative_sell_pct=25.0,
        value_to_harvest=harvest,
        remaining_sell_capacity=75.0,
        gain_basis="paid",
        vol_spike_context=None,
    )


# ── decision_matrix: data-quality guard ──────────────────────────────

class TestDecisionMatrixInsufficientData:
    """Non-LIVE data_quality must return INSUFFICIENT_DATA, no raise."""

    def test_static_quality_returns_insufficient_data(self) -> None:
        """STATIC provider gives INSUFFICIENT_DATA verdict."""
        env = _make_env(data_quality=DataQuality.STATIC)
        result = decision_matrix(
            env, convexity_now_pct=15.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.INSUFFICIENT_DATA
        assert result.data_quality_note is not None
        assert "STATIC" in result.data_quality_note

    def test_unavailable_quality_returns_insufficient_data(self) -> None:
        """UNAVAILABLE provider gives INSUFFICIENT_DATA verdict."""
        env = _make_env(
            data_quality=DataQuality.UNAVAILABLE,
            hedge_cost_verdict=None,
        )
        result = decision_matrix(
            env, convexity_now_pct=15.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.INSUFFICIENT_DATA

    def test_hedge_adequacy_still_set_on_insufficient_data(self) -> None:
        """STATIC quality: hedge_adequacy is computed from convexity."""
        env = _make_env(data_quality=DataQuality.STATIC)
        # 8.0 < target_min_pct=10.0 → UNDER
        result = decision_matrix(
            env, convexity_now_pct=8.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.INSUFFICIENT_DATA
        assert result.hedge_adequacy is HedgeAdequacy.UNDER

    def test_none_cost_verdict_with_live_data(self) -> None:
        """LIVE but cost_verdict=None returns INSUFFICIENT_DATA."""
        env = _make_env(hedge_cost_verdict=None)
        result = decision_matrix(
            env, convexity_now_pct=15.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.INSUFFICIENT_DATA
        assert result.data_quality_note is not None
        assert result.cost_verdict is None


# ── decision_matrix: BUY signals ─────────────────────────────────────

class TestDecisionMatrixBuySignals:
    """UNDER-hedged + CHEAP or FAIR → BUY."""

    def test_under_hedged_cheap_is_buy(self) -> None:
        """Under-hedged with cheap protection → BUY."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.CHEAP)
        result = decision_matrix(
            env, convexity_now_pct=5.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.BUY
        assert result.hedge_adequacy is HedgeAdequacy.UNDER

    def test_under_hedged_fair_is_buy(self) -> None:
        """Under-hedged with fair protection → BUY (adequacy takes priority)."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.FAIR)
        result = decision_matrix(
            env, convexity_now_pct=5.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.BUY

    def test_adequacy_boundary_just_below_min_is_under(self) -> None:
        """Convexity just below target_min_pct=10.0 is UNDER."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.CHEAP)
        result = decision_matrix(
            env, convexity_now_pct=9.99, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.BUY
        assert result.hedge_adequacy is HedgeAdequacy.UNDER


# ── decision_matrix: AVOID signal ────────────────────────────────────

class TestDecisionMatrixAvoidSignal:
    """UNDER-hedged + EXPENSIVE → AVOID."""

    def test_under_hedged_expensive_is_avoid(self) -> None:
        """Under-hedged with expensive protection → AVOID."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.EXPENSIVE)
        result = decision_matrix(
            env, convexity_now_pct=5.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.AVOID
        assert result.hedge_adequacy is HedgeAdequacy.UNDER


# ── decision_matrix: MAINTAIN signals ────────────────────────────────

class TestDecisionMatrixMaintainSignals:
    """Various paths that should resolve to MAINTAIN."""

    def test_adequate_fair_no_gains_is_maintain(self) -> None:
        """Adequate convexity, fair cost, no gains → MAINTAIN."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.FAIR)
        result = decision_matrix(
            env, convexity_now_pct=20.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.MAINTAIN
        assert result.hedge_adequacy is HedgeAdequacy.ADEQUATE

    def test_adequate_cheap_with_gains_is_maintain(self) -> None:
        """Adequate + cheap + gains → MAINTAIN (FAIR cost, don't harvest)."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.CHEAP)
        result = decision_matrix(
            env,
            convexity_now_pct=20.0,
            ips_convexity=_IPS,
            monetization_plan=_make_plan(harvest=10_000.0),
        )
        assert result.verdict is DecisionVerdict.MAINTAIN

    def test_adequate_fair_with_gains_is_maintain(self) -> None:
        """Adequate + fair + gains → MAINTAIN (FAIR cost, don't harvest)."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.FAIR)
        result = decision_matrix(
            env,
            convexity_now_pct=20.0,
            ips_convexity=_IPS,
            monetization_plan=_make_plan(harvest=10_000.0),
        )
        assert result.verdict is DecisionVerdict.MAINTAIN

    def test_adequate_expensive_no_gains_is_maintain(self) -> None:
        """Adequate + expensive but no gains → MAINTAIN."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.EXPENSIVE)
        result = decision_matrix(
            env, convexity_now_pct=20.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.MAINTAIN

    def test_over_hedged_no_gains_is_maintain(self) -> None:
        """Over-hedged with no gains → MAINTAIN (nothing to harvest)."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.EXPENSIVE)
        result = decision_matrix(
            env, convexity_now_pct=35.0, ips_convexity=_IPS,
        )
        assert result.verdict is DecisionVerdict.MAINTAIN
        assert result.hedge_adequacy is HedgeAdequacy.OVER

    def test_adequacy_at_min_boundary_is_adequate(self) -> None:
        """Convexity exactly at target_min_pct=10.0 is ADEQUATE."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.FAIR)
        result = decision_matrix(
            env, convexity_now_pct=10.0, ips_convexity=_IPS,
        )
        assert result.hedge_adequacy is HedgeAdequacy.ADEQUATE

    def test_adequacy_at_max_boundary_is_adequate(self) -> None:
        """Convexity exactly at target_max_pct=30.0 is ADEQUATE."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.FAIR)
        result = decision_matrix(
            env, convexity_now_pct=30.0, ips_convexity=_IPS,
        )
        assert result.hedge_adequacy is HedgeAdequacy.ADEQUATE


# ── decision_matrix: MONETIZE signals ────────────────────────────────

class TestDecisionMatrixMonetizeSignals:
    """Conditions that should resolve to MONETIZE."""

    def test_adequate_expensive_with_gains_is_monetize(self) -> None:
        """Adequate + expensive + gains → MONETIZE."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.EXPENSIVE)
        result = decision_matrix(
            env,
            convexity_now_pct=20.0,
            ips_convexity=_IPS,
            monetization_plan=_make_plan(harvest=10_000.0),
        )
        assert result.verdict is DecisionVerdict.MONETIZE
        assert result.gains_available is True

    def test_over_hedged_cheap_with_gains_is_monetize(self) -> None:
        """Over-hedged + cheap + gains → MONETIZE (reduce over-size)."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.CHEAP)
        result = decision_matrix(
            env,
            convexity_now_pct=35.0,
            ips_convexity=_IPS,
            monetization_plan=_make_plan(harvest=5_000.0),
        )
        assert result.verdict is DecisionVerdict.MONETIZE

    def test_over_hedged_expensive_with_gains_is_monetize(self) -> None:
        """Over-hedged + expensive + gains → MONETIZE."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.EXPENSIVE)
        result = decision_matrix(
            env,
            convexity_now_pct=35.0,
            ips_convexity=_IPS,
            monetization_plan=_make_plan(harvest=5_000.0),
        )
        assert result.verdict is DecisionVerdict.MONETIZE

    def test_zero_harvest_not_gains_available(self) -> None:
        """value_to_harvest=0 → gains_available False → MAINTAIN."""
        env = _make_env(hedge_cost_verdict=HedgeCostVerdict.EXPENSIVE)
        result = decision_matrix(
            env,
            convexity_now_pct=20.0,
            ips_convexity=_IPS,
            monetization_plan=_make_plan(harvest=0.0),
        )
        assert result.verdict is DecisionVerdict.MAINTAIN
        assert result.gains_available is False


# ── entry_timing_tree: data-quality guard ────────────────────────────

class TestEntryTimingTreeInsufficientData:
    """Non-LIVE data quality declines entry-timing evaluation."""

    def test_static_quality_declines(self) -> None:
        """STATIC env → INSUFFICIENT_DATA, should_enter=False."""
        env = _make_env(data_quality=DataQuality.STATIC)
        result = entry_timing_tree(env)
        assert result.should_enter is False
        assert result.recommendation == "INSUFFICIENT_DATA"
        assert result.data_quality_note is not None
        assert len(result.steps) == 0

    def test_unavailable_quality_declines(self) -> None:
        """UNAVAILABLE env → INSUFFICIENT_DATA, empty steps."""
        env = _make_env(
            data_quality=DataQuality.UNAVAILABLE, vix=None,
        )
        result = entry_timing_tree(env)
        assert result.should_enter is False
        assert len(result.steps) == 0

    def test_live_but_vix_none_returns_insufficient_data(self) -> None:
        """LIVE but vix=None → INSUFFICIENT_DATA, step 1 recorded."""
        env = _make_env(vix=None)
        result = entry_timing_tree(env)
        assert result.should_enter is False
        assert len(result.steps) == 1
        assert result.steps[0].proceed is False

    def test_live_but_skew_none_returns_insufficient_data(self) -> None:
        """LIVE, vix ok, skew=None → stops at step 2."""
        env = _make_env(vix=18.0, skew_percentile=None)
        result = entry_timing_tree(env)
        assert result.should_enter is False
        assert len(result.steps) == 2
        assert result.steps[0].proceed is True
        assert result.steps[1].proceed is False


# ── entry_timing_tree: VIX-level stops ───────────────────────────────

class TestEntryTimingTreeVixStop:
    """Elevated VIX stops the tree at step 1."""

    def test_vix_above_very_high_threshold_stops_at_step1(self) -> None:
        """VIX > 40 → monetize recommendation, should_enter=False."""
        env = _make_env(vix=42.0)
        result = entry_timing_tree(env)
        assert result.should_enter is False
        assert len(result.steps) == 1
        assert result.steps[0].proceed is False
        assert "monetize" in result.recommendation.lower()

    def test_vix_at_very_high_threshold_is_caution_not_monetize(
        self,
    ) -> None:
        """VIX exactly = 40 is not > 40, so falls to caution branch."""
        env = _make_env(vix=40.0)
        result = entry_timing_tree(env)
        assert result.should_enter is False
        assert "caution" in result.recommendation.lower()

    def test_vix_in_caution_range_stops_at_step1(self) -> None:
        """VIX 25-40 → caution recommendation, should_enter=False."""
        env = _make_env(vix=30.0)
        result = entry_timing_tree(env)
        assert result.should_enter is False
        assert len(result.steps) == 1
        assert "caution" in result.recommendation.lower()


# ── entry_timing_tree: skew-level stop ───────────────────────────────

class TestEntryTimingTreeSkewStop:
    """Expensive skew stops the tree at step 2."""

    def test_expensive_skew_stops_at_step2(self) -> None:
        """VIX ok, skew > 0.70 → step 2 stops, should_enter=False."""
        env = _make_env(vix=18.0, skew_percentile=0.80)
        result = entry_timing_tree(env)
        assert result.should_enter is False
        assert len(result.steps) == 2
        assert result.steps[0].proceed is True
        assert result.steps[1].proceed is False


# ── entry_timing_tree: full three-step paths ─────────────────────────

class TestEntryTimingTreeFullPath:
    """Three-step paths that reach step 3 with should_enter=True."""

    def test_low_vix_low_skew_contango_enters(self) -> None:
        """Low VIX, cheap skew, contango → 3 steps, should_enter=True."""
        env = _make_env(
            vix=12.0,
            skew_percentile=0.20,
            term_shape=TermShape.CONTANGO,
        )
        result = entry_timing_tree(env)
        assert result.should_enter is True
        assert len(result.steps) == 3
        assert all(s.proceed for s in result.steps)
        assert "contango" in result.recommendation.lower()

    def test_normal_vix_normal_skew_flat_enters(self) -> None:
        """Moderate VIX, mid-range skew, flat term → enters."""
        env = _make_env(
            vix=18.0,
            skew_percentile=0.50,
            term_shape=TermShape.FLAT,
        )
        result = entry_timing_tree(env)
        assert result.should_enter is True
        assert len(result.steps) == 3

    def test_low_vix_records_urgency_in_step1(self) -> None:
        """VIX <= vix_low triggers 'increased urgency' note."""
        env = _make_env(
            vix=13.0,
            skew_percentile=0.50,
            term_shape=TermShape.FLAT,
        )
        result = entry_timing_tree(env)
        assert "urgency" in result.steps[0].recommendation.lower()

    def test_backwardation_noted_in_step3(self) -> None:
        """Backwardation term structure is reflected in the recommendation."""
        env = _make_env(
            vix=18.0,
            skew_percentile=0.40,
            term_shape=TermShape.BACKWARDATION,
        )
        result = entry_timing_tree(env)
        assert result.should_enter is True
        assert "backwardation" in result.recommendation.lower()

    def test_cheap_skew_noted_in_step2(self) -> None:
        """Skew < skew_low → step 2 recommends aggressive accumulation."""
        env = _make_env(
            vix=18.0,
            skew_percentile=0.20,
            term_shape=TermShape.FLAT,
        )
        result = entry_timing_tree(env)
        assert result.should_enter is True
        assert "aggressively" in result.steps[1].recommendation.lower()
