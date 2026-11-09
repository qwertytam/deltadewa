"""Tests for hand-entered liquidity observations (8c, N10).

Covers the domain object (``portfolio/liquidity.py``), recording one
against a leg (``OptionPortfolioBase.record_liquidity``), the rules that
keep an observation honest (a contract change discards it; "mark inputs
reviewed" never refreshes it), and the JSON/YAML round-trip.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.persistence import YAML_AVAILABLE, PortfolioSerializer
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.liquidity import LiquidityObservation
from deltadewa.reporting.audit import PortfolioLogger
from tests.clock_helpers import days_from_today

if TYPE_CHECKING:
    from pathlib import Path

_SEEN = datetime(2026, 11, 6, 15, 30, tzinfo=UTC)


def _obs(**overrides: object) -> LiquidityObservation:
    fields: dict[str, object] = {
        "bid": 2.40,
        "ask": 2.60,
        "open_interest": 3_400,
        "observed_at": _SEEN,
    }
    fields.update(overrides)
    return LiquidityObservation(**fields)  # type: ignore[arg-type]


def _book() -> OptionPortfolio:
    portfolio = OptionPortfolio(
        spot_price=100.0,
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=80.0,
        maturity_date=days_from_today(365),
        quantity=10,
        option_type=OptionType.PUT,
    )
    return portfolio


class TestLiquidityObservation:
    """The quote itself: spread % and what a market cannot show."""

    def test_spread_pct_is_the_handbooks_formula(self) -> None:
        """(Ask - Bid) / Mid: the handbook's own 2.40/2.60 example is 8%."""
        obs = _obs()

        assert obs.mid == pytest.approx(2.50)
        assert obs.spread_pct == pytest.approx(8.0)

    def test_no_bid_reads_as_maximally_wide(self) -> None:
        """A zero bid is legal and reads 200%, not an error."""
        assert _obs(bid=0.0, ask=0.10).spread_pct == pytest.approx(200.0)

    def test_open_interest_is_optional(self) -> None:
        assert _obs(open_interest=None).open_interest is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"bid": -0.01},
            {"ask": 0.0},
            {"bid": 2.70, "ask": 2.60},
            {"open_interest": -1},
        ],
    )
    def test_rejects_a_quote_no_market_shows(
        self,
        overrides: dict[str, object],
    ) -> None:
        with pytest.raises(ValueError, match=r"bid|ask|crossed|open interest"):
            _obs(**overrides)


class TestRecordLiquidity:
    """Recording a quote against a leg, keyed by its stable id."""

    def test_records_against_the_named_leg(self) -> None:
        portfolio = _book()
        leg = portfolio.positions[0]

        stored = portfolio.record_liquidity(
            leg.position_id,
            bid=2.40,
            ask=2.60,
            open_interest=3_400,
            observed_at=_SEEN,
        )

        assert leg.liquidity == stored
        assert stored.observed_at == _SEEN

    def test_unknown_id_raises(self) -> None:
        with pytest.raises(KeyError, match="no position"):
            _book().record_liquidity(
                "not-a-leg",
                bid=1.0,
                ask=1.1,
                open_interest=None,
            )

    def test_defaults_observed_at_to_now(self) -> None:
        portfolio = _book()

        stored = portfolio.record_liquidity(
            portfolio.positions[0].position_id,
            bid=1.0,
            ask=1.1,
            open_interest=None,
        )

        assert stored.observed_at.tzinfo is not None

    def test_mark_inputs_reviewed_does_not_refresh_it(self) -> None:
        """A quote is data, not a confirmation: reviewing can't re-read it."""
        portfolio = _book()
        leg = portfolio.positions[0]
        portfolio.record_liquidity(
            leg.position_id,
            bid=2.40,
            ask=2.60,
            open_interest=None,
            observed_at=_SEEN,
        )

        portfolio.confirm_current_inputs(
            as_of=datetime(2026, 12, 1, tzinfo=UTC),
        )

        assert leg.liquidity is not None
        assert leg.liquidity.observed_at == _SEEN

    def test_changing_the_contract_discards_the_quote(self) -> None:
        """A quote for the 80 strike says nothing about the 75 strike."""
        portfolio = _book()
        leg = portfolio.positions[0]
        portfolio.record_liquidity(
            leg.position_id,
            bid=2.40,
            ask=2.60,
            open_interest=None,
        )

        portfolio.update_position(0, strike=75.0)

        assert leg.liquidity is None

    def test_quantity_or_vol_edit_keeps_the_quote(self) -> None:
        """Same contract, so the quote still describes it."""
        portfolio = _book()
        leg = portfolio.positions[0]
        portfolio.record_liquidity(
            leg.position_id,
            bid=2.40,
            ask=2.60,
            open_interest=None,
        )

        portfolio.update_position(0, quantity=20, volatility=0.25)
        portfolio.update_position(0, exercise_style=ExerciseStyle.AMERICAN)

        assert leg.liquidity is not None


class TestLiquidityPersistence:
    """Observations survive export/import verbatim, never re-stamped."""

    def _recorded(self) -> OptionPortfolio:
        portfolio = _book()
        portfolio.record_liquidity(
            portfolio.positions[0].position_id,
            bid=2.40,
            ask=2.60,
            open_interest=3_400,
            observed_at=_SEEN,
        )
        return portfolio

    def test_json_round_trip(self, tmp_path: Path) -> None:
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_json(
            self._recorded(),
            PortfolioLogger(),
            "liq.json",
        )

        restored = serializer.import_from_json(path)["portfolio"]

        assert restored.positions[0].liquidity == _obs()

    @pytest.mark.skipif(not YAML_AVAILABLE, reason="PyYAML not installed")
    def test_yaml_round_trip(self, tmp_path: Path) -> None:
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_yaml(
            self._recorded(),
            PortfolioLogger(),
            "liq.yaml",
        )
        assert path is not None

        restored = serializer.import_from_yaml(path)["portfolio"]

        assert restored.positions[0].liquidity == _obs()

    def test_unrecorded_leg_round_trips_as_none(self, tmp_path: Path) -> None:
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_json(_book(), PortfolioLogger(), "n.json")

        data = json.loads(path.read_text())
        restored = serializer.import_from_json(path)["portfolio"]

        assert data["positions"][0]["liquidity"] is None
        assert restored.positions[0].liquidity is None

    def test_pre_8c_file_has_no_key_and_reads_never_checked(
        self,
        tmp_path: Path,
    ) -> None:
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_json(_book(), PortfolioLogger(), "o.json")
        data = json.loads(path.read_text())
        del data["positions"][0]["liquidity"]
        path.write_text(json.dumps(data))

        restored = serializer.import_from_json(path)["portfolio"]

        assert restored.positions[0].liquidity is None

    def test_malformed_stored_quote_is_refused(self, tmp_path: Path) -> None:
        serializer = PortfolioSerializer(tmp_path)
        path = serializer.export_to_json(
            self._recorded(),
            PortfolioLogger(),
            "bad.json",
        )
        data = json.loads(path.read_text())
        data["positions"][0]["liquidity"]["bid"] = 9.99  # crossed
        path.write_text(json.dumps(data))

        with pytest.raises(ValueError, match="crossed"):
            serializer.import_from_json(path)
