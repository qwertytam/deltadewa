"""Tests for deltadewa.reporting.program_report."""

import datetime

import pytest

from deltadewa.analysis.crash_payoff import (
    CrashConvexityResult,
    CrashScenarioRow,
    PremiumBasis,
)
from deltadewa.analysis.market_environment import (
    DataQuality,
    HedgeCostVerdict,
    MarketEnvironment,
    RegimeLabel,
    TermShape,
)
from deltadewa.analysis.monetization import (
    MonetizationPlan,
    MonetizationStepStatus,
)
from deltadewa.constants import ExerciseStyle
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsMonetizationStep,
    IpsPricing,
    IpsProgram,
    IpsTriggers,
)
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.reporting.program_report import (
    ProgramReport,
    build_program_report,
    render_html,
    render_markdown,
)

# ── Fixtures / helpers ────────────────────────────────────────────────────

_AS_OF = datetime.date(2026, 6, 24)
_IPS_CONVEXITY = IpsConvexity(
    crash_scenario_pct=-25.0,
    target_min_pct=10.0,
    target_max_pct=30.0,
)


def _make_ips_config(
    annual_carry_pct: float = 2.0,
    schedule_steps: int = 2,
) -> IpsConfig:
    steps = tuple(
        IpsMonetizationStep(gain_pct=float(i + 1) * 100, sell_pct=50.0)
        for i in range(schedule_steps)
    )
    return IpsConfig(
        program=IpsProgram(name="SPX Tail Hedge", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=annual_carry_pct),
        convexity=_IPS_CONVEXITY,
        drawdown=IpsDrawdown(max_tolerance_pct=5.0),
        triggers=IpsTriggers(
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_time_months=2.0,
            rally_rebalance_pct=5.0,
            strike_drift_max_otm_pct=10.0,
        ),
        monetization=IpsMonetization(schedule=steps),
    )


def _make_crash_result(
    *,
    ips_convexity: IpsConvexity | None = _IPS_CONVEXITY,
    payoff_ratio: float | None = 8.5,
    convexity_pct: float = 15.0,
    meets_target: bool = True,
    premium_paid: float = 10_000.0,
) -> CrashConvexityResult:
    rows = []
    if ips_convexity is not None:
        rows.append(
            CrashScenarioRow(
                shock_pct=ips_convexity.crash_scenario_pct,
                hedge_pnl=premium_paid * (payoff_ratio or 0),
                payoff_ratio=payoff_ratio or 0.0,
                convexity_pct=convexity_pct,
                meets_target=meets_target,
            ),
        )
    return CrashConvexityResult(
        curve=[],
        scenario_rows=rows,
        payoff_ratio=payoff_ratio,
        premium_paid=premium_paid,
        premium_basis=PremiumBasis.PAID,
        ips_convexity=ips_convexity,
    )


def _make_market_env(
    data_quality: DataQuality = DataQuality.LIVE,
) -> MarketEnvironment:
    if data_quality is DataQuality.UNAVAILABLE:
        return MarketEnvironment(
            vix=None,
            regime_percentile=None,
            regime_label=None,
            skew_index=None,
            skew_percentile=None,
            term_structure=None,
            term_shape=None,
            forward_vol_front_3m=None,
            hedge_cost_verdict=None,
            data_quality=DataQuality.UNAVAILABLE,
        )
    return MarketEnvironment(
        vix=18.0,
        regime_percentile=30.0,
        regime_label=RegimeLabel.NORMAL,
        skew_index=130.0,
        skew_percentile=0.45,
        term_structure={
            "VIX": 18.0,
            "VIX3M": 19.0,
            "VIX6M": 20.0,
            "VIX1Y": 21.0,
        },
        term_shape=TermShape.CONTANGO,
        forward_vol_front_3m=20.0,
        hedge_cost_verdict=HedgeCostVerdict.FAIR,
        data_quality=data_quality,
    )


def _make_carry_metrics(theta_annual: float = -8_000.0) -> dict:
    return {"total_theta_annual": theta_annual}


def _make_portfolio(
    underlying_quantity: float = 100.0,
    spot_price: float = 5_000.0,
) -> OptionPortfolio:
    return OptionPortfolio(
        underlying_quantity=underlying_quantity,
        spot_price=spot_price,
    )


