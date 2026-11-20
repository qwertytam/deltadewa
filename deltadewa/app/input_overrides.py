"""Overriding a fetched input, and editing the dividend yield (9b, D5/D7).

The logic behind `/design`'s Pricing inputs controls, with no Dash import, so
it is tested with plain values, like :mod:`deltadewa.app.trade_entry`. Each
action is two steps, the idiom the trade forms use:

1. :func:`review_entry` validates what was typed and says, in words, exactly
   what confirming would do, with a warning when your number is far from the
   feed's. Nothing is written.
2. :func:`record_entry` replays the same parsed entry into
   :class:`~deltadewa.state.ProgramState`.

Three actions need that gate, because each changes what every number on every
page is priced on:

* **Override spot or one option's IV**: your typed value is pinned above the
  feed until you clear it (D7). Lasts until cleared, so it can be forgotten:
  it is listed on `/monitor` and in the digest with its age and the feed's
  figure beside it.
* **Clear an override**: the feed prices it again; your value stays as the
  fallback.
* **Edit the dividend yield** (D5): never fetched (put-call parity cannot
  separate it from funding and timing), so it is typed and confirmed
  quarterly. Changing it re-solves every option's IV at the new yield.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from deltadewa.analysis.pricing_resolution import InputOrigin, OverrideKind

if TYPE_CHECKING:
    from collections.abc import Mapping

    from deltadewa.state import ProgramState

__all__ = [
    "EntryKind",
    "InputEntry",
    "InputEntryError",
    "Review",
    "parse_entry",
    "record_entry",
    "review_entry",
]

#: The form's ``target`` for the book's spot and for the dividend yield; an
#: option is ``"iv:<position_id>"``.
TARGET_SPOT: Final = "spot"
TARGET_DIVIDEND: Final = "dividend"
_IV_PREFIX: Final = "iv:"

_LISTED: Final = (
    "It is listed on /monitor and in the digest, with its age and what the "
    "feed says, so it is not forgotten."
)

#: A typed IV below this many percent is almost certainly a fraction typed
#: where a percentage was asked for (``0.27`` for 27%), which would price an
#: option at a quarter of one percent.
_MIN_IV_PCT: Final = 1.0
_MAX_IV_PCT: Final = 500.0
#: Yields at or above this are not a dividend yield.
_MAX_DIVIDEND_PCT: Final = 20.0


class InputEntryError(ValueError):
    """What was typed cannot be acted on; the message says why."""


class EntryKind(StrEnum):
    """What an entry does."""

    OVERRIDE_SPOT = "override_spot"
    OVERRIDE_IV = "override_iv"
    CLEAR_SPOT = "clear_spot"
    CLEAR_IV = "clear_iv"
    DIVIDEND = "dividend"


@dataclass(frozen=True)
class InputEntry:
    """One parsed, valid entry.

    Attributes:
        kind: What it does.
        value: The index level, the IV as a fraction, or the yield as a
            fraction. ``None`` for a clear.
        position_id: The option, for an IV entry.

    """

    kind: EntryKind
    value: float | None
    position_id: str | None = None


@dataclass(frozen=True)
class Review:
    """What confirming an entry would do.

    Attributes:
        summary: One sentence.
        lines: The facts behind it.
        warnings: What to think twice about; never blocks.

    """

    summary: str
    lines: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _number(raw: object, what: str) -> float:
    """Read a typed number, refusing blanks, text and non-finite values."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise InputEntryError(f"Enter {what}.")
    try:
        value = float(str(raw).replace(",", "").replace("%", "").strip())
    except ValueError as exc:
        raise InputEntryError(f"{what.capitalize()} is not a number.") from exc
    if not math.isfinite(value):
        raise InputEntryError(f"{what.capitalize()} is not a number.")
    return value


def _leg_id(target: str, state: ProgramState) -> str:
    position_id = target.removeprefix(_IV_PREFIX)
    if all(p.position_id != position_id for p in state.positions_snapshot()):
        raise InputEntryError(
            "That option is no longer in the book; pick it again.",
        )
    return position_id


