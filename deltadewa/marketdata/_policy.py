"""Policy-derived market-data settings, sourced from ``ips.yaml``.

Kept apart from ``cboe_fred_provider`` because these read program policy
(``IpsConfig``) and process environment, not provider mechanics — the
CACHED/STALE boundary is a policy decision, not a caching implementation
detail, and the cache location is an operational one shared between the
read-only app and the refresh job that keeps it warm.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

from deltadewa.ips_config import DEFAULT_DATA_TTL_MINUTES

if TYPE_CHECKING:
    from collections.abc import Mapping

    from deltadewa.ips_config import IpsConfig

_CACHE_DIR_ENV_VAR = "DELTADEWA_CACHE_DIR"

CACHE_MANIFEST_FILENAME: Final[str] = "refresh-manifest.json"


def default_cache_dir() -> Path:
    """Resolve the market-data disk-cache directory.

    Honours ``DELTADEWA_CACHE_DIR`` so a production refresh job and the
    read-only app *resolve the same directory by the same logic* — in
    production this points at a path under the ``exports/`` bind mount, so
    the cache survives container recreation, unlike the per-container
    writable layer. Falls back to ``~/.cache/deltadewa/marketdata`` for
    notebook/local use, unchanged from the provider's own prior default.

    Sharing this resolution function is not the same guarantee as the two
    processes actually agreeing at runtime: ``app`` and ``jobs`` each read
    ``DELTADEWA_CACHE_DIR`` from their own environment, set by their own
    ``compose.yaml`` service literal — nothing enforces those two literals
    stay identical (#372/#378). ``app.health_checks.
    check_cache_manifest_matches`` is the runtime cross-check for that:
    it compares the cache dir the refresh job last recorded writing to
    against what this app process itself resolved.
    """
    override = os.environ.get(_CACHE_DIR_ENV_VAR)
    if override:
        return Path(override)
    return Path.home() / ".cache" / "deltadewa" / "marketdata"


@dataclass(frozen=True)
class CacheManifest:
    """What the refresh job last recorded about its own resolved cache dir.

    Written by ``marketdata.refresh`` on every run (#378) and read by
    ``app.health_checks`` to detect a divergence between what ``app`` and
    ``jobs`` each resolve for ``DELTADEWA_CACHE_DIR`` — see this module's
    ``default_cache_dir`` docstring for why the *resolution logic* being
    shared isn't the same guarantee as the two compose.yaml literals
    actually agreeing.
    """

    cache_dir: str
    written_at: str
    series: dict[str, str]


def write_cache_manifest(
    cache_dir: Path,
    series: Mapping[str, datetime],
) -> None:
    """Write the #378 manifest into *cache_dir*, on every refresh run.

    Records what this process resolved *cache_dir* to be, when it ran,
    and each series' fetched_at — independent of whether #377's read-back
    verification later succeeds, so the manifest stays meaningful even
    when the write-readability check itself is what's broken.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "cache_dir": str(cache_dir),
        "written_at": datetime.now(tz=UTC).isoformat(),
        "series": {name: at.isoformat() for name, at in series.items()},
    }
    (cache_dir / CACHE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def read_cache_manifest(cache_dir: Path) -> CacheManifest | None:
    """Read the #378 manifest from *cache_dir*, or ``None`` if unreadable.

    Never raises — mirrors ``_DiskCache._read``'s tolerant style in
    ``cboe_fred_provider.py``: a missing, corrupt, or malformed manifest
    reads as "no manifest," which ``check_cache_manifest_matches`` then
    reports as a failing check rather than crashing ``/health``.
    """
    path = cache_dir / CACHE_MANIFEST_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CacheManifest(
            cache_dir=str(data["cache_dir"]),
            written_at=str(data["written_at"]),
            series=dict(data.get("series", {})),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def resolve_data_ttl(ips_config: IpsConfig | None) -> timedelta:
    """Return the market-data freshness window from IPS policy.

    The CACHED/STALE boundary is policy, so it comes from ``ips.yaml``
    rather than the provider's constructor default. A missing or
    unreadable ``ips.yaml`` falls back to the same
    ``DEFAULT_DATA_TTL_MINUTES`` single source the dataclass default uses.
    """
    minutes = (
        DEFAULT_DATA_TTL_MINUTES
        if ips_config is None
        else ips_config.market_environment.data_ttl_minutes
    )
    return timedelta(minutes=minutes)