def _make_plan(
    *,
    current_gain_pct: float | None = 75.0,
    recommended_cumulative_sell_pct: float = 25.0,
    value_to_harvest: float = 2_500.0,
) -> MonetizationPlan:
    """Minimal MonetizationPlan for use in report tests."""
    return MonetizationPlan(
        current_gain_pct=current_gain_pct,
        steps=[
            MonetizationStepStatus(
                gain_pct=50.0,
                sell_pct=25.0,
                triggered=True,
            ),
            MonetizationStepStatus(
                gain_pct=100.0,
                sell_pct=25.0,
                triggered=False,
            ),
        ],
        recommended_cumulative_sell_pct=recommended_cumulative_sell_pct,
        value_to_harvest=value_to_harvest,
        remaining_sell_capacity=25.0,
        gain_basis="paid",
        vol_spike_context=None,
    )


def _build(
    *,
    theta_annual: float = -8_000.0,
    budget_pct: float = 2.0,
    underlying_quantity: float = 100.0,
    spot_price: float = 5_000.0,
    ips_convexity: IpsConvexity | None = _IPS_CONVEXITY,
    payoff_ratio: float | None = 8.5,
    convexity_pct: float = 15.0,
    meets_target: bool = True,
    data_quality: DataQuality = DataQuality.LIVE,
    schedule_steps: int = 2,
    monetization_plan: MonetizationPlan | None = None,
) -> ProgramReport:
    return build_program_report(
        portfolio=_make_portfolio(
            underlying_quantity=underlying_quantity,
            spot_price=spot_price,
        ),
        ips_config=_make_ips_config(
            annual_carry_pct=budget_pct,
            schedule_steps=schedule_steps,
        ),
        crash_result=_make_crash_result(
            ips_convexity=ips_convexity,
            payoff_ratio=payoff_ratio,
            convexity_pct=convexity_pct,
            meets_target=meets_target,
        ),
        carry_metrics=_make_carry_metrics(theta_annual),
        market_env=_make_market_env(data_quality),
        period_label="Q2 2026",
        as_of=_AS_OF,
        monetization_plan=monetization_plan,
    )


# ── build_program_report ──────────────────────────────────────────────────


