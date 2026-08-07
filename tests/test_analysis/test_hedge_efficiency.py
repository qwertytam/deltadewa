"""Tests for the hedge efficiency ratio (Part X items #5 / #15).

The band values used throughout are the handbook's own (3 / 6, from
``docs/hedging handbook.md:4342-4348``), and the two worked examples are
lifted from the handbook rather than invented, so a failure here means the
implementation drifted from the cited definition — not that a fixture went
stale.
"""

from __future__ import annotations

import pytest

from deltadewa.analysis.hedge_efficiency import (
    EfficiencyVerdict,
    HedgeEfficiency,
    hedge_efficiency,
)

# The handbook's interpretation table: < 3 poor, 3 to 6 acceptable, > 6
# attractive (docs/hedging handbook.md:4342-4348).
_BAND_MIN = 3.0
_BAND_MAX = 6.0


def _efficiency(payoff: float, carry: float) -> HedgeEfficiency:
    """Build an efficiency reading against the handbook's own band."""
    return hedge_efficiency(
        crash_payoff=payoff,
        annual_carry=carry,
        band_min_ratio=_BAND_MIN,
        band_max_ratio=_BAND_MAX,
    )


class TestHandbookWorkedExamples:
    """Both examples the handbook computes by hand, reproduced exactly."""

    def test_dollar_form_example(self) -> None:
        """``1.5M / 300k = 5x`` (docs/hedging handbook.md:2044-2050)."""
        result = _efficiency(1_500_000.0, -300_000.0)

        assert result.ratio == pytest.approx(5.0)
        assert result.verdict is EfficiencyVerdict.ACCEPTABLE

    def test_percentage_form_example(self) -> None:
        """``22% / 3% = 7.3`` (docs/hedging handbook.md:4336-4340).

        The percentage form is the same division on a common normalizer, so
        the function takes the two percentages unchanged and must produce the
        handbook's figure.
        """
        result = _efficiency(22.0, 3.0)

        assert result.ratio == pytest.approx(7.3333, abs=1e-4)
        assert result.verdict is EfficiencyVerdict.ATTRACTIVE


class TestCarrySignHandling:
    """Carry is a magnitude in the denominator; payoff keeps its sign."""

    def test_carry_sign_does_not_change_the_ratio(self) -> None:
        """Theta arrives negative from the engine and positive from a %."""
        assert _efficiency(1_500_000.0, -300_000.0).ratio == pytest.approx(
            _efficiency(1_500_000.0, 300_000.0).ratio,
        )

    def test_annual_carry_is_echoed_back_signed(self) -> None:
        """The stored input keeps its sign even though the divisor doesn't."""
        result = _efficiency(1_500_000.0, -300_000.0)

        assert result.annual_carry == pytest.approx(-300_000.0)

    def test_negative_payoff_keeps_its_sign(self) -> None:
        """A hedge that loses value in the crash reads negative, not zero.

        Clamping would turn "this hedge costs you money in a crash" into
        "this hedge is merely poor", which is a different statement.
        """
        result = _efficiency(-50_000.0, -100_000.0)

        assert result.ratio == pytest.approx(-0.5)
        assert result.verdict is EfficiencyVerdict.POOR


class TestUndefinedRatio:
    """Zero carry is undefined, not zero — the distinction is the point."""

    def test_zero_carry_yields_none_not_zero(self) -> None:
        result = _efficiency(1_500_000.0, 0.0)

        assert result.ratio is None
        assert result.verdict is None

    def test_zero_carry_still_echoes_its_inputs_and_band(self) -> None:
        """A renderer can still say what it was given, and against what."""
        result = _efficiency(1_500_000.0, 0.0)

        assert result.crash_payoff == pytest.approx(1_500_000.0)
        assert result.annual_carry == pytest.approx(0.0)
        assert result.band_min_ratio == pytest.approx(_BAND_MIN)
        assert result.band_max_ratio == pytest.approx(_BAND_MAX)


class TestBandClassification:
    """Boundaries are inclusive at both ends, matching the convexity band."""

    @pytest.mark.parametrize(
        ("ratio", "expected"),
        [
            (0.5, EfficiencyVerdict.POOR),
            (2.999, EfficiencyVerdict.POOR),
            (3.0, EfficiencyVerdict.ACCEPTABLE),
            (4.5, EfficiencyVerdict.ACCEPTABLE),
            (6.0, EfficiencyVerdict.ACCEPTABLE),
            (6.001, EfficiencyVerdict.ATTRACTIVE),
            (20.0, EfficiencyVerdict.ATTRACTIVE),
        ],
    )
    def test_verdict_bands(
        self,
        ratio: float,
        expected: EfficiencyVerdict,
    ) -> None:
        """A unit carry makes the payoff argument the ratio directly."""
        assert _efficiency(ratio, 1.0).verdict is expected

    def test_band_is_echoed_back_for_rendering(self) -> None:
        result = _efficiency(15.0, 1.0)

        assert result.band_min_ratio == pytest.approx(_BAND_MIN)
        assert result.band_max_ratio == pytest.approx(_BAND_MAX)


class TestBandValidation:
    """An inverted band can never be satisfied, so it is rejected loudly."""

    def test_inverted_band_raises(self) -> None:
        with pytest.raises(ValueError, match="band_min_ratio"):
            hedge_efficiency(
                crash_payoff=1.0,
                annual_carry=1.0,
                band_min_ratio=6.0,
                band_max_ratio=3.0,
            )

    def test_degenerate_band_is_allowed(self) -> None:
        """``min == max`` is a single cut point, not an error."""
        result = hedge_efficiency(
            crash_payoff=5.0,
            annual_carry=1.0,
            band_min_ratio=5.0,
            band_max_ratio=5.0,
        )

        assert result.verdict is EfficiencyVerdict.ACCEPTABLE
