"""Tests for deltadewa.app.format — pure formatting helpers."""

from deltadewa.analysis.roll_status import (
    MoneynessDrift,
    RollStatusRecord,
    RollVerdict,
    TriggerReason,
)
from deltadewa.app.format import (
    compact_currency,
    currency,
    percent,
    roll_verdict_reason,
    signed_compact_currency,
    signed_currency,
    signed_percent,
)


class TestCurrency:
    """Tests for currency."""

    def test_positive(self) -> None:
        assert currency(1_234_567.0) == "$1,234,567"

    def test_negative(self) -> None:
        assert currency(-1_234.0) == "$-1,234"

    def test_zero(self) -> None:
        assert currency(0.0) == "$0"

    def test_custom_decimals(self) -> None:
        assert currency(1_234.5, decimals=2) == "$1,234.50"


class TestSignedCurrency:
    """Tests for signed_currency."""

    def test_positive(self) -> None:
        assert signed_currency(45_000.0) == "+$45,000"

    def test_negative(self) -> None:
        assert signed_currency(-12_300.0) == "-$12,300"

    def test_zero(self) -> None:
        assert signed_currency(0.0) == "+$0"


class TestPercent:
    """Tests for percent."""

    def test_positive(self) -> None:
        assert percent(12.3) == "12.3%"

    def test_negative(self) -> None:
        assert percent(-4.5) == "-4.5%"

    def test_zero(self) -> None:
        assert percent(0.0) == "0.0%"

    def test_custom_decimals(self) -> None:
        assert percent(12.345, decimals=2) == "12.35%"


class TestSignedPercent:
    """Tests for signed_percent."""

    def test_positive(self) -> None:
        assert signed_percent(12.3) == "+12.3%"

    def test_negative(self) -> None:
        assert signed_percent(-4.5) == "-4.5%"

    def test_zero(self) -> None:
        assert signed_percent(0.0) == "+0.0%"


class TestCompactCurrency:
    """Tests for compact_currency."""

    def test_hundreds_tier(self) -> None:
        assert compact_currency(942.0) == "$942"

    def test_thousands_tier(self) -> None:
        assert compact_currency(45_231.0) == "$45.2K"

    def test_thousands_tier_no_decimal_needed(self) -> None:
        assert compact_currency(823_000.0) == "$823K"

    def test_millions_tier(self) -> None:
        assert compact_currency(5_226_004.0) == "$5.23M"

    def test_billions_tier(self) -> None:
        assert compact_currency(2_360_000_000.0) == "$2.36B"

    def test_rollover_boundary_does_not_use_scientific_notation(self) -> None:
        assert compact_currency(999_500.0) == "$1.00M"

    def test_zero(self) -> None:
        assert compact_currency(0.0) == "$0.00"


class TestSignedCompactCurrency:
    """Tests for signed_compact_currency."""

    def test_positive(self) -> None:
        assert signed_compact_currency(5_226_004.0) == "+$5.23M"

    def test_negative(self) -> None:
        assert signed_compact_currency(-823_000.0) == "-$823K"

    def test_zero(self) -> None:
        assert signed_compact_currency(0.0) == "+$0.00"

    def test_rollover_boundary(self) -> None:
        assert signed_compact_currency(-999_500.0) == "-$1.00M"


def _make_record(
    *,
    verdict: RollVerdict,
    suppressed: bool,
    time_verdict: RollVerdict,
    convexity_verdict: RollVerdict,
    drift_verdict: RollVerdict,
) -> RollStatusRecord:
    return RollStatusRecord(
        position=None,  # type: ignore[arg-type]
        moneyness=MoneynessDrift(
            entry_otm_pct=10.0,
            current_otm_pct=8.0,
            drift_pct=-2.0,
        ),
        days_to_maturity=200,
        roll_window_days=30,
        crash_convexity_pct=20.0,
        convexity_target_min_pct=15.0,
        convexity_target_max_pct=25.0,
        verdict=verdict,
        suppressed=suppressed,
        estimated_roll_up_cost=None,
        time_trigger=TriggerReason(time_verdict, reason="time reason"),
        convexity_trigger=TriggerReason(
            convexity_verdict,
            reason="convexity reason",
        ),
        drift_trigger=TriggerReason(drift_verdict, reason="drift reason"),
    )


class TestRollVerdictReason:
    """Tests for roll_verdict_reason."""

    def test_matches_time_trigger(self) -> None:
        record = _make_record(
            verdict=RollVerdict.ROLL,
            suppressed=False,
            time_verdict=RollVerdict.ROLL,
            convexity_verdict=RollVerdict.HOLD,
            drift_verdict=RollVerdict.HOLD,
        )

        assert roll_verdict_reason(record) == "time reason"

    def test_matches_convexity_trigger(self) -> None:
        record = _make_record(
            verdict=RollVerdict.MONITOR,
            suppressed=False,
            time_verdict=RollVerdict.HOLD,
            convexity_verdict=RollVerdict.MONITOR,
            drift_verdict=RollVerdict.HOLD,
        )

        assert roll_verdict_reason(record) == "convexity reason"

    def test_matches_drift_trigger(self) -> None:
        record = _make_record(
            verdict=RollVerdict.ROLL,
            suppressed=False,
            time_verdict=RollVerdict.HOLD,
            convexity_verdict=RollVerdict.HOLD,
            drift_verdict=RollVerdict.ROLL,
        )

        assert roll_verdict_reason(record) == "drift reason"

    def test_suppressed_case_names_suppression(self) -> None:
        record = _make_record(
            verdict=RollVerdict.MONITOR,
            suppressed=True,
            time_verdict=RollVerdict.HOLD,
            convexity_verdict=RollVerdict.HOLD,
            drift_verdict=RollVerdict.ROLL,
        )

        reason = roll_verdict_reason(record)

        assert "held at MONITOR" in reason
