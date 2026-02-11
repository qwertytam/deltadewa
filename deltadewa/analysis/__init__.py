"""
Portfolio Analysis Module for Options Portfolios

This module provides advanced analytical utilities for options portfolio management,
including carry analysis, risk concentration, maturity classification, scenario
generation, and hedge recommendation logic.

Usage:
    from deltadewa.analysis import PortfolioAnalyzer

    analyzer = PortfolioAnalyzer(portfolio)
    carry_metrics = analyzer.calculate_carry_metrics()
    concentration = analyzer.analyze_risk_concentration()

Author: DeltaDewa Team
Date: 2026-01-12
"""

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.functions import (
    classify_maturity_bucket,
    quick_carry_analysis,
    quick_risk_concentration,
    ScenarioGridCache,
)
from deltadewa.analysis.volatility import (
    calculate_portfolio_avg_volatility,
    apply_proportional_volatility_shift,
    restore_volatilities,
    get_volatility_stats,
)

__all__ = [
    "PortfolioAnalyzer",
    "classify_maturity_bucket",
    "quick_carry_analysis",
    "quick_risk_concentration",
    "ScenarioGridCache",
    "calculate_portfolio_avg_volatility",
    "apply_proportional_volatility_shift",
    "restore_volatilities",
    "get_volatility_stats",
]
