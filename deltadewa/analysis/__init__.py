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
from deltadewa.analysis.sizing import (
    HedgeSizingResult,
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
    "HedgeCostVerdict",
    "HedgeSizingResult",
    "HedgeTriggerThresholds",
    "LadderRung",
    "MarketEnvironment",
    "PortfolioAnalyzer",
    "PremiumBasis",
    "RegimeLabel",
    "ScenarioGridCache",
    "StrikeLadder",
    "TermShape",
    "assess_market_environment",
    "build_strike_ladder",
    "classify_vix_regime",
    "compute_crash_convexity",
    "crash_payoff_ratio",
    "crash_scenario_table",
    "evaluate_candidate",
    "evaluate_hedge_triggers",
    "forward_vol",
    "get_volatility_stats",
    "required_crash_offset",
    "size_from_unit",
    "size_hedge",
    "strike_for_delta",
    "term_structure_shape",
]
