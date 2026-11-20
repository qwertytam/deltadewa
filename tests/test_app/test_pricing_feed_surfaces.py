"""What every surface says when the feed prices the book (9b).

The ledger grades a fed input as the fetched data it is and its typed twin
not at all; the banner and the header tell a reader the prices were read once
and a reload does not re-read them; ``/health`` counts an adopted series
toward ``status``; the digest says what it priced on and lists every
override. All of it on the one #393/#398 rule, unchanged.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from deltadewa.analysis.market_environment import (
    DataQuality,
    assess_market_environment,
)
from deltadewa.analysis.pricing_resolution import (
    OverrideKind,
    newer_cached_session,
)
from deltadewa.analysis.provenance import (
    InputKind,
    ProvenanceLedger,
    assess_freshness,
    build_provenance_ledger,
)
from deltadewa.app.chrome import build_chrome
from deltadewa.app.factory import create_app
from deltadewa.app.provenance_panel import build_provenance_panel
from deltadewa.clock import program_trading_date
from deltadewa.marketdata import Source, write_cache_manifest
from deltadewa.reporting.program_report import _input_lines
from deltadewa.state import ProgramState
from tests.clock_helpers import days_from_today
from tests.feed_fixtures import (
    STRIKES,
    adopting_ips,
    fed_chain,
    leg_expiry,
    load_state,
    make_provider,
    write_typed_book,
)
from tests.test_app.test_design import _collect_text

if TYPE_CHECKING:
    from pathlib import Path

    from deltadewa.ips_config import IpsConfig
    from deltadewa.marketdata import MarketDataProvider


@pytest.fixture(autouse=True)
def _isolated_cache_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-test cache dir, as the ``/health`` tests do (#309's write probe)."""
    monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))
    write_cache_manifest(tmp_path / "cache", {})


def _state(
    tmp_path: Path,
    *,
    feed_source: Source | None = None,
    with_chain: bool = True,
    adopt: tuple[str, ...] = ("spot", "risk_free_rate", "volatility"),
) -> tuple[ProgramState, MarketDataProvider]:
    ips = adopting_ips(tmp_path, adopt)
    write_typed_book(tmp_path, ips)
    provider = make_provider(
        feed_source=feed_source,
        with_chain=with_chain,
    )
    return load_state(tmp_path, ips, provider), provider


def _ledger(
    state: ProgramState,
    provider: MarketDataProvider,
) -> ProvenanceLedger:
    ips = state.ips_config
    assert ips is not None
    return build_provenance_ledger(
        assess_market_environment(provider, ips.market_environment),
        state.portfolio,
        ips.pricing_inputs,
        as_of=program_trading_date(ips.program.timezone).date(),
        resolution=state.resolution,
    )


def _health(state: ProgramState, provider: MarketDataProvider) -> dict:
    app = create_app(
        state=state,
        market_data=provider,
        ips_config=state.ips_config,
    )
    return app.server.test_client().get("/health").get_json()


