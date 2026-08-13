"""Maturity classification mixin for portfolio analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pandas as pd

from deltadewa.clock import days_between

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio

# classify_maturity_bucket's own chronological order. A plain `groupby`
# sorts group keys alphabetically, which scrambles a maturity ordering
# ("0-7" < "31-60" < "61-90" < "8-30" < "90+" as strings) -- this is the
# canonical order a term-structure display (M2.8's vega exposure panel)
# reads against.
_BUCKET_ORDER: Final[tuple[str, ...]] = (
    "0-7 days (Weekly)",
    "8-30 days (Monthly)",
    "31-60 days (2M)",
    "61-90 days (3M)",
    "90+ days (Long-term)",
)


@dataclass(frozen=True)
class MaturityVegaExposure:
    """Handbook Part X §14: vega aggregated by maturity bucket.

    Part X: `Institutional Hedge Dashboards
    <https://github.com/qwertytam/deltadewa-handbook/blob/main/HANDBOOK.md#part-x--institutional-hedge-dashboards>`_.

    Attributes:
        vega_by_bucket: Vega total per maturity bucket, keyed by the same
            labels :meth:`MaturityMixin.classify_maturity_bucket` assigns
            (and :meth:`~deltadewa.analysis.carry.CarryMixin
            .calculate_carry_metrics` groups theta by -- one bucketing
            scheme, reused by both). Every canonical bucket is present,
            zero-filled when empty -- a real absence of positions in that
            bucket, not missing data, so it is shown as ``0.0`` rather than
            omitted.
        total_vega: Sum of every leg's position vega. Reconciles exactly to
            ``sum(vega_by_bucket.values())``.

    """

    vega_by_bucket: dict[str, float]
    total_vega: float


class MaturityMixin:
    """Mixin for maturity bucket classification.

    Provides methods for classifying options by time to expiration
    and adding maturity bucket columns to DataFrames.
    """

    if TYPE_CHECKING:
        portfolio: OptionPortfolio

    @staticmethod
    def classify_maturity_bucket(days_to_expiry: int) -> str:
        """Classify option by time to expiration bucket.

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
        if days_to_expiry <= 30:
            return "8-30 days (Monthly)"
        if days_to_expiry <= 60:
            return "31-60 days (2M)"
        if days_to_expiry <= 90:
            return "61-90 days (3M)"
        return "90+ days (Long-term)"

    def add_maturity_buckets(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add maturity bucket column to positions DataFrame.

        Args:
            df: DataFrame with 'maturity' column

        Returns:
            DataFrame with added 'maturity_bucket' and 'days_to_expiry' columns

        """
        df = df.copy()

        # Days to expiry measured against the portfolio's (what-if) valuation
        # date, not the wall clock, and as a calendar-date difference so the
        # bucket boundaries land where the pricing engine puts them (#182).
        as_of = self.portfolio.valuation_date
        df["days_to_expiry"] = df["maturity"].apply(
            lambda x: days_between(as_of, pd.to_datetime(x)),
        )

        # Classify into buckets
        df["maturity_bucket"] = df["days_to_expiry"].apply(
            self.classify_maturity_bucket,
        )

        return df

    def calculate_vega_by_maturity(self) -> MaturityVegaExposure:
        """Handbook Part X §14: vega aggregated by maturity bucket.

        Extends :meth:`add_maturity_buckets` -- the same bucketing
        :class:`~deltadewa.analysis.carry.CarryMixin` already applies to
        theta (``theta_by_bucket``) -- rather than a second bucketing
        scheme, so the two panels can never disagree on where a boundary
        falls.

        Returns:
            Vega totals per maturity bucket (every canonical bucket
            present, zero-filled) and the book's total vega. An empty book
            returns an all-zero, fully-populated
            :class:`MaturityVegaExposure` -- a real reading, not a missing
            one (matches
            :meth:`~deltadewa.analysis.carry.CarryMixin._empty_carry_metrics`'s
            convention).

        """
        df = self.portfolio.to_dataframe()
        if df.empty:
            return MaturityVegaExposure(
                vega_by_bucket=dict.fromkeys(_BUCKET_ORDER, 0.0),
                total_vega=0.0,
            )

        df = self.add_maturity_buckets(df)
        grouped = df.groupby("maturity_bucket")["position_vega"].sum()
        vega_by_bucket = {
            bucket: float(grouped.get(bucket, 0.0)) for bucket in _BUCKET_ORDER
        }
        total_vega = float(df["position_vega"].sum())

        return MaturityVegaExposure(
            vega_by_bucket=vega_by_bucket,
            total_vega=total_vega,
        )
