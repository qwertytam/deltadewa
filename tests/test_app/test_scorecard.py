"""A ladder proposal is graded exactly as the book is (#410)."""

from __future__ import annotations

import pytest

from deltadewa.analysis.ladder import (
    LadderSource,
    ProposedLadder,
    RungSpec,
    ladder_from_book,
    materialize_ladder,
    size_ladder,
)
from deltadewa.app.compliance import (
    compliance_sections_at_ips_anchor,
    scorecard,
)
from deltadewa.reporting.program_report import build_ips_compliance

from ..test_analysis.test_convexity_agreement import _ips, _portfolio
from ..test_analysis.test_ladder import _BIG_QTY, _held_book


class TestScorecardIsTheStripPlusEfficiency:
    """No second grader: the rows are the compliance strip's own."""

    def test_compliance_is_exactly_the_strips_for_the_same_book(self) -> None:
        ips = _ips()
        book = _held_book()

        card = scorecard(book, ips)

        assert card.compliance == build_ips_compliance(
            *compliance_sections_at_ips_anchor(book, ips),
        )

    def test_a_held_ladder_materialised_scores_like_the_book(self) -> None:
        """Round trip through ladder_from_book/materialize_ladder.

        The shadow of what the book already holds must read exactly as the
        book does -- every compliance row (carry, convexity, vega) and the
        efficiency ratio -- or a baseline-vs-proposal comparison would be
        comparing two different measuring sticks.
        """
        ips = _ips()
        book = _held_book()
        held = ladder_from_book(book)
        assert held is not None
        shadow = materialize_ladder(book, size_ladder(book, ips, held))

        baseline = scorecard(book, ips)
        proposal = scorecard(shadow, ips)

        assert [r.actual for r in proposal.compliance.rows] == [
            r.actual for r in baseline.compliance.rows
        ]
        assert [r.passes for r in proposal.compliance.rows] == [
            r.passes for r in baseline.compliance.rows
        ]
        assert baseline.efficiency.ratio is not None
        assert proposal.efficiency.ratio == pytest.approx(
            baseline.efficiency.ratio,
            rel=1e-9,
        )
        assert proposal.efficiency.verdict == baseline.efficiency.verdict

    def test_a_ladder_with_nothing_sized_does_not_crash_the_scorecard(
        self,
    ) -> None:
        """An empty shadow (no legs) is graded, not raised on."""
        ips = _ips()
        portfolio = _portfolio(_BIG_QTY)
        ladder = ProposedLadder(
            rungs=(RungSpec(20.0, 1.5, 1.0, contracts=0),),
            source=LadderSource.OPERATOR,
        )
        shadow = materialize_ladder(
            portfolio,
            size_ladder(portfolio, ips, ladder),
        )

        card = scorecard(shadow, ips)

        assert len(card.compliance.rows) == 3
        assert card.efficiency.ratio is None
