"""Tests for deltadewa.dashboard package __init__.py.

Verifies:
- All six new display classes are importable from the top-level package
- All names appear in __all__
- Importing the package does not trigger expensive side effects
"""

# ruff: noqa: S101 D101 D102 ANN001
# pylint: disable=missing-function-docstring, import-outside-toplevel, unused-import, missing-class-docstring

from __future__ import annotations

import time

import pytest

# ===========================================================================
# Importability
# ===========================================================================


class TestDashboardPackageImports:
    @pytest.mark.parametrize(
        "class_name",
        [
            "CarryDisplay",
            "ChangeLogDisplay",
            "MonteCarloStalenessWidget",
            "PositionAgingDisplay",
            "PositionDetailDisplay",
            "VolatilityProfileDisplay",
        ],
    )
    def test_class_importable_from_package(self, class_name: str) -> None:
        """Each class must be importable directly from deltadewa.dashboard."""
        import deltadewa.dashboard as dashboard

        cls = getattr(dashboard, class_name, None)
        assert (
            cls is not None
        ), f"deltadewa.dashboard.{class_name} is not accessible"

    def test_carry_display_importable(self) -> None:
        from deltadewa.dashboard import CarryDisplay  # noqa: F401

    def test_changelog_display_importable(self) -> None:
        from deltadewa.dashboard import ChangeLogDisplay  # noqa: F401

    def test_monte_carlo_staleness_widget_importable(self) -> None:
        from deltadewa.dashboard import MonteCarloStalenessWidget  # noqa: F401

    def test_position_aging_display_importable(self) -> None:
        from deltadewa.dashboard import PositionAgingDisplay  # noqa: F401

    def test_position_detail_display_importable(self) -> None:
        from deltadewa.dashboard import PositionDetailDisplay  # noqa: F401

    def test_volatility_profile_display_importable(self) -> None:
        from deltadewa.dashboard import VolatilityProfileDisplay  # noqa: F401


# ===========================================================================
# __all__ contract
# ===========================================================================


class TestDashboardDunderAll:
    _EXPECTED_NAMES = frozenset(
        [
            "CarryDisplay",
            "ChangeLogDisplay",
            "MonteCarloStalenessWidget",
            "PositionAgingDisplay",
            "PositionDetailDisplay",
            "VolatilityProfileDisplay",
        ],
    )

    def test_all_expected_names_in_dunder_all(self) -> None:
        import deltadewa.dashboard as dashboard

        all_set = set(getattr(dashboard, "__all__", []))
        missing = self._EXPECTED_NAMES - all_set
        assert not missing, f"Missing from __all__: {missing}"

    def test_no_unexpected_private_names_in_dunder_all(self) -> None:
        import deltadewa.dashboard as dashboard

        all_set = set(getattr(dashboard, "__all__", []))
        private = {name for name in all_set if name.startswith("_")}
        assert not private, f"Private names should not be in __all__: {private}"

    def test_dunder_all_contains_only_strings(self) -> None:
        import deltadewa.dashboard as dashboard

        all_list = getattr(dashboard, "__all__", [])
        for item in all_list:
            assert isinstance(item, str), f"Non-string in __all__: {item!r}"


# ===========================================================================
# Import side-effects
# ===========================================================================


class TestDashboardImportSideEffects:
    def test_import_completes_in_reasonable_time(self) -> None:
        """Importing the package must not trigger slow QuantLib engine builds.

        Threshold: 3 seconds. In practice a bare import with no pricing
        engines should complete in milliseconds.
        """
        import importlib
        import sys

        # Remove cached module so we can time a fresh import
        modules_to_remove = [
            k for k in sys.modules if k.startswith("deltadewa.dashboard")
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]

        start = time.monotonic()
        importlib.import_module("deltadewa.dashboard")
        elapsed = time.monotonic() - start

        assert elapsed < 3.0, (
            f"deltadewa.dashboard import took {elapsed:.2f}s — "
            "check for side effects (QuantLib, widget renders, "
            "filesystem access)"
        )

    def test_import_does_not_write_to_stdout(self, capsys) -> None:
        """Importing the package must not print anything."""
        import importlib
        import sys

        modules_to_remove = [
            k for k in sys.modules if k.startswith("deltadewa.dashboard")
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]

        importlib.import_module("deltadewa.dashboard")
        out, err = capsys.readouterr()
        assert out == "", f"Unexpected stdout on import: {out!r}"
        assert err == "", f"Unexpected stderr on import: {err!r}"
