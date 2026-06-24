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
    CrashScenarioRow,
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
from deltadewa.analysis.volatility import get_volatility_stats

__all__ = [
    "CrashScenarioRow",
    "DataQuality",
    "HedgeCostVerdict",
    "HedgeTriggerThresholds",
    "MarketEnvironment",
    "PortfolioAnalyzer",
    "RegimeLabel",
    "ScenarioGridCache",
    "TermShape",
    "assess_market_environment",
    "classify_vix_regime",
    "crash_payoff_ratio",
    "crash_scenario_table",
    "evaluate_hedge_triggers",
    "forward_vol",
    "get_volatility_stats",
    "term_structure_shape",
]
