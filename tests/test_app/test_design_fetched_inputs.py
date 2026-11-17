"""The /design Fetched inputs panel (9b): read-only, nothing priced on it."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages.design.planning import fetched_inputs
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.marketdata.chain import parse_cboe_chain
from deltadewa.state import ProgramState
from tests.chain_builders import (
    SESSION,
    TIMESTAMP,
    payload,
    priced_contract,
    smile,
)
from tests.clock_helpers import days_from_today
from tests.test_app.test_design import _collect_text

_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)
_STRIKE = 4000.0
_OLD_TIMESTAMP = "2020-01-03 01:00:00"  # the 2020-01-02 session


def _app(
    tmp_path: Path,
    *,
    chain_timestamp: str | None = TIMESTAMP,
    rates: dict[str, float] | None = None,
) -> ProgramDashApp:
    """One long put, and a cached chain that lists it (unless None)."""
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state.add_position(
        strike_price=_STRIKE,
        maturity_date=days_from_today(365),
        quantity=10,
        option_type=OptionType.PUT,
    )
    portfolio = state.portfolio
    chains = {}
    if chain_timestamp is not None:
        option = portfolio.positions[0].option
        # Priced at the book's own r and q, so the IV solved back at them
        # is the smile exactly.
        contract = priced_contract(
            "SPX",
            option.maturity_date.date(),
            OptionType.PUT,
            _STRIKE,
            rate=portfolio.risk_free_rate,
            dividend=portfolio.dividend_yield,
        )
        chains = {
            "SPX": parse_cboe_chain(
                payload([contract], timestamp=chain_timestamp),
            ),
        }
    return create_app(
        state=state,
        market_data=StaticProvider(
            spot_prices={"SPX": 5000.0},
            vix=18.0,
            chains=chains,
            rates=rates if rates is not None else {"DGS1": 4.6},
        ),
        ips_config=state.ips_config,
    )


def _text(app: ProgramDashApp, ips_config: object = None) -> str:
    config = ips_config if ips_config is not None else app.ips_config
    return _collect_text(
        fetched_inputs._render_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=config,  # type: ignore[arg-type]
            market_data=app.market_data,
        ),
    )


class TestFetchedInputsPanel:
    """What the panel shows, and what it refuses to claim."""

    def test_no_policy_section_says_nothing_is_fetched(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        assert app.ips_config is not None
        no_feed = replace(app.ips_config, pricing_feed=None)

        text = _text(app, no_feed)

        assert "no pricing_feed section" in text
        assert "every pricing input is hand-entered" in text
        assert "Held options" not in text

    def test_a_cold_cache_is_a_note_not_a_broken_panel(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path, chain_timestamp=None))

        assert "No option chain is cached yet" in text
        assert "Something went wrong" not in text

    def test_inputs_table_sets_fetched_beside_typed(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)

        text = _text(app)

        assert "Index level (spot)" in text
        assert "5,000.00" in text  # the chain's index level
        assert f"chain, {SESSION:%Y-%m-%d} close" in text
        assert "DGS1 4.60% as published" in text
        assert "% continuous" in text

    def test_the_dividend_yield_is_never_fetched_and_says_why(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path))

        assert "Dividend yield" in text
        assert "cannot isolate the yield" in text

    def test_a_missing_rate_is_a_note_beside_a_working_chain(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path, rates={}))

        assert "no DGS1 reading cached yet" in text
        assert "Held options" in text

    def test_a_held_option_shows_its_contract_quote_and_solved_iv(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        option = app.program_state.portfolio.positions[0].option

        text = _text(app)

        assert f"PUT {_STRIKE:g} exp {option.maturity_date:%Y-%m-%d}" in text
        assert "(SPX)" in text
        assert f"{smile(_STRIKE) * 100:.2f}%" in text  # Cboe's, and ours
        assert "IV at book r, q" in text

    def test_the_policy_ladder_rungs_are_listed_as_candidates(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path))

        assert "strike_ladder rungs (candidates, not held)" in text
        assert "20% OTM" in text

    def test_adopt_is_stated_as_recorded_not_applied(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path))

        assert "Policy adopt: nothing." in text
        assert "recorded, not applied" in text

    def test_an_old_chain_is_flagged_stale(self, tmp_path: Path) -> None:
        text = _text(_app(tmp_path, chain_timestamp=_OLD_TIMESTAMP))

        assert "STALE-QUOTE" in text

    def test_nothing_is_written_to_the_book(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        before = app.program_state.portfolio.positions[0].option.volatility

        _text(app)

        assert app.program_state.portfolio.positions[0].option.volatility == (
            before
        )
        assert app.program_state.portfolio.positions[0].liquidity is None
        assert app.program_state.dirty is False
