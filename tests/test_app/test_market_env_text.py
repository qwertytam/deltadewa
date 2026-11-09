"""N5: the market-environment panel renders words, never internals.

Review finding N5 caught ``/design``'s entry-timing step 2 rendering
``skew_percentile: 0.876984126984127`` — a Python identifier and a
15-decimal float on a page the partner reads. These tests drive the
entry-timing tree down every branch and check what reaches the page.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest

from deltadewa.analysis.decision_matrix import entry_timing_tree
from deltadewa.analysis.market_environment import (
    DataQuality,
    HedgeCostVerdict,
    MarketEnvironment,
    RegimeLabel,
    TermShape,
)
from deltadewa.app.pages.design.planning.market_env import (
    TIMING_STEP_FORMATS,
    format_timing_step,
)

_VIX_THRESHOLDS = {"vix_very_high": 40.0, "vix_caution": 25.0, "vix_low": 15.0}

# A lower_snake identifier, or a dotted Class.attribute — what N5 found.
_IDENTIFIER = re.compile(r"\b[a-z]+_[a-z_]+\b|\b[A-Z][A-Za-z]+\.[a-z_]+\b")


def _env(**overrides: Any) -> MarketEnvironment:
    defaults: dict[str, Any] = {
        "vix": 18.0,
        "regime_percentile": 15.0,
        "regime_label": RegimeLabel.NORMAL,
        "skew_index": 140.0,
        "skew_percentile": 0.5,
        "term_structure": {"VIX": 18.0, "VIX3M": 20.0, "VIX6M": 21.0},
        "term_shape": TermShape.CONTANGO,
        "forward_vol_front_3m": 21.0,
        "hedge_cost_verdict": HedgeCostVerdict.FAIR,
        "data_quality": DataQuality.LIVE,
        "as_of": datetime(2026, 11, 6, tzinfo=UTC),
        "skew_lookback_days": 1260,
    }
    return MarketEnvironment(**{**defaults, **overrides})


# One environment per branch of entry_timing_tree, so every step label the
# tree can emit (with and without a value) is exercised.
_BRANCHES: dict[str, MarketEnvironment] = {
    "vix missing": _env(vix=None),
    "vix very high": _env(vix=45.0),
    "vix caution": _env(vix=30.0),
    "skew missing": _env(skew_percentile=None),
    "skew expensive": _env(skew_percentile=0.876984126984127),
    "skew cheap": _env(skew_percentile=0.10, vix=14.0),
    "term missing": _env(term_shape=None),
    "term backwardation": _env(term_shape=TermShape.BACKWARDATION),
    "term flat": _env(term_shape=TermShape.FLAT),
    "term contango": _env(term_shape=TermShape.CONTANGO),
}


@pytest.mark.parametrize("branch", list(_BRANCHES))
def test_every_emitted_step_label_has_a_display_format(branch: str) -> None:
    """A new step label cannot fall through to a raw identifier."""
    timing = entry_timing_tree(_BRANCHES[branch], **_VIX_THRESHOLDS)

    for step in timing.steps:
        assert step.label in TIMING_STEP_FORMATS, step.label


@pytest.mark.parametrize("branch", list(_BRANCHES))
def test_rendered_steps_and_notes_carry_no_identifiers(branch: str) -> None:
    """No snake_case name or Class.attribute reaches the page."""
    env = _BRANCHES[branch]
    timing = entry_timing_tree(env, **_VIX_THRESHOLDS)
    rendered = [format_timing_step(step, env) for step in timing.steps]
    if timing.data_quality_note is not None:
        rendered.append(timing.data_quality_note)

    for text in rendered:
        assert not _IDENTIFIER.search(text), text
        assert "MarketEnvironment" not in text


def test_skew_step_reads_as_a_stated_percentile() -> None:
    """The exact N5 reading: 0.876984126984127 on a five-year window."""
    env = _BRANCHES["skew expensive"]
    timing = entry_timing_tree(env, **_VIX_THRESHOLDS)

    skew_step = next(s for s in timing.steps if s.label == "skew_percentile")

    text = format_timing_step(skew_step, env)
    assert text.startswith("2. Skew: 88th percentile (trailing 5y) — ")
    assert "0.87" not in text


def test_term_step_reads_as_a_word() -> None:
    env = _BRANCHES["term contango"]
    timing = entry_timing_tree(env, **_VIX_THRESHOLDS)

    term_step = next(s for s in timing.steps if s.label == "term_shape")

    assert format_timing_step(term_step, env).startswith(
        "3. Term structure: contango — ",
    )


def test_missing_reading_reads_as_unavailable() -> None:
    env = _BRANCHES["vix missing"]
    timing = entry_timing_tree(env, **_VIX_THRESHOLDS)

    assert format_timing_step(timing.steps[0], env).startswith(
        "1. VIX: unavailable — ",
    )
