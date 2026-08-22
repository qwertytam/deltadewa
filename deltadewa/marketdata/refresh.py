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
usable value a reader could still consult. The exit code summarizes the
run:

    0   every series refreshed live
    1   some series refreshed live, some did not (partial)
    2   no series refreshed live

FRED's VIXCLS series publishes with a lag, so an early-morning run
reporting exit 1 with only the VIX-derived series unavailable is a
plausible *normal* state, not an incident by itself — a caller consuming
this exit code should treat 0 and 1 alike and escalate only on sustained
1s or any 2.

If ``REFRESH_HEARTBEAT_URL`` is set, this job pings it on exit 0 and 1
(see ``deltadewa.heartbeat`` for why exit 2 does not ping).

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
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deltadewa.heartbeat import ping
from deltadewa.ips_config import IpsConfigError, load_ips_config
from deltadewa.marketdata import (
    CboeFredProvider,
    MarketDataError,
    Observation,
    Source,
    default_cache_dir,
    resolve_data_ttl,
)

if TYPE_CHECKING:
    from deltadewa.marketdata import MarketDataProvider

_logger = logging.getLogger(__name__)

_DEFAULT_SYMBOL = "SPX"
_DEFAULT_IPS_PATH = Path("config/ips.yaml")
_HEARTBEAT_ENV_VAR = "REFRESH_HEARTBEAT_URL"


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


def refresh_all(provider: MarketDataProvider, symbol: str) -> tuple[int, int]:
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
        ``(refreshed, total)`` series counts — ``refreshed`` counts only
        ``Source.LIVE`` results.

    """
    series = _series(provider, symbol)
    refreshed = 0
    for name, fetch in series:
        try:
            observation = fetch()
        except MarketDataError as exc:
            _logger.warning("%s: FAILED — %s", name, exc)
            continue
        if observation.source is Source.LIVE:
            refreshed += 1
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
    return refreshed, len(series)


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
        Process exit code: ``0`` if every series refreshed live, ``1`` if
        some did and some didn't (partial — a stale fallback or a hard
        failure), ``2`` if none did.

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
    provider = CboeFredProvider(
        cache_dir=cache_dir,
        # Inert for this job: force_fetch below bypasses the TTL check
        # that would otherwise consult it. Still resolved and passed
        # through so --ips-path/load_ips_config above isn't dead code,
        # and so the constructor's ttl/force_fetch contract stays
        # visible from this call site.
        ttl=resolve_data_ttl(ips_config),
        read_only=False,
        force_fetch=True,
    )

    refreshed, total = refresh_all(provider, args.symbol)
    _logger.info("Refreshed %d/%d series live", refreshed, total)

    if refreshed == total:
        exit_code = 0
    elif refreshed == 0:
        exit_code = 2
    else:
        exit_code = 1

    if exit_code in (0, 1):
        ping(os.environ.get(_HEARTBEAT_ENV_VAR), label="refresh")
    else:
        _logger.warning(
            "refresh: total failure, skipping heartbeat ping so it stays "
            "visible instead of masking a real outage",
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
