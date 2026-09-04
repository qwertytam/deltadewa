"""Tests for deltadewa.reporting.program_report."""

import dataclasses
import datetime

import pytest

from deltadewa.analysis.crash_payoff import (
    CrashConvexityResult,
    CrashScenarioRow,
    PremiumBasis,
)
from deltadewa.analysis.crash_repricing import describe_expired_legs
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
from deltadewa.analysis.provenance import (
    ProvenanceLedger,
    build_provenance_ledger,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsMonetizationStep,
    IpsPricing,
    IpsPricingInputs,
    IpsProgram,
    IpsTriggers,
)
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.stamps import MarketParameterStamps
from deltadewa.reporting.program_report import (
    HTML_STYLE,
    ProgramReport,
    build_program_report,
    build_protection_section,
    expired_legs_caveat,
    render_html,
    render_html_body,
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
            delta_ratio_deviation_warn_pct=5.0,
            delta_ratio_deviation_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_at_months_remaining=2.0,
            rally_monitor_pct=5.0,
            rally_review_pct=10.0,
            rally_action_pct=15.0,
            rally_urgent_pct=20.0,
        ),
        monetization=IpsMonetization(schedule=steps),
    )


def _expired_put_position() -> object:
    """One long put whose maturity is already past the valuation date."""
    portfolio = OptionPortfolio(
        spot_price=5_000.0,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        valuation_date=datetime.datetime(2026, 6, 24, tzinfo=datetime.UTC),
    )
    portfolio.add_position(
        strike_price=4_500.0,
        maturity_date=datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC),
        quantity=5,
        option_type=OptionType.PUT,
        # #365: this fixture deliberately wants an already-expired leg.
        reject_expired=False,
    )
    return portfolio.positions[0]


def _make_crash_result(
    *,
    ips_convexity: IpsConvexity | None = _IPS_CONVEXITY,
    payoff_vs_premium: float | None = 8.5,
    convexity_pct: float = 15.0,
    meets_target: bool = True,
    premium_paid: float = 10_000.0,
    excluded_expired: tuple = (),
) -> CrashConvexityResult:
    rows = []
    if ips_convexity is not None:
        rows.append(
            CrashScenarioRow(
                shock_pct=ips_convexity.crash_scenario_pct,
                hedge_pnl=premium_paid * (payoff_vs_premium or 0),
                payoff_vs_premium=payoff_vs_premium or 0.0,
                convexity_pct=convexity_pct,
                meets_target=meets_target,
                intrinsic_floor=premium_paid * (payoff_vs_premium or 0) * 0.2,
            ),
        )
    return CrashConvexityResult(
        curve=[],
        scenario_rows=rows,
        payoff_vs_premium=payoff_vs_premium,
        premium_paid=premium_paid,
        premium_basis=PremiumBasis.PAID,
        ips_convexity=ips_convexity,
        excluded_expired=excluded_expired,
    )


_ENV_AS_OF = datetime.datetime(2026, 7, 24, tzinfo=datetime.UTC)


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
            as_of=None,
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
        as_of=_ENV_AS_OF,
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
        # Freshly confirmed as of _AS_OF, so ProvenanceLedger.combined_
        # quality falls through to the fetched market-data grade below,
        # exactly like every one of this module's data_quality assertions
        # already assumes — a portfolio with no stamps would report
        # UNKNOWN pricing inputs and override every data_quality= this
        # file's tests pass in (#367).
        stamps=MarketParameterStamps(
            spot_as_of=_ENV_AS_OF,
            risk_free_rate_as_of=_ENV_AS_OF,
            dividend_yield_as_of=_ENV_AS_OF,
        ),
    )


def _make_provenance_ledger(
    portfolio: OptionPortfolio,
    market_env: MarketEnvironment,
) -> ProvenanceLedger:
    return build_provenance_ledger(
        market_env,
        portfolio,
        IpsPricingInputs(),
        as_of=_AS_OF,
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
                cumulative_sell_value=2_500.0,
            ),
            MonetizationStepStatus(
                gain_pct=100.0,
                sell_pct=25.0,
                triggered=False,
                cumulative_sell_value=0.0,
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
    payoff_vs_premium: float | None = 8.5,
    convexity_pct: float = 15.0,
    meets_target: bool = True,
    data_quality: DataQuality = DataQuality.LIVE,
    schedule_steps: int = 2,
    monetization_plan: MonetizationPlan | None = None,
) -> ProgramReport:
    portfolio = _make_portfolio(
        underlying_quantity=underlying_quantity,
        spot_price=spot_price,
    )
    market_env = _make_market_env(data_quality)
    return build_program_report(
        portfolio=portfolio,
        ips_config=_make_ips_config(
            annual_carry_pct=budget_pct,
            schedule_steps=schedule_steps,
        ),
        crash_result=_make_crash_result(
            ips_convexity=ips_convexity,
            payoff_vs_premium=payoff_vs_premium,
            convexity_pct=convexity_pct,
            meets_target=meets_target,
        ),
        carry_metrics=_make_carry_metrics(theta_annual),
        market_env=market_env,
        provenance_ledger=_make_provenance_ledger(portfolio, market_env),
        period_label="Q2 2026",
        as_of=_AS_OF,
        monetization_plan=monetization_plan,
    )


