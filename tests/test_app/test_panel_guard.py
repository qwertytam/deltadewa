"""Tests for deltadewa.app.panel_guard — the panel-level error boundary.

Pure unit tests, no Dash app needed. #326: a panel's dead end has four
distinct shapes (input / blocked / empty / error), and every one of them
must be visually distinct from the panels' own ``.plain-language`` prose.
"""

from __future__ import annotations

from dash import html

from deltadewa.app.panel_guard import (
    NoticeKind,
    incomplete_notice,
    panel_notice,
    safe_render,
    status_message,
)


def _class_names(node: object) -> set[str]:
    """Collect every className found anywhere under *node*."""
    found: set[str] = set()
    if isinstance(node, html.Div | html.P):
        class_name = getattr(node, "className", None)
        if class_name:
            found.add(class_name)
        children = getattr(node, "children", None)
        if isinstance(children, list):
            for child in children:
                found |= _class_names(child)
        elif children is not None:
            found |= _class_names(children)
    return found


class TestNoticeKind:
    """The four dead-end shapes #326 names."""

    def test_four_kinds_exist(self) -> None:
        assert {kind.value for kind in NoticeKind} == {
            "input",
            "blocked",
            "empty",
            "error",
        }


class TestPanelNotice:
    """One idiom, never the panels' own explanatory-prose class."""

    def test_headline_and_detail_both_render(self) -> None:
        notice = panel_notice(
            "Nothing solves here.",
            kind=NoticeKind.EMPTY,
            detail="Try wider deltas.",
        )

        text = str(notice)
        assert "Nothing solves here." in text
        assert "Try wider deltas." in text

    def test_no_detail_renders_headline_only(self) -> None:
        notice = panel_notice("Blocked.", kind=NoticeKind.BLOCKED)

        assert "Blocked." in str(notice)

    def test_class_name_carries_the_kind(self) -> None:
        notice = panel_notice("x", kind=NoticeKind.INPUT)

        assert notice.className == "panel-notice panel-notice--input"

    def test_four_kinds_produce_four_distinct_class_names(self) -> None:
        class_names = {
            panel_notice("x", kind=kind).className for kind in NoticeKind
        }

        assert len(class_names) == 4

    def test_never_uses_the_plain_language_class(self) -> None:
        """The #326 root cause: a dead end must not look like body prose."""
        for kind in NoticeKind:
            notice = panel_notice("x", kind=kind)
            assert "plain-language" not in _class_names(notice)

    def test_body_content_is_appended(self) -> None:
        notice = panel_notice(
            "Unsolvable.",
            kind=NoticeKind.EMPTY,
            body=[html.P("0.60Δ @ 0.50y — outside the solvable range")],
        )

        assert "outside the solvable range" in str(notice)


class TestIncompleteNoticeBackwardCompatible:
    """Every existing _incomplete(...) caller keeps working unchanged."""

    def test_still_takes_one_message_argument(self) -> None:
        notice = incomplete_notice("Enter comma-separated values.")

        assert "Enter comma-separated values." in str(notice)

    def test_renders_as_the_input_kind(self) -> None:
        notice = incomplete_notice("x")

        assert notice.className == "panel-notice panel-notice--input"


class TestStatusMessageUnchanged:
    """status_message is for mutation toasts, not panel dead ends (#326)."""

    def test_error_variant(self) -> None:
        notice = status_message("Removed.", error=True)

        assert notice.className == "status-message status-message--error"

    def test_success_variant(self) -> None:
        notice = status_message("Removed.", error=False)

        assert notice.className == "status-message status-message--success"


class TestSafeRender:
    """The raise-handling half of the boundary."""

    def test_returns_build_result_when_nothing_raises(self) -> None:
        result = safe_render(lambda: html.Div("ok"))

        assert "ok" in str(result)

    def test_value_error_renders_as_blocked(self) -> None:
        def _build() -> html.Div:
            msg = "no underlying position"
            raise ValueError(msg)

        result = safe_render(_build)

        assert result.className == "panel-notice panel-notice--blocked"
        assert "no underlying position" in str(result)

    def test_blocked_hint_appears_as_the_detail_line(self) -> None:
        def _build() -> html.Div:
            msg = "book notional is 0"
            raise ValueError(msg)

        result = safe_render(
            _build,
            blocked_hint="Set the spot and quantity in the BOOK zone.",
        )

        text = str(result)
        assert "book notional is 0" in text
        assert "Set the spot and quantity in the BOOK zone." in text

    def test_no_blocked_hint_omits_the_detail_line(self) -> None:
        def _build() -> html.Div:
            msg = "book notional is 0"
            raise ValueError(msg)

        result = safe_render(_build)

        assert "panel-notice__detail" not in str(result)

    def test_unexpected_exception_renders_as_error(self) -> None:
        def _build() -> html.Div:
            msg = "boom"
            raise RuntimeError(msg)

        result = safe_render(_build)

        assert result.className == "panel-notice panel-notice--error"
        assert "Something went wrong" in str(result)
