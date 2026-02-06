"""
To hold pallete for colours
"""

from dataclasses import dataclass

# Single constants
COLOUR_POSITIVE = "#26a641"
COLOUR_POSITIVE_FADED = "#ccffcc"
COLOUR_NEGATIVE = "#d73a49"
COLOUR_NEGATIVE_FADED = "#ffcccc"
COLOUR_CALL = "#2196F3"
COLOUR_PUT = "#F44336"
AXIS_LINE_COLOUR = "#aaaaaa"

ORANGE = "#f57c00"
ORANGE_FADED = "#ffffcc"

WHITE = "#ffffff"
VERY_LIGHT_GREY = "#f0f0f0"
MEDIUM_GREY = "#999999"
BLACK = "#000000"

MEDIUM_BACKGROUND = "#1f77b4"
DARK_BACKGROUND = "#2c3e50"


# Optional grouped palette
@dataclass(frozen=True)
class Palette:
    """
    To hold colours
    """

    positive: str = COLOUR_POSITIVE
    positive_faded: str = COLOUR_POSITIVE_FADED
    negative: str = COLOUR_NEGATIVE
    negative_faded: str = COLOUR_NEGATIVE_FADED
    call: str = COLOUR_CALL
    put: str = COLOUR_PUT
    axis: str = AXIS_LINE_COLOUR

    orange: str = ORANGE
    orange_faded: str = ORANGE_FADED

    white: str = WHITE
    very_light_grey: str = VERY_LIGHT_GREY
    medium_grey: str = MEDIUM_GREY
    black: str = BLACK

    medium_background: str = MEDIUM_BACKGROUND
    dark_background: str = DARK_BACKGROUND


DEFAULT_PALETTE = Palette()
__all__ = [
    "COLOUR_POSITIVE",
    "COLOUR_NEGATIVE",
    "COLOUR_CALL",
    "COLOUR_PUT",
    "AXIS_LINE_COLOUR",
    "Palette",
    "DEFAULT_PALETTE",
]
