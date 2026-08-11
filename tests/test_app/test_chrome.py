"""Tests for deltadewa.app.chrome — the shared as-of stamp + banner."""

from datetime import UTC, datetime

from deltadewa.analysis.market_environment import DataQuality, MarketEnvironment
from deltadewa.app.chrome import build_chrome

_AS_OF = datetime(2026, 7, 29, 21, 0, tzinfo=UTC)


def _environment(
    data_quality: DataQuality,
    as_of: datetime | None,
) -> MarketEnvironment:
    """Build a MarketEnvironment with only data_quality/as_of populated."""
    return MarketEnvironment(
        vix=None,
        regime_percentile=None,
        regime_label=None,
        skew_index=None,
        skew_percentile=None,
        term_structure=None,
        term_shape=None,
        forward_vol_front_3m=None,
        hedge_cost_verdict=None,
        data_quality=data_quality,
        as_of=as_of,
    )


def _has_banner_class(chrome, suffix: str) -> bool:
    return any(
        f"chrome-banner--{suffix}" in getattr(child, "className", "")
        for child in chrome.children
    )


class TestQuietQualities:
    """LIVE/CACHED get the quiet stamp only — no loud banner."""

    def test_live_has_no_banner(self) -> None:
        chrome = build_chrome(_environment(DataQuality.LIVE, _AS_OF))

        assert len(chrome.children) == 1
        assert "2026-07-29" in chrome.children[0].children

    def test_cached_has_no_banner(self) -> None:
        chrome = build_chrome(_environment(DataQuality.CACHED, _AS_OF))

        assert len(chrome.children) == 1
        assert "2026-07-29" in chrome.children[0].children


class TestStampIsInTheProgramTimezone:
    """The as-of stamp reads as the desk's clock, not the server's (#182)."""

    def test_stamp_names_the_zone_it_is_showing(self) -> None:
        """An unlabelled time is worse than a converted one."""
        chrome = build_chrome(_environment(DataQuality.LIVE, _AS_OF))

        stamp = chrome.children[0].children

        assert "EDT" in stamp
        assert "UTC" not in stamp

    def test_converts_rather_than_relabels(self) -> None:
        """21:00 UTC is 17:00 in New York — the clock moves, not the label."""
        chrome = build_chrome(_environment(DataQuality.LIVE, _AS_OF))

        assert "17:00" in chrome.children[0].children

    def test_evening_utc_reads_as_the_previous_us_day(self) -> None:
        """The case the old stamp got wrong.

        A feed observed at 01:00 UTC was stamped with tomorrow's date,
        while the US desk reading it was still on the previous session.
        """
        after_utc_midnight = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)

        chrome = build_chrome(
            _environment(DataQuality.LIVE, after_utc_midnight),
        )

        assert "2026-07-29" in chrome.children[0].children


class TestDegradedQualitiesGetABanner:
    """STATIC/STALE/UNAVAILABLE mount a second, loudly-classed element."""

    def test_stale_has_a_distinct_banner(self) -> None:
        chrome = build_chrome(_environment(DataQuality.STALE, _AS_OF))

        assert len(chrome.children) == 2
        assert _has_banner_class(chrome, "stale")
        assert "STALE" in chrome.children[1].children

    def test_static_has_a_distinct_banner_with_no_as_of(self) -> None:
        chrome = build_chrome(_environment(DataQuality.STATIC, None))

        assert len(chrome.children) == 2
        assert _has_banner_class(chrome, "static")
        assert "SYNTHETIC" in chrome.children[1].children
        # No as_of must not crash the stamp; it must say so honestly.
        assert "No as-of date" in chrome.children[0].children

    def test_unavailable_has_a_distinct_banner_with_no_as_of(self) -> None:
        chrome = build_chrome(_environment(DataQuality.UNAVAILABLE, None))

        assert len(chrome.children) == 2
        assert _has_banner_class(chrome, "unavailable")
        assert "UNAVAILABLE" in chrome.children[1].children
        assert "No as-of date" in chrome.children[0].children

    def test_stale_and_static_banners_are_visually_distinct(self) -> None:
        stale_banner = build_chrome(
            _environment(DataQuality.STALE, _AS_OF),
        ).children[1]
        static_banner = build_chrome(
            _environment(DataQuality.STATIC, None),
        ).children[1]

        assert stale_banner.className != static_banner.className
