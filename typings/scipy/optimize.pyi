"""Typing stubs for scipy.optimize.

Minimal, hand-maintained typing stubs for the scipy.optimize symbols used in
this project.
"""

# pylint: disable=missing-function-docstring, unused-argument, invalid-name

from collections.abc import Callable

def brentq(
    f: Callable[[float], float],
    a: float,
    b: float,
    xtol: float = ...,
    rtol: float = ...,
    maxiter: int = ...,
    full_output: bool = ...,
    disp: bool = ...,
) -> float: ...
