"""Module-level convenience functions for portfolio analysis."""

from typing import Dict, List


def classify_maturity_bucket(days_to_expiry: int) -> str:
    """
    Convenience function for maturity classification.

    Args:
        days_to_expiry: Days until expiration

    Returns:
        Bucket label string
    """
    # Lazy import to prevent circular dependency:
    # analysis.functions -> analysis.base -> analysis.risk_reward -> analysis.functions
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
    # Lazy import to prevent circular dependency:
    # analysis.functions -> analysis.base -> analysis.risk_reward -> analysis.functions
    # pylint: disable=import-outside-toplevel
    from deltadewa.analysis.base import PortfolioAnalyzer

    analyzer = PortfolioAnalyzer(portfolio)
    return analyzer.calculate_carry_metrics()


def quick_risk_concentration(
    portfolio, metrics: list[str] | None = None
) -> Dict:
    """
    Quick risk concentration analysis.

    Args:
        portfolio: OptionPortfolio instance
        metrics: Greeks to analyze (default: ['delta', 'gamma', 'vega'])

    Returns:
        Dictionary with concentration analysis
    """
    # Lazy import to prevent circular dependency:
    # analysis.functions -> analysis.base -> analysis.risk_reward -> analysis.functions
    # pylint: disable=import-outside-toplevel
    from deltadewa.analysis.base import PortfolioAnalyzer

    analyzer = PortfolioAnalyzer(portfolio)
    return analyzer.analyze_risk_concentration(metrics=metrics)
