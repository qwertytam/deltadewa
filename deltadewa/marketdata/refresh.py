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

Each series is fetched independently: one failure never aborts the run,
and a failed series' previous cache entry is left untouched — the disk
cache only writes on a successful fetch, so there is nothing to poison or
blank. The exit code summarizes the run:

    0   every series refreshed live
    1   some series refreshed, some failed (partial)
    2   every series failed

FRED's VIXCLS series publishes with a lag, so an early-morning run
reporting exit 1 with only the VIX-derived series unavailable is a
plausible *normal* state, not an incident by itself — a caller consuming
this exit code should treat 0 and 1 alike and escalate only on sustained
1s or any 2.

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
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deltadewa.ips_config import IpsConfigError, load_ips_config
from deltadewa.marketdata import (
    CboeFredProvider,
    MarketDataError,
    Observation,
    default_cache_dir,
    resolve_data_ttl,
)

if TYPE_CHECKING:
    from deltadewa.marketdata import MarketDataProvider

_logger = logging.getLogger(__name__)

_DEFAULT_SYMBOL = "SPX"
_DEFAULT_IPS_PATH = Path("config/ips.yaml")


def _series(
    provider: MarketDataProvider,
    symbol: str,
) -> list[tuple[str, Callable[[], Observation[Any]]]]:
    """List the (name, fetch) pairs the app depends on, in fetch order.

    Mirrors exactly the calls ``assess_market_environment`` makes (``vix``,
    ``vix_term_structure``, ``skew_index``, ``skew_percentile``) plus
    ``vix_history`` (``analysis.health``) and ``spot`` (``dashboard.session``)
    — every key the app or notebook path may read is warmed here.
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

    Args:
        provider: A live (``read_only=False``) provider to fetch through.
        symbol: Underlying symbol to warm the spot cache for.

    Returns:
        ``(succeeded, total)`` series counts.

    """
    series = _series(provider, symbol)
    succeeded = 0
    for name, fetch in series:
        try:
            observation = fetch()
        except MarketDataError as exc:
            _logger.warning("%s: FAILED — %s", name, exc)
            continue
        succeeded += 1
        _logger.info(
            "%s: %s as_of=%s fetched_at=%s",
            name,
            observation.source,
            observation.as_of,
            observation.fetched_at,
        )
    return succeeded, len(series)


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

    Returns:
        Process exit code: ``0`` if every series refreshed live, ``1`` if
        some succeeded and some failed (partial), ``2`` if every series
        failed.

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
        ttl=resolve_data_ttl(ips_config),
        read_only=False,
    )

    succeeded, total = refresh_all(provider, args.symbol)
    _logger.info("Refreshed %d/%d series", succeeded, total)

    if succeeded == total:
        return 0
    if succeeded == 0:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
