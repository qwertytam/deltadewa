"""The planning panels say what their candidates were priced on (9b, D3).

With a fetched smile each candidate has its own IV, so a panel that showed
them as if priced at the book's one volatility would be telling the reader
something false. Without one (no feed, or the feed does not price volatility)
the panels say nothing new, as before.
"""

from __future__ import annotations

from datetime import date, timedelta

from deltadewa.analysis.ladder import (
    LadderSource,
    ProposedLadder,
    RungSpec,
    size_ladder,
)
from deltadewa.analysis.sizing import size_hedge
from deltadewa.analysis.strike_ladder import build_candidate_grid
from deltadewa.app.pages.design.planning import (
    ladder,
    ladder_composer,
    sizing,
)
from deltadewa.constants import OptionType
from deltadewa.portfolio.vol_quote import VolOrigin, VolQuote
from tests.test_analysis.test_convexity_agreement import _SPOT, _ips, _portfolio
from tests.test_app.test_design import _collect_text


class _Smile:
    def vol_for(
        self,
        *,
        strike: float,
        maturity: date,
        option_type: OptionType,
    ) -> VolQuote:
        del maturity, option_type
        downside = max((_SPOT - strike) / _SPOT, 0.0)
        return VolQuote(0.18 + 0.4 * downside, VolOrigin.BETWEEN_STRIKES)


def _ladder() -> ProposedLadder:
    return ProposedLadder(
        rungs=(RungSpec(20.0, 1.5, 60.0), RungSpec(30.0, 1.5, 40.0)),
        source=LadderSource.OPERATOR,
    )


class TestSizing:
    def test_a_priced_candidate_names_its_iv_and_basis(self) -> None:
        book = _portfolio(10_000.0)
        book.vol_source = _Smile()
        result = size_hedge(
            book,
            _ips(),
            candidate_pct_otm=20.0,
            candidate_maturity_years=1.0,
        )

        text = _collect_text(sizing._vol_basis_children(result))

        assert "Priced at an IV of" in text
        assert "between strikes" in text
        assert "between listed strikes" in text

    def test_a_flat_candidate_says_nothing_new(self) -> None:
        result = size_hedge(
            _portfolio(10_000.0),
            _ips(),
            candidate_pct_otm=20.0,
            candidate_maturity_years=1.0,
        )

        assert sizing._vol_basis_children(result) == []

    def test_an_override_says_nothing_about_the_chain(self) -> None:
        book = _portfolio(10_000.0)
        book.vol_source = _Smile()
        result = size_hedge(
            book,
            _ips(),
            candidate_pct_otm=20.0,
            candidate_maturity_years=1.0,
            vol=0.30,
        )

        text = _collect_text(sizing._vol_basis_children(result))

        assert "30.0%" in text
        assert "override" in text
        assert "fetched chain" not in text


class TestStrikeGrid:
    def test_the_grid_counts_its_candidates_by_basis(self) -> None:
        book = _portfolio(10_000.0)
        book.vol_source = _Smile()
        result = build_candidate_grid(
            book,
            _ips(),
            target_deltas=[0.05, 0.10],
            maturities_years=[0.5, 1.0],
        )

        text = _collect_text(ladder._vol_basis_children(result))

        assert "Candidates are priced from the fetched chain" in text
        assert "between listed strikes" in text

    def test_a_flat_grid_says_nothing_new(self) -> None:
        result = build_candidate_grid(
            _portfolio(10_000.0),
            _ips(),
            target_deltas=[0.05, 0.10],
            maturities_years=[0.5, 1.0],
        )

        assert ladder._vol_basis_children(result) == []


class TestComposer:
    def test_the_paragraph_reports_the_rungs_origins(self) -> None:
        book = _portfolio(10_000.0)
        book.vol_source = _Smile()
        sized = size_ladder(book, _ips(), _ladder())

        text = ladder_composer._rung_vol_text(book, sized)

        assert "priced from the fetched chain" in text
        assert "2 between listed strikes" in text

    def test_a_flat_book_keeps_the_old_sentence(self) -> None:
        book = _portfolio(10_000.0)
        sized = size_ladder(book, _ips(), _ladder())

        text = ladder_composer._rung_vol_text(book, sized)

        assert "Rungs are priced at the book's volatility" in text

    def test_the_rung_table_shows_each_rungs_iv_and_basis(self) -> None:
        book = _portfolio(10_000.0)
        book.vol_source = _Smile()
        sized = size_ladder(book, _ips(), _ladder())

        text = _collect_text(ladder_composer._rung_table(sized))

        assert "IV (basis)" in text
        assert "between_strikes" in text

    def test_the_comparability_note_is_about_the_surface_not_a_flat_vol(
        self,
    ) -> None:
        book = _portfolio(10_000.0)
        book.vol_source = _Smile()
        book.add_position(
            strike_price=_SPOT * 0.8,
            maturity_date=book.valuation_date + timedelta(days=400),
            quantity=3,
            option_type=OptionType.PUT,
            volatility=0.30,
        )

        notes = ladder_composer._comparability_notes(book, _ladder())

        assert any(
            "rungs are priced from the fetched chain" in n for n in notes
        )
        assert not any(
            "book's" in n and "entered volatility" in n for n in notes
        )
