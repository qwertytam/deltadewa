"""Tests for the /design Ladder composer's logic and rendering (#410, 8d)."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
from dash.development.base_component import Component

from deltadewa.analysis.convexity_band import ConvexityGrade, grade_convexity
from deltadewa.analysis.ladder import (
    LadderSource,
    ProposedLadder,
    RungSpec,
    materialize_ladder,
    size_ladder,
)
from deltadewa.analysis.sizing import GROSS_SIZING_NOTE
from deltadewa.app.compliance import scorecard
from deltadewa.app.pages.design.planning import ladder_composer as composer
from deltadewa.constants import OptionType
from deltadewa.ips_config import IpsConfig, IpsLadderRung, IpsStrikeLadder

from ..test_analysis.test_convexity_agreement import _SPOT, _ips, _portfolio
from ..test_analysis.test_ladder import _BIG_QTY, _held_book

_TENOR = 1.5


def _with_ips_ladder(ips: IpsConfig) -> IpsConfig:
    return dataclasses.replace(
        ips,
        strike_ladder=IpsStrikeLadder(
            rungs=(
                IpsLadderRung(pct_otm=20.0, weight_pct=35.0),
                IpsLadderRung(pct_otm=30.0, weight_pct=40.0),
                IpsLadderRung(pct_otm=40.0, weight_pct=25.0),
            ),
        ),
    )


def _walk(node: object) -> list[Component]:
    """Every Dash component under *node*, depth first."""
    found: list[Component] = []
    if isinstance(node, Component):
        found.append(node)
        found.extend(_walk(getattr(node, "children", None)))
    elif isinstance(node, (list, tuple)):
        for child in node:
            found.extend(_walk(child))
    return found


def _text(node: object) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, Component):
        return _text(getattr(node, "children", None))
    if isinstance(node, (list, tuple)):
        return " ".join(_text(c) for c in node)
    return ""


def _tables(node: object) -> list[Component]:
    return [c for c in _walk(node) if type(c).__name__ == "Table"]


def _parse(raw: str | None) -> tuple[ProposedLadder | None, str | None]:
    return composer._parse_rungs(raw, default_tenor=_TENOR)


class TestParse:
    def test_full_rungs(self) -> None:
        ladder, error = _parse("20@1.5:35, 30@1.5:40, 40@2:25")

        assert error is None
        assert ladder is not None
        assert ladder.source is LadderSource.OPERATOR
        assert [
            (r.pct_otm, r.maturity_years, r.weight) for r in ladder.rungs
        ] == [
            (20.0, 1.5, 35.0),
            (30.0, 1.5, 40.0),
            (40.0, 2.0, 25.0),
        ]

    def test_omitted_years_and_weight_take_defaults(self) -> None:
        ladder, error = _parse("20, 30")

        assert error is None
        assert ladder is not None
        assert [(r.maturity_years, r.weight) for r in ladder.rungs] == [
            (_TENOR, 1.0),
            (_TENOR, 1.0),
        ]

    @pytest.mark.parametrize("raw", [None, "", "   ", " , "])
    def test_blank_is_not_an_error(self, raw: str | None) -> None:
        assert _parse(raw) == (None, None)

    @pytest.mark.parametrize(
        ("raw", "needle"),
        [
            ("twenty@1.5:35", "Could not read"),
            ("20@1.5:abc", "Could not read"),
            ("20@1.5:0", "weight must be > 0"),
            ("20@0:5", "maturity_years must be > 0"),
            ("100:5", "pct_otm must be"),
            ("20@1.5:5, 20@1.5:7", "repeat"),
        ],
    )
    def test_bad_text_names_the_problem(self, raw: str, needle: str) -> None:
        ladder, error = _parse(raw)

        assert ladder is None
        assert error is not None
        assert needle in error

    def test_format_then_parse_is_a_round_trip(self) -> None:
        rungs = (
            RungSpec(20.0, 1.5, 35.0),
            RungSpec(21.37, 1.499, 12.5),
        )

        ladder, error = _parse(composer._format_rungs(rungs))

        assert error is None
        assert ladder is not None
        assert ladder.rungs == rungs


class TestAppendRung:
    def test_first_rung_takes_weight_one(self) -> None:
        text = composer._append_rung(
            "",
            pct_otm=21.37,
            maturity_years=1.5,
            default_tenor=_TENOR,
        )

        assert text == composer._Update("21.37@1.5:1")

    def test_new_rung_takes_the_average_existing_weight(self) -> None:
        """A bare 1 beside 35/40/25 would be a rounding error."""
        text = composer._append_rung(
            "20@1.5:30, 30@1.5:50",
            pct_otm=40.0,
            maturity_years=1.5,
            default_tenor=_TENOR,
        )

        assert text == composer._Update("20@1.5:30, 30@1.5:50, 40@1.5:40")

    def test_a_strike_already_in_the_ladder_changes_nothing_and_says_so(
        self,
    ) -> None:
        update = composer._append_rung(
            "20@1.5:30",
            pct_otm=20.001,
            maturity_years=1.5,
            default_tenor=_TENOR,
        )

        assert update.text is None
        assert update.note is not None
        assert "already in the ladder" in update.note

    def test_unparseable_text_is_left_alone_and_says_so(self) -> None:
        update = composer._append_rung(
            "garbage",
            pct_otm=20.0,
            maturity_years=1.5,
            default_tenor=_TENOR,
        )

        assert update.text is None
        assert update.note is not None
        assert "Fix the rungs text" in update.note

    def test_a_strike_the_ladder_cannot_hold_says_why(self) -> None:
        """A zero-maturity row would raise inside RungSpec; it must not."""
        update = composer._append_rung(
            "20@1.5:30",
            pct_otm=25.0,
            maturity_years=0.0,
            default_tenor=_TENOR,
        )

        assert update.text is None
        assert update.note is not None
        assert "Could not add" in update.note


class TestNextText:
    def test_load_ips_uses_the_ips_ladder(self) -> None:
        ips = _with_ips_ladder(_ips())

        text = composer._next_rungs_text(
            composer._LOAD_IPS_ID,
            current="",
            portfolio=_portfolio(_BIG_QTY),
            ips_config=ips,
        )

        assert text.text == "20@1.5:35, 30@1.5:40, 40@1.5:25"
        assert text.note is None

    def test_load_ips_without_a_section_changes_nothing_and_says_so(
        self,
    ) -> None:
        update = composer._next_rungs_text(
            composer._LOAD_IPS_ID,
            current="x",
            portfolio=_portfolio(_BIG_QTY),
            ips_config=_ips(),
        )

        assert update.text is None
        assert update.note is not None
        assert "strike_ladder" in update.note

    def test_load_book_uses_the_held_shape(self) -> None:
        text = composer._next_rungs_text(
            composer._LOAD_BOOK_ID,
            current="",
            portfolio=_held_book(),
            ips_config=_ips(),
        )

        assert text.text is not None
        ladder, error = _parse(text.text)
        assert error is None
        assert ladder is not None
        assert sorted(r.weight for r in ladder.rungs) == [16.0, 23.0, 26.0]

    def test_load_book_with_no_puts_changes_nothing_and_says_so(self) -> None:
        update = composer._next_rungs_text(
            composer._LOAD_BOOK_ID,
            current="x",
            portfolio=_portfolio(_BIG_QTY),
            ips_config=_ips(),
        )

        assert update.text is None
        assert update.note is not None
        assert "no live long puts" in update.note

    def test_add_button_trigger_appends(self) -> None:
        text = composer._next_rungs_text(
            {"type": "ladder-add-rung", "pct_otm": 25.0, "maturity": 1.5},
            current="20@1.5:10",
            portfolio=_portfolio(_BIG_QTY),
            ips_config=_ips(),
        )

        assert text == composer._Update("20@1.5:10, 25@1.5:10")

    def test_unknown_trigger_changes_nothing(self) -> None:
        assert composer._next_rungs_text(
            None,
            current="x",
            portfolio=_portfolio(_BIG_QTY),
            ips_config=_ips(),
        ) == composer._Update(None)


class TestSeed:
    def test_ips_ladder_wins_over_the_book(self) -> None:
        seed = composer._seed_text(_held_book(), _with_ips_ladder(_ips()))

        assert seed == "20@1.5:35, 30@1.5:40, 40@1.5:25"

    def test_book_is_the_fallback(self) -> None:
        seed = composer._seed_text(_held_book(), _ips())

        assert seed.count(",") == 2

    def test_nothing_to_seed_from_is_empty_text(self) -> None:
        assert composer._seed_text(_portfolio(_BIG_QTY), _ips()) == ""


class TestRender:
    def _render(self, raw: str | None, *, qty: float = _BIG_QTY) -> Component:
        return composer._render_composer_logic(
            portfolio=_portfolio(qty),
            ips_config=_ips(),
            rungs_raw=raw,
        )

    def test_blank_input_is_an_empty_notice_that_says_how_to_start(
        self,
    ) -> None:
        text = _text(self._render(""))

        assert "No rungs yet" in text
        assert "pct@years:weight" in text

    def test_unreadable_input_is_an_input_notice(self) -> None:
        panel = self._render("nonsense")

        assert "panel-notice--input" in str(panel.className)  # type: ignore[attr-defined]
        assert "Could not read" in _text(panel)

    def test_no_underlying_is_blocked_with_a_pointer(self) -> None:
        panel = self._render("20@1.5:35, 30@1.5:40", qty=0.0)

        assert "panel-notice--blocked" in str(panel.className)  # type: ignore[attr-defined]
        assert "BOOK zone" in _text(panel)

    def test_valid_ladder_shows_rungs_scorecard_and_depths(self) -> None:
        panel = self._render("20@1.5:35, 30@1.5:40, 40@1.5:25")

        text = _text(panel)
        for expected in (
            "Rungs",
            "Scorecard",
            "Crash gain by depth",
            "Current book",
            "This ladder",
            "Annual carry cost",
            "Vega sufficiency",
            "Hedge efficiency",
            "20.0% OTM",
        ):
            assert expected in text, expected
        # The two things a reader must not misread.
        assert composer._CONVEXITY_CAVEAT in text
        assert composer._DEPTH_FOOTNOTE in text

    def test_only_the_ips_depth_is_graded(self) -> None:
        """Four depths are shown ungraded; the IPS depth carries one badge."""
        panel = self._render("20@1.5:35, 30@1.5:40, 40@1.5:25")
        depth_table = _tables(panel)[-1]

        badges = [
            c
            for c in _walk(depth_table)
            if "verdict-badge" in str(getattr(c, "className", ""))
        ]
        rows = [c for c in _walk(depth_table) if type(c).__name__ == "Tr"][1:]
        assert len(rows) == 5
        assert len(badges) == 1

    def test_printed_figures_are_the_analysis_layers_own(self) -> None:
        """Agreement: the panel prints what scorecard() computes."""
        raw = "20@1.5:35, 30@1.5:40, 40@1.5:25"
        ips = _ips()
        portfolio = _portfolio(_BIG_QTY)
        ladder, _ = _parse(raw)
        assert ladder is not None
        sized = size_ladder(portfolio, ips, ladder)
        expected = scorecard(materialize_ladder(portfolio, sized), ips)

        text = _text(self._render(raw))

        for row in expected.compliance.rows:
            assert row.actual in text
        assert f"{sized.total_contracts:,}" in text

    def test_notes_say_what_the_ladder_cannot_represent(self) -> None:
        book = _held_book()
        maturity = book.valuation_date + timedelta(days=400)
        book.add_position(
            strike_price=_SPOT * 0.9,
            maturity_date=maturity,
            quantity=-5,
            option_type=OptionType.PUT,
        )
        book.add_position(
            strike_price=_SPOT * 0.7,
            maturity_date=book.valuation_date - timedelta(days=10),
            quantity=9,
            option_type=OptionType.PUT,
            reject_expired=False,
        )
        ladder, _ = _parse("20@1.5:35, 30@1.5:40")
        assert ladder is not None

        notes = composer._comparability_notes(book, ladder)

        assert len(notes) == 1
        assert "2 leg(s)" in notes[0]
        assert "short, call or expired" in notes[0]

    def test_a_book_of_only_long_puts_has_nothing_to_flag(self) -> None:
        ladder, _ = _parse("20@1.5:35, 30@1.5:40")
        assert ladder is not None

        assert composer._comparability_notes(_held_book(), ladder) == []

    def test_a_leg_at_a_different_volatility_is_flagged_not_hidden(
        self,
    ) -> None:
        book = _held_book()
        book.positions[0].option.volatility = book.volatility + 0.05
        ladder, _ = _parse("20@1.5:35, 30@1.5:40")
        assert ladder is not None

        notes = composer._comparability_notes(book, ladder)

        assert len(notes) == 1
        assert "own entered volatility" in notes[0]
        assert "not on one volatility basis" in notes[0]

    def test_a_leg_entered_at_the_book_volatility_is_not_a_warning(
        self,
    ) -> None:
        """The §4 golden book states vol on every leg, equal to the book's.

        That is an explicit entry, not a different basis; flagging it would
        be a false alarm on the program's own reference book.
        """
        book = _held_book()
        for position in book.positions:
            position.custom_volatility = True
            position.option.volatility = book.volatility
        ladder, _ = _parse("20@1.5:35, 30@1.5:40")
        assert ladder is not None

        assert composer._comparability_notes(book, ladder) == []

    def test_the_panel_shows_the_notes_for_a_book_with_shorts(self) -> None:
        book = _held_book()
        book.add_position(
            strike_price=_SPOT * 0.9,
            maturity_date=book.valuation_date + timedelta(days=400),
            quantity=-5,
            option_type=OptionType.PUT,
        )

        panel = composer._render_composer_logic(
            portfolio=book,
            ips_config=_ips(),
            rungs_raw="20@1.5:35, 30@1.5:40, 40@1.5:25",
        )

        assert "1 leg(s) of the current book" in _text(panel)

    def test_share_held_is_shown_beside_the_weight_asked(self) -> None:
        """Rounding up moves a rung off its weight; the table says so."""
        panel = self._render("20@1.5:5, 30@1.5:45, 40@1.5:50")

        text = _text(panel)
        assert "Weight asked" in text
        assert "Share held" in text

    def test_same_strike_different_tenor_rungs_get_distinct_headers(
        self,
    ) -> None:
        ladder, _ = _parse("20@1:50, 20@2:50")
        assert ladder is not None
        sized = size_ladder(_portfolio(_BIG_QTY), _ips(), ladder)

        labels = composer._rung_labels(sized)

        assert len(set(labels)) == 2
        assert "1.00y" in labels[0]
        assert "2.00y" in labels[1]

    def test_a_zero_offset_says_no_contracts_are_needed(self) -> None:
        """Tolerance at or past the crash depth: an empty ladder is correct."""
        ips = _ips(max_tolerance_pct=30.0)

        panel = composer._render_composer_logic(
            portfolio=_portfolio(_BIG_QTY),
            ips_config=ips,
            rungs_raw="20@1.5:35, 30@1.5:40",
        )

        assert "No contracts are needed" in _text(panel)

    def test_the_overall_verdict_is_rendered(self) -> None:
        text = _text(self._render("20@1.5:35, 30@1.5:40, 40@1.5:25"))

        assert "All IPS checks above" in text


class TestLayout:
    def test_load_ips_is_disabled_without_an_ips_ladder(self) -> None:
        layout = composer.layout(
            portfolio=_portfolio(_BIG_QTY),
            ips_config=_ips(),
            basis_crash_skew="basis: test",
        )

        button = next(
            c
            for c in _walk(layout)
            if getattr(c, "id", None) == composer._LOAD_IPS_ID
        )
        assert button.disabled is True  # type: ignore[attr-defined]

    def test_load_ips_is_enabled_with_one(self) -> None:
        layout = composer.layout(
            portfolio=_portfolio(_BIG_QTY),
            ips_config=_with_ips_ladder(_ips()),
            basis_crash_skew="basis: test",
        )

        button = next(
            c
            for c in _walk(layout)
            if getattr(c, "id", None) == composer._LOAD_IPS_ID
        )
        assert button.disabled is False  # type: ignore[attr-defined]


class TestSeedNeverBreaksThePage:
    """layout() runs outside safe_render: a bad book must not escape it."""

    def test_a_zero_spot_book_seeds_blank_instead_of_raising(self) -> None:
        book = _held_book()
        book.spot_price = 0.0

        assert composer._safe_seed_text(book, _ips()) == ""

        layout = composer.layout(
            portfolio=book,
            ips_config=_ips(),
            basis_crash_skew="basis: test",
        )
        assert layout is not None


class TestDepthTableAgreesWithTheScorecard:
    """The IPS-depth cell and the convexity row are one number."""

    def test_rendered_ips_depth_cell_equals_the_scorecard_actual(self) -> None:
        from deltadewa.analysis.ladder import (
            ladder_depth_profile,
            profile_depths,
        )

        ips = _ips()
        portfolio = _portfolio(_BIG_QTY)
        ladder, _ = _parse("20@1.5:35, 30@1.5:40, 40@1.5:25")
        assert ladder is not None
        sized = size_ladder(portfolio, ips, ladder)
        shadow = materialize_ladder(portfolio, sized)
        shock = sized.basis.shock
        ips_row = next(
            r
            for r in ladder_depth_profile(
                shadow,
                sized,
                shock=shock,
                depths=profile_depths(shock),
            )
            if r.is_ips_depth
        )
        convexity_row = composer._convexity_row(
            scorecard(shadow, ips).compliance,
        )
        assert convexity_row is not None

        panel = composer._render_composer_logic(
            portfolio=portfolio,
            ips_config=ips,
            rungs_raw="20@1.5:35, 30@1.5:40, 40@1.5:25",
        )

        # The same figure, printed by the referee's rule (#434): a reading
        # just under the floor reads "4.99%" beside its FAIL, where
        # ``fmt.percent`` said "5.0%" next to a badge that said below.
        rendered = grade_convexity(
            ips_row.combined_pct_of_book,
            ips.convexity,
            at_shock_pct=ips_row.shock_pct,
        ).display()
        assert convexity_row.actual == rendered
        assert rendered in _text(panel)


class TestGrossSizingNote:
    """#436: the composer says sizing is gross and convexity is net."""

    def test_the_shared_note_sits_beside_covers_the_offset(self) -> None:
        panel = composer._render_composer_logic(
            portfolio=_portfolio(_BIG_QTY),
            ips_config=_ips(),
            rungs_raw="20@1.5:35, 30@1.5:40, 40@1.5:25",
        )

        text = _text(panel)
        assert "covers" in text
        assert GROSS_SIZING_NOTE in text


