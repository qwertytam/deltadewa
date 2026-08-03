"""Pins concrete providers' structural conformance to MarketDataProvider.

mypy only structurally checks a concrete provider against
``MarketDataProvider`` at a call site that actually annotates its parameter
that way — and ``tests/`` is excluded from mypy entirely (see
``pyproject.toml``). A provider could drift (rename an accessor, add a
bare-value accessor alongside the ``Observation`` one, change a return type)
without the gate ever catching it. This test calls every accessor on every
concrete provider and pins two invariants directly, rather than trusting a
docstring or a call site that happens to exercise the same methods. Same
structural-guard instinct as ``tests/test_crash_pricing_contract.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import requests

from deltadewa.marketdata import (
    CboeFredProvider,
    MarketDataProvider,
    Observation,
    StaticProvider,
)

if TYPE_CHECKING:
    from pathlib import Path

# Real CBOE price-only format (SPX, SKEW): DATE + symbol-name column.
_SPX_CSV = "DATE,SPX\n06/15/2026,5000.0\n"
_SKEW_CSV = "DATE,SKEW\n06/15/2026,120.0\n"

# Real CBOE VIX-family OHLCV format, shared by VIX9D/VIX/VIX3M/VIX6M/VIX1Y.
_VIX_FAMILY_CSV = "DATE,OPEN,HIGH,LOW,CLOSE\n06/15/2026,16.0,16.5,15.5,16.5\n"

# Real FRED format: "observation_date" as the date column.
_VIXCLS_CSV = "observation_date,VIXCLS\n2026-06-15,16.5\n"


def _mock_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.raise_for_status = MagicMock()
    return response


def _csv_for_url(url: str) -> str:
    """Route a CBOE/FRED URL to its canned CSV fixture by symbol suffix."""
    if "fredgraph.csv" in url:
        return _VIXCLS_CSV
    if url.endswith("SPX_History.csv"):
        return _SPX_CSV
    if url.endswith("SKEW_History.csv"):
        return _SKEW_CSV
    return _VIX_FAMILY_CSV


def _fake_get(url: str, timeout: float | None = None) -> MagicMock:
    _ = timeout
    return _mock_response(_csv_for_url(url))


def _cboe_fred_provider(tmp_path: Path) -> CboeFredProvider:
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = _fake_get
    return CboeFredProvider(cache_dir=tmp_path, session=session)


def _static_provider() -> StaticProvider:
    return StaticProvider(
        spot_prices={"SPX": 5000.0},
        vix_history=[10.0, 11.0, 12.0],
    )


@pytest.fixture(params=["cboe_fred", "static"])
def provider(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> MarketDataProvider:
    """A concrete provider of each kind, wired to succeed on every call."""
    if request.param == "static":
        return _static_provider()
    return _cboe_fred_provider(tmp_path)


_ACCESSORS: list[tuple[str, tuple[object, ...]]] = [
    ("get_spot", ("SPX",)),
    ("get_vix", ()),
    ("get_vix_history", ()),
    ("get_vix_term_structure", ()),
    ("get_skew_index", ()),
    ("get_skew_percentile", ()),
]


class TestProviderProtocolConformance:
    """Every concrete provider structurally satisfies MarketDataProvider."""

    def test_provider_is_a_market_data_provider(
        self,
        provider: MarketDataProvider,
    ) -> None:
        """isinstance() against the @runtime_checkable Protocol holds."""
        assert isinstance(provider, MarketDataProvider)

    @pytest.mark.parametrize(("accessor", "args"), _ACCESSORS)
    def test_accessor_returns_an_observation(
        self,
        provider: MarketDataProvider,
        accessor: str,
        args: tuple[object, ...],
    ) -> None:
        """Every accessor wraps its value in an Observation, never bare.

        isinstance() against the Protocol only checks member presence, not
        return types — a method that started returning a bare float would
        still pass that check. Actually invoking each accessor is what
        catches it.
        """
        result = getattr(provider, accessor)(*args)

        assert isinstance(result, Observation)

    def test_is_read_only_is_a_bool(
        self,
        provider: MarketDataProvider,
    ) -> None:
        """The read-only capability flag is present and boolean-typed."""
        assert isinstance(provider.is_read_only, bool)
