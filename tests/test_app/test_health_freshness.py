"""#393: which freshness states degrade ``/health``'s ``status``.

One rule, two channels, two cuts on the one ``FRESH < AGING < UNKNOWN <
MISSING`` ordering — stated with its reasoning in ``health_checks.py``'s
module docstring. The fetched channel degrades at ``_STALE_OR_WORSE``;
the hand-entered one at ``UNKNOWN`` or worse, so a merely ``AGING``
input stays quiet.

The boundary that most needs a test is the *quiet* one. With the shipped
``spot_max_age_days: 1``, ``AGING`` is true on most days of a program
whose review rhythm is a weekly digest, so a rule that degraded on it
would leave ``/health`` permanently red — a dead-man's switch nobody
reads, which is the same false-green failure the endpoint exists to
prevent, arriving from the other side. ``test_aging_hand_entered_input_
stays_quiet`` is the pin that stops someone "tightening" that later
without reading the argument first.

Every test drives the real request path through the Flask test client,
the same convention ``test_provenance_guard.py`` follows.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from deltadewa.analysis.market_environment import DataQuality
from deltadewa.analysis.provenance import (
    _QUALITY_TO_FRESHNESS,
    Freshness,
)
from deltadewa.app.factory import create_app
from deltadewa.app.health_checks import _STALE_OR_WORSE
from deltadewa.constants import ExerciseStyle
from deltadewa.marketdata import (
    MarketDataUnavailableError,
    StaticProvider,
    default_cache_dir,
    write_cache_manifest,
)
from deltadewa.state import ProgramState
from tests.test_app.freshness_fixtures import (
    GradedProvider,
    cached_provider,
    stale_provider,
    stamp_inputs,
)

if TYPE_CHECKING:
    from deltadewa.app.factory import ProgramDashApp

_EXAMPLE_IPS = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)
# ips.example.yaml's own spot_max_age_days, restated so the AGING test
# says what it is exercising rather than depending on the reader knowing.
_SPOT_MAX_AGE_DAYS = 1


@pytest.fixture(autouse=True)
def _isolated_cache_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep #309's real write-then-unlink probe inside tmp_path."""
    monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))