class TestIpsDepthRowIsTheRefereesDepth:
    """One depth rule: the composer's graded row is the referee's."""

    def test_a_depth_within_float_noise_is_the_ips_row_and_a_neighbour_is_not(
        self,
    ) -> None:
        from deltadewa.analysis.ladder import ladder_depth_profile

        ips = _ips()
        portfolio = _portfolio(_BIG_QTY)
        ladder, _ = _parse("20@1.5:35, 30@1.5:40, 40@1.5:25")
        assert ladder is not None
        sized = size_ladder(portfolio, ips, ladder)
        shadow = materialize_ladder(portfolio, sized)
        shock = sized.basis.shock
        ips_pct = shock.crash_scenario_pct

        rows = ladder_depth_profile(
            shadow,
            sized,
            shock=shock,
            depths=(ips_pct + 4e-5, ips_pct + 2e-4),
        )

        assert [row.is_ips_depth for row in rows] == [True, False]
        for row in rows:
            graded = grade_convexity(
                row.combined_pct_of_book,
                ips.convexity,
                at_shock_pct=row.shock_pct,
            )
            assert (graded.grade is not ConvexityGrade.UNMEASURED) is (
                row.is_ips_depth
            )


class TestComposerLabelsAndBaseline:
    def test_a_fractional_depth_is_not_rounded_in_its_label(self) -> None:
        assert composer._depth_label(-25.0) == "-25%"
        assert composer._depth_label(-22.5) == "-22.5%"
        assert composer._depth_label(10.0) == "+10%"

    def test_the_baseline_at_the_graded_depth_is_the_scorecards_text(
        self,
    ) -> None:
        ips = _ips()
        portfolio = _portfolio(_BIG_QTY)

        panel = composer._render_composer_logic(
            portfolio=portfolio,
            ips_config=ips,
            rungs_raw="20@1.5:35, 30@1.5:40, 40@1.5:25",
        )

        baseline_row = composer._convexity_row(
            scorecard(portfolio, ips).compliance,
        )
        assert baseline_row is not None
        assert baseline_row.actual in _text(panel)
