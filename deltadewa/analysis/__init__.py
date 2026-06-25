"""Portfolio Analysis Module for Options Portfolios.

This module provides advanced analytical utilities for options portfolio
management, including carry analysis, risk concentration, maturity
classification, scenario generation, and hedge recommendation logic.

Author: DeltaDewa Team
Date: 2026-01-12
"""

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.cache import ScenarioGridCache
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
from deltadewa.analysis.volatility import get_volatility_stats

__all__ = [
    "CrashConvexityResult",
    "CrashScenarioRow",
    "DataQuality",
    "HedgeCostVerdict",
    "HedgeSizingResult",
    "HedgeTriggerThresholds",
    "MarketEnvironment",
    "PortfolioAnalyzer",
    "PremiumBasis",
    "RegimeLabel",
    "ScenarioGridCache",
    "TermShape",
    "assess_market_environment",
    "classify_vix_regime",
    "compute_crash_convexity",
    "crash_payoff_ratio",
    "crash_scenario_table",
    "evaluate_hedge_triggers",
    "forward_vol",
    "get_volatility_stats",
    "required_crash_offset",
    "size_from_unit",
    "size_hedge",
    "term_structure_shape",
]
