"""Module-level convenience functions for portfolio analysis."""

from typing import Dict, List, Optional

# Re-export generate_spot_range for backward compatibility
# The function has been moved to deltadewa.spot_utils to avoid circular dependencies
from deltadewa.spot_utils import generate_spot_range  # noqa: F401


def classify_maturity_bucket(days_to_expiry: int) -> str:
    """
    Convenience function for maturity classification.

    Args:
        days_to_expiry: Days until expiration

    Returns:
        Bucket label string
    """
    # pylint: disable=import-outside-toplevel
    from deltadewa.analysis.base import PortfolioAnalyzer

    return PortfolioAnalyzer.classify_maturity_bucket(days_to_expiry)


def quick_carry_analysis(portfolio) -> Dict:
    """
    Quick carry analysis for a portfolio.

    Args:
        portfolio: OptionPortfolio instance

    Returns:
        Dictionary with carry metrics
    """
    # pylint: disable=import-outside-toplevel
    from deltadewa.analysis.base import PortfolioAnalyzer

    analyzer = PortfolioAnalyzer(portfolio)
    return analyzer.calculate_carry_metrics()


def quick_risk_concentration(
    portfolio, metrics: Optional[List[str]] = None
) -> Dict:
    """
    Quick risk concentration analysis.

    Args:
        portfolio: OptionPortfolio instance
        metrics: Greeks to analyze (default: ['delta', 'gamma', 'vega'])

    Returns:
        Dictionary with concentration analysis
    """
    # pylint: disable=import-outside-toplevel
    from deltadewa.analysis.base import PortfolioAnalyzer

    analyzer = PortfolioAnalyzer(portfolio)
    return analyzer.analyze_risk_concentration(metrics=metrics)