def parse_entry(raw: Mapping[str, Any], state: ProgramState) -> InputEntry:
    """Turn the form's raw values into one valid entry.

    Args:
        raw: ``action`` (``"set"`` or ``"clear"``), ``target`` (``"spot"``,
            ``"dividend"`` or ``"iv:<position_id>"``) and, for a set,
            ``value`` (spot as an index level; an IV or a yield in percent).
        state: The program state, for which options exist.

    Returns:
        The entry.

    Raises:
        InputEntryError: If anything is missing, unreadable or implausible.

    """
    target = str(raw.get("target") or "")
    action = str(raw.get("action") or "set")
    if not target:
        raise InputEntryError("Pick the input first.")
    if target == TARGET_DIVIDEND:
        pct = _number(raw.get("value"), "the dividend yield (in %)")
        if not 0.0 <= pct < _MAX_DIVIDEND_PCT:
            raise InputEntryError(
                f"A dividend yield is between 0% and {_MAX_DIVIDEND_PCT:g}%; "
                f"{pct:g}% is not one.",
            )
        return InputEntry(EntryKind.DIVIDEND, pct / 100.0)
    if target == TARGET_SPOT:
        if action == "clear":
            return InputEntry(EntryKind.CLEAR_SPOT, None)
        spot = _number(raw.get("value"), "your spot")
        if spot <= 0.0:
            raise InputEntryError("A spot must be positive.")
        return InputEntry(EntryKind.OVERRIDE_SPOT, spot)
    if not target.startswith(_IV_PREFIX):
        raise InputEntryError("Pick the input first.")
    position_id = _leg_id(target, state)
    if action == "clear":
        return InputEntry(EntryKind.CLEAR_IV, None, position_id)
    pct = _number(raw.get("value"), "your IV (in %)")
    if pct < _MIN_IV_PCT or pct > _MAX_IV_PCT:
        raise InputEntryError(
            f"An IV is entered in percent, between {_MIN_IV_PCT:g} and "
            f"{_MAX_IV_PCT:g} (27.5 for 27.5%); {pct:g} is not one.",
        )
    return InputEntry(EntryKind.OVERRIDE_IV, pct / 100.0, position_id)


def _set_value(entry: InputEntry) -> float:
    """Return the value of an entry that sets one; a clear has none."""
    if entry.value is None:
        raise InputEntryError("Enter a value first.")
    return entry.value


def _feed_figure(state: ProgramState, entry: InputEntry) -> float | None:
    """Return what the feed says for the entry's input, if it says anything."""
    resolution = state.resolution
    if entry.kind in (EntryKind.OVERRIDE_SPOT, EntryKind.CLEAR_SPOT):
        value = resolution.spot
    elif entry.position_id is not None and (
        entry.position_id in resolution.legs
    ):
        value = resolution.legs[entry.position_id]
    else:
        return None
    return value.value if value.from_feed else value.fetched


def _leg_label(state: ProgramState, position_id: str | None) -> str:
    for position in state.positions_snapshot():
        if position.position_id == position_id:
            option = position.option
            return (
                f"{option.option_type.value} {option.strike_price:g} exp "
                f"{option.maturity_date:%Y-%m-%d}"
            )
    return "that option"


def review_entry(entry: InputEntry, state: ProgramState) -> Review:
    """Say what confirming *entry* would do. Writes nothing.

    Raises:
        InputEntryError: If the policy does not adopt the input, so there is
            nothing to override.

    """
    ips = state.ips_config
    policy = ips.pricing_feed if ips is not None else None
    if entry.kind is EntryKind.DIVIDEND:
        return _review_dividend(entry, state)
    adopt = frozenset(policy.adopt) if policy is not None else frozenset()
    needed = "spot" if entry.kind.name.endswith("SPOT") else "volatility"
    if needed not in adopt:
        raise InputEntryError(
            f"{needed} is not adopted from the feed (pricing_feed.adopt in "
            "ips.yaml), so there is nothing to override. Edit the value "
            "instead.",
        )
    fed = _feed_figure(state, entry)
    if entry.kind is EntryKind.OVERRIDE_SPOT:
        return _review_override_spot(entry, state, fed)
    if entry.kind is EntryKind.OVERRIDE_IV:
        return _review_override_iv(entry, state, fed)
    return _review_clear(entry, state, fed)


