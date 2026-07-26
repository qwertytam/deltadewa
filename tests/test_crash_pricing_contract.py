"""Repo-wide structural contract for crash-pricing inputs (M1.4 → M1.9).

One rule, enforced across the whole package rather than a hand-listed set of
functions: **a crash-pricing input may never carry a default**.

The rule exists because every regression in this area has been an instance of
the same class, and each one was invisible until someone changed policy:

* **M1.4/M1.5** — ``crash_vol_shock`` defaulted, so a surface that omitted it
  repriced *spot-only* and under-reported convexity.
* **M1.7** — ``skew_steepening`` defaulted to ``0.0``, so a surface that
  omitted it repriced a *flat bump* instead of the skew-aware shock.
* **M1.8** — ``skew_reference_delta`` defaulted to ``0.10`` on the pricing
  primitive, so the book gauges silently ignored the IPS anchor while the
  sizing workbench honoured it. No observable difference at the shipped
  ``0.10``; a book-vs-candidate divergence the moment anyone tuned it.
* **M1.9** — ``NetHedgeSummary`` defaulted all three, and the notebooks passed
  only the first, so the summary ladder priced flat against a skew-aware gauge.

Each was fixed by making that one input required. This test generalises the
fix: any *new* crash-pricing entry point that reintroduces a default fails
here, whether or not anyone remembers the history. The defaults that
legitimately exist live on :class:`~deltadewa.ips_config.IpsConvexity` (policy
declaring its own fallbacks) and are dataclass *fields*, not function
parameters, so they are out of scope by construction.

Scans the AST rather than importing, so a module that is never imported by the
rest of the suite is still covered.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PACKAGE_ROOT = Path(__file__).parent.parent / "deltadewa"

# Parameter names that carry a crash-pricing input. Deliberately includes the
# historical spellings (``vol_shock`` on the primitive, ``crash_pct`` on the
# candidate path) so a revert to an older signature is caught too, and
# ``anchor_delta`` — the wing solver's internal name for the same quantity.
_PRICING_PARAMS = frozenset(
    {
        "anchor_delta",
        "crash_move",
        "crash_pct",
        "crash_scenario_pct",
        "crash_vol_shock",
        "skew_reference_delta",
        "skew_steepening",
        "vol_shock",
    },
)

# The value object the four inputs travel as. An optional/defaulted one would
# reopen the same hole at the object level.
_SHOCK_PARAM = "shock"


def _iter_function_defs() -> list[tuple[Path, ast.FunctionDef]]:
    """Every function and method defined anywhere in the package.

    Returns:
        ``(path, node)`` pairs for all ``def`` and ``async def`` statements.

    """
    found: list[tuple[Path, ast.FunctionDef]] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found.extend(
            (path, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        )
    return found


def _defaulted_param_names(node: ast.FunctionDef) -> set[str]:
    """Names of parameters that declare a default value.

    Covers positional-or-keyword parameters (whose defaults right-align onto
    the tail of the list) and keyword-only parameters (which pair positionally
    with ``kw_defaults``, using ``None`` for "no default").

    Args:
        node: The function definition to inspect.

    Returns:
        The subset of parameter names carrying a default.

    """
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaulted = {
        a.arg for a in positional[len(positional) - len(args.defaults) :]
    }
    defaulted |= {
        a.arg
        for a, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
        if default is not None
    }
    return defaulted


def _offenders(param_names: frozenset[str] | set[str]) -> list[str]:
    """Locations where a parameter in *param_names* carries a default.

    Args:
        param_names: Parameter names that must never be defaulted.

    Returns:
        Human-readable ``path:line function(param)`` strings, one per offence.

    """
    hits: list[str] = []
    for path, node in _iter_function_defs():
        for name in sorted(_defaulted_param_names(node) & set(param_names)):
            rel = path.relative_to(_PACKAGE_ROOT.parent)
            hits.append(f"{rel}:{node.lineno} {node.name}({name}=...)")
    return hits


class TestCrashPricingInputsAreNeverDefaulted:
    """No crash-pricing input may default, anywhere in the package."""

    def test_no_pricing_scalar_carries_a_default(self) -> None:
        """The generalised M1.4/M1.5/M1.7/M1.8 guard.

        A defaulted pricing scalar lets a caller state part of the crash basis
        and inherit the rest — which is how every divergence in this area
        began. Pass an explicit value (``0.0`` for a genuinely spot-only
        crash); never let omission decide.
        """
        offenders = _offenders(_PRICING_PARAMS)

        assert not offenders, (
            "crash-pricing inputs must never default; found:\n  "
            + "\n  ".join(offenders)
        )

    def test_no_crash_shock_parameter_carries_a_default(self) -> None:
        """The same rule at the object level (M1.9).

        ``CrashShock`` bundles the four inputs, so a defaulted — or optional —
        ``shock`` would reopen the identical hole one level up.
        """
        offenders = _offenders({_SHOCK_PARAM})

        assert not offenders, (
            "`shock` must never default; found:\n  " + "\n  ".join(offenders)
        )

    def test_crash_shock_itself_declares_no_field_defaults(self) -> None:
        """The bundle cannot be half-constructed either.

        Checked on the class rather than the AST because the fields are what a
        caller actually constructs.
        """
        import dataclasses

        from deltadewa.analysis.crash_repricing import CrashShock

        for field in dataclasses.fields(CrashShock):
            assert field.default is dataclasses.MISSING, field.name
            assert field.default_factory is dataclasses.MISSING, field.name


class TestGuardActuallyScansThePackage:
    """Meta-guards — a repo-wide scan must not pass by finding nothing.

    An AST walk that silently matches zero functions would make every
    assertion above vacuously true, which is the one way this file could fail
    at its job while staying green.
    """

    def test_scan_reaches_a_realistic_number_of_functions(self) -> None:
        """The walk finds the package, not an empty directory."""
        assert len(_iter_function_defs()) > 200

    @pytest.mark.parametrize(
        "module_name",
        [
            "crash_repricing.py",
            "crash_payoff.py",
            "candidate.py",
            "health.py",
            "sizing.py",
            "strike_ladder.py",
        ],
    )
    def test_scan_covers_each_crash_pricing_module(
        self,
        module_name: str,
    ) -> None:
        """Every module that reprices a crash is actually visited."""
        visited = {path.name for path, _ in _iter_function_defs()}

        assert module_name in visited

    def test_detector_flags_a_default_when_one_exists(self) -> None:
        """The detector reports defaults — it is not stuck returning empty.

        Without this, a bug in :func:`_defaulted_param_names` would silently
        disarm every assertion in this file.
        """
        tree = ast.parse(
            "def f(a, b=1, *, c, d=2, e=None): ...",
        )
        node = tree.body[0]
        assert isinstance(node, ast.FunctionDef)

        assert _defaulted_param_names(node) == {"b", "d", "e"}

    def test_detector_reports_no_default_when_none_exists(self) -> None:
        """The mirror case: required parameters are not miscounted."""
        tree = ast.parse("def f(a, *, b, c): ...")
        node = tree.body[0]
        assert isinstance(node, ast.FunctionDef)

        assert _defaulted_param_names(node) == set()