class TestBuildProgramReport:
    """Tests for build_program_report."""

    def test_header_fields(self) -> None:
        """Header is populated from IPS config and call arguments."""
        report = _build()
        h = report.header
        assert h.program_name == "SPX Tail Hedge"
        assert h.instrument == "SPX"
        assert h.period_label == "Q2 2026"
        assert h.as_of == _AS_OF

    def test_cost_within_budget(self) -> None:
        """carry_pct <= budget → within_budget True."""
        # notional = 100 * 5000 = 500_000; carry = 8000/500000*100 = 1.6%
        report = _build(theta_annual=-8_000.0, budget_pct=2.0)
        assert report.cost.carry_pct_of_notional == pytest.approx(1.6)
        assert report.cost.within_budget is True

    def test_cost_over_budget(self) -> None:
        """carry_pct > budget → within_budget False."""
        report = _build(theta_annual=-15_000.0, budget_pct=2.0)
        # 15000/500000*100 = 3%
        assert report.cost.carry_pct_of_notional == pytest.approx(3.0)
        assert report.cost.within_budget is False

    def test_cost_exactly_at_budget(self) -> None:
        """carry_pct == budget exactly → within_budget True."""
        # 10_000 / 500_000 * 100 = 2.0%
        report = _build(theta_annual=-10_000.0, budget_pct=2.0)
        assert report.cost.within_budget is True

    def test_cost_book_notional(self) -> None:
        """book_notional derives from underlying_quantity * spot_price."""
        report = _build(underlying_quantity=200.0, spot_price=3_000.0)
        assert report.cost.book_notional == pytest.approx(600_000.0)

    def test_protection_row_matched(self) -> None:
        """IPS crash_pct matches a scenario_row → fields populated."""
        report = _build(convexity_pct=18.0, meets_target=True)
        p = report.protection
        assert p.ips_crash_pct == pytest.approx(-25.0)
        assert p.convexity_pct == pytest.approx(18.0)
        assert p.meets_target is True
        assert p.payoff_ratio == pytest.approx(8.5)
        assert p.target_min_pct == pytest.approx(10.0)
        assert p.target_max_pct == pytest.approx(30.0)

    def test_protection_row_not_meeting_target(self) -> None:
        """meets_target False when convexity below band."""
        report = _build(convexity_pct=5.0, meets_target=False)
        assert report.protection.meets_target is False

    def test_protection_no_ips_convexity(self) -> None:
        """All optional protection fields are None when no IPS scenario."""
        report = _build(ips_convexity=None, payoff_ratio=None)
        p = report.protection
        assert p.ips_crash_pct is None
        assert p.convexity_pct is None
        assert p.target_min_pct is None
        assert p.target_max_pct is None
        assert p.meets_target is None

    def test_market_context_live(self) -> None:
        """LIVE quality → all fields populated."""
        report = _build(data_quality=DataQuality.LIVE)
        mc = report.market_context
        assert mc.data_quality == "LIVE"
        assert mc.vix == pytest.approx(18.0)
        assert mc.regime_label == "NORMAL"
        assert mc.skew_percentile == pytest.approx(0.45)
        assert mc.hedge_cost_verdict == "FAIR"

    def test_market_context_static(self) -> None:
        """STATIC quality surfaced in data_quality field."""
        report = _build(data_quality=DataQuality.STATIC)
        assert report.market_context.data_quality == "STATIC"

    def test_market_context_unavailable(self) -> None:
        """UNAVAILABLE → regime/skew/verdict all None."""
        report = _build(data_quality=DataQuality.UNAVAILABLE)
        mc = report.market_context
        assert mc.data_quality == "UNAVAILABLE"
        assert mc.vix is None
        assert mc.regime_label is None
        assert mc.skew_percentile is None
        assert mc.hedge_cost_verdict is None

    def test_return_framing_carry_drag(self) -> None:
        """carry_drag_annual_pct mirrors cost.carry_pct_of_notional."""
        report = _build(theta_annual=-8_000.0)
        assert report.return_framing.carry_drag_annual_pct == pytest.approx(
            report.cost.carry_pct_of_notional,
        )

    def test_monetization_label_is_placeholder(self) -> None:
        """realized_label is always the placeholder string."""
        report = _build()
        assert "planned" in report.monetization.realized_label
        assert "C4" in report.monetization.realized_label

    def test_monetization_schedule_steps(self) -> None:
        """schedule_steps reflects the IPS monetization schedule length."""
        report = _build(schedule_steps=3)
        assert report.monetization.schedule_steps == 3

    def test_monetization_separate_from_carry(self) -> None:
        """Monetization realized_label is never derived from cost fields."""
        report = _build()
        assert report.monetization.realized_label != str(
            report.cost.total_theta_annual,
        )
        assert report.monetization.realized_label != str(
            report.cost.carry_pct_of_notional,
        )

    def test_ips_compliance_all_pass(self) -> None:
        """all_pass True when both carry and convexity pass."""
        report = _build(
            theta_annual=-8_000.0,
            budget_pct=2.0,
            convexity_pct=15.0,
            meets_target=True,
        )
        assert report.ips_compliance.all_pass is True

    def test_ips_compliance_carry_fail(self) -> None:
        """all_pass False when carry exceeds budget."""
        report = _build(
            theta_annual=-20_000.0,
            budget_pct=2.0,
            meets_target=True,
        )
        assert report.ips_compliance.all_pass is False

    def test_ips_compliance_convexity_fail(self) -> None:
        """all_pass False when convexity misses the band."""
        report = _build(
            theta_annual=-8_000.0,
            budget_pct=2.0,
            meets_target=False,
        )
        assert report.ips_compliance.all_pass is False

    def test_ips_compliance_row_count(self) -> None:
        """Exactly two compliance rows: carry and convexity."""
        report = _build()
        assert len(report.ips_compliance.rows) == 2


# ── render_markdown ───────────────────────────────────────────────────────


def _make_full_report() -> ProgramReport:
    return _build()


