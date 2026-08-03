"""Tests for deltadewa.app.bands — the band_bar display component.

Pure unit tests, no Dash/Playwright needed — same shape as
``tests/test_visualization/test_crash_charts_plotly.py``: assert
directly on the returned component tree.
"""

import pytest

from deltadewa.app.bands import band_bar


def _track(bar):
    """Return the .band-track child (the sole child of the outer div)."""
    return bar.children[0]


def _good_zone(bar):
    return _track(bar).children[0]


def _marker(bar):
    return _track(bar).children[1]


class TestBandBar:
    """Tests for band_bar."""

    def test_value_within_range_gets_within_class(self) -> None:
        bar = band_bar(value=20.0, low=15.0, high=25.0)

        marker = _marker(bar)
        assert "band-marker--within" in marker.className
        assert "band-marker--outside" not in marker.className

    def test_marker_positioned_between_good_zone_bounds(self) -> None:
        bar = band_bar(value=20.0, low=15.0, high=25.0)

        good_zone = _good_zone(bar)
        marker = _marker(bar)
        zone_left = float(good_zone.style["left"].rstrip("%"))
        zone_width = float(good_zone.style["width"].rstrip("%"))
        marker_left = float(marker.style["left"].rstrip("%"))

        assert zone_left <= marker_left <= zone_left + zone_width

    def test_value_below_low_gets_outside_class_and_is_left_of_zone(
        self,
    ) -> None:
        bar = band_bar(value=5.0, low=15.0, high=25.0)

        good_zone = _good_zone(bar)
        marker = _marker(bar)
        zone_left = float(good_zone.style["left"].rstrip("%"))
        marker_left = float(marker.style["left"].rstrip("%"))

        assert "band-marker--outside" in marker.className
        assert marker_left < zone_left

    def test_value_above_high_gets_outside_class_and_is_right_of_zone(
        self,
    ) -> None:
        bar = band_bar(value=40.0, low=15.0, high=25.0)

        good_zone = _good_zone(bar)
        marker = _marker(bar)
        zone_right = float(good_zone.style["left"].rstrip("%")) + float(
            good_zone.style["width"].rstrip("%"),
        )
        marker_left = float(marker.style["left"].rstrip("%"))

        assert "band-marker--outside" in marker.className
        assert marker_left > zone_right

    def test_value_exactly_at_low_is_within(self) -> None:
        bar = band_bar(value=15.0, low=15.0, high=25.0)

        assert "band-marker--within" in _marker(bar).className

    def test_value_exactly_at_high_is_within(self) -> None:
        bar = band_bar(value=25.0, low=15.0, high=25.0)

        assert "band-marker--within" in _marker(bar).className

    def test_marker_never_clips_off_track_for_wildly_out_of_range_value(
        self,
    ) -> None:
        bar = band_bar(value=-500.0, low=15.0, high=25.0)

        marker_left = float(_marker(bar).style["left"].rstrip("%"))
        assert 0.0 <= marker_left <= 100.0

    def test_low_greater_than_high_raises(self) -> None:
        with pytest.raises(ValueError, match="low"):
            band_bar(value=20.0, low=25.0, high=15.0)

    def test_low_equal_high_raises(self) -> None:
        with pytest.raises(ValueError, match="low"):
            band_bar(value=20.0, low=20.0, high=20.0)
