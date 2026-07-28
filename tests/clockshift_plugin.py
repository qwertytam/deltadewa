"""Pytest plugin: move the wall clock by N days for the whole suite.

A determinism probe, not a test. Any test whose asserted values depend on
wall-clock "now" fails under a shift; tests that pin their dates do not. Run it
against the full suite — the point is to catch the drift nobody knew about.

Why it exists: this probe found the ``TestBuildPutValuation`` time bomb in PR
**#205** — four tests pricing a hardcoded ``2026-10-01`` expiry against a
``now()`` valuation date, which would have started failing in October 2026 as
mystery breakage on an unrelated branch. Fixed in ``962010a``.

Not wired into the per-commit gate: it runs the suite once per shift and swaps
a type that C extensions hold pointers to. It runs nightly against ``main``
(``.github/workflows/clockshift.yml``) and on demand::

    make test-clockshift                    # the +0/+90/+1000/+3000 matrix
    CLOCK_SHIFT_DAYS=400 poetry run pytest -q -p tests.clockshift_plugin

``tests/test_clockshift_canary.py`` is this plugin's self-test: it fails if the
shift does not reach library code, so a green matrix means something.

The default shift is 0, deliberately: a bare ``-p`` load is the control run,
and the plugin and the canary read the same environment variable with the same
default, so they can never disagree about how far the clock moved.
"""

from __future__ import annotations

import datetime as _datetime
import os
import platform
from typing import Any

import pytest

SHIFT = _datetime.timedelta(days=int(os.environ.get("CLOCK_SHIFT_DAYS", "0")))

# The applied shift is measured from two now() reads microseconds apart, so
# the observed offset is SHIFT plus jitter. Anything past a second is not
# jitter, it is the probe not doing what it was asked.
_SHIFT_TOLERANCE = _datetime.timedelta(seconds=1)

_real_datetime = _datetime.datetime
_real_date = _datetime.date


class ShiftedDatetime(_real_datetime):
    """``datetime.datetime`` with ``now()``/``today()`` moved by ``SHIFT``."""

    @classmethod
    def now(cls, tz: Any = None) -> Any:
        """Return the real current time plus ``SHIFT``."""
        return _real_datetime.now(tz) + SHIFT

    @classmethod
    def today(cls) -> Any:
        """Return the real current local time plus ``SHIFT``."""
        return _real_datetime.today() + SHIFT

    @classmethod
    def utcnow(cls) -> Any:
        """Return the real UTC time plus ``SHIFT``."""
        return _real_datetime.now(_datetime.UTC).replace(tzinfo=None) + SHIFT


class ShiftedDate(_real_date):
    """``datetime.date`` with ``today()`` moved by ``SHIFT``."""

    @classmethod
    def today(cls) -> Any:
        """Return the real current date plus ``SHIFT``."""
        return _real_date.today() + SHIFT


# ---------------------------------------------------------------------------
# DO NOT REMOVE — these imports must run BEFORE the type swap below.
#
# pandas caches a pointer to datetime.datetime in its C layer at import time.
# If it imports *after* the swap, the interpreter segfaults inside
# pandas/_libs/tslibs/nattype's __pyx_tp_traverse — no traceback, no test
# output, just a dead process. Importing the native extensions here means they
# capture the real type (which is what they want) and only later pure-Python
# imports — deltadewa and the test modules — bind the shifted one.
#
# These look like stray misplaced imports. They are load-bearing. numpy and
# QuantLib are included for the same reason: they are C extensions loaded by
# the suite, and this is the one place their import order can be guaranteed.
# ---------------------------------------------------------------------------
import numpy  # ruff: ignore[module-import-not-at-top-of-file, unused-import]
import pandas  # ruff: ignore[module-import-not-at-top-of-file, unused-import]
import QuantLib  # ruff: ignore[module-import-not-at-top-of-file, unused-import]