class TestRenderMarkdown:
    """Tests for render_markdown."""

    def test_returns_string(self) -> None:
        """render_markdown returns a str."""
        md = render_markdown(_make_full_report())
        assert isinstance(md, str)

    def test_section_headers_present(self) -> None:
        """All six numbered section headers are present."""
        md = render_markdown(_make_full_report())
        for heading in (
            "## 1. Cost",
            "## 2. Protection",
            "## 3. Market Context",
            "## 4. Return Framing",
            "## 5. Monetization Realized",
            "## 6. IPS Compliance",
        ):
            assert heading in md, f"missing: {heading!r}"

    def test_pass_symbols_present(self) -> None:
        """✓ PASS and ✗ appear somewhere in the output."""
        md_pass = render_markdown(
            _build(theta_annual=-8_000.0, meets_target=True),
        )
        assert "✓ PASS" in md_pass

        md_fail = render_markdown(
            _build(theta_annual=-20_000.0, meets_target=False),
        )
        assert "✗ FAIL" in md_fail

    def test_pending_return_note_present(self) -> None:
        """PENDING label appears in the return framing section."""
        md = render_markdown(_make_full_report())
        assert "PENDING" in md

    def test_static_caveat_present_when_static(self) -> None:
        """Data-quality caveat appears for STATIC data."""
        md = render_markdown(_build(data_quality=DataQuality.STATIC))
        assert "STATIC" in md
        assert "reference values" in md

    def test_caveat_absent_when_live(self) -> None:
        """No caveat injected for LIVE data."""
        md = render_markdown(_build(data_quality=DataQuality.LIVE))
        assert "reference values" not in md

    def test_monetization_placeholder_present(self) -> None:
        """The monetization placeholder string appears in the output."""
        md = render_markdown(_make_full_report())
        assert "planned (C4)" in md

    def test_key_figures_in_output(self) -> None:
        """Cost % and budget % appear numerically in the output."""
        report = _build(theta_annual=-8_000.0, budget_pct=2.0)
        md = render_markdown(report)
        # 1.60% carry; budget ≤ 2.00%
        assert "1.60%" in md
        assert "2.00%" in md

    def test_ips_compliance_table_row_count(self) -> None:
        """Compliance pipe-table has two data rows (header + separator + 2)."""
        md = render_markdown(_make_full_report())
        # Count lines that look like table rows with 4 pipes
        table_rows = [
            ln
            for ln in md.splitlines()
            if ln.startswith("|") and ln.count("|") >= 5
        ]
        # header row + 2 data rows = 3
        assert len(table_rows) >= 2


# ── render_html ───────────────────────────────────────────────────────────


class TestRenderHtml:
    """Tests for render_html."""

    def test_returns_string(self) -> None:
        """render_html returns a str."""
        html = render_html(_make_full_report())
        assert isinstance(html, str)

    def test_doctype_present(self) -> None:
        """Output starts with <!DOCTYPE html>."""
        html = render_html(_make_full_report())
        assert html.startswith("<!DOCTYPE html>")

    def test_section_headings_present(self) -> None:
        """All six <h2> section headings appear in the HTML."""
        html = render_html(_make_full_report())
        for heading in (
            "1. Cost",
            "2. Protection",
            "3. Market Context",
            "4. Return Framing",
            "5. Monetization Realized",
            "6. IPS Compliance",
        ):
            assert heading in html, f"missing heading: {heading!r}"

    def test_compliance_table_present(self) -> None:
        """The compliance table tag is present."""
        html = render_html(_make_full_report())
        assert "<table>" in html

    def test_pending_label_present(self) -> None:
        """PENDING label appears in the return-framing section."""
        html = render_html(_make_full_report())
        assert "PENDING" in html

    def test_monetization_placeholder_present(self) -> None:
        """Monetization placeholder string is in the HTML."""
        html = render_html(_make_full_report())
        assert "planned (C4)" in html

    def test_data_quality_caveat_static(self) -> None:
        """Caveat div appears for STATIC data."""
        html = render_html(_build(data_quality=DataQuality.STATIC))
        assert 'class="caveat"' in html
        assert "STATIC" in html

    def test_data_quality_caveat_absent_live(self) -> None:
        """No caveat div for LIVE data."""
        html = render_html(_build(data_quality=DataQuality.LIVE))
        assert 'class="caveat"' not in html

    def test_pass_class_present(self) -> None:
        """HTML class 'pass' appears for passing metrics."""
        html = render_html(
            _build(theta_annual=-8_000.0, meets_target=True),
        )
        assert 'class="pass"' in html

    def test_fail_class_present(self) -> None:
        """HTML class 'fail' appears for failing metrics."""
        html = render_html(
            _build(theta_annual=-20_000.0, meets_target=False),
        )
        assert 'class="fail"' in html

    def test_inline_style_block(self) -> None:
        """Output contains an inline <style> block."""
        html = render_html(_make_full_report())
        assert "<style>" in html

    def test_no_external_dependencies(self) -> None:
        """No link rel=stylesheet or script src in the output."""
        html = render_html(_make_full_report())
        assert 'rel="stylesheet"' not in html
        assert "<script" not in html


