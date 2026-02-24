"""Base class for portfolio analysis."""

from typing import TYPE_CHECKING

from deltadewa.analysis.carry import CarryMixin
from deltadewa.analysis.health import HealthMixin
# Import mixins after base class definition to avoid circular imports
from deltadewa.analysis.maturity import MaturityMixin
from deltadewa.analysis.recommendations import RecommendationsMixin
from deltadewa.analysis.risk_reward import RiskRewardMixin
from deltadewa.analysis.scenarios import ScenariosMixin
from deltadewa.analysis.summary import SummaryMixin

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


class PortfolioAnalyzer(
    MaturityMixin,
    CarryMixin,
    RecommendationsMixin,
    ScenariosMixin,
    RiskRewardMixin,
    SummaryMixin,
    HealthMixin,
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
    - Risk/reward analysis
    - Portfolio health metrics
    """

    pass  # pylint: disable=unnecessary-pass