class TestTheLedgerGradesWhatPrices:
    """A fed input is fetched data; its typed twin is not graded at all."""

    def test_the_feed_series_are_fetched_entries(self, tmp_path: Path) -> None:
        state, provider = _state(tmp_path)

        ledger = _ledger(state, provider)

        fetched = {e.key for e in ledger.by_kind(InputKind.FETCHED)}
        assert fetched == {"market_data", "feed.chain", "feed.rate"}

    def test_a_typed_value_the_feed_hides_is_not_graded(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path)

        ledger = _ledger(state, provider)

        typed = {e.key for e in ledger.by_kind(InputKind.HAND_ENTERED)}
        assert typed == {"book.dividend_yield"}

    def test_a_healthy_feed_does_not_alarm(self, tmp_path: Path) -> None:
        state, provider = _state(tmp_path)

        assert assess_freshness(_ledger(state, provider)) is None

    def test_a_stale_cache_alarms_through_the_fetched_channel(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path, feed_source=Source.STALE)

        reason = assess_freshness(_ledger(state, provider))

        assert reason is not None
        assert "STALE" in reason

    def test_nothing_adopted_is_graded_exactly_as_before(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path, adopt=())

        ledger = _ledger(state, provider)

        keys = {e.key for e in ledger.entries}
        assert "book.spot" in keys
        assert "book.risk_free_rate" in keys
        assert not any(key.startswith("feed.") for key in keys)
        assert ledger.priced_at is None
        assert ledger.overrides == ()

    def test_an_input_that_is_overridden_is_graded_by_its_stamp(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path)
        state.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)

        ledger = _ledger(state, provider)

        spot = next(e for e in ledger.entries if e.key == "book.spot")
        assert spot.kind is InputKind.HAND_ENTERED
        assert spot.origin == "OVERRIDE"
        assert "your override" in spot.detail

    def test_an_unusable_quote_never_reads_fresh(self, tmp_path: Path) -> None:
        """A leg the chain cannot price falls back to a typed IV nobody
        confirmed: that is an unconfirmed input, and it alarms."""
        ips = adopting_ips(tmp_path)
        write_typed_book(tmp_path, ips)
        state_file = tmp_path / "program_state.json"
        data = json.loads(state_file.read_text())
        data["positions"][1]["strike_price"] = 4050.0  # not listed
        data["positions"][1]["volatility_as_of"] = None  # never confirmed
        state_file.write_text(json.dumps(data))
        provider = make_provider()

        state = load_state(tmp_path, ips, provider)
        ledger = _ledger(state, provider)

        fallback = [e for e in ledger.entries if e.origin == "FALLBACK"]
        assert len(fallback) == 1
        assert fallback[0].kind is InputKind.HAND_ENTERED
        assert fallback[0].freshness.value == "UNKNOWN"
        assert assess_freshness(ledger) is not None
        assert any("not listed" in note for note in ledger.input_notes)

    def test_a_dead_feed_folds_into_the_one_rule(self, tmp_path: Path) -> None:
        ips = adopting_ips(tmp_path)
        write_typed_book(tmp_path, ips)
        provider = make_provider(with_chain=False)
        provider.chains = {
            "SPX": fed_chain(
                leg_expiry().date(),
                STRIKES,
                program_day=days_from_today(-30),
            ),
        }

        state = load_state(tmp_path, ips, provider)
        ledger = _ledger(state, provider)

        assert ledger.market_data_quality is DataQuality.UNAVAILABLE
        assert ledger.oldest_series == "chain (pricing feed)"
        reason = assess_freshness(ledger)
        assert reason is not None
        assert "chain (pricing feed)" in reason


class TestTheBannerAndHeader:
    """The viewer is told prices are read once, and what a dead feed means."""

    def test_the_header_says_a_reload_does_not_update_prices(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path)

        text = _collect_text(build_chrome(_ledger(state, provider)))

        assert "Prices read at" in text
        assert "close" in text
        assert "only when it restarts" in text
        assert "refreshing this page does not update them" in text

    def test_no_feed_no_notice(self, tmp_path: Path) -> None:
        state, provider = _state(tmp_path, adopt=())

        text = _collect_text(build_chrome(_ledger(state, provider)))

        assert "Prices read at" not in text
        assert "refreshing this page" not in text

    def test_a_dead_feed_says_what_the_book_is_priced_on(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path)
        write_typed_book(tmp_path, ips)
        provider = make_provider()
        provider.chains = {
            "SPX": fed_chain(
                leg_expiry().date(),
                STRIKES,
                program_day=days_from_today(-30),
            ),
        }
        state = load_state(tmp_path, ips, provider)

        text = _collect_text(build_chrome(_ledger(state, provider)))

        assert "PRICING FEED DOWN" in text
        assert "feed down since" in text
        assert "pricing on your value from" in text

    def test_last_good_data_is_named(self, tmp_path: Path) -> None:
        state, provider = _state(tmp_path, feed_source=Source.STALE)

        text = _collect_text(build_chrome(_ledger(state, provider)))

        assert "PRICING ON THE LAST GOOD FEED DATA" in text


