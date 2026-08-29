"""Portfolio Analysis Module for Options Portfolios.

This module provides advanced analytical utilities for options portfolio
management, including carry analysis, risk concentration, maturity
classification, scenario generation, and hedge recommendation logic.

Author: DeltaDewa Team
Date: 2026-01-12
"""

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.cache import ScenarioGridCache
from deltadewa.analysis.candidate import CandidateMetrics, evaluate_candidate
from deltadewa.analysis.crash_payoff import (
    CrashConvexityResult,
    CrashScenarioRow,
    PremiumBasis,
    compute_crash_convexity,
    crash_scenario_table,
    default_crash_shock,
    payoff_vs_premium_multiple,
)
from deltadewa.analysis.crash_repricing import CrashShock, crash_skew_vol
from deltadewa.analysis.decision_matrix import (
    DecisionResult,
    DecisionVerdict,
    EntryTimingResult,
    EntryTimingStep,
    HedgeAdequacy,
    decision_matrix,
    entry_timing_tree,
)
from deltadewa.analysis.hedge_efficiency import (
    EfficiencyVerdict,
    HedgeEfficiency,
    hedge_efficiency,
)
from deltadewa.analysis.hedge_triggers import (
    HedgeTriggerReason,
    HedgeTriggerSet,
    HedgeTriggerThresholds,
    TriggerStatus,
    evaluate_hedge_trigger_set,
    evaluate_hedge_triggers,
)
from deltadewa.analysis.market_environment import (
    DataQuality,
    HedgeCostVerdict,
    MarketEnvironment,
    RegimeLabel,
    TermShape,
    assess_market_environment,
    classify_vix_regime,
    forward_vol,
    term_structure_shape,
)
from deltadewa.analysis.monetization import (
    MonetizationPlan,
    MonetizationStepStatus,
    build_monetization_plan,
    compute_hedge_gain_pct,
)
from deltadewa.analysis.portfolio_shape import (
    PortfolioShape,
    classify_portfolio_shape,
)
from deltadewa.analysis.position_aging import (
    AgedPosition,
    ExpiryBoundaries,
    ExpiryBucketLabel,
    ExpiryBucketTotal,
    ExpiryCalendarEntry,
    PositionAging,
    classify_expiry_bucket,
    evaluate_position_aging,
    expiry_boundaries,
)
from deltadewa.analysis.provenance import (
    Freshness,
    InputKind,
    InputProvenance,
    ProvenanceLedger,
    build_provenance_ledger,
)
from deltadewa.analysis.repricing import (
    MarketShock,
    MarketState,
    VolMapping,
    flat_bump_vol,
    proportional_vol,
    reprice_leg,
    reprice_legs_at,
    reprice_portfolio,
    shocked_leg_option,
)
from deltadewa.analysis.roll_planner import (
    RollAction,
    RollPlanRecord,
    build_roll_plan,
    gamma_theta_delay,
)
from deltadewa.analysis.roll_status import (
    GRADABLE_VERDICTS,
    RollVerdict,
    evaluate_roll_status,
    leg_convexity_contribution_pct,
    new_strike_for_entry_otm,
    verdict_reason,
)
from deltadewa.analysis.sizing import (
    HedgeSizingResult,
    beta_adjusted_notional,
    required_crash_offset,
    size_from_unit,
    size_hedge,
)
from deltadewa.analysis.spot_reading import SpotReading, observe_spot
from deltadewa.analysis.stress import (
    EmpiricalCdf,
    PnlHistogram,
    SpotVolGridSpec,
    TimePriceGridSpec,
    build_spot_vol_grid_spec,
    build_time_price_grid_spec,
    compute_empirical_cdf,
    compute_pnl_histogram,
    days_to_max_maturity,
    percentile_of_value,
    recompute_concentration,
)
from deltadewa.analysis.strike_ladder import (
    LadderRung,
    StrikeLadder,
    StrikeLadderResult,
    UnsolvableRung,
    build_strike_ladder,
    strike_for_delta,
)
from deltadewa.analysis.volatility import get_volatility_stats

__all__ = [
    "GRADABLE_VERDICTS",
    "AgedPosition",
    "CandidateMetrics",
    "CrashConvexityResult",
    "CrashScenarioRow",
    "CrashShock",
    "DataQuality",
    "DecisionResult",
    "DecisionVerdict",
    "EfficiencyVerdict",
    "EmpiricalCdf",
    "EntryTimingResult",
    "EntryTimingStep",
    "ExpiryBoundaries",
    "ExpiryBucketLabel",
    "ExpiryBucketTotal",
    "ExpiryCalendarEntry",
    "Freshness",
    "HedgeAdequacy",
    "HedgeCostVerdict",
    "HedgeEfficiency",
    "HedgeSizingResult",
    "HedgeTriggerReason",
    "HedgeTriggerSet",
    "HedgeTriggerThresholds",
    "InputKind",
    "InputProvenance",
    "LadderRung",
    "MarketEnvironment",
    "MarketShock",
    "MarketState",
    "MonetizationPlan",
    "MonetizationStepStatus",
    "PnlHistogram",
    "PortfolioAnalyzer",
    "PortfolioShape",
    "PositionAging",
    "PremiumBasis",
    "ProvenanceLedger",
    "RegimeLabel",
    "RollAction",
    "RollPlanRecord",
    "RollVerdict",
    "ScenarioGridCache",
    "SpotReading",
    "SpotVolGridSpec",
    "StrikeLadder",
    "StrikeLadderResult",
    "TermShape",
    "TimePriceGridSpec",
    "TriggerStatus",
    "UnsolvableRung",
    "VolMapping",
    "assess_market_environment",
    "beta_adjusted_notional",
    "build_monetization_plan",
    "build_provenance_ledger",
    "build_roll_plan",
    "build_spot_vol_grid_spec",
    "build_strike_ladder",
    "build_time_price_grid_spec",
    "classify_expiry_bucket",
    "classify_portfolio_shape",
    "classify_vix_regime",
    "compute_crash_convexity",
    "compute_empirical_cdf",
    "compute_hedge_gain_pct",
    "compute_pnl_histogram",
    "crash_scenario_table",
    "crash_skew_vol",
    "days_to_max_maturity",
    "decision_matrix",
    "default_crash_shock",
    "entry_timing_tree",
    "evaluate_candidate",
    "evaluate_hedge_trigger_set",
    "evaluate_hedge_triggers",
    "evaluate_position_aging",
    "evaluate_roll_status",
    "expiry_boundaries",
    "flat_bump_vol",
    "forward_vol",
    "gamma_theta_delay",
    "get_volatility_stats",
    "hedge_efficiency",
    "leg_convexity_contribution_pct",
    "new_strike_for_entry_otm",
    "observe_spot",
    "payoff_vs_premium_multiple",
    "percentile_of_value",
    "proportional_vol",
    "recompute_concentration",
    "reprice_leg",
    "reprice_legs_at",
    "reprice_portfolio",
    "required_crash_offset",
    "shocked_leg_option",
    "size_from_unit",
    "size_hedge",
    "strike_for_delta",
    "term_structure_shape",
    "verdict_reason",
]
