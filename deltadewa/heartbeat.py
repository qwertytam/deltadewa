"""Dead-man's-switch pings (healthchecks.io-compatible) for cron jobs.

M2.6 runs two independent cron jobs — the market-data refresh
(``deltadewa.marketdata.refresh``) and the weekly digest
(``deltadewa.reporting.weekly_report``) — and each needs its own check,
because they fail independently and mean different things when overdue:

- **Refresh** pings on a full *or* partial success. FRED's ``VIXCLS``
  series routinely publishes with a lag, so an early-morning partial
  refresh is the normal state, not an incident — paging on it would alert
  most mornings for a healthy system. A total failure does not ping, so it
  stays visible (in logs, and as an eventually-overdue check) without
  drowning the routine partial-failure signal.
- **Digest** pings only once the weekly email is confirmed sent. This is
  the one where silence is most dangerous: a missing weekly email is
  exactly what gets rationalised as "quiet week," so an overdue digest
  check must alarm.

Both checks live at top level (not inside ``marketdata/`` or
``reporting/``) because both jobs share this one pinger.
"""

from __future__ import annotations

import logging

import requests

_logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 10


class HeartbeatError(Exception):
    """Reserved for future use — ``ping()`` itself never raises.

    A heartbeat-delivery failure must never fail the job it's reporting
    on; see :func:`ping`. This exists so a caller that genuinely wants to
    escalate a ping failure has a typed exception to catch, without
    ``ping`` needing to raise it by default.
    """


def ping(
    url: str | None,
    *,
    label: str,
    session: requests.Session | None = None,
) -> None:
    """Best-effort GET to a healthchecks.io-style ping URL.

    Never raises. Two cases are deliberately swallowed rather than
    propagated:

    - *url* is ``None`` or empty (unconfigured): logged at ``INFO`` and
      skipped. Heartbeat wiring is an operational add-on, not a
      job-blocking dependency — a dev/test run without a heartbeat URL
      configured must still be able to succeed.
    - The request itself fails (network error or non-2xx response):
      logged at ``WARNING``. A heartbeat-delivery hiccup must not fail the
      job it's reporting on — that would invert the point of a dead-man's
      switch (the job actually ran, but the *ping* silently failed, must
      not read as the job having failed).

    Args:
        url: The healthchecks.io (or equivalent) check URL, or ``None`` if
            not configured.
        label: Short identifier for log messages (e.g. ``"refresh"`` or
            ``"digest"``).
        session: Optional ``requests.Session`` to use (for testing).
            Defaults to a new ``Session``.

    """
    if not url:
        _logger.info("%s: heartbeat URL not configured, skipping ping", label)
        return

    session = session or requests.Session()
    try:
        response = session.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        _logger.warning("%s: heartbeat ping failed: %s", label, exc)
        return

    _logger.info("%s: heartbeat ping sent", label)
