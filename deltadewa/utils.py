"""Utility functions for the deltadewa package.

This module provides common utilities.

"""

import pandas as pd


def abs_sum(series: pd.Series) -> float:
    """Sum of absolute values, for use in DataFrame.agg()."""
    return float(series.abs().sum())
