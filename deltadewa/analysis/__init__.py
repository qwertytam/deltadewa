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
    crash_payoff_ratio,
    crash_scenario_table,
)
from deltadewa.analysis.decision_matrix import (
    DecisionResult,
    DecisionVerdict,
    EntryTimingResult,
    EntryTimingStep,
    HedgeAdequacy,
    decision_matrix,
    entry_timing_tree,
)
from deltadewa.analysis.hedge_triggers import (
    HedgeTriggerThresholds,
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
from deltadewa.analysis.roll_planner import (
    RollAction,
    RollPlanRecord,
    build_roll_plan,
    gamma_theta_delay,
)
from deltadewa.analysis.roll_status import (
    RollVerdict,
    evaluate_roll_status,
    new_strike_for_entry_otm,
)
from deltadewa.analysis.sizing import (
    HedgeSizingResult,
    beta_adjusted_notional,
    required_crash_offset,
    size_from_unit,
    size_hedge,
)
from deltadewa.analysis.strike_ladder import (
    LadderRung,
    StrikeLadder,
    build_strike_ladder,
    strike_for_delta,
)
from deltadewa.analysis.volatility import get_volatility_stats

__all__ = [
    "CandidateMetrics",
    "CrashConvexityResult",
    "CrashScenarioRow",
    "DataQuality",
    "DecisionResult",
    "DecisionVerdict",
    "EntryTimingResult",
    "EntryTimingStep",
    "HedgeAdequacy",
    "HedgeCostVerdict",
    "HedgeSizingResult",
    "HedgeTriggerThresholds",
    "LadderRung",
    "MarketEnvironment",
    "MonetizationPlan",
    "MonetizationStepStatus",
    "PortfolioAnalyzer",
    "PortfolioShape",
    "PremiumBasis",
    "RegimeLabel",
    "RollAction",
    "RollPlanRecord",
    "RollVerdict",
    "ScenarioGridCache",
    "StrikeLadder",
    "TermShape",
    "assess_market_environment",
    "beta_adjusted_notional",
    "build_monetization_plan",
    "build_roll_plan",
    "build_strike_ladder",
    "classify_portfolio_shape",
    "classify_vix_regime",
    "compute_crash_convexity",
    "compute_hedge_gain_pct",
    "crash_payoff_ratio",
    "crash_scenario_table",
    "decision_matrix",
    "entry_timing_tree",
    "evaluate_candidate",
    "evaluate_hedge_triggers",
    "evaluate_roll_status",
    "forward_vol",
    "gamma_theta_delay",
    "get_volatility_stats",
    "new_strike_for_entry_otm",
    "required_crash_offset",
    "size_from_unit",
    "size_hedge",
    "strike_for_delta",
    "term_structure_shape",
]
