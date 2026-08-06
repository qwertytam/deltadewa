"""Policy-derived market-data settings, sourced from ``ips.yaml``.

Kept apart from ``cboe_fred_provider`` because these read program policy
(``IpsConfig``) and process environment, not provider mechanics — the
CACHED/STALE boundary is a policy decision, not a caching implementation
detail, and the cache location is an operational one shared between the
read-only app and the refresh job that keeps it warm.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from deltadewa.ips_config import DEFAULT_DATA_TTL_MINUTES

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig

_CACHE_DIR_ENV_VAR = "DELTADEWA_CACHE_DIR"


def default_cache_dir() -> Path:
    """Resolve the market-data disk-cache directory.

    Honours ``DELTADEWA_CACHE_DIR`` so a production refresh job and the
    read-only app agree on the same directory by construction — in
    production this points at a path under the ``exports/`` bind mount, so
    the cache survives container recreation, unlike the per-container
    writable layer. Falls back to ``~/.cache/deltadewa/marketdata`` for
    notebook/local use, unchanged from the provider's own prior default.
    """
    override = os.environ.get(_CACHE_DIR_ENV_VAR)
    if override:
        return Path(override)
    return Path.home() / ".cache" / "deltadewa" / "marketdata"


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
