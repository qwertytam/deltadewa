"""Guard: the vol/skew bands have exactly one source (Mo2).

Changing a band in one place (the IPS ``market_environment`` policy, backed by
the ``ips_config`` ``DEFAULT_*`` constants) moves every consumer, and no
consumer module re-hardcodes a band literal.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from deltadewa.ips_config import (
    DEFAULT_SKEW_HIGH_PCTILE,
    DEFAULT_SKEW_LOW_PCTILE,
    DEFAULT_VOL_REGIME_HIGH,
    DEFAULT_VOL_REGIME_LOW,
    IpsMarketEnvironment,
)

# Load the modules via importlib: ``deltadewa.analysis.decision_matrix`` is
# shadowed by the re-exported ``decision_matrix`` function in the package
# namespace, so attribute-style ``import ... as`` would bind the function.
decision_matrix = importlib.import_module(
    "deltadewa.analysis.decision_matrix",
)
health = importlib.import_module("deltadewa.analysis.health")
market_environment = importlib.import_module(
    "deltadewa.analysis.market_environment",
)
health_dashboard = importlib.import_module(
    "deltadewa.widgets.health_dashboard",
)

# The old duplicate band pairs, in the forms they appeared as source literals.
# Pair forms (not bare values) so the crash-vol-shock docstring's lone ``0.15``
# example is not a false positive.
_BANNED_PAIRS = (
    "0.15, 0.35",
    "(0.15, 0.35)",
    "0.30, 0.70",
    "(0.30, 0.70)",
    "0.15-0.35",
)
_MODULES = (health, market_environment, decision_matrix, health_dashboard)


def test_no_duplicate_band_pair_literal_survives() -> None:
    """No consumer module carries a duplicated vol/skew band literal."""
    for module in _MODULES:
        src = inspect.getsource(module)
        for pair in _BANNED_PAIRS:
            assert pair not in src, (
                f"band literal {pair!r} still present in {module.__name__}"
            )


def test_health_module_no_longer_defines_band_constants() -> None:
    """The old health.py band constants are gone (single source is the IPS)."""
    assert not hasattr(health, "VOL_REGIME_LOW")
    assert not hasattr(health, "VOL_REGIME_HIGH")


def test_classify_vix_regime_defaults_from_ips_source() -> None:
    """classify_vix_regime's band defaults resolve from the IPS source."""
    sig = inspect.signature(market_environment.classify_vix_regime)
    assert sig.parameters["low"].default == DEFAULT_VOL_REGIME_LOW
    assert sig.parameters["high"].default == DEFAULT_VOL_REGIME_HIGH


def test_entry_timing_skew_defaults_from_ips_source() -> None:
    """entry_timing_tree skew defaults are the IPS percentiles, as fractions."""
    sig = inspect.signature(decision_matrix.entry_timing_tree)
    assert sig.parameters["skew_low"].default == pytest.approx(
        DEFAULT_SKEW_LOW_PCTILE / 100.0, rel=1e-4
    )
    assert sig.parameters["skew_high"].default == pytest.approx(
        DEFAULT_SKEW_HIGH_PCTILE / 100.0, rel=1e-4
    )


def test_ips_market_environment_defaults_match_source() -> None:
    """IpsMarketEnvironment surfaces the DEFAULT_* single source unchanged."""
    env = IpsMarketEnvironment()
    assert env.vol_regime_low == DEFAULT_VOL_REGIME_LOW
    assert env.vol_regime_high == DEFAULT_VOL_REGIME_HIGH
    assert env.skew_low_pctile == DEFAULT_SKEW_LOW_PCTILE
    assert env.skew_high_pctile == DEFAULT_SKEW_HIGH_PCTILE
