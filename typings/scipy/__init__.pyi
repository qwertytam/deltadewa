"""Typing stubs for scipy.

Minimal, hand-maintained typing stubs for the scipy symbols used in this
project.
"""

# pylint: disable=missing-function-docstring, unused-argument, invalid-name
# ruff: noqa: UP037 N801

class norm_gen:
    """scipy.stats.norm_gen class."""

    def pdf(self, x: float) -> float: ...
    def cdf(self, x: float) -> float: ...
    def ppf(self, q: float) -> float: ...
    def __call__(
        self,
        loc: float = ...,
        scale: float = ...,
    ) -> "norm_gen": ...

class _StatsNS:
    """Namespace for scipy.stats symbols used in this project."""

    norm: norm_gen

stats: _StatsNS