# ── MonetizationSection with plan ────────────────────────────────────────


class TestMonetizationSectionWithPlan:
    """build_program_report with a MonetizationPlan: advisory fields."""

    def test_advisory_fields_populated(self) -> None:
        """Advisory fields mirror the plan's values."""
        plan = _make_plan(
            current_gain_pct=75.0,
            recommended_cumulative_sell_pct=25.0,
            value_to_harvest=2_500.0,
        )
        report = _build(monetization_plan=plan)
        m = report.monetization
        assert m.current_gain_pct == pytest.approx(75.0)
        assert m.recommended_cumulative_sell_pct == pytest.approx(25.0)
        assert m.value_to_harvest == pytest.approx(2_500.0)

    def test_realized_label_still_placeholder(self) -> None:
        """realized_label keeps the placeholder even with a plan supplied."""
        report = _build(monetization_plan=_make_plan())
        assert "planned" in report.monetization.realized_label

    def test_advisory_not_netted_against_carry(self) -> None:
        """recommended_cumulative_sell_pct is independent of cost fields."""
        plan = _make_plan(recommended_cumulative_sell_pct=25.0)
        report = _build(
            theta_annual=-8_000.0,
            monetization_plan=plan,
        )
        m = report.monetization
        assert m.recommended_cumulative_sell_pct != pytest.approx(
            report.cost.carry_pct_of_notional,
        )
        assert m.recommended_cumulative_sell_pct != pytest.approx(
            abs(report.cost.total_theta_annual),
        )

    def test_unknown_gain_renders_gracefully(self) -> None:
        """current_gain_pct=None is stored without error."""
        plan = _make_plan(current_gain_pct=None)
        report = _build(monetization_plan=plan)
        assert report.monetization.current_gain_pct is None

    def test_markdown_shows_recommended_table(self) -> None:
        """Markdown includes the advisory table header and key labels."""
        report = _build(monetization_plan=_make_plan())
        md = render_markdown(report)
        assert "Recommended advisory (not realized)" in md
        assert "Recommended cumulative sell" in md
        assert "Estimated value to harvest" in md

    def test_markdown_unknown_gain_shows_label(self) -> None:
        """When gain is None, markdown shows 'unknown' in the table."""
        report = _build(monetization_plan=_make_plan(current_gain_pct=None))
        md = render_markdown(report)
        assert "unknown" in md

    def test_html_shows_recommended_table(self) -> None:
        """HTML includes the advisory table header and key labels."""
        report = _build(monetization_plan=_make_plan())
        html = render_html(report)
        assert "Recommended advisory (not realized)" in html
        assert "Recommended cumulative sell" in html
        assert "Estimated value to harvest" in html

    def test_html_placeholder_still_present(self) -> None:
        """Realized-label placeholder remains in HTML alongside advisory."""
        report = _build(monetization_plan=_make_plan())
        html = render_html(report)
        assert "planned (C4)" in html


# ── MonetizationSection without plan ─────────────────────────────────────


class TestMonetizationSectionWithoutPlan:
    """build_program_report without a plan preserves legacy behaviour."""

    def test_advisory_fields_are_none(self) -> None:
        """Without a plan, all three advisory fields are None."""
        report = _build()
        m = report.monetization
        assert m.current_gain_pct is None
        assert m.recommended_cumulative_sell_pct is None
        assert m.value_to_harvest is None

    def test_placeholder_renders_markdown(self) -> None:
        """Placeholder text still appears in markdown output."""
        md = render_markdown(_build())
        assert "planned (C4)" in md

    def test_placeholder_renders_html(self) -> None:
        """Placeholder text still appears in HTML output."""
        html = render_html(_build())
        assert "planned (C4)" in html

    def test_no_advisory_table_in_markdown(self) -> None:
        """Without a plan, the advisory table header is absent."""
        md = render_markdown(_build())
        assert "Recommended advisory (not realized)" not in md

    def test_no_advisory_table_in_html(self) -> None:
        """Without a plan, the advisory table header is absent."""
        html = render_html(_build())
        assert "Recommended advisory (not realized)" not in html
