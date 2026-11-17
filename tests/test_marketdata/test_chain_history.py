"""Tests for deltadewa.marketdata.chain_history: the daily chain record."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from deltadewa.constants import OptionType
from deltadewa.marketdata.chain import parse_cboe_chain
from deltadewa.marketdata.chain_history import (
    HeldContract,
    append_daily_record,
    market_quotes,
    read_held_contracts,
)
from tests.chain_builders import (
    BOTH_ROOTS,
    DECEMBER,
    JUNE_THURSDAY,
    SESSION,
    TIMESTAMP,
    WEEKLY_ONLY,
    payload,
    priced_contract,
    standard_chain,
)

_HELD = HeldContract(DECEMBER, OptionType.PUT, 4000.0)


@pytest.fixture(name="snapshot")
def _snapshot():
    return parse_cboe_chain(standard_chain())


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestMarketQuotes:
    """The fixed market points."""

    def test_only_standard_expiries_inside_the_window(self, snapshot) -> None:
        """The weekly-only date is not a standard expiry, so it is not kept."""
        expiries = {quote.expiry for quote in market_quotes(snapshot)}

        assert expiries == {JUNE_THURSDAY, DECEMBER, BOTH_ROOTS}
        assert WEEKLY_ONLY not in expiries

    def test_points_are_distinct(self, snapshot) -> None:
        """A coarse grid can land two percentages on one strike: kept once."""
        quotes = market_quotes(snapshot)
        keys = [(q.expiry, q.option_type, q.strike) for q in quotes]

        assert len(keys) == len(set(keys))

    def test_puts_at_the_fixed_distances_out_of_the_money(
        self,
        snapshot,
    ) -> None:
        """5000 spot: 20/30/40/50% OTM are 4000/3500/3000/2500."""
        strikes = {
            q.strike
            for q in market_quotes(snapshot)
            if q.expiry == DECEMBER and q.option_type is OptionType.PUT
        }

        assert {4000.0, 3500.0, 3000.0, 2500.0} <= strikes
        assert 5000.0 in strikes

    def test_a_call_is_taken_at_the_money_when_listed(self) -> None:
        """The at-the-money call joins the puts where calls are listed."""
        contracts = [
            priced_contract("SPX", DECEMBER, OptionType.PUT, 5000.0),
            priced_contract("SPX", DECEMBER, OptionType.CALL, 5000.0),
        ]
        quotes = market_quotes(parse_cboe_chain(payload(contracts)))

        assert {q.option_type for q in quotes} == {
            OptionType.PUT,
            OptionType.CALL,
        }

    def test_the_count_is_bounded(self, snapshot) -> None:
        """Roughly a handful per expiry, never the whole chain."""
        assert 3 <= len(market_quotes(snapshot)) <= 3 * 8


class TestAppendDailyRecord:
    """One session's rows, idempotently."""

    def test_writes_held_and_market_rows_to_a_yearly_file(
        self,
        snapshot,
        tmp_path: Path,
    ) -> None:
        written = append_daily_record(snapshot, [_HELD], tmp_path)

        rows = _rows(tmp_path / "SPX-2026.jsonl")
        assert written == len(rows)
        assert {row["kind"] for row in rows} == {"held", "market"}
        assert {row["session"] for row in rows} == {SESSION.isoformat()}
        held = [row for row in rows if row["kind"] == "held"]
        assert len(held) == 1
        assert held[0]["strike"] == pytest.approx(4000.0)
        assert held[0]["underlying"] == pytest.approx(5000.0)
        assert held[0]["bid"] > 0
        assert held[0]["vendor_iv"] is not None

    def test_a_second_run_for_the_same_session_writes_nothing(
        self,
        snapshot,
        tmp_path: Path,
    ) -> None:
        append_daily_record(snapshot, [_HELD], tmp_path)
        before = (tmp_path / "SPX-2026.jsonl").read_text()

        assert append_daily_record(snapshot, [_HELD], tmp_path) == 0
        assert (tmp_path / "SPX-2026.jsonl").read_text() == before

    def test_a_new_session_appends(self, snapshot, tmp_path: Path) -> None:
        append_daily_record(snapshot, [_HELD], tmp_path)
        next_day = parse_cboe_chain(
            {**standard_chain(), "timestamp": "2026-11-18 01:33:27"},
        )
        assert next_day.session_date == date(2026, 11, 17)

        written = append_daily_record(next_day, [_HELD], tmp_path)

        sessions = [r["session"] for r in _rows(tmp_path / "SPX-2026.jsonl")]
        assert written > 0
        assert sessions[-1] == "2026-11-17"
        assert SESSION.isoformat() in sessions

    def test_no_book_still_records_the_market_points(
        self,
        snapshot,
        tmp_path: Path,
    ) -> None:
        append_daily_record(snapshot, None, tmp_path)

        rows = _rows(tmp_path / "SPX-2026.jsonl")
        assert rows
        assert {row["kind"] for row in rows} == {"market"}

    def test_a_held_option_the_chain_does_not_list_is_skipped(
        self,
        snapshot,
        tmp_path: Path,
    ) -> None:
        unlisted = HeldContract(DECEMBER, OptionType.PUT, 4050.0)

        append_daily_record(snapshot, [unlisted, _HELD], tmp_path)

        held = [
            r for r in _rows(tmp_path / "SPX-2026.jsonl") if r["kind"] == "held"
        ]
        assert [row["strike"] for row in held] == [4000.0]

    def test_a_torn_last_line_does_not_defeat_idempotency(
        self,
        snapshot,
        tmp_path: Path,
    ) -> None:
        """A partial final row is skipped; the last readable row decides."""
        append_daily_record(snapshot, None, tmp_path)
        path = tmp_path / "SPX-2026.jsonl"
        path.write_text(path.read_text() + '{"session": "2026-11-1')

        assert append_daily_record(snapshot, None, tmp_path) == 0

    def test_the_file_is_named_for_the_sessions_year(
        self,
        tmp_path: Path,
    ) -> None:
        january = parse_cboe_chain(
            {**standard_chain(), "timestamp": "2027-01-05 01:33:27"},
        )

        append_daily_record(january, None, tmp_path)

        assert (tmp_path / "SPX-2027.jsonl").exists()

    def test_the_history_directory_is_created(
        self,
        snapshot,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "exports" / "chain-history"

        append_daily_record(snapshot, None, target)

        assert (target / "SPX-2026.jsonl").exists()

    def test_the_timestamp_in_the_default_chain_is_the_session_above(
        self,
        snapshot,
    ) -> None:
        """Guards the builder: the fixtures describe the 2026-11-16 close."""
        assert TIMESTAMP.startswith("2026-11-17")
        assert snapshot.session_date == SESSION


class TestReadHeldContracts:
    """The book is read for its contracts only, read-only."""

    def _book(self, tmp_path: Path, positions: list[dict]) -> Path:
        path = tmp_path / "program_state.json"
        path.write_text(json.dumps({"positions": positions}))
        return path

    def test_reads_type_strike_and_expiry_in_book_order(
        self,
        tmp_path: Path,
    ) -> None:
        path = self._book(
            tmp_path,
            [
                {
                    "option_type": "PUT",
                    "strike_price": 4000.0,
                    "maturity_date": "2027-12-17T00:00:00-05:00",
                },
                {
                    "option_type": "PUT",
                    "strike_price": 4600.0,
                    "maturity_date": "2027-06-17T00:00:00",
                },
            ],
        )

        assert read_held_contracts(path) == (
            HeldContract(DECEMBER, OptionType.PUT, 4000.0),
            HeldContract(JUNE_THURSDAY, OptionType.PUT, 4600.0),
        )

    def test_a_contract_held_in_two_lots_is_one(self, tmp_path: Path) -> None:
        lot = {
            "option_type": "PUT",
            "strike_price": 4000.0,
            "maturity_date": "2027-12-17T00:00:00",
        }

        assert len(read_held_contracts(self._book(tmp_path, [lot, lot]))) == 1

    def test_a_missing_file_raises_os_error(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            read_held_contracts(tmp_path / "program_state.json")

    @pytest.mark.parametrize(
        "text",
        ["not json", "{}", '{"positions": [{"option_type": "PUT"}]}'],
    )
    def test_an_unexpected_shape_raises(
        self,
        tmp_path: Path,
        text: str,
    ) -> None:
        path = tmp_path / "program_state.json"
        path.write_text(text)

        with pytest.raises((ValueError, KeyError, TypeError)):
            read_held_contracts(path)
