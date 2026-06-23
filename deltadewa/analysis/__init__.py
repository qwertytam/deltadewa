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
from deltadewa.analysis.volatility import get_volatility_stats

__all__ = [
    "CrashScenarioRow",
    "HedgeTriggerThresholds",
    "PortfolioAnalyzer",
    "ScenarioGridCache",
    "crash_payoff_ratio",
    "crash_scenario_table",
    "evaluate_hedge_triggers",
    "get_volatility_stats",
]