def _review_override_spot(
    entry: InputEntry,
    state: ProgramState,
    fed: float | None,
) -> Review:
    value = _set_value(entry)
    ips = state.ips_config
    lines = [
        "Your spot prices every number on every page until you clear it.",
        _LISTED,
        (
            "It does not re-solve the options' IVs: they stay solved at the "
            "chain's own index level."
        ),
    ]
    warnings: list[str] = []
    if fed is not None and fed > 0.0:
        gap = (value - fed) / fed * 100.0
        lines.insert(0, f"The feed says {fed:,.2f} today.")
        threshold = (
            ips.market_environment.spot_divergence_warn_pct
            if ips is not None
            else None
        )
        if threshold is not None and abs(gap) >= threshold:
            warnings.append(
                f"Your spot is {gap:+.2f}% from the feed's (the policy warns "
                f"from {threshold:g}%).",
            )
    return Review(
        f"Price the book on spot {value:,.2f} until you clear it.",
        tuple(lines),
        tuple(warnings),
    )


def _review_override_iv(
    entry: InputEntry,
    state: ProgramState,
    fed: float | None,
) -> Review:
    value = _set_value(entry)
    ips = state.ips_config
    policy = ips.pricing_feed if ips is not None else None
    label = _leg_label(state, entry.position_id)
    lines = [
        f"{label} is priced on your IV until you clear it.",
        _LISTED,
    ]
    warnings: list[str] = []
    if fed is not None:
        gap = (value - fed) * 100.0
        lines.insert(
            0,
            f"The feed's IV for it, solved at the book's rate and yield, is "
            f"{fed:.2%}.",
        )
        if policy is not None and abs(gap) >= policy.override_warn_vol_points:
            warnings.append(
                f"Your IV is {gap:+.1f} vol points from the feed's (the "
                f"policy warns from {policy.override_warn_vol_points:g}).",
            )
    return Review(
        f"Price {label} on IV {value:.2%} until you clear it.",
        tuple(lines),
        tuple(warnings),
    )


def _review_clear(
    entry: InputEntry,
    state: ProgramState,
    fed: float | None,
) -> Review:
    what = (
        "spot"
        if entry.kind is EntryKind.CLEAR_SPOT
        else _leg_label(state, entry.position_id)
    )
    lines = ["Your typed value stays, as the fallback."]
    if fed is not None:
        shown = f"{fed:,.2f}" if what == "spot" else f"{fed:.2%}"
        lines.insert(0, f"The feed says {shown}, and will price it again.")
    return Review(f"Let the feed price {what} again.", tuple(lines))


def _review_dividend(entry: InputEntry, state: ProgramState) -> Review:
    value = _set_value(entry)
    current = state.entered.dividend_yield
    return Review(
        f"Set the dividend yield to {value:.2%} (it is {current:.2%}).",
        (
            (
                "It is never fetched: put-call parity measures the dividend, "
                "funding and timing together and cannot isolate it. Confirm "
                "it against the published yield each quarter."
            ),
            (
                "Every option's IV is solved at the book's rate and yield, "
                "so changing it re-solves every adopted IV."
            ),
        ),
    )


def record_entry(entry: InputEntry, state: ProgramState) -> None:
    """Write *entry* to the program state.

    Raises:
        ConfirmationRequiredError: Never: the page's Review then Confirm is
            the gate, so this passes ``confirm=True``.
        ValueError: If the state refuses the value or the option.

    """
    kind = entry.kind
    if kind is EntryKind.DIVIDEND:
        state.update_market_conditions(dividend_yield=entry.value)
    elif kind is EntryKind.OVERRIDE_SPOT and entry.value is not None:
        state.set_input_override(OverrideKind.SPOT, entry.value, confirm=True)
    elif kind is EntryKind.OVERRIDE_IV and entry.value is not None:
        state.set_input_override(
            OverrideKind.VOLATILITY,
            entry.value,
            position_id=entry.position_id,
            confirm=True,
        )
    elif kind is EntryKind.CLEAR_SPOT:
        state.clear_input_override(OverrideKind.SPOT, confirm=True)
    elif kind is EntryKind.CLEAR_IV:
        state.clear_input_override(
            OverrideKind.VOLATILITY,
            position_id=entry.position_id,
            confirm=True,
        )


def origin_text(origin: InputOrigin) -> str:
    """Return the label a table shows for an input's origin."""
    return {
        InputOrigin.FETCHED: "fetched",
        InputOrigin.LAST_GOOD: "last good (feed not refreshed)",
        InputOrigin.OVERRIDE: "your override",
        InputOrigin.FALLBACK: "fallback: your value",
        InputOrigin.ENTERED: "your value",
    }[origin]
