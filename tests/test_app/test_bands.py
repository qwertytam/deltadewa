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


def _value_label(bar):
    return _track(bar).children[2]


def _scale_labels(bar):
    """Return the .band-scale-labels row (the second child of the outer div)."""
    return bar.children[1]


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


class TestBandBarLabels:
    """Tests for the five point labels: two domain edges, low, high, value."""

    def test_value_label_uses_default_formatter(self) -> None:
        bar = band_bar(value=20.0, low=15.0, high=25.0)

        assert _value_label(bar).children == "20.0"

    def test_value_label_carries_the_marker_modifier(self) -> None:
        within = band_bar(value=20.0, low=15.0, high=25.0)
        outside = band_bar(value=5.0, low=15.0, high=25.0)

        assert "band-value-label--within" in _value_label(within).className
        assert "band-value-label--outside" in _value_label(outside).className

    def test_value_label_is_positioned_at_the_marker(self) -> None:
        bar = band_bar(value=20.0, low=15.0, high=25.0)

        marker_left = _marker(bar).style["left"]
        assert _value_label(bar).style["left"] == marker_left

    def test_scale_labels_name_low_high_and_the_track_extremes(self) -> None:
        bar = band_bar(value=20.0, low=15.0, high=25.0)

        labels = _scale_labels(bar).children
        edge_start, low_label, high_label, edge_end = labels
        assert low_label.children == "15.0"
        assert high_label.children == "25.0"
        # Domain is low/high padded 25% each side: pad = 2.5.
        assert edge_start.children == "12.5"
        assert edge_end.children == "27.5"

    def test_edge_labels_have_no_inline_position_style(self) -> None:
        # 0%/100% is exact by construction (they *are* the domain's own
        # extremes), so CSS pins them with left:0/right:0 rather than a
        # computed inline style.
        bar = band_bar(value=20.0, low=15.0, high=25.0)

        edge_start, _low, _high, edge_end = _scale_labels(bar).children
        assert not hasattr(edge_start, "style")
        assert not hasattr(edge_end, "style")

    def test_mid_labels_are_positioned_at_low_and_high(self) -> None:
        bar = band_bar(value=20.0, low=15.0, high=25.0)
        good_zone = _good_zone(bar)
        zone_left = good_zone.style["left"]
        zone_right_pct = float(good_zone.style["left"].rstrip("%")) + float(
            good_zone.style["width"].rstrip("%"),
        )

        _edge_start, low_label, high_label, _edge_end = _scale_labels(
            bar,
        ).children
        assert low_label.style["left"] == zone_left
        assert float(high_label.style["left"].rstrip("%")) == pytest.approx(
            zone_right_pct,
        )

    def test_domain_extends_to_cover_a_wildly_out_of_range_value(self) -> None:
        bar = band_bar(value=-500.0, low=15.0, high=25.0)

        edge_start, *_rest = _scale_labels(bar).children
        assert edge_start.children == "-500.0"

    def test_custom_fmt_is_used_for_every_label(self) -> None:
        bar = band_bar(
            value=20.0,
            low=15.0,
            high=25.0,
            fmt=lambda v: f"${v:.0f}",
        )

        labels = _scale_labels(bar).children
        edge_start, low_label, high_label, edge_end = labels
        assert _value_label(bar).children == "$20"
        assert low_label.children == "$15"
        assert high_label.children == "$25"
        assert edge_start.children == "$12"
        assert edge_end.children == "$28"