# ── expired_legs_caveat / build_protection_section (#375) ─────────────────


class TestExpiredLegsCaveat:
    """Tests for expired_legs_caveat."""

    def test_none_when_no_legs(self) -> None:
        assert expired_legs_caveat(()) is None

    def test_singular_for_one_leg(self) -> None:
        text = expired_legs_caveat(("4,500 PUT, expired 2026-05-01",))
        assert text == (
            "Convexity excludes 1 expired leg: 4,500 PUT, expired 2026-05-01."
        )

    def test_plural_for_multiple_legs(self) -> None:
        text = expired_legs_caveat(
            (
                "4,500 PUT, expired 2026-05-01",
                "4,600 PUT, expired 2026-05-15",
            ),
        )
        assert text is not None
        assert text.startswith("Convexity excludes 2 expired legs: ")

    def test_caps_at_three_named_legs(self) -> None:
        legs = tuple(f"leg-{i}" for i in range(5))
        text = expired_legs_caveat(legs)
        assert text is not None
        assert "leg-0" in text
        assert "leg-1" in text
        assert "leg-2" in text
        assert "leg-3" not in text
        assert "…and 2 more" in text


class TestBuildProtectionSectionExcludedExpired:
    """build_protection_section threads excluded_expired through (#375)."""

    def test_empty_when_nothing_excluded(self) -> None:
        result = _make_crash_result()
        section = build_protection_section(result)
        assert section.excluded_expired_legs == ()

    def test_names_excluded_expired_legs(self) -> None:
        position = _expired_put_position()
        result = _make_crash_result(excluded_expired=(position,))

        section = build_protection_section(result)

        assert section.excluded_expired_legs == describe_expired_legs(
            (position,),
        )
        assert len(section.excluded_expired_legs) == 1

    def test_names_excluded_expired_legs_without_ips_convexity(self) -> None:
        """The no-IPS branch also threads excluded_expired (#375)."""
        position = _expired_put_position()
        result = _make_crash_result(
            ips_convexity=None,
            excluded_expired=(position,),
        )

        section = build_protection_section(result)

        assert len(section.excluded_expired_legs) == 1


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
        assert p.payoff_vs_premium == pytest.approx(8.5)
        assert p.target_min_pct == pytest.approx(10.0)
        assert p.target_max_pct == pytest.approx(30.0)

    def test_protection_row_not_meeting_target(self) -> None:
        """meets_target False when convexity below band."""
        report = _build(convexity_pct=5.0, meets_target=False)
        assert report.protection.meets_target is False

    def test_protection_no_ips_convexity(self) -> None:
        """All optional protection fields are None when no IPS scenario."""
        report = _build(ips_convexity=None, payoff_vs_premium=None)
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

    def test_market_context_reads_the_ledgers_combined_quality(
        self,
    ) -> None:
        """#367: data_quality is provenance_ledger.combined_quality, not
        market_env.data_quality directly — the same grade the live
        pages' banner reflects (Batch 3b's "one grader" rule).
        """
        portfolio = _make_portfolio()
        market_env = _make_market_env(DataQuality.LIVE)
        ledger = _make_provenance_ledger(portfolio, market_env)

        report = build_program_report(
            portfolio=portfolio,
            ips_config=_make_ips_config(),
            crash_result=_make_crash_result(),
            carry_metrics=_make_carry_metrics(),
            market_env=market_env,
            provenance_ledger=ledger,
            period_label="Q2 2026",
            as_of=_AS_OF,
        )

        assert report.market_context.data_quality == (
            ledger.combined_quality.value
        )

    def test_stale_hand_entered_input_turns_the_digest_grade(self) -> None:
        """#367's acceptance: a stale hand-entered input can turn the
        digest's data-quality caveat even though the fetched market data
        is fully LIVE.
        """
        # No stamps at all — every hand-entered input is UNKNOWN.
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=5_000.0
        )
        market_env = _make_market_env(DataQuality.LIVE)
        ledger = _make_provenance_ledger(portfolio, market_env)

        report = build_program_report(
            portfolio=portfolio,
            ips_config=_make_ips_config(),
            crash_result=_make_crash_result(),
            carry_metrics=_make_carry_metrics(),
            market_env=market_env,
            provenance_ledger=ledger,
            period_label="Q2 2026",
            as_of=_AS_OF,
        )

        # The fetched market data is LIVE, but the never-confirmed
        # hand-entered inputs (UNKNOWN) are worse and must win.
        assert market_env.data_quality == DataQuality.LIVE
        assert report.market_context.data_quality == "STATIC"

    def test_return_framing_carry_drag(self) -> None:
        """carry_drag_annual_pct mirrors cost.carry_pct_of_notional."""
        report = _build(theta_annual=-8_000.0)
        assert report.return_framing.carry_drag_annual_pct == pytest.approx(
            report.cost.carry_pct_of_notional,
        )

    def test_return_framing_weekly_fields_default_none(self) -> None:
        """The standalone builder never populates the weekly-carry fields.

        Only build_weekly_digest (weekly_report.py) has a prior-week
        baseline to compute them from — see Issue #171.
        """
        rf = _build().return_framing
        assert rf.weekly_carry_cost is None
        assert rf.elapsed_days is None
        assert rf.cumulative_carry_cost is None
        assert rf.cumulative_since is None
        assert rf.premium_paid_point_in_time is None

    def test_monetization_label_is_placeholder(self) -> None:
        """realized_label is always the placeholder string, citing #70."""
        report = _build()
        assert "not tracked" in report.monetization.realized_label
        assert "#70" in report.monetization.realized_label

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

    def test_passing_rows_have_no_action(self) -> None:
        """action is None exactly when passes is True (#307)."""
        report = _build(
            theta_annual=-8_000.0, budget_pct=2.0, meets_target=True
        )
        for row in report.ips_compliance.rows:
            assert row.passes is True
            assert row.action is None

    def test_carry_over_budget_has_an_action(self) -> None:
        report = _build(
            theta_annual=-20_000.0, budget_pct=2.0, meets_target=True
        )
        row = next(
            r
            for r in report.ips_compliance.rows
            if r.metric == "Annual carry cost"
        )
        assert row.passes is False
        assert row.action is not None
        assert "budget" in row.action

    def test_convexity_below_band_action_says_under_hedged(self) -> None:
        # target_min_pct=10.0 on _IPS_CONVEXITY — 5.0 is below it.
        report = _build(convexity_pct=5.0, meets_target=False)
        row = next(
            r
            for r in report.ips_compliance.rows
            if "Crash convexity" in r.metric
        )
        assert row.action is not None
        assert "under-hedged" in row.action
        assert "over-hedged" not in row.action

    def test_convexity_above_band_action_says_over_hedged(self) -> None:
        # target_max_pct=30.0 on _IPS_CONVEXITY — 35.0 is above it.
        report = _build(convexity_pct=35.0, meets_target=False)
        row = next(
            r
            for r in report.ips_compliance.rows
            if "Crash convexity" in r.metric
        )
        assert row.action is not None
        assert "over-hedged" in row.action
        assert "under-hedged" not in row.action

    def test_no_convexity_policy_action_names_the_gap(self) -> None:
        report = _build(ips_convexity=None)
        row = next(
            r
            for r in report.ips_compliance.rows
            if r.metric == "Crash convexity"
        )
        assert row.action is not None
        assert "No IPS convexity policy" in row.action

    def test_decision_populated_with_a_real_verdict(self) -> None:
        """build_program_report always sets decision — never None (#307)."""
        report = _build()
        assert report.decision is not None
        assert report.decision.verdict != "INSUFFICIENT_DATA"
        assert report.decision.entry_recommendation != ""

    def test_decision_insufficient_data_without_a_convexity_policy(
        self,
    ) -> None:
        """No fabricated number is fed to the classifier (#307)."""
        report = _build(ips_convexity=None)
        assert report.decision is not None
        assert report.decision.verdict == "INSUFFICIENT_DATA"
        assert report.decision.data_quality_note is not None


