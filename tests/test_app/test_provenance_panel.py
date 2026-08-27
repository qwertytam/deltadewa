"""Tests for deltadewa.app.provenance_panel (Batch 3d / #367)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from deltadewa.analysis.market_environment import DataQuality, MarketEnvironment
from deltadewa.analysis.provenance import build_provenance_ledger
from deltadewa.app.provenance_panel import build_provenance_panel
from deltadewa.constants import ExerciseStyle
from deltadewa.ips_config import IpsPricingInputs
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.stamps import MarketParameterStamps

_AS_OF = datetime(2026, 8, 26, tzinfo=UTC)
_TODAY = date(2026, 8, 26)
_POLICY = IpsPricingInputs()


def _environment(
    data_quality: DataQuality = DataQuality.LIVE,
    as_of: datetime | None = _AS_OF,
) -> MarketEnvironment:
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
        data_quality=data_quality,
        as_of=as_of,
    )


def _table_row_texts(panel) -> list[str]:
    table = panel.children[1].children[1]  # Details -> Table
    body = table.children[1]  # Tbody
    return ["".join(str(c) for c in row.children) for row in body.children]


class TestBuildProvenancePanel:
    def test_renders_one_row_per_entry(self) -> None:
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.EUROPEAN
        )
        ledger = build_provenance_ledger(
            _environment(),
            portfolio,
            _POLICY,
            as_of=_TODAY,
        )

        panel = build_provenance_panel(ledger)

        rows = _table_row_texts(panel)
        assert len(rows) == len(ledger.entries)

    def test_summary_reports_all_clear_when_everything_fresh(self) -> None:
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.EUROPEAN,
            stamps=MarketParameterStamps(
                spot_as_of=_AS_OF,
                risk_free_rate_as_of=_AS_OF,
                dividend_yield_as_of=_AS_OF,
            ),
        )
        ledger = build_provenance_ledger(
            _environment(),
            portfolio,
            _POLICY,
            as_of=_TODAY,
        )

        panel = build_provenance_panel(ledger)

        summary = panel.children[0].children
        assert "All inputs current" in summary

    def test_summary_names_the_worst_entry_when_not_fresh(self) -> None:
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.EUROPEAN
        )
        ledger = build_provenance_ledger(
            _environment(),
            portfolio,
            _POLICY,
            as_of=_TODAY,
        )

        panel = build_provenance_panel(ledger)

        summary = panel.children[0].children
        assert "Worst:" in summary
        assert ledger.worst is not None
        assert ledger.worst.label in summary

    def test_detail_table_is_collapsed_by_default(self) -> None:
        """Details/Summary — quiet unless the operator expands it."""
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.EUROPEAN
        )
        ledger = build_provenance_ledger(
            _environment(),
            portfolio,
            _POLICY,
            as_of=_TODAY,
        )

        panel = build_provenance_panel(ledger)

        details = panel.children[1]
        assert details.__class__.__name__ == "Details"
        assert not getattr(details, "open", False)
