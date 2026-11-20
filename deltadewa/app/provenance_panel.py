"""The provenance panel: every graded pricing input, not just the worst one.

Batch 3d / #367. ``chrome.py``'s banner deliberately shows only the single
worst channel — stacking one line per input is the alarm-fatigue failure
the batch's design explicitly rejected. #367's acceptance criterion is
still that every input's age/provenance is "reachable without leaving the
page it's rendered on" — this panel is that full breakdown, collapsed by
default (mirroring ``monitor.py``'s position-detail table) so a healthy
book stays quiet and an operator chasing the banner's one line can expand
straight to the rest.

Shared by ``/monitor`` and ``/design`` — both wrap it in their own
:func:`~deltadewa.app.panel_guard.safe_render` closure, per that module's
isolation rule, rather than this module reaching for one itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import html

from deltadewa.analysis.provenance import Freshness, InputKind

if TYPE_CHECKING:
    from deltadewa.analysis.provenance import (
        InputProvenance,
        OverrideNote,
        ProvenanceLedger,
    )

_KIND_LABEL = {
    InputKind.FETCHED: "Fetched",
    InputKind.HAND_ENTERED: "Hand-entered",
}


def _entry_row(entry: InputProvenance) -> html.Tr:
    as_of_text = (
        f"{entry.as_of:%Y-%m-%d %H:%M}" if entry.as_of is not None else "—"
    )
    age_text = f"{entry.age_days}d" if entry.age_days is not None else "—"
    max_age_text = (
        f"{entry.max_age_days}d" if entry.max_age_days is not None else "—"
    )
    return html.Tr(
        [
            html.Td(entry.label),
            html.Td(_KIND_LABEL[entry.kind]),
            html.Td(
                entry.freshness.value,
                className=(
                    f"provenance-freshness provenance-freshness--"
                    f"{entry.freshness.value.lower()}"
                ),
            ),
            html.Td(as_of_text),
            html.Td(age_text),
            html.Td(max_age_text),
            html.Td(entry.detail),
        ],
    )


def _override_row(note: OverrideNote) -> html.Tr:
    age = f"{note.age_days}d" if note.age_days is not None else "never"
    return html.Tr(
        [
            html.Td(note.label),
            html.Td(note.show(note.value)),
            html.Td(note.show(note.fetched)),
            html.Td(age),
        ],
    )


def overrides_block(ledger: ProvenanceLedger) -> list[html.Div]:
    """List every active override, with its age and the feed's figure.

    An override lasts until it is cleared (D7), so it is the one pricing
    input that can be forgotten and keep pricing the book on a stale number
    while the feed has moved on. Listing each with its age and what the feed
    says today, on every page that shows the provenance panel and in the
    digest, is what keeps it from being forgotten. Empty when there is none.
    """
    if not ledger.overrides:
        return []
    return [
        html.Div(
            [
                html.Div(
                    f"{len(ledger.overrides)} active override"
                    f"{'s' if len(ledger.overrides) != 1 else ''}: your "
                    "value prices the book until you clear it.",
                    className="provenance-overrides-title",
                ),
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th("Input"),
                                    html.Th("Your value"),
                                    html.Th("Feed today"),
                                    html.Th("Confirmed"),
                                ],
                            ),
                        ),
                        html.Tbody(
                            [_override_row(n) for n in ledger.overrides]
                        ),
                    ],
                    className="provenance-table",
                ),
            ],
            className="provenance-overrides",
        ),
    ]


def _notes_block(ledger: ProvenanceLedger) -> list[html.Div]:
    """List the inputs that fell back to your value, and why."""
    return [
        html.Div(note, className="provenance-input-note")
        for note in ledger.input_notes
    ]


def _summary_text(ledger: ProvenanceLedger) -> str:
    """One line naming the ledger's worst entry, however it's showing up.

    Distinct from ``chrome.py``'s banner text: this always renders
    (there is no alarm-fatigue concern inside an already-collapsed
    ``Details`` element), and it names the worst entry even when it's
    FRESH, so a fully healthy book still gets an explicit "all clear"
    rather than a suspicious absence of a summary line.
    """
    worst = ledger.worst
    if worst is None:
        return "No pricing inputs to grade."
    if worst.freshness is Freshness.FRESH:
        if ledger.input_notes:
            # Every graded input is within its review age, but something the
            # grades do not cover needs saying (an input on a fallback).
            return (
                "Graded inputs are within their review ages, but the notes "
                "below need attention."
            )
        return f"All inputs current. Worst: {worst.label} ({worst.detail})."
    return f"Worst: {worst.label} — {worst.freshness.value}. {worst.detail}"


def build_provenance_panel(ledger: ProvenanceLedger) -> html.Div:
    """Build the full provenance breakdown, one row per graded input.

    Covers fetched market data and every hand-entered input.

    Args:
        ledger: The provenance ledger for this request — see
            ``analysis.provenance.build_provenance_ledger``.

    Returns:
        A ``Div`` containing a summary line, the flat-IV nudge when one
        applies, and a collapsed detail table.

    """
    header = html.Tr(
        [
            html.Th("Input"),
            html.Th("Kind"),
            html.Th("Freshness"),
            html.Th("As of"),
            html.Th("Age"),
            html.Th("Max age"),
            html.Th("Detail"),
        ],
    )
    rows = [_entry_row(entry) for entry in ledger.entries]
    nudge = (
        [html.Div(ledger.flat_iv_note, className="provenance-nudge")]
        if ledger.flat_iv_note is not None
        else []
    )
    return html.Div(
        [
            html.Div(_summary_text(ledger), className="provenance-summary"),
            *_notes_block(ledger),
            *overrides_block(ledger),
            *nudge,
            html.Details(
                [
                    # Not the section title: the page owns the heading
                    # (and its anchor), so repeating it here rendered a
                    # duplicated heading pair (N8a).
                    html.Summary(f"Show all {len(ledger.entries)} inputs"),
                    html.Table(
                        [html.Thead(header), html.Tbody(rows)],
                        className="provenance-table",
                    ),
                ],
                className="provenance-detail",
            ),
        ],
        id="provenance-panel",
        className="provenance-panel",
    )