# ---------------------------------------------------------------------------
# DO NOT REMOVE the unconditional patch — it must happen at SHIFT == 0 too.
#
# A control run that skipped the substitution would not be a control. What it
# rules out is concrete: ShiftedDatetime subclasses the *real* datetime, so
# once datetime.date is patched, isinstance(a_datetime, datetime.date) is
# False — a shifted-run failure could be that type-identity breakage rather
# than real date drift. The +0 control is what tells the two apart, and it can
# only do that if it exercises the same substitution.
#
# Guarding this with `if SHIFT:` would make every shifted failure ambiguous.
# ---------------------------------------------------------------------------
_datetime.datetime = ShiftedDatetime  # type: ignore[misc]
_datetime.date = ShiftedDate  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DO NOT REMOVE the `-p` loading contract: this module must be imported as a
# pytest plugin, never converted into a conftest fixture or an autouse patch.
#
# `-p` imports it before conftest and before any test or deltadewa module, so
# module-level constants evaluated at import — `_MATURITY = now() + 180d` and
# friends — bind the shifted clock. Patching after collection instead shifts
# the library while leaving the test module that builds its inputs unshifted,
# which reports failures that are artifacts of the probe rather than real
# drift. That mistake once produced a confident report of 23 broken tests when
# only 4 were real.
# ---------------------------------------------------------------------------


def _applied_shift() -> _datetime.timedelta:
    """Measure the offset actually in force, not the one requested.

    Looks ``datetime.datetime`` up through the module attribute — the same
    lookup library code makes — so what comes back is what the swap did,
    rather than ``CLOCK_SHIFT_DAYS`` read back to us.
    """
    before = _real_datetime.now(_datetime.UTC)
    return _datetime.datetime.now(_datetime.UTC) - before


# ---------------------------------------------------------------------------
# DO NOT convert this back to `pytest_report_header`.
#
# That was the original mechanism, and every caller runs `pytest -q`: the
# nightly matrix, the per-PR advisory job via the Makefile, and every local
# `make test-clockshift`. `-q` suppresses the report header, so the shift
# never reached a log and the CI step name was the only record of it —
# a label, unverified against what the plugin actually did. A line written
# through the terminal reporter is not verbosity-gated, and putting it here
# rather than in the callers means no future `-q` can silently undo it.
#
# `trylast` is load-bearing too. `-p` plugins register after the builtins and
# `pytest_configure` is called last-registered-first, so at default hook order
# this fires *before* the terminal plugin creates the reporter and
# `get_plugin("terminalreporter")` returns None.
# ---------------------------------------------------------------------------
@pytest.hookimpl(trylast=True)
def pytest_configure(config: Any) -> None:
    """Announce the applied shift, and abort if it is not the requested one.

    Turns a silent non-propagation — a lost ``-p``, a rename, an import-order
    regression — into an immediate error rather than a green suite that
    proves nothing. This is a fast fail with a clear message, not a new
    claim: ``tests/test_clockshift_canary.py`` remains the check that the
    shift reaches *library* code.
    """
    applied = _applied_shift()
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    line = (
        f"clockshift: requested {SHIFT.days:+d} days, "
        f"applied {round(applied.total_seconds() / 86400):+d} days "
        f"(Python {platform.python_version()})"
    )
    if reporter is None:
        print(line)
    else:
        reporter.write_line(line)

    substituted = (
        _datetime.datetime is ShiftedDatetime and _datetime.date is ShiftedDate
    )
    if not substituted:
        raise pytest.UsageError(
            "clock-shift probe: the datetime substitution is not live. "
            "Every leg, including the +0 control, must run with it — see "
            "the DO NOT REMOVE note on the unconditional patch.",
        )
    if abs(applied - SHIFT) > _SHIFT_TOLERANCE:
        raise pytest.UsageError(
            f"clock-shift probe applied no usable shift: requested "
            f"{SHIFT.days:+d} days, measured {applied}. The suite would "
            f"otherwise have reported a meaningless green.",
        )
