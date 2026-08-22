"""Tests for deltadewa.app.wsgi — provider construction wiring."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from deltadewa import state as state_module
from deltadewa.analysis.candidate import build_put_valuation
from deltadewa.app import wsgi as wsgi_module
from deltadewa.constants import ExerciseStyle
from deltadewa.ips_config import load_ips_config
from deltadewa.marketdata import default_cache_dir


class TestBuild:
    """_build() must wire the read-only provider correctly (M2.6)."""

    def test_provider_is_read_only_with_shared_cache_and_policy_ttl(
        self,
        tmp_path: Path,
    ) -> None:
        """cache_dir/ttl come from the shared resolver, not bare defaults.

        Patches ``load_ips_config`` at the ``state`` call site (rather than
        relying on ``_build()``'s real default ``config/ips.yaml``, which is
        gitignored and not guaranteed to exist on every checkout — #245) with
        an ``IpsConfig`` loaded from a throwaway fixture file, so ``_build()``
        is exercised end-to-end without depending on any file outside the
        test.
        """
        example_ips_yaml = (
            Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
        )
        fixture_ips_path = tmp_path / "ips.yaml"
        fixture_ips_path.write_text(
            example_ips_yaml.read_text(encoding="utf-8").replace(
                "data_ttl_minutes: 1440",
                "data_ttl_minutes: 2160",
            ),
            encoding="utf-8",
        )
        fixture_ips_config = load_ips_config(fixture_ips_path)

        with (
            patch.object(wsgi_module, "CboeFredProvider") as mock_provider,
            patch.object(
                state_module,
                "load_ips_config",
                return_value=fixture_ips_config,
            ),
        ):
            wsgi_module._build()

        mock_provider.assert_called_once()
        _, kwargs = mock_provider.call_args
        assert kwargs["read_only"] is True
        assert kwargs["cache_dir"] == default_cache_dir()
        # The fixture IPS config sets data_ttl_minutes to 2160 (36h) — not
        # the provider's own 15-minute constructor default.
        assert kwargs["ttl"] == timedelta(minutes=2160)

    def test_default_exercise_style_wired_from_ips_at_boot(
        self,
        tmp_path: Path,
    ) -> None:
        """#295: the real gunicorn/dev entrypoint wires pricing.exercise_style.

        Calls ``_build()`` itself — the exact function ``server()`` and
        ``dash_app()`` call — rather than constructing a portfolio and
        setting the style directly, which is the blind spot that let #295
        ship with a fully green suite. Also proves the dead surface is
        alive again: ``build_put_valuation`` (what the sizing workbench and
        strike ladder call) no longer raises for the boot-produced
        portfolio.
        """
        example_ips_yaml = (
            Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
        )
        fixture_ips_path = tmp_path / "ips.yaml"
        fixture_ips_path.write_text(
            example_ips_yaml.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        fixture_ips_config = load_ips_config(fixture_ips_path)

        with (
            patch.object(wsgi_module, "CboeFredProvider"),
            patch.object(
                state_module,
                "load_ips_config",
                return_value=fixture_ips_config,
            ),
        ):
            app = wsgi_module._build()

        portfolio = app.program_state.portfolio
        assert portfolio.default_exercise_style is ExerciseStyle.EUROPEAN

        # The dead surface #295 named: candidate pricing used by the
        # sizing workbench (analysis/sizing.py) and strike ladder
        # (analysis/strike_ladder.py) both go through this helper, and it
        # raises ValueError precisely when default_exercise_style is None.
        valuation = build_put_valuation(
            portfolio.spot_price,
            portfolio.spot_price * 0.9,
            portfolio.valuation_date + timedelta(days=30),
            0.2,
            portfolio,
        )
        assert valuation.exercise_style is ExerciseStyle.EUROPEAN
