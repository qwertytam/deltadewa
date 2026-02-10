"""Base class for portfolio analysis."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class PortfolioAnalyzerBase:
    """
    Base class for portfolio analysis with core initialization.
    
    This class provides the foundational structure for portfolio analysis,
    holding the reference to the portfolio being analyzed. All analysis
    mixins build upon this base class.
    """

    def __init__(self, portfolio):
        """
        Initialize analyzer with portfolio.

        Args:
            portfolio: OptionPortfolio instance to analyze
        """
        self.portfolio = portfolio


# Compose the full PortfolioAnalyzer with all mixins
from deltadewa.analysis.maturity import MaturityMixin
from deltadewa.analysis.carry import CarryMixin
from deltadewa.analysis.concentration import ConcentrationMixin
from deltadewa.analysis.hedge import HedgeMixin
from deltadewa.analysis.scenarios import ScenariosMixin
from deltadewa.analysis.insights import InsightsMixin


class PortfolioAnalyzer(
    MaturityMixin,
    CarryMixin,
    ConcentrationMixin,
    HedgeMixin,
    ScenariosMixin,
    InsightsMixin,
    PortfolioAnalyzerBase,
):
    """
    Advanced portfolio analysis utilities.

    Provides methods for:
    - Maturity bucket classification
    - Theta/carry analysis
    - Risk concentration identification
    - Hedge recommendations
    - Scenario grid generation
    - Risk summary formatting
    - Actionable insights generation
    """

    pass
