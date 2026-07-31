"""Tests for deltadewa.marketdata._observation."""

import dataclasses
from datetime import UTC, datetime

import pytest

from deltadewa.marketdata import Observation, Source, worst_source

_AS_OF = datetime(2026, 7, 24, tzinfo=UTC)
_FETCHED = datetime(2026, 7, 30, 14, 5, tzinfo=UTC)


def _live(value: float = 1.0, **kwargs: object) -> Observation[float]:
    """Build a LIVE observation, overriding fields for invariant tests."""
    fields: dict[str, object] = {
        "value": value,
        "source": Source.LIVE,
        "as_of": _AS_OF,
        "fetched_at": _FETCHED,
    }
    fields.update(kwargs)
    return Observation(**fields)  # type: ignore[arg-type]


class TestObservationInvariant:
    """STATIC if and only if the timestamps are absent."""

    def test_static_factory_carries_no_timestamps(self) -> None:
        """Observation.static builds the only valid STATIC shape."""
        obs = Observation.static(16.0)

        assert obs.source is Source.STATIC
        assert obs.as_of is None
        assert obs.fetched_at is None

    def test_static_with_as_of_is_rejected(self) -> None:
        """A synthetic value must not claim an observation date."""
        with pytest.raises(ValueError, match="must carry no timestamps"):
            Observation(
                value=16.0,
                source=Source.STATIC,
                as_of=_AS_OF,
                fetched_at=None,
            )

    def test_static_with_fetched_at_is_rejected(self) -> None:
        """A synthetic value was never fetched."""
        with pytest.raises(ValueError, match="must carry no timestamps"):
            Observation(
                value=16.0,
                source=Source.STATIC,
                as_of=None,
                fetched_at=_FETCHED,
            )

    @pytest.mark.parametrize(
        "source",
        [Source.LIVE, Source.CACHED, Source.STALE],
    )
    def test_observed_source_without_as_of_is_rejected(
        self,
        source: Source,
    ) -> None:
        """A missing as-of on a live source would read as 'unknown'.

        The whole point of the invariant: absence must never be able to pass
        for freshness.
        """
        with pytest.raises(ValueError, match="requires both timestamps"):
            Observation(
                value=16.0,
                source=source,
                as_of=None,
                fetched_at=_FETCHED,
            )

    def test_observed_source_without_fetched_at_is_rejected(self) -> None:
        """Both timestamps are required together on an observed value."""
        with pytest.raises(ValueError, match="requires both timestamps"):
            _live(fetched_at=None)

    def test_observation_is_frozen(self) -> None:
        """Provenance cannot be edited off a value after the fact."""
        obs = _live()

        with pytest.raises(dataclasses.FrozenInstanceError):
            obs.source = Source.LIVE  # type: ignore[misc]


class TestWorstSource:
    """Severity ordering: LIVE < CACHED < STALE < STATIC."""

    @pytest.mark.parametrize(
        ("sources", "expected"),
        [
            ([Source.LIVE], Source.LIVE),
            ([Source.LIVE, Source.CACHED], Source.CACHED),
            ([Source.LIVE, Source.STALE, Source.CACHED], Source.STALE),
            ([Source.LIVE, Source.STATIC], Source.STATIC),
            ([Source.STALE, Source.STATIC], Source.STATIC),
        ],
    )
    def test_returns_least_trustworthy(
        self,
        sources: list[Source],
        expected: Source,
    ) -> None:
        """A combined reading is only as good as its weakest input."""
        assert worst_source(sources) is expected

    def test_empty_raises(self) -> None:
        """There is no honest answer for no inputs at all."""
        with pytest.raises(ValueError, match="at least one source"):
            worst_source([])


class TestObservationCombine:
    """Combining takes the worst source and the oldest timestamps."""

    def test_takes_the_oldest_as_of(self) -> None:
        """A curve is only as fresh as its stalest leg."""
        older = datetime(2026, 7, 20, tzinfo=UTC)
        combined = Observation.combine(
            {"a": 1.0},
            [_live(as_of=_AS_OF), _live(as_of=older)],
        )

        assert combined.as_of == older

    def test_takes_the_worst_source(self) -> None:
        """One cached leg downgrades an otherwise live reading."""
        combined = Observation.combine(
            0.0,
            [_live(), _live(source=Source.CACHED)],
        )

        assert combined.source is Source.CACHED

    def test_one_static_part_makes_the_whole_static(self) -> None:
        """A reading containing an invented number has no as-of date."""
        combined = Observation.combine(
            0.0,
            [_live(), Observation.static(2.0)],
        )

        assert combined.source is Source.STATIC
        assert combined.as_of is None
        assert combined.fetched_at is None

    def test_carries_the_supplied_value(self) -> None:
        """Combining sets provenance, not the payload."""
        combined = Observation.combine({"VIX": 18.0}, [_live()])

        assert combined.value == {"VIX": 18.0}

    def test_empty_raises(self) -> None:
        """Provenance for nothing is not a meaningful answer."""
        with pytest.raises(ValueError, match="at least one observation"):
            Observation.combine(0.0, [])
