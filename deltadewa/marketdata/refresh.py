"""CLI: refresh the on-disk market-data cache the read-only app reads.

Usage::

    python -m deltadewa.marketdata.refresh [--symbol SPX]

The only process in the deployment permitted to make a live market-data
fetch — the Dash app is constructed with ``read_only=True``
(``deltadewa.app.wsgi``), and ``create_app`` enforces that structurally
(``FetchCapableProviderError``). Meant to run on a cron, daily, **seven
days a week**: CBOE/FRED are closed on weekends, so a weekend run simply
re-observes Friday's close and refreshes ``fetched_at`` — a five-day
schedule would instead leave a 72-hour Friday-to-Monday gap that the TTL
would have to absorb, which is what turns a cache-warming cron into a
policy problem.

This job always attempts a live fetch for every series, regardless of the
on-disk cache's freshness — the market-data TTL (``ips.yaml``'s
``market_environment.data_ttl_minutes``, resolved via ``resolve_data_ttl``)
governs when the *read-only* Dash app should treat a cached value as
stale, not when this writer should bother re-observing. A within-TTL
cache hit here must never stand in for the job actually running: on a
daily cron against a multi-hour TTL, that would mean this job silently
no-ops every other run, still logging success and still pinging the
heartbeat, while ``fetched_at`` stops advancing behind a green exit code.
The provider is constructed with ``force_fetch=True`` for exactly this
reason (see ``CboeFredProvider``'s constructor docstring).

Each series is fetched independently: one failure never aborts the run,
and a failed series' previous cache entry is left untouched — the disk
cache only writes on a successful fetch, so there is nothing to poison or
blank. Only a ``Source.LIVE`` result counts as refreshed — a ``CACHED``
result (should not occur given ``force_fetch=True``, but is not trusted
blindly either) or a ``STALE`` fallback (the live fetch ran and failed)
both count the same as an outright failure here, even though each is a
usable value a reader could still consult.

A fetch counting as ``LIVE`` only proves the write happened *in this
process*. #300's original acceptance criterion for this job was that the
app can actually read what the job wrote — a write that lands somewhere
the read path can't see (a permissions mismatch, a differently-resolved
``DELTADEWA_CACHE_DIR``, a filesystem quirk) would still report a green
exit code under that weaker test. #377 closes that gap: after every
series has had its live-fetch attempt, :func:`verify_read_back`
constructs a **separate, read-only** ``CboeFredProvider`` over the same
resolved ``cache_dir`` and re-reads each series that fetched live through
it — deliberately not trusting the writer's own tally, since the writer
succeeding is exactly the thing under test. The exit code summarizes the
run:

    0   every series refreshed live and read back through the app's own path
    1   some series refreshed+verified live, some did not
    2   no series fetched live at all (a fetch failure) — or the provider
        construction / fetch / read-back sequence itself raised an
        exception this job did not anticipate (R-a.3): either way, no
        usable outcome came out of this run, so it is reported the same
    3   at least one series fetched live, but none of it reads back through
        the app's own read path (a write-readability failure — #377 —
        distinct from a fetch failure: the network worked, the write
        didn't land somewhere this process's own read path can see)

FRED's VIXCLS series publishes with a lag, so an early-morning run
reporting exit 1 with only the VIX-derived series unavailable is a
plausible *normal* state, not an incident by itself — a caller consuming
this exit code should treat 0 and 1 alike and escalate only on sustained
1s or any 2 or 3.

If ``REFRESH_HEARTBEAT_URL`` is set, this job pings it on exit 0 and 1
(exit 2 and 3 do not ping — see ``deltadewa.heartbeat``).

A note on ``as_of``: it is the *source series'* observation date, not when
this job ran — a Saturday run fetching Friday's close reports
``as_of=Friday``. That's expected and already documented at the
``Observation`` level (``deltadewa.marketdata.Observation``); it's called
out here because once this job runs daily, "the banner's as_of is a day or
more behind fetched_at" becomes the routine case rather than a rare one.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from deltadewa.heartbeat import ping
from deltadewa.ips_config import IpsConfigError, load_ips_config
from deltadewa.marketdata import (
    CboeFredProvider,
    MarketDataError,
    Observation,
    Source,
    default_cache_dir,
    resolve_data_ttl,
    write_cache_manifest,
)

if TYPE_CHECKING:
    from datetime import datetime

    from deltadewa.marketdata import MarketDataProvider

_logger = logging.getLogger(__name__)

_DEFAULT_SYMBOL = "SPX"
_DEFAULT_IPS_PATH = Path("config/ips.yaml")
_HEARTBEAT_ENV_VAR = "REFRESH_HEARTBEAT_URL"

_EXIT_OK: Final[int] = 0
_EXIT_PARTIAL: Final[int] = 1
_EXIT_FETCH_FAILED: Final[int] = 2
_EXIT_WRITE_UNREADABLE: Final[int] = 3


def _series(
    provider: MarketDataProvider,
    symbol: str,
) -> list[tuple[str, Callable[[], Observation[Any]]]]:
    """List the (name, fetch) pairs the app depends on, in fetch order.

    Five of the six mirror exactly the calls ``assess_market_environment``
    makes (``vix``, ``vix_term_structure``, ``skew_index``,
    ``skew_percentile``) plus ``vix_history`` (``analysis.health``).

    ``spot`` was the exception until #336: fetched here since before #279,
    but read by nothing once #279 deleted its old consumer,
    ``dashboard.session``, with the rest of the Jupyter layer. #322 decided
    to wire it rather than retire the fetch; #336 did so —
    ``analysis.spot_reading.observe_spot`` reads this cache key and
    ``/monitor`` renders it as a labelled cross-check beside the book's
    hand-entered ``portfolio.spot_price``. See ``docs/market-data.md`` for
    the full reading-by-reading map.

    One pair listed separately here shares a single disk-cache key —
    ``vix``/``vix_history`` both write ``"vix_fred"`` (see
    ``CboeFredProvider._request_vix``). ``skew_index``/``skew_percentile``
    used to share ``"spot_SKEW"`` the same way; #185 item 1 gave
    ``_request_skew`` its own ``"skew_percentile_history"`` key so the two
    readings no longer overwrite each other's cache entry, even though
    they currently fetch the same underlying CBOE SKEW series. For the
    ``vix`` pair that still shares a key: with ``force_fetch=True`` each
    name still issues its own live request — the second call's result
    simply overwrites the first's with an (almost always identical) fresh
    observation — so a full run costs two upstream hits for that pair
    rather than one. Harmless at daily cadence and well inside FRED's
    limits, but a real behaviour change from the pre-``force_fetch`` world
    where the second call was a same-run cache hit and no second request
    went out.
    """
    return [
        ("vix", provider.get_vix),
        ("vix_history", provider.get_vix_history),
        ("vix_term_structure", provider.get_vix_term_structure),
        ("skew_index", provider.get_skew_index),
        ("skew_percentile", provider.get_skew_percentile),
        ("spot", lambda: provider.get_spot(symbol)),
    ]


def refresh_all(
    provider: MarketDataProvider,
    symbol: str,
) -> tuple[dict[str, datetime], int]:
    """Refresh every series the app depends on, independently.

    A failure fetching one series is logged and does not stop the rest —
    the underlying disk cache only writes on success, so a failed series
    simply retains whatever it last cached.

    Only a series whose ``Observation.source`` comes back ``Source.LIVE``
    counts toward the returned tally. ``CACHED`` and ``STALE`` are both
    real, usable values a caller could still read — but neither one is a
    refresh, and counting either as one is exactly the silent-no-op bug
    this function exists not to repeat.

    Args:
        provider: A live (``read_only=False``) provider to fetch through.
        symbol: Underlying symbol to warm the spot cache for.

    Returns:
        ``(live, total)`` — ``live`` maps each series name that fetched
        ``Source.LIVE`` to the ``fetched_at`` timestamp that fetch wrote
        to disk; ``total`` is the total number of series attempted.

    """
    series = _series(provider, symbol)
    live: dict[str, datetime] = {}
    for name, fetch in series:
        try:
            observation = fetch()
        except MarketDataError as exc:
            _logger.warning("%s: FAILED — %s", name, exc)
            continue
        if observation.source is Source.LIVE:
            if observation.fetched_at is not None:
                live[name] = observation.fetched_at
            _logger.info(
                "%s: refreshed live, as_of=%s fetched_at=%s",
                name,
                observation.as_of,
                observation.fetched_at,
            )
        else:
            _logger.warning(
                "%s: NOT refreshed (%s, as_of=%s fetched_at=%s)",
                name,
                observation.source,
                observation.as_of,
                observation.fetched_at,
            )
    return live, len(series)


def verify_read_back(
    cache_dir: Path,
    symbol: str,
    live: Mapping[str, datetime],
) -> tuple[str, ...]:
    """Confirm each just-refreshed series reads back through the app's own path.

    Builds a **separate**, read-only ``CboeFredProvider`` over the same
    resolved *cache_dir* the writer just used — not the writer's own
    provider — and re-fetches only the series named in *live* through it.
    Deliberately does not trust the writer's own ``Source.LIVE`` tally:
    that only proves the write happened in this process, not that the
    app's own read path can see it (#300's original acceptance criterion
    for this job; #377).

    A series counts as verified iff (a) the re-read doesn't raise
    ``MarketDataError``, and (b) the re-read ``fetched_at`` is **not
    older than** (``>=``) the *live*-recorded ``fetched_at`` for that
    name — not exact equality. ``vix``/``vix_history`` share one on-disk
    cache key (see ``_series()``'s own docstring), so in a real run the
    second write legitimately overwrites the first's ``fetched_at`` —
    an exact-equality check would falsely flag ``vix`` as a write-
    readability failure on every single healthy run. ``>=`` verifies
    "this run's own write reached the read path" without that false
    positive, while still catching a genuine failure: a stale on-disk
    value from a previous run reads back *older* than what this run just
    recorded writing.

    Args:
        cache_dir: The resolved cache directory the writer just used.
        symbol: Underlying symbol, for the ``spot`` series.
        live: The series names and ``fetched_at`` timestamps
            ``refresh_all`` reported as freshly written.

    Returns:
        The subset of *live*'s names that verified, in *live*'s
        iteration order.

    """
    if not live:
        return ()

    reader = CboeFredProvider(cache_dir=cache_dir, read_only=True)
    fetch_by_name = dict(_series(reader, symbol))

    verified: list[str] = []
    for name, recorded_fetched_at in live.items():
        fetch = fetch_by_name[name]
        try:
            observation = fetch()
        except MarketDataError as exc:
            _logger.warning("%s: read-back FAILED — %s", name, exc)
            continue
        read_fetched_at = observation.fetched_at
        if (
            read_fetched_at is not None
            and read_fetched_at >= recorded_fetched_at
        ):
            verified.append(name)
            _logger.info(
                "%s: read-back verified (%s)",
                name,
                observation.source,
            )
        else:
            _logger.warning(
                "%s: read-back STALE — wrote fetched_at=%s, read back "
                "fetched_at=%s (%s)",
                name,
                recorded_fetched_at,
                read_fetched_at,
                observation.source,
            )
    return tuple(verified)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for the refresh job."""
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the on-disk market-data cache the read-only Dash app "
            "reads. Intended to run on a cron, daily, seven days a week."
        ),
    )
    parser.add_argument(
        "--symbol",
        default=_DEFAULT_SYMBOL,
        help=f"Underlying to warm spot cache for (default: {_DEFAULT_SYMBOL})",
    )
    parser.add_argument(
        "--ips-path",
        type=Path,
        default=_DEFAULT_IPS_PATH,
        help=(
            "Path to the hedge program policy file, used for the "
            f"CACHED/STALE TTL boundary (default: {_DEFAULT_IPS_PATH})."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=(
            "Directory for the disk cache. Defaults to DELTADEWA_CACHE_DIR "
            "if set, else ~/.cache/deltadewa/marketdata — the same "
            "resolution the app itself uses, so they agree by construction."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Refresh every market-data series the app depends on.

    Always attempts a live fetch for each series regardless of the
    on-disk cache's freshness — see the module docstring for why a
    within-TTL cache hit must never stand in for this job having run.

    Returns:
        Process exit code — see the module docstring's table: ``0``
        every series refreshed live and read back, ``1`` some did,
        ``2`` no series fetched live at all, ``3`` at least one fetched
        live but none of it read back (a write-readability failure).

    """
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)

    try:
        ips_config = load_ips_config(args.ips_path)
    except IpsConfigError as exc:
        _logger.warning(
            "%s unavailable, using the default TTL: %s",
            args.ips_path,
            exc,
        )
        ips_config = None

    cache_dir = (
        args.cache_dir if args.cache_dir is not None else default_cache_dir()
    )

    try:
        provider = CboeFredProvider(
            cache_dir=cache_dir,
            # Inert for this job: force_fetch below bypasses the TTL
            # check that would otherwise consult it. Still resolved and
            # passed through so --ips-path/load_ips_config above isn't
            # dead code, and so the constructor's ttl/force_fetch
            # contract stays visible from this call site.
            ttl=resolve_data_ttl(ips_config),
            read_only=False,
            force_fetch=True,
        )

        live, total = refresh_all(provider, args.symbol)
        _logger.info("Fetched %d/%d series live", len(live), total)

        verified = verify_read_back(cache_dir, args.symbol, live)
        _logger.info(
            "Verified %d/%d fetched series read back through the app's "
            "own path",
            len(verified),
            len(live),
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Unanticipated on purpose (mirrors weekly_report.py's #364 guard
        # and panel_guard.safe_render's precedent, #363): a blast-radius
        # audit (R-a.3) found this whole sequence — provider construction,
        # refresh_all, verify_read_back — unguarded. Left that way, a
        # raise here exits with Python's bare default (1), indistinguish-
        # able from _EXIT_PARTIAL — a state that WOULD have pinged the
        # heartbeat. Falls back to the same exit code and silent-heartbeat
        # contract as a total fetch failure (2): from the operator's
        # chair, "every series failed" and "the run crashed before
        # finishing" both mean nothing usable came out of this run.
        _logger.exception("refresh: run FAILED unexpectedly")
        print(
            f"refresh: could not complete the run — {exc}",
            file=sys.stderr,
        )
        return _EXIT_FETCH_FAILED

    try:
        write_cache_manifest(cache_dir, live)
    except OSError as exc:
        _logger.warning(
            "could not write refresh manifest to %s: %s",
            cache_dir,
            exc,
        )

    if len(verified) == total:
        exit_code = _EXIT_OK
    elif verified:
        exit_code = _EXIT_PARTIAL
    elif live:
        exit_code = _EXIT_WRITE_UNREADABLE
    else:
        exit_code = _EXIT_FETCH_FAILED

    if exit_code in (_EXIT_OK, _EXIT_PARTIAL):
        ping(os.environ.get(_HEARTBEAT_ENV_VAR), label="refresh")
    elif exit_code == _EXIT_WRITE_UNREADABLE:
        _logger.warning(
            "refresh: fetched %d series live but none read back through "
            "the app's own path, skipping heartbeat ping so it stays "
            "visible instead of masking a real outage",
            len(live),
        )
    else:
        _logger.warning(
            "refresh: total failure, skipping heartbeat ping so it stays "
            "visible instead of masking a real outage",
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