# ── render_markdown ───────────────────────────────────────────────────────


def _make_full_report() -> ProgramReport:
    return _build()


def _with_weekly_carry_framing(report: ProgramReport) -> ProgramReport:
    """Populate return_framing's weekly-carry fields (Issue #171).

    Mirrors what build_weekly_digest (weekly_report.py) does to the
    embedded report before rendering, so these tests exercise the same
    "populated" branch a real digest hits.
    """
    return dataclasses.replace(
        report,
        return_framing=dataclasses.replace(
            report.return_framing,
            weekly_carry_cost=1_400.0,
            elapsed_days=7,
            cumulative_carry_cost=2_800.0,
            cumulative_since=datetime.date(2026, 7, 1),
            premium_paid_point_in_time=report.protection.premium_paid,
        ),
    )


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

    def test_weekly_carry_framing_replaces_pending(self) -> None:
        """Populated weekly-carry fields render real figures, not PENDING.

        Issue #171: a digest embedding this report must never show a
        PENDING return-framing section under one that already answered
        the same question with real numbers.
        """
        md = render_markdown(_with_weekly_carry_framing(_make_full_report()))

        assert "PENDING" not in md
        assert "Carry cost this period" in md
        assert "$1,400 over 7 day(s)" in md
        assert "Cumulative carry cost since 2026-07-01" in md
        assert "$2,800" in md
        assert "Point-in-time premium invested" in md
        assert "not a return" in md

    def test_static_caveat_present_when_static(self) -> None:
        """Data-quality caveat appears for STATIC data."""
        md = render_markdown(_build(data_quality=DataQuality.STATIC))
        assert "STATIC" in md
        assert "reference values" in md

    def test_caveat_absent_when_live(self) -> None:
        """No caveat injected for LIVE data."""
        md = render_markdown(_build(data_quality=DataQuality.LIVE))
        assert "reference values" not in md

    def test_caveat_absent_when_cached(self) -> None:
        """No caveat for CACHED — the steady state once a cron exists."""
        md = render_markdown(_build(data_quality=DataQuality.CACHED))
        assert "reference values" not in md

    def test_caveat_present_when_stale(self) -> None:
        """The caveat still fires for STALE — worse than CACHED."""
        md = render_markdown(_build(data_quality=DataQuality.STALE))
        assert "STALE" in md
        assert "reference values" in md

    def test_expired_legs_caveat_absent_by_default(self) -> None:
        """No #375 caveat when no legs were excluded."""
        md = render_markdown(_make_full_report())
        assert "Convexity excludes" not in md

    def test_expired_legs_caveat_present_when_legs_excluded(self) -> None:
        """The #375 caveat names the excluded expired leg, after §2."""
        report = _make_full_report()
        report = dataclasses.replace(
            report,
            protection=dataclasses.replace(
                report.protection,
                excluded_expired_legs=("4,500 PUT, expired 2026-05-01",),
            ),
        )
        md = render_markdown(report)
        assert "Convexity excludes 1 expired leg" in md
        assert "4,500 PUT, expired 2026-05-01" in md
        assert md.index("Convexity excludes") > md.index("## 2. Protection")
        assert md.index("Convexity excludes") < md.index("## 3. Market Context")

    def test_monetization_placeholder_present(self) -> None:
        """The monetization placeholder string appears in the output."""
        md = render_markdown(_make_full_report())
        assert "not tracked" in md
        assert "#70" in md

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

    def test_decision_section_present(self) -> None:
        """§7 Decision & entry timing renders when report.decision is set."""
        md = render_markdown(_make_full_report())
        assert "## 7. Decision & entry timing" in md
        assert "**Verdict:**" in md
        assert "**Entry-timing recommendation:**" in md

    def test_decision_section_absent_when_none(self) -> None:
        """§7 is skipped entirely for a report with no decision (#307)."""
        report = dataclasses.replace(_make_full_report(), decision=None)
        md = render_markdown(report)
        assert "Decision & entry timing" not in md

    def test_recommended_action_line_for_failing_row(self) -> None:
        report = _build(
            theta_annual=-20_000.0, budget_pct=2.0, meets_target=True
        )
        md = render_markdown(report)
        assert "**Recommended action — Annual carry cost:**" in md

    def test_no_recommended_action_line_when_all_pass(self) -> None:
        report = _build(
            theta_annual=-8_000.0, budget_pct=2.0, meets_target=True
        )
        md = render_markdown(report)
        assert "Recommended action" not in md


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

    def test_wraps_render_html_body_unchanged(self) -> None:
        """render_html is exactly render_html_body wrapped in the shell.

        Locks the M2.6 refactor that split the two apart (so the weekly
        digest can embed the body without a second, nested HTML document):
        render_html's own output must stay byte-for-byte what it was
        before the split.
        """
        report = _make_full_report()
        html = render_html(report)
        body = render_html_body(report)

        assert body in html
        assert html == (
            f"<!DOCTYPE html>\n"
            f'<html lang="en">\n'
            f"<head>\n"
            f'<meta charset="UTF-8">\n'
            f"<title>Hedge Program Report &mdash; "
            f"{report.header.program_name}</title>\n"
            f"<style>\n{HTML_STYLE}\n</style>\n"
            f"</head>\n"
            f"<body>\n\n{body}\n\n</body>\n"
            f"</html>"
        )

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

    def test_weekly_carry_framing_replaces_pending(self) -> None:
        """Populated weekly-carry fields render real figures, not PENDING.

        HTML counterpart of the markdown test above (Issue #171).
        """
        html = render_html(_with_weekly_carry_framing(_make_full_report()))

        assert "PENDING" not in html
        assert "Carry cost this period" in html
        assert "Cumulative carry cost since 2026-07-01" in html
        assert "Point-in-time premium invested" in html
        assert "not a return" in html

    def test_monetization_placeholder_present(self) -> None:
        """Monetization placeholder string is in the HTML."""
        html = render_html(_make_full_report())
        assert "not tracked" in html
        assert "#70" in html

    def test_data_quality_caveat_static(self) -> None:
        """Caveat div appears for STATIC data."""
        html = render_html(_build(data_quality=DataQuality.STATIC))
        assert 'class="caveat"' in html
        assert "STATIC" in html

    def test_data_quality_caveat_absent_live(self) -> None:
        """No caveat div for LIVE data."""
        html = render_html(_build(data_quality=DataQuality.LIVE))
        assert 'class="caveat"' not in html

    def test_data_quality_caveat_absent_cached(self) -> None:
        """No caveat div for CACHED — the steady state once a cron exists."""
        html = render_html(_build(data_quality=DataQuality.CACHED))
        assert 'class="caveat"' not in html

    def test_data_quality_caveat_present_stale(self) -> None:
        """Caveat div still appears for STALE — worse than CACHED."""
        html = render_html(_build(data_quality=DataQuality.STALE))
        assert 'class="caveat"' in html
        assert "STALE" in html

    def test_expired_legs_caveat_absent_by_default(self) -> None:
        """No #375 caveat when no legs were excluded."""
        html = render_html(_make_full_report())
        assert "Convexity excludes" not in html

    def test_expired_legs_caveat_present_when_legs_excluded(self) -> None:
        """The #375 caveat names the excluded expired leg, after §2."""
        report = _make_full_report()
        report = dataclasses.replace(
            report,
            protection=dataclasses.replace(
                report.protection,
                excluded_expired_legs=("4,500 PUT, expired 2026-05-01",),
            ),
        )
        html = render_html(report)
        assert "Convexity excludes 1 expired leg" in html
        assert "4,500 PUT, expired 2026-05-01" in html
        assert html.index("Convexity excludes") > html.index(
            "<h2>2. Protection</h2>",
        )
        assert html.index("Convexity excludes") < html.index(
            "<h2>3. Market Context</h2>",
        )

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

    def test_decision_section_present(self) -> None:
        """§7 Decision & entry timing renders when report.decision is set."""
        html = render_html(_make_full_report())
        assert "7. Decision &amp; entry timing" in html
        assert "<strong>Verdict:</strong>" in html

    def test_decision_section_absent_when_none(self) -> None:
        """§7 is skipped entirely for a report with no decision (#307)."""
        report = dataclasses.replace(_make_full_report(), decision=None)
        html = render_html(report)
        assert "Decision &amp; entry timing" not in html

    def test_recommended_action_line_for_failing_row(self) -> None:
        report = _build(
            theta_annual=-20_000.0, budget_pct=2.0, meets_target=True
        )
        html = render_html(report)
        assert "Recommended action &mdash; Annual carry cost:" in html

    def test_no_recommended_action_line_when_all_pass(self) -> None:
        report = _build(
            theta_annual=-8_000.0, budget_pct=2.0, meets_target=True
        )
        html = render_html(report)
        assert "Recommended action" not in html


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
        assert "not tracked" in report.monetization.realized_label

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
        assert "not tracked" in html
        assert "#70" in html


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
        assert "not tracked" in md
        assert "#70" in md

    def test_placeholder_renders_html(self) -> None:
        """Placeholder text still appears in HTML output."""
        html = render_html(_build())
        assert "not tracked" in html
        assert "#70" in html

    def test_no_advisory_table_in_markdown(self) -> None:
        """Without a plan, the advisory table header is absent."""
        md = render_markdown(_build())
        assert "Recommended advisory (not realized)" not in md

    def test_no_advisory_table_in_html(self) -> None:
        """Without a plan, the advisory table header is absent."""
        html = render_html(_build())
        assert "Recommended advisory (not realized)" not in html
