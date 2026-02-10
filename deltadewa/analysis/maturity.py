"""Maturity classification mixin for portfolio analysis."""

from typing import TYPE_CHECKING
import pandas as pd

if TYPE_CHECKING:
    from deltadewa.analysis.base import PortfolioAnalyzerBase


class MaturityMixin:
    """
    Mixin for maturity bucket classification.
    
    Provides methods for classifying options by time to expiration
    and adding maturity bucket columns to DataFrames.
    """

    @staticmethod
    def classify_maturity_bucket(days_to_expiry: int) -> str:
        """
        Classify option by time to expiration bucket.

        Buckets:
        - 0-7 days: Weekly options (high theta, significant gamma)
        - 8-30 days: Monthly options (moderate theta)
        - 31-60 days: 2-month options (lower theta)
        - 61-90 days: 3-month options (very low theta)
        - 90+ days: Long-term options (minimal theta)

        Args:
            days_to_expiry: Days until option expiration

        Returns:
            Bucket label string
        """
        if days_to_expiry <= 7:
            return "0-7 days (Weekly)"
        elif days_to_expiry <= 30:
            return "8-30 days (Monthly)"
        elif days_to_expiry <= 60:
            return "31-60 days (2M)"
        elif days_to_expiry <= 90:
            return "61-90 days (3M)"
        else:
            return "90+ days (Long-term)"

    def add_maturity_buckets(
        self: "PortfolioAnalyzerBase", df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Add maturity bucket column to positions DataFrame.

        Args:
            df: DataFrame with 'maturity' column

        Returns:
            DataFrame with added 'maturity_bucket' and 'days_to_expiry' columns
        """
        df = df.copy()

        # Calculate days to expiry
        df["days_to_expiry"] = df["maturity"].apply(
            lambda x: (pd.to_datetime(x) - pd.Timestamp.now()).days
        )

        # Classify into buckets
        df["maturity_bucket"] = df["days_to_expiry"].apply(
            self.classify_maturity_bucket
        )

        return df
