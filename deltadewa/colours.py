"""
To hold pallete for colours
"""

from dataclasses import dataclass

# Single constants
# Greens - success / positive / good
TROPICAL_JUICE = "#ccffcc"
GAMMA_GREEN = "#26a641"

# Reds and pinks - error / negative / bad
SPICY_PASTEL_PINK = "#ffcccc"
CLAYEY_RED = "#d73a49"
BLAZE_RED = "#F44336"

# Blues - neutral, informational, or background
RUSSIAN_BLUE = "#2196F3"
EARTH_BLUE = "#1f77b4"
TEAL_BLUE = "#0f4761"
MYSTIC_NAVY = "#2c3e50"

# Oranges - warnings / cautions / attention
VIBRANT_CREAM = "#ffffcc"
CHILEAN_FIRE = "#f57c00"
GILDED_LILY = "#f5a623"

# Yellows
LIGHT_YELLOW = "#ffffe0"

# Neutrals - neutral / background
FULL_WHITE = "#ffffff"
OFF_WHITE_GREY = "#f0f0f0"
SUPER_GREY = "#999999"
DARK_CHARCOAL = "#333333"
AFRICAN_TURQUOISE = "#000000"


# Optional grouped palette
@dataclass(frozen=True)
class Palette:
    """
    To hold colours
    """

    positive: str = GAMMA_GREEN
    positive_faded: str = TROPICAL_JUICE
    negative: str = CLAYEY_RED
    negative_faded: str = SPICY_PASTEL_PINK
    call: str = RUSSIAN_BLUE
    put: str = BLAZE_RED
    axis: str = SUPER_GREY

    orange: str = CHILEAN_FIRE
    orange_faded: str = VIBRANT_CREAM

    yellow: str = GILDED_LILY
    yellow_faded: str = LIGHT_YELLOW

    white: str = FULL_WHITE
    very_light_grey: str = OFF_WHITE_GREY
    medium_grey: str = SUPER_GREY
    dark_grey: str = DARK_CHARCOAL
    black: str = AFRICAN_TURQUOISE

    medium_background: str = EARTH_BLUE
    med_dark_background: str = TEAL_BLUE
    dark_background: str = MYSTIC_NAVY


DEFAULT_PALETTE = Palette()
__all__ = [
    "Palette",
    "DEFAULT_PALETTE",
]
