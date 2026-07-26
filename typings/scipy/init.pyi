"""Typing stubs for scipy.

Minimal, hand-maintained typing stubs for the scipy symbols used in this
project.
"""

# pylint: disable=missing-function-docstring, unused-argument, invalid-name
# ruff: file-ignore[quoted-annotation, invalid-class-name]

class stats:
    """scipy stats class."""

    def norm(self, loc: float = 0.0, scale: float = 1.0) -> "norm_gen": ...

class norm_gen:
    """scipy.stats.norm_gen class."""

    def pdf(self, x: float) -> float: ...
    def cdf(self, x: float) -> float: ...
    def ppf(self, q: float) -> float: ...
