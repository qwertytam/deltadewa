"""The carry row's pass flag is a native ``bool`` on the real numpy path.

``carry_vs_budget`` compared a numpy float, so ``within_budget`` was a
``numpy.bool_``. The IPS compliance table reads a row with ``is True`` and
``is False``, and a ``numpy.False_`` is neither, so on a real book:

- a breached carry row was not in ``failing_metrics`` (the digest headline
  counted one metric fewer than the table showed as FAIL), and
- a passing carry row made ``all_pass`` False while ``standing`` read PASS, so
  a book with every row in policy printed ``BREACH: 0 IPS metrics out of
  policy``.

``snapshot_from_report`` had coerced the flag since M2.6, for ``json.dumps``,
which is why the snapshot file looked right while the section it was built from
did not. The unit tests built ``CostSection`` by hand with Python bools, which
is why nothing here caught it. These drive the numpy path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from deltadewa.analysis.carry import carry_vs_budget
from deltadewa.app.import_portfolio import main as import_portfolio_main
from deltadewa.reporting.program_report import (
    ComplianceStanding,
    IpsComplianceSection,
    build_cost_section,
    build_ips_compliance,
    build_protection_section,
    build_vega_section,
)
from deltadewa.reporting.weekly_report import main

from ..test_analysis.test_roll_by import _book, _ips, _put
from .test_weekly_report import _EXAMPLE_IPS_YAML, _EXAMPLE_PORTFOLIO

if TYPE_CHECKING:
    from pathlib import Path

_NOTIONAL = np.float64(1_000_000.0)


class TestTheFlagIsANativeBool:
    @pytest.mark.parametrize(
        ("theta", "expected"),
        [(-5_000.0, True), (-10_000.0, True), (-20_000.0, False)],
        ids=["well inside", "on the budget", "over"],
    )
    def test_a_numpy_theta_gives_a_python_bool(
        self,
        theta: float,
        expected: bool,
    ) -> None:
        status = carry_vs_budget(
            theta_annual=np.float64(theta),
            book_notional=_NOTIONAL,
            budget_annual_pct=1.0,
        )

        assert type(status.within_budget) is bool
        assert status.within_budget is expected


def _compliance(theta: float, *, vega_in_band: bool = True) -> object:
    """The real builders, fed a numpy theta as the analyzer feeds them."""
    cost = build_cost_section(
        carry_metrics={"total_theta_annual": np.float64(theta)},
        book_notional=float(_NOTIONAL),
        budget_annual_pct=1.0,
    )
    book = _book(_put(days=400))
    book.underlying_quantity = 500
    protection = build_protection_section(
        _crash_result(book),
    )
    vega = build_vega_section(
        sufficiency_pct=2.5 if vega_in_band else 0.7,
        ips_vega=_ips().vega,
    )
    return build_ips_compliance(cost, protection, vega)


def _crash_result(book: object) -> object:
    from deltadewa.analysis.crash_payoff import compute_crash_convexity
    from deltadewa.analysis.crash_repricing import CrashShock

    ips = _ips()
    return compute_crash_convexity(
        book,  # type: ignore[arg-type]
        shock=CrashShock.from_ips(ips.convexity),
        ips_convexity=ips.convexity,
    )


class TestTheSectionReadsTheCarryRow:
    def test_a_breached_carry_row_is_a_failing_metric(self) -> None:
        compliance = _compliance(-20_000.0)
        assert isinstance(compliance, IpsComplianceSection)

        assert "Annual carry cost" in compliance.failing_metrics
        assert compliance.standing is ComplianceStanding.FAIL

    def test_a_row_in_policy_does_not_break_all_pass(self) -> None:
        """Carry inside its budget, and the others measured and passing."""
        compliance = _compliance(-5_000.0)
        assert isinstance(compliance, IpsComplianceSection)
        carry = next(
            r for r in compliance.rows if r.metric.startswith("Annual")
        )

        assert carry.passes is True
        # Whatever the other rows say, all_pass and standing agree.
        assert compliance.all_pass is (
            compliance.standing is ComplianceStanding.PASS
        )

    def test_a_clean_book_through_the_real_cli_does_not_read_breach(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The reported symptom, end to end: every row in policy.

        The example book with a budget and a convexity ceiling wide enough
        that carry, convexity and vega all pass. ``all_pass`` used to be False
        here (carry was a ``numpy.True_``), and the headline printed
        "BREACH: 0 IPS metrics out of policy".
        """
        monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))
        text = _EXAMPLE_IPS_YAML.read_text(encoding="utf-8")
        assert text.count("annual_carry_pct: 1.0") == 1
        assert text.count("target_max_pct: 20.0") == 1
        ips_path = tmp_path / "ips.yaml"
        ips_path.write_text(
            text.replace(
                "annual_carry_pct: 1.0", "annual_carry_pct: 9.0"
            ).replace("target_max_pct: 20.0", "target_max_pct: 30.0"),
            encoding="utf-8",
        )
        assert (
            import_portfolio_main(
                [
                    str(_EXAMPLE_PORTFOLIO),
                    "--export-dir",
                    str(tmp_path),
                    "--ips-path",
                    str(ips_path),
                ],
            )
            == 0
        )

        assert (
            main(
                [
                    "--export-dir",
                    str(tmp_path),
                    "--ips-path",
                    str(ips_path),
                    "--as-of",
                    "2026-08-05",
                ],
            )
            == 0
        )

        markdown = (
            tmp_path / "reports" / "weekly" / "digest-2026-08-05.md"
        ).read_text(encoding="utf-8")
        title = markdown.splitlines()[0]
        assert "BREACH" not in title
        assert "**Overall: \u2713 PASS**" in markdown
