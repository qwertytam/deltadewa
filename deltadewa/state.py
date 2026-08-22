"""Shared server-side program state, backed by ``exports/``.

One hedge program, one shared ``OptionPortfolio`` + ``IpsConfig`` — not
per-browser-session state. Both viewers of the dashboard must see the same
book, and a single shared instance is what makes autosave meaningful: there
is exactly one file to keep in sync.

Persistence stays in :mod:`deltadewa.persistence`
(``PortfolioSerializer.export_to_json`` / ``import_portfolio``); this module
is the owner above it — it decides *when* to read and write, keeps the
in-memory portfolio authoritative between saves, and closes off two ways a
caller could silently lose work: an autosave nobody remembered to call, and a
destructive edit or import applied over unsaved changes. Every mutator on
``ProgramState`` marks the state dirty and immediately autosaves itself, and
the two destructive operations (``remove_position``, ``clear_positions``) and
``import_portfolio`` require an explicit ``confirm=True`` — there is no
context-manager or other path that hands back the live portfolio for
unguarded mutation, so a caller cannot reach a destructive
``OptionPortfolio`` method without going through the guard.

``ProgramState.portfolio`` returns the live, shared object — read it fresh
each time rather than caching a reference, since ``import_portfolio``
replaces the instance wholesale.

Concurrency (#299)
------------------
The server runs one worker with four threads (``Dockerfile``'s ``CMD``:
``--workers 1 --worker-class gthread --threads 4``) — deliberately, so that
this stays one shared in-memory instance rather than forking into several
independently-drifting books. Four request threads therefore share it.

One ``threading.RLock`` guards every mutator, both saves, and the
``import_portfolio`` portfolio replacement. It is an ``RLock`` because the
call graph nests: ``import_portfolio`` → ``_mutate_and_save`` →
``save_if_dirty``; a plain ``Lock`` deadlocks on the first mutation.

What the lock is *for* is easy to mistake.
``PortfolioSerializer.export_to_json`` already writes tmp-then-rename, so the
state file is never torn and never half-read. The unprotected failure was a
**lost update**: building the export data prices every position (slow), so a
thread could snapshot the book, have a second thread mutate *and* fully save
underneath it, then land its own older snapshot on top — reverting the second
change and clearing ``dirty``, so nothing would ever re-save it. Both writes
were individually atomic; what was missing is that snapshot-then-write is one
unit and the write order must be total. Holding the lock across both provides
that.

**Readers do not take the lock**, and that is what keeps a coarse lock from
becoming a latency bug: a page render prices the whole book, so a locked
reader would put mutators behind renders and renders behind saves. See
:attr:`ProgramState.portfolio` for the accepted-stale contract that buys, and
:meth:`ProgramState.positions_snapshot` for the one case that needs a
consistent view.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Final

from deltadewa import create_empty_portfolio
from deltadewa.clock import program_trading_date
from deltadewa.constants import OptionType
from deltadewa.ips_config import IpsConfigError, load_ips_config
from deltadewa.persistence import PortfolioSerializer
from deltadewa.reporting import PortfolioLogger

if TYPE_CHECKING:
    from datetime import datetime as dt

    from deltadewa.constants import ExerciseStyle
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition

STATE_FILENAME: Final = "program_state.json"

_logger = logging.getLogger(__name__)


class ConfirmationRequiredError(RuntimeError):
    """A destructive operation or an unsafe import was attempted.

    Raised when a destructive mutator is called without ``confirm=True``, or
    when ``import_portfolio`` would discard unsaved changes.
    """


class ProgramState:
    """Owns the one shared ``OptionPortfolio`` + ``IpsConfig``.

    Construct via :meth:`load`, not directly — the constructor takes
    already-resolved objects so ``load`` can keep all the "file missing /
    invalid" fallback logic in one place.
    """

    def __init__(
        self,
        *,
        portfolio: OptionPortfolio,
        loaded_from: Path | None,
        ips_config: IpsConfig | None,
        serializer: PortfolioSerializer,
        default_exercise_style: ExerciseStyle | None,
    ) -> None:
        """Wrap already-resolved state; prefer :meth:`load`."""
        self._portfolio = portfolio
        self._loaded_from = loaded_from
        self._ips_config = ips_config
        self._serializer = serializer
        self._default_exercise_style = default_exercise_style
        self._changelog = PortfolioLogger(name="program_state.changelog")
        self._dirty = False
        # RLock, not Lock: the mutators nest into _mutate_and_save() ->
        # save_if_dirty(), and import_portfolio() nests into both, so a
        # non-reentrant lock would deadlock on the first mutation (#299).
        self._lock = threading.RLock()

    @classmethod
    def load(
        cls,
        export_dir: Path,
        *,
        ips_path: str | Path = Path("config/ips.yaml"),
        default_exercise_style: ExerciseStyle | None = None,
    ) -> ProgramState:
        """Load the shared program state from ``export_dir``.

        Reads ``export_dir/program_state.json`` if present; otherwise starts
        an empty book and says so via a log record — startup never
        fabricates an empty portfolio silently.

        Args:
            export_dir: Directory holding the shared state file (and where
                autosaves are written).
            ips_path: Path to the hedge program policy file; ``str`` or
                ``Path``, matching ``load_ips_config`` (#182). If missing or
                invalid, ``ips_config`` is ``None`` and loading still
                succeeds — this never raises for that reason.
            default_exercise_style: Exercise style applied to positions in
                the loaded file that have no explicit ``exercise_style``.
                When ``None`` (the default) and an IPS loaded, this is
                taken from ``ips_config.pricing.exercise_style`` (#295) —
                pass an explicit value only to override the program's own
                policy.

        Returns:
            A ready-to-use ``ProgramState``.

        """
        serializer = PortfolioSerializer(export_dir=export_dir)
        state_path = export_dir / STATE_FILENAME

        # Policy is read before the book, because the book's valuation date
        # depends on it: `program.timezone` decides which day's close the
        # positions are priced against (#182). Without an IPS the program
        # falls back to the US equity calendar, not to the server's UTC.
        try:
            ips_config = load_ips_config(ips_path)
        except IpsConfigError as exc:
            _logger.warning(
                "ips.yaml unavailable, continuing without it: %s",
                exc,
            )
            ips_config = None

        # #295: an explicit caller override always wins; otherwise the
        # program's own policy sets the style positions get when they don't
        # carry one of their own. Before this, every real boot path (wsgi.py,
        # weekly_report.py, import_portfolio.py's initial ProgramState.load()
        # call) left this None regardless of what pricing.exercise_style
        # said, because ips_config was loaded here and then never consulted
        # for it — only unit tests that constructed the portfolio directly
        # (or passed default_exercise_style= explicitly) exercised the wired
        # case, so the gap shipped with a green suite.
        if default_exercise_style is None and ips_config is not None:
            default_exercise_style = ips_config.pricing.exercise_style

        as_of = program_trading_date(
            ips_config.program.timezone if ips_config is not None else None,
        )

        loaded_from: Path | None
        if state_path.exists():
            result = serializer.import_from_json(
                state_path,
                default_exercise_style=default_exercise_style,
                valuation_date=as_of,
            )
            portfolio = result["portfolio"]
            loaded_from = state_path
            _logger.info("Loaded shared program state from %s", state_path)
        else:
            portfolio = create_empty_portfolio(
                default_exercise_style=default_exercise_style,
                valuation_date=as_of,
            )
            loaded_from = None
            _logger.info(
                "No saved state at %s — starting an empty book",
                state_path,
            )

        return cls(
            portfolio=portfolio,
            loaded_from=loaded_from,
            ips_config=ips_config,
            serializer=serializer,
            default_exercise_style=default_exercise_style,
        )

    @property
    def portfolio(self) -> OptionPortfolio:
        """The live, shared portfolio. **Deliberately unlocked** (#299).

        Reading the attribute is a single load, so this never hands back a
        torn *reference* — even mid-``import_portfolio``, a caller gets
        either the old book or the new one. What it does not promise is
        that the object's *interior* holds still: a mutator on another
        thread can add, remove or edit a position while the caller is
        reading this one.

        That is the accepted trade, not an oversight. Taking the lock here
        would be the real regression — a page render prices the whole book
        while holding the portfolio, so a locked reader would queue
        mutators behind renders and renders behind saves. Renders tolerate
        a slightly stale book; they do not tolerate blocking.

        Use :meth:`positions_snapshot` where iteration must not tear.
        """
        return self._portfolio

    def positions_snapshot(self) -> tuple[OptionPosition, ...]:
        """Return a point-in-time copy of the positions, safe to iterate.

        Take this instead of iterating ``portfolio.positions`` directly
        when another thread could be mutating the book: a plain iteration
        races ``add_position``/``remove_position`` and raises
        ``RuntimeError: list changed size during iteration`` (#299).
        Copying the list under the lock is microseconds — unlike a save,
        it prices nothing.

        Note the limit: this gives a consistent *list*, not a consistent
        *book*. The ``OptionPosition`` objects are the live, shared ones, so
        ``update_position`` can still change one while the caller reads it.
        Closing that would need copy-on-write inside ``OptionPortfolio``.

        Returns:
            The positions held at the moment of the call.

        """
        with self._lock:
            return tuple(self._portfolio.positions)

    @property
    def ips_config(self) -> IpsConfig | None:
        """The hedge program policy, loaded once at startup. Read-only."""
        return self._ips_config

    @property
    def dirty(self) -> bool:
        """Whether the in-memory portfolio differs from the last save.

        Normally ``False`` immediately after any mutation, since every
        mutator autosaves itself. Becomes ``True`` only when an autosave
        attempt itself fails.

        Program-wide, not per-caller: one shared book means one flag. Under
        concurrency that has a visible consequence — a failed save on one
        thread leaves this ``True``, which makes another thread's
        ``import_portfolio`` refuse until it passes ``confirm=True``. The
        refusal is correct (there really are unsaved changes) even though
        the second operator did not cause them.
        """
        return self._dirty

    @property
    def loaded_from(self) -> Path | None:
        """The state file this instance was loaded from, or ``None``."""
        return self._loaded_from

    def save_if_dirty(self) -> bool:
        """Atomically persist to ``exports/program_state.json`` if dirty.

        Holds the state lock across the whole check-build-write-clear
        sequence, not just the flag (#299). The write itself was already
        atomic; what needed protecting is that a slow snapshot could
        otherwise land on top of a newer one and clear ``dirty`` with the
        newer change missing.

        Returns:
            Whether a write happened.

        """
        with self._lock:
            if not self._dirty:
                return False
            self._serializer.export_to_json(
                self._portfolio,
                self._changelog,
                filename=STATE_FILENAME,
            )
            self._dirty = False
            return True

    def export_snapshot(self, filename: str) -> Path:
        """Write a point-in-time copy of the live portfolio to *filename*.

        Unlike the mutators, this never touches ``dirty`` — it's a
        read-only snapshot for the operator to download, not a change to
        the live book, and it goes through this class's own serializer/
        changelog rather than a second ``PortfolioSerializer`` pointed at
        the same directory, so it stays inside the guarded session layer.

        Takes the same lock as the mutators (#299) — an operator must never
        download a book that never existed — but still never touches
        ``dirty``, since this is a copy, not a change to the live book. The
        cost is that an export blocks a concurrent edit for its duration;
        that is the point of a point-in-time snapshot, not a side effect.

        Args:
            filename: Name of the file to write under this state's
                export directory. Should not be ``STATE_FILENAME`` — a
                snapshot is a separate artifact, not the autosave slot.

        Returns:
            Path to the written file.

        """
        with self._lock:
            return self._serializer.export_to_json(
                self._portfolio,
                self._changelog,
                filename=filename,
            )

    def _mutate_and_save(self) -> None:
        with self._lock:
            self._dirty = True
            self.save_if_dirty()

    def add_position(  # pylint: disable=too-many-arguments
        self,
        strike_price: float,
        maturity_date: dt,
        quantity: int,
        option_type: OptionType = OptionType.CALL,
        contract_size: int | None = None,
        volatility: float | None = None,
        exercise_style: ExerciseStyle | None = None,
        entry_spot: float | None = None,
        entry_date: dt | None = None,
        entry_premium: float | None = None,
    ) -> OptionPosition:
        """Add a position. See ``OptionPortfolio.add_position``."""
        with self._lock:
            position = self._portfolio.add_position(
                strike_price=strike_price,
                maturity_date=maturity_date,
                quantity=quantity,
                option_type=option_type,
                contract_size=contract_size,
                volatility=volatility,
                exercise_style=exercise_style,
                entry_spot=entry_spot,
                entry_date=entry_date,
                entry_premium=entry_premium,
            )
            self._mutate_and_save()
            return position

    def update_position(  # pylint: disable=too-many-arguments
        self,
        index: int,
        quantity: int | None = None,
        strike: float | None = None,
        expiry: dt | None = None,
        option_type: OptionType | None = None,
        contract_size: int | None = None,
        volatility: float | None = None,
        exercise_style: ExerciseStyle | None = None,
    ) -> None:
        """Update a position by index.

        See ``OptionPortfolio.update_position``.

        The lock makes this operation atomic, but note what it cannot fix:
        *index* was chosen in the browser before the request, so a
        concurrent ``remove_position`` that shifts the list still leaves
        this editing a different leg than the operator picked. That needs
        stable position IDs, not a lock.
        """
        with self._lock:
            self._portfolio.update_position(
                index,
                quantity=quantity,
                strike=strike,
                expiry=expiry,
                option_type=option_type,
                contract_size=contract_size,
                volatility=volatility,
                exercise_style=exercise_style,
            )
            self._mutate_and_save()

    def set_volatility(self, volatility: float) -> None:
        """Set portfolio volatility. See ``OptionPortfolio.set_volatility``."""
        with self._lock:
            self._portfolio.set_volatility(volatility)
            self._mutate_and_save()

    def set_underlying_quantity(self, underlying_quantity: float) -> None:
        """Set underlying quantity.

        See ``OptionPortfolio.set_underlying_quantity``.
        """
        with self._lock:
            self._portfolio.set_underlying_quantity(underlying_quantity)
            self._mutate_and_save()

    def update_market_conditions(  # pylint: disable=too-many-arguments
        self,
        spot_price: float | None = None,
        volatility: float | None = None,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
        valuation_date: dt | None = None,
        override_custom_volatility: bool = False,
    ) -> None:
        """Update market conditions.

        See ``OptionPortfolio.update_market_conditions``.
        """
        with self._lock:
            self._portfolio.update_market_conditions(
                spot_price=spot_price,
                volatility=volatility,
                risk_free_rate=risk_free_rate,
                dividend_yield=dividend_yield,
                valuation_date=valuation_date,
                override_custom_volatility=override_custom_volatility,
            )
            self._mutate_and_save()

    def remove_position(self, index: int, *, confirm: bool = False) -> None:
        """Remove a position by index. Destructive — requires confirm=True."""
        if not confirm:
            raise ConfirmationRequiredError(
                "remove_position is destructive; pass confirm=True",
            )
        with self._lock:
            self._portfolio.remove_position(index)
            self._mutate_and_save()

    def clear_positions(self, *, confirm: bool = False) -> None:
        """Remove every position. Destructive — requires confirm=True."""
        if not confirm:
            raise ConfirmationRequiredError(
                "clear_positions is destructive; pass confirm=True",
            )
        with self._lock:
            self._portfolio.clear_positions()
            self._mutate_and_save()

    def import_portfolio(
        self,
        filepath: Path,
        *,
        default_exercise_style: ExerciseStyle | None = None,
        confirm: bool = False,
    ) -> None:
        """Replace the live portfolio from *filepath*.

        Refuses when there are unsaved changes unless ``confirm=True`` — an
        import would otherwise silently discard whatever hasn't been
        autosaved yet.

        The lock is held across the whole method, the parse of *filepath*
        included (#299). That is deliberate rather than merely simple: the
        ``dirty`` check and the portfolio replacement have to be one atomic
        unit or another thread can dirty the book in the gap, and an import
        in flight *should* block concurrent edits — those edits are about to
        be discarded anyway. The cost is that a large or slow source file
        blocks mutators for the duration of the read.

        Args:
            filepath: Path to a JSON or YAML portfolio export.
            default_exercise_style: Exercise style applied to positions with
                no explicit ``exercise_style``. Defaults to the style this
                ``ProgramState`` was loaded with.
            confirm: Must be ``True`` if ``dirty`` is currently ``True``.

        Raises:
            ConfirmationRequiredError: If ``dirty`` and not ``confirm``.

        """
        with self._lock:
            if self._dirty and not confirm:
                raise ConfirmationRequiredError(
                    "unsaved changes would be discarded; pass confirm=True",
                )
            style = (
                default_exercise_style
                if default_exercise_style is not None
                else self._default_exercise_style
            )
            result = self._serializer.import_portfolio(
                filepath,
                default_exercise_style=style,
            )
            self._portfolio = result["portfolio"]
            self._mutate_and_save()