def _wired_state(tmp_path: Path) -> ProgramState:
    """A state with the real example IPS loaded — boot wiring all green.

    So a degraded ``status`` in this module can only have come from the
    freshness half, never from a check that happened to fail too.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    ips_path = tmp_path / "ips.yaml"
    shutil.copy(_EXAMPLE_IPS, ips_path)
    # Written to the cache dir the route itself resolves, not to a path
    # rebuilt from tmp_path — #378's check compares the two.
    write_cache_manifest(default_cache_dir(), {})
    return ProgramState.load(tmp_path, ips_path=ips_path)


def _app(
    tmp_path: Path,
    provider: object,
    *,
    stamped_days_ago: int | None = 0,
) -> ProgramDashApp:
    """Build an app whose only variable is its freshness.

    ``stamped_days_ago=None`` leaves the book unstamped — the #367
    pre-existing-book state that grades ``UNKNOWN``.
    """
    state = _wired_state(tmp_path)
    if stamped_days_ago is not None:
        stamp_inputs(state.portfolio, days_ago=stamped_days_ago)
    return create_app(state=state, market_data=provider)  # type: ignore[arg-type]


class TestQuietStates:
    """What must *not* turn the endpoint red."""

    def test_cached_feed_and_confirmed_inputs_read_ok(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path, cached_provider())

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "ok"
        assert payload["freshness_reason"] is None
        assert payload["market_data"]["source"] == "CACHED"

    def test_aging_hand_entered_input_stays_quiet(
        self,
        tmp_path: Path,
    ) -> None:
        # The load-bearing one. spot_max_age_days is 1, so a book
        # confirmed three days ago is AGING — true on most days of a
        # weekly-rhythm program. Degrading here would leave /health
        # permanently red; see health_checks.py's module docstring.
        app = _app(
            tmp_path,
            cached_provider(),
            stamped_days_ago=_SPOT_MAX_AGE_DAYS + 2,
        )

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "ok"
        assert payload["freshness_reason"] is None
        # Quiet in the headline, still reported in full below it — the
        # omission is from `status`, never from the payload.
        assert payload["pricing_inputs"]["worst"] == "AGING"


class TestDegradingStates:
    """What must turn the endpoint red, and how it says why."""

    def test_stale_feed_degrades_and_names_market_data(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path, stale_provider())

        response = app.server.test_client().get("/health")

        # 200 throughout: degraded means investigate, never restart.
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["status"] == "degraded"
        assert payload["freshness_reason"].startswith("market_data STALE")

    def test_static_feed_degrades(self, tmp_path: Path) -> None:
        # StaticProvider is every other app test's provider, so this is
        # also the record of why those tests now read degraded: a book
        # priced on synthetic numbers is not a healthy program.
        app = _app(
            tmp_path,
            StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0),
        )

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "degraded"
        assert payload["freshness_reason"].startswith("market_data STATIC")

    def test_never_confirmed_inputs_degrade_and_name_the_input(
        self,
        tmp_path: Path,
    ) -> None:
        # The #367 pre-existing book: no stamp at all, which is a
        # different and worse thing than a stamp that has gone overdue.
        app = _app(tmp_path, cached_provider(), stamped_days_ago=None)

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "degraded"
        assert payload["freshness_reason"].startswith("pricing_inputs UNKNOWN")
        # The two channels stay separate: an unconfirmed hand-entered
        # input must not make the endpoint claim the *feed* is stale
        # (#368's confusion, which worst_of() exists to prevent).
        assert payload["market_data"]["source"] == "CACHED"
        assert payload["pricing_inputs"]["worst"] == "UNKNOWN"

    def test_both_channels_bad_gives_one_reason_not_two(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path, stale_provider(), stamped_days_ago=None)

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "degraded"
        # The fetched channel is named first — it is the half an operator
        # acts on first, and the other is still rendered below.
        assert payload["freshness_reason"].startswith("market_data STALE")
        assert payload["pricing_inputs"]["worst"] == "UNKNOWN"


class TestStatusStaysTwoValued:
    """One field, two words; the distinction lives in the reason fields."""

    def test_a_wiring_fault_leaves_freshness_reason_null(
        self,
        tmp_path: Path,
    ) -> None:
        # A missing IPS fails ips_loaded, so status is degraded for the
        # #309 reason. freshness_reason must not fire for it — otherwise
        # the field stops distinguishing anything.
        state = ProgramState.load(
            tmp_path,
            ips_path=tmp_path / "does-not-exist-ips.yaml",
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        stamp_inputs(state.portfolio)
        write_cache_manifest(default_cache_dir(), {})
        app = create_app(state=state, market_data=cached_provider())

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "degraded"
        assert payload["freshness_reason"] is None
        assert payload["boot_wiring"]["ips_loaded"]["ok"] is False

    def test_status_is_only_ever_ok_or_degraded(
        self,
        tmp_path: Path,
    ) -> None:
        # #393 asked for no third status word; this is that promise, held
        # across every freshness state the rule distinguishes.
        providers = (
            cached_provider(),
            stale_provider(),
            StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0),
        )
        seen = set()
        for index, provider in enumerate(providers):
            app = _app(tmp_path / f"case{index}", provider)
            payload = app.server.test_client().get("/health").get_json()
            seen.add(payload["status"])

        assert seen <= {"ok", "degraded"}


class TestOneDefinitionOfNotFresh:
    """``_STALE_OR_WORSE`` and ``Freshness`` must not drift apart."""

    def test_stale_or_worse_is_exactly_the_not_fresh_qualities(self) -> None:
        # #393 asked for the existing definition to be reused rather than
        # a second one invented. health_checks.py holds a local mirror,
        # the convention four other modules already follow — this is what
        # keeps the mirror honest: the set must stay exactly "every
        # DataQuality the provenance layer does not call FRESH".
        not_fresh = {
            quality
            for quality in DataQuality
            if _QUALITY_TO_FRESHNESS[quality] is not Freshness.FRESH
        }

        assert not_fresh == _STALE_OR_WORSE

    def test_unavailable_feed_degrades(self, tmp_path: Path) -> None:
        # The set's remaining member, reached the way the real provider
        # reaches it: the fetch raising, which assess_market_environment
        # catches into UNAVAILABLE rather than propagating.
        provider = GradedProvider(vix_history=[])

        def _raise(*_args: object, **_kwargs: object) -> float:
            raise MarketDataUnavailableError("feed down")

        provider.get_vix = _raise  # type: ignore[method-assign]
        app = _app(tmp_path, provider)

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "degraded"
        assert payload["market_data"]["source"] == "UNAVAILABLE"
        assert payload["freshness_reason"].startswith("market_data UNAVAILABLE")