class TestOverridesAreListed:
    """An override lasts until cleared, so it must not be forgotten."""

    def test_the_panel_lists_each_with_age_and_the_feeds_figure(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path)
        state.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)
        leg = state.portfolio.positions[0].position_id
        state.set_input_override(
            OverrideKind.VOLATILITY,
            0.40,
            position_id=leg,
            confirm=True,
        )

        text = _collect_text(build_provenance_panel(_ledger(state, provider)))

        assert "2 active overrides" in text
        assert "4,900.00" in text
        assert "5,000.00" in text
        assert "40.00%" in text

    def test_no_override_no_list(self, tmp_path: Path) -> None:
        state, provider = _state(tmp_path)

        text = _collect_text(build_provenance_panel(_ledger(state, provider)))

        assert "active override" not in text

    def test_the_digest_lists_them_and_names_the_close(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path)
        state.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)

        lines = _input_lines(_ledger(state, provider))

        assert any("close from the pricing feed" in line for line in lines)
        assert any(
            "Override: Spot price is your 4,900.00" in line
            and "the feed says 5,000.00 today" in line
            for line in lines
        )

    def test_a_fallback_and_a_resolver_fault_are_in_the_digest_lines(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path, with_chain=False)

        lines = _input_lines(_ledger(state, provider))

        assert any("Spot price:" in line for line in lines)

    def test_the_digest_says_nothing_without_a_feed(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path, adopt=())

        assert _input_lines(_ledger(state, provider)) == ()


