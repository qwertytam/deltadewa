"""Structural protocols for mixin composition.

These are never instantiated at runtime. They exist solely to give static
analysers (mypy, pyright, pylint) an accurate picture of what self looks
like inside each mixin at runtime — i.e., the full composed PortfolioAnalyzer.
"""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class _AnalyzerProtocol(Protocol):
    """Structural type of self inside all PortfolioAnalyzer mixins."""

    portfolio: "OptionPortfolio"

    # Mixin methods (defined in their respective mixin classes, but declared
    # here for static type checking)

    # CarryMixin
    def calculate_carry_metrics(self) -> dict: ...
    def _empty_carry_metrics(self) -> dict: ...
    def create_theta_summary_table(self) -> pd.DataFrame: ...

    # MaturityMixin
    def add_maturity_buckets(self, df: pd.DataFrame) -> pd.DataFrame: ...

    # RecommendationsMixin
    def _calculate_option_alternatives(
        self,
        delta_change_needed: float,
        max_alternatives: int,
    ) -> list: ...
    def _empty_concentration(self) -> dict: ...
    def analyze_risk_concentration(
        self,
        metrics: list[str] | None = None,
        top_n: int = 3,
    ) -> dict: ...

    # RiskRewardMixin
    def risk_reward_analysis(
        self, spot_range: np.ndarray | None = None, num_simulations: int = 10**4
    ) -> dict: ...

    # SummaryMixin
    def format_risk_summary(
        self,
        stats: dict | None = None,
    ) -> str: ...
    def format_risk_reward_summary(
        self,
        spot_range: np.ndarray | None = None,
    ) -> str: ...
