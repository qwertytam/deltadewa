"""Maturity classification mixin for portfolio analysis."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Final

import pandas as pd

from deltadewa.clock import days_between

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsMaturityBuckets
    from deltadewa.portfolio.core import OptionPortfolio


@dataclass(frozen=True)
class MaturityBuckets:
    """The maturity term-structure bucketing, derived from its own edges.

    One source of truth (#305). The scheme used to be a pair of hand-kept
    literals — a five-entry label tuple and a five-branch ``if`` ladder — that
    had to agree with each other, and whose edges (0-7 / 8-30 / 31-60 / 61-90
    / 90+) were sized for weekly options. An 18-month tail ladder, which is
    the program this package exists for, put every dollar of vega and theta in
    the terminal bucket, so both panels reading it answered nothing: the live
    book's 310d and 493d tranches were indistinguishable.

    Edges are **policy**, not presentation — they decide what "long-dated"
    means for a given program — so they come from ``ips.yaml``'s
    ``maturity_buckets`` section. Labels are *derived* from the edges rather
    than stored beside them, which is what makes a label incapable of
    disagreeing with the boundary it names.

    Attributes:
        edges_days: Strictly increasing, positive upper bounds, each
            inclusive. A final open-ended bucket above the last edge is
            always present, so ``n`` edges yield ``n + 1`` buckets.

    """

    edges_days: tuple[int, ...]

    def __post_init__(self) -> None:
        """Reject an edge list that cannot describe a term structure."""
        if not self.edges_days:
            msg = "maturity_buckets.edges_days must not be empty"
            raise ValueError(msg)
        if self.edges_days[0] <= 0:
            msg = (
                "maturity_buckets.edges_days must be positive; got "
                f"{self.edges_days[0]}"
            )
            raise ValueError(msg)
        if any(lower >= upper for lower, upper in pairwise(self.edges_days)):
            msg = (
                "maturity_buckets.edges_days must be strictly increasing; "
                f"got {list(self.edges_days)}"
            )
            raise ValueError(msg)

    @classmethod
    def from_ips(cls, section: IpsMaturityBuckets) -> MaturityBuckets:
        """Build from the IPS ``maturity_buckets`` section."""
        return cls(edges_days=section.edges_days)

    @property
    def labels(self) -> tuple[str, ...]:
        """Bucket labels in chronological order, shortest runway first.

        The canonical order every consumer reads against. A plain pandas
        ``groupby`` sorts group keys as strings, which scrambles a maturity
        ordering ("0-30" < "181-365" < "31-90"), so no consumer may rely on
        the grouped result's own order.

        Purely numeric — the old labels carried names ("Weekly",
        "Monthly", "Long-term") that were the weekly-options assumption
        #305 is about, and that a configurable edge list cannot honestly
        generate.
        """
        out: list[str] = []
        lower = 0
        for edge in self.edges_days:
            out.append(f"{lower}-{edge} days")
            lower = edge + 1
        out.append(f"{self.edges_days[-1]}+ days")
        return tuple(out)

    def classify(self, days_to_expiry: int) -> str:
        """Return the bucket label *days_to_expiry* falls in.

        Args:
            days_to_expiry: Days until expiration. Values at or below zero
                fall in the first bucket; an expired leg's own grading is
                ``position_aging``'s job, not this scheme's.

        Returns:
            One of :attr:`labels`.

        """
        labels = self.labels
        for label, edge in zip(labels, self.edges_days, strict=False):
            if days_to_expiry <= edge:
                return label
        return labels[-1]


DEFAULT_MATURITY_BUCKETS: Final[MaturityBuckets] = MaturityBuckets(
    edges_days=(30, 90, 180, 365, 730),
)
"""Tail-hedge-shaped edges: 1M / 3M / 6M / 1Y / 2Y / 2Y+.

The fallback for call sites that do not render a term structure and so have
no opinion on the edges (``analysis/summary.py``'s carry roll-up, for
instance). Those pass this constant **explicitly** — the parameter is
required everywhere, with no default anywhere, so a rendering surface cannot
silently fall back to it while claiming to show the operator's policy. That
silent-fallback shape is #295, and it is what this constant is arranged to
avoid rather than reintroduce.
"""


@dataclass(frozen=True)
class MaturityVegaExposure:
    """Handbook Part X §14: vega aggregated by maturity bucket.

    Part X: `Institutional Hedge Dashboards
    <https://qwertytam.github.io/deltadewa-handbook/part-10/>`_.

    Attributes:
        vega_by_bucket: Vega total per maturity bucket, keyed by
            :attr:`MaturityBuckets.labels`
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
    def classify_maturity_bucket(
        days_to_expiry: int,
        buckets: MaturityBuckets,
    ) -> str:
        """Classify an option by time to expiration bucket.

        A thin delegate to :meth:`MaturityBuckets.classify`, kept so the
        analyzer's surface is unchanged for existing callers.

        Args:
            days_to_expiry: Days until option expiration.
            buckets: The bucketing scheme. **Required, with no default** —
                the edges are policy (#305), and a rendering surface that
                fell back to a built-in scheme would show a term structure
                the operator never configured while looking correct.

        Returns:
            Bucket label string.

        """
        return buckets.classify(days_to_expiry)

    def add_maturity_buckets(
        self,
        df: pd.DataFrame,
        buckets: MaturityBuckets,
    ) -> pd.DataFrame:
        """Add maturity bucket column to positions DataFrame.

        Args:
            df: DataFrame with 'maturity' column
            buckets: The bucketing scheme (see
                :meth:`classify_maturity_bucket`).

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
        df["maturity_bucket"] = df["days_to_expiry"].apply(buckets.classify)

        return df

    def calculate_vega_by_maturity(
        self,
        buckets: MaturityBuckets,
    ) -> MaturityVegaExposure:
        """Handbook Part X §14: vega aggregated by maturity bucket.

        Extends :meth:`add_maturity_buckets` -- the same bucketing
        :class:`~deltadewa.analysis.carry.CarryMixin` already applies to
        theta (``theta_by_bucket``) -- rather than a second bucketing
        scheme, so the two panels can never disagree on where a boundary
        falls.

        Args:
            buckets: The bucketing scheme (see
                :meth:`classify_maturity_bucket`).

        Returns:
            Vega totals per maturity bucket (every canonical bucket
            present, zero-filled) and the book's total vega. An empty book
            returns an all-zero, fully-populated
            :class:`MaturityVegaExposure` -- a real reading, not a missing
            one (matches
            :meth:`~deltadewa.analysis.carry.CarryMixin._empty_carry_metrics`'s
            convention).

        """
        labels = buckets.labels
        df = self.portfolio.to_dataframe()
        if df.empty:
            return MaturityVegaExposure(
                vega_by_bucket=dict.fromkeys(labels, 0.0),
                total_vega=0.0,
            )

        df = self.add_maturity_buckets(df, buckets)
        grouped = df.groupby("maturity_bucket")["position_vega"].sum()
        vega_by_bucket = {
            bucket: float(grouped.get(bucket, 0.0)) for bucket in labels
        }
        total_vega = float(df["position_vega"].sum())

        return MaturityVegaExposure(
            vega_by_bucket=vega_by_bucket,
            total_vega=total_vega,
        )