class TestHealth:
    """/health counts an adopted series, and says what the app priced on."""

    def test_a_healthy_fed_app_is_ok_and_reports_what_it_priced_on(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path)

        payload = _health(state, provider)

        assert payload["status"] == "ok", payload["freshness_reason"]
        resolution = payload["market_data"]["resolution"]
        assert resolution["adopting"] is True
        assert resolution["book"] == {
            "spot": "FETCHED",
            "risk_free_rate": "FETCHED",
            "dividend_yield": "ENTERED",
        }
        assert resolution["legs"] == {"FETCHED": 2}
        assert resolution["error"] is None
        assert resolution["newer_cached_session"] is None
        assert resolution["resolved_at"]
        assert payload["market_data"]["feed"]["chain"]["adopted"] is True
        assert payload["market_data"]["feed"]["rate"]["adopted"] is True

    def test_an_adopted_stale_chain_degrades_status(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path, feed_source=Source.STALE)

        payload = _health(state, provider)

        assert payload["status"] == "degraded"
        # Both feed series are stale; the reason names the older of them.
        assert "(pricing feed)" in payload["freshness_reason"]

    def test_a_chain_nothing_adopts_does_not_degrade_status(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path, adopt=("risk_free_rate",))
        provider.chains = {}

        payload = _health(state, provider)

        assert payload["market_data"]["feed"]["chain"]["adopted"] is False
        assert payload["market_data"]["feed"]["chain"]["quality"] == (
            "UNAVAILABLE"
        )
        assert payload["status"] == "ok", payload["freshness_reason"]

    def test_a_newer_cached_chain_is_reported_but_not_priced(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path)
        write_typed_book(tmp_path, ips)
        older = make_provider()
        older.chains = {
            "SPX": fed_chain(
                leg_expiry().date(),
                STRIKES,
                program_day=days_from_today(-2),
            ),
        }
        state = load_state(tmp_path, ips, older)
        priced_session = state.resolution.session_date
        newer = make_provider()

        payload = _health(state, newer)

        resolution = payload["market_data"]["resolution"]
        assert priced_session is not None
        assert resolution["session_date"] == priced_session.isoformat()
        assert resolution["newer_cached_session"] is not None
        assert resolution["newer_cached_session"] > priced_session.isoformat()
        assert state.resolution.session_date == priced_session

    def test_a_resolver_fault_degrades_status_and_is_named(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ips = adopting_ips(tmp_path)
        write_typed_book(tmp_path, ips)

        def boom(**_kwargs: object) -> object:
            raise RuntimeError("resolver fault")

        monkeypatch.setattr("deltadewa.state.resolve_pricing_inputs", boom)
        provider = make_provider()
        state = load_state(tmp_path, ips, provider)

        payload = _health(state, provider)

        assert payload["status"] == "degraded"
        assert payload["resolution_error"] == "resolver fault"
        assert payload["market_data"]["resolution"]["error"] == (
            "resolver fault"
        )
        note = _ledger(state, provider).input_notes[0]
        assert "could not be resolved" in note
        assert "resolver fault" in note


def test_the_ips_type_is_what_the_state_exposes(tmp_path: Path) -> None:
    """A guard on the fixtures: the loaded policy carries the adopt list."""
    state, _provider = _state(tmp_path)
    ips: IpsConfig | None = state.ips_config

    assert ips is not None
    assert ips.pricing_feed is not None
    assert set(ips.pricing_feed.adopt) == {
        "spot",
        "risk_free_rate",
        "volatility",
    }


class TestTheLedgerNamesTheSeriesItDates:
    """The stamp pairs a date with the series it belongs to."""

    def test_the_date_and_the_name_are_the_feeds_when_the_feed_is_worst(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path, feed_source=Source.STALE)

        ledger = _ledger(state, provider)

        assert ledger.oldest_series is not None
        assert ledger.oldest_series.endswith("(pricing feed)")
        named = ledger.oldest_series.split(" ")[0]
        series = next(u for u in state.resolution.series if u.name == named)
        assert ledger.market_data_as_of == series.as_of
        assert ledger.market_data_fetched_at == series.fetched_at

    def test_of_equally_bad_series_the_oldest_is_named(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path, feed_source=Source.STALE)
        older, newer = state.resolution.series
        series = (
            replace(older, name="rate", as_of=datetime(2026, 1, 5, tzinfo=UTC)),
            replace(
                newer, name="chain", as_of=datetime(2026, 3, 5, tzinfo=UTC)
            ),
        )
        resolution = replace(state.resolution, series=series)
        ips = state.ips_config
        assert ips is not None

        ledger = build_provenance_ledger(
            assess_market_environment(provider, ips.market_environment),
            state.portfolio,
            ips.pricing_inputs,
            as_of=program_trading_date(ips.program.timezone).date(),
            resolution=resolution,
        )

        assert ledger.oldest_series == "rate (pricing feed)"
        assert ledger.market_data_as_of == datetime(2026, 1, 5, tzinfo=UTC)

    def test_a_series_with_no_date_is_the_oldest(self, tmp_path: Path) -> None:
        state, provider = _state(tmp_path, feed_source=Source.STALE)
        dated, undated = state.resolution.series
        resolution = replace(
            state.resolution,
            series=(
                replace(dated, name="chain"),
                replace(undated, name="rate", as_of=None),
            ),
        )
        ips = state.ips_config
        assert ips is not None

        ledger = build_provenance_ledger(
            assess_market_environment(provider, ips.market_environment),
            state.portfolio,
            ips.pricing_inputs,
            as_of=program_trading_date(ips.program.timezone).date(),
            resolution=resolution,
        )

        assert ledger.oldest_series == "rate (pricing feed)"


class TestAResolverFaultReachesTheReader:
    """A fault in the resolving code is graded like a dead feed."""

    def _faulted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[ProgramState, MarketDataProvider]:
        ips = adopting_ips(tmp_path)
        write_typed_book(tmp_path, ips)

        def boom(**_kwargs: object) -> object:
            raise RuntimeError("resolver fault")

        monkeypatch.setattr("deltadewa.state.resolve_pricing_inputs", boom)
        provider = make_provider()
        return load_state(tmp_path, ips, provider), provider

    def test_the_banner_says_so(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state, provider = self._faulted(tmp_path, monkeypatch)

        text = _collect_text(build_chrome(_ledger(state, provider)))

        assert "PRICING INPUTS NOT RESOLVED" in text
        assert "resolver fault" in text

    def test_the_one_rule_alarms_on_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state, provider = self._faulted(tmp_path, monkeypatch)

        reason = assess_freshness(_ledger(state, provider))

        assert reason is not None
        assert "pricing inputs (pricing feed)" in reason

    def test_the_panel_does_not_say_all_inputs_are_current(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state, provider = self._faulted(tmp_path, monkeypatch)

        text = _collect_text(build_provenance_panel(_ledger(state, provider)))

        assert "All inputs current" not in text
        assert "could not be resolved" in text

    def test_the_digest_says_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state, provider = self._faulted(tmp_path, monkeypatch)

        lines = _input_lines(_ledger(state, provider))

        assert any("could not be resolved" in line for line in lines)


class TestPricedSession:
    """The digest names the close the book was priced on."""

    def test_a_spot_fed_from_the_index_close_still_names_its_session(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path, ("spot",))
        write_typed_book(tmp_path, ips)
        provider = make_provider(with_chain=False)
        provider.index_close = 4950.0
        state = load_state(tmp_path, ips, provider)

        ledger = _ledger(state, provider)

        assert state.resolution.spot.from_feed
        assert ledger.priced_session is not None
        assert any(
            "close from the pricing feed" in line
            for line in _input_lines(ledger)
        )


class TestANewerChainMustBeUsable:
    """ "Restart to price on it" is only said where a restart would."""

    def test_a_cached_chain_still_past_the_limit_is_not_newer(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path)
        write_typed_book(tmp_path, ips)
        stale = make_provider()
        stale.chains = {
            "SPX": fed_chain(
                leg_expiry().date(),
                STRIKES,
                program_day=days_from_today(-30),
            ),
        }
        state = load_state(tmp_path, ips, stale)
        assert state.resolution.session_date is None

        newer = newer_cached_session(stale, state.ips_config, state.resolution)

        assert newer is None

    def test_a_usable_chain_cached_after_a_dead_start_is_newer(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path)
        write_typed_book(tmp_path, ips)
        state = load_state(tmp_path, ips, make_provider(with_chain=False))
        assert state.resolution.session_date is None

        newer = newer_cached_session(
            make_provider(),
            state.ips_config,
            state.resolution,
        )

        assert newer is not None


class TestHealthIsNeverA500:
    """/health reports a fault in its own resolution block, not as a 500."""

    def test_a_resolution_that_raises_is_reported_in_the_payload(
        self,
        tmp_path: Path,
    ) -> None:
        from deltadewa.app.factory import _resolution_payload

        class _Broken:
            @property
            def resolution(self) -> object:
                raise RuntimeError("broken resolution")

        payload = _resolution_payload(
            _Broken(),  # type: ignore[arg-type]
            make_provider(),
            None,
        )

        assert payload == {"error": "RuntimeError: broken resolution"}

    def test_the_book_and_the_legs_are_reported_apart(
        self,
        tmp_path: Path,
    ) -> None:
        state, provider = _state(tmp_path)

        resolution = _health(state, provider)["market_data"]["resolution"]

        assert resolution["book"]["dividend_yield"] == "ENTERED"
        assert "dividend_yield" not in resolution["legs"]
        assert sum(resolution["legs"].values()) == len(
            state.portfolio.positions,
        )

    def test_the_chain_block_reports_its_session(self, tmp_path: Path) -> None:
        state, provider = _state(tmp_path)

        feed = _health(state, provider)["market_data"]["feed"]

        assert feed["chain"]["session_date"] is not None
        assert feed["rate"]["session_date"] is None


class TestACandidateSurfaceFailureIsLoud:
    """Candidates silently reverting to the flat vol would be a false green."""

    def test_it_is_in_health_the_notes_and_status(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("surface fault")

        monkeypatch.setattr("deltadewa.state.ChainVolSource", boom)
        state, provider = _state(tmp_path)

        payload = _health(state, provider)

        assert state.portfolio.vol_source is None
        assert state.resolution.surface_error == "RuntimeError: surface fault"
        assert payload["status"] == "degraded"
        assert payload["surface_error"] == "RuntimeError: surface fault"
        notes = _ledger(state, provider).input_notes
        assert any("flat volatility" in note for note in notes)
        assert any("surface fault" in note for note in notes)

    def test_held_legs_are_still_priced_on_the_feed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("surface fault")

        monkeypatch.setattr("deltadewa.state.ChainVolSource", boom)
        state, _provider = _state(tmp_path)

        assert state.resolution.error is None
        assert state.resolution.legs
        assert all(leg.from_feed for leg in state.resolution.legs.values())
