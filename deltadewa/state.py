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

What this module still does not do (#355)
------------------------------------------
There is no reload path, and this is deliberate rather than an omission.
``self._portfolio`` is rebound in exactly one place — inside
``import_portfolio``, in-process, under the lock — and nowhere else. A file
watcher or an admin reload endpoint would rebind it from *outside* a
request, mid-render: a page callback reads :attr:`ProgramState.portfolio`
more than once, so half the panels would price the book a reload swapped in
underneath them and half would price the one from before it, with the
header disagreeing with the table. That is a new failure mode, worse than
the accepted-stale one above, not a variant of it.

Instead, :meth:`ProgramState.external_write_detected` lets a caller (the
importer CLI, or ``/health``) learn that ``program_state.json`` was written
by a process other than this one, so a human can decide to restart rather
than the app silently swapping its own book. That check is a single
``Path.stat()`` compared against an mtime recorded at ``load()``/save time —
it deliberately does **not** take the lock, for the same reason
``portfolio`` doesn't: it must stay cheap enough for a liveness probe, and a
stale read of it costs at most one late warning, never a torn book.

Position history (#313)
-----------------------
Every change to the book is also journaled to ``exports/history/``
(:mod:`deltadewa.history_store`), so realized carry can be measured. The
mutator decides which record:

* a trade method (``open_position``, ``close_position``,
  ``settle_position``, ``roll_position``) writes a
  :class:`~deltadewa.portfolio.history.Fill` with its price and fees;
* ``add_position`` writes an ``OPEN`` fill at ``entry_premium`` with the
  fees *not captured*. It is the existing entry form, and the form has no
  fee field;
* ``update_position`` (when it changes a lot's contract or quantity),
  ``remove_position``, ``clear_positions`` and ``import_portfolio``
  change the book without a fill, so they write a
  :class:`~deltadewa.portfolio.history.BookEdit`. Any period containing
  one reports itself as not reconcilable, naming the edit.

Market-input setters (spot, volatility, rates) write nothing: they move
the marks, not the book.

The order is **mutate, then journal, then save**, under the same lock.
Journaling first would record an edit that never happened every time the
mutation's own validation refused it, and that is the common failure: a
mistyped strike or an expired maturity. So the history is read once
before mutating, which fails fast on a corrupt file. If the append itself
then fails, the in-memory book is reverted to its last save, but only
when the file on disk is provably that save (same mtime, nothing
unsaved). Otherwise the change is left unsaved and marked dirty, and
``analysis.realized_carry.reconcile_book`` will name the lot the history
does not explain. Either way, the error is raised.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from deltadewa import create_empty_portfolio
from deltadewa.clock import program_now, program_trading_date
from deltadewa.constants import OptionType
from deltadewa.history_store import HISTORY_DIRNAME, HistoryStore
from deltadewa.ips_config import IpsConfigError, load_ips_config
from deltadewa.persistence import PortfolioSerializer
from deltadewa.portfolio.history import (
    BookEdit,
    CloseReason,
    ContractTerms,
    EditKind,
    Fill,
    FillKind,
    new_event_id,
)
from deltadewa.reporting import PortfolioLogger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from zoneinfo import ZoneInfo

    from deltadewa.constants import ExerciseStyle
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.history import OpenOrder
    from deltadewa.portfolio.position import OptionPosition

STATE_FILENAME: Final = "program_state.json"

# #325: the /design import picker's second source, alongside a state's own
# export directory — bundled example portfolios, not operator data. Shipped
# into the production image at this same relative path (Dockerfile).
_DEFAULT_EXAMPLES_DIR: Final = Path("examples/portfolios")

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportCandidate:
    """One server-side file :meth:`ProgramState.list_import_candidates` offers.

    Just enough to render one `/design` import-picker option: a path to
    pass back in as the import target, and a modified time to tell two
    same-named-looking files apart (or, more often, to show which export
    is newest).
    """

    path: Path
    modified_at: datetime


class ConfirmationRequiredError(RuntimeError):
    """A destructive operation or an unsafe import was attempted.

    Raised when a destructive mutator is called without ``confirm=True``, or
    when ``import_portfolio`` would discard unsaved changes.
    """


class ProgramState:  # pylint: disable=too-many-public-methods
    # A thin, lock-wrapped facade over OptionPortfolio: each portfolio
    # mutator gets exactly one public twin here (add this, mark_inputs_
    # reviewed for #367 is the latest), so the count tracks the domain
    # model's own mutator surface rather than growing responsibilities.
    """Owns the one shared ``OptionPortfolio`` + ``IpsConfig``.

    Construct via :meth:`load`, not directly — the constructor takes
    already-resolved objects so ``load`` can keep all the "file missing /
    invalid" fallback logic in one place.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        portfolio: OptionPortfolio,
        loaded_from: Path | None,
        ips_config: IpsConfig | None,
        serializer: PortfolioSerializer,
        default_exercise_style: ExerciseStyle | None,
        state_path: Path,
        ips_path: Path,
        ips_load_error: str | None = None,
        written_by: str | None = None,
        loaded_at: str | None = None,
        loaded_mtime: float | None = None,
        history: HistoryStore | None = None,
    ) -> None:
        """Wrap already-resolved state; prefer :meth:`load`.

        ``history`` is ``None`` only for a state constructed directly,
        e.g. in a test; :meth:`load` always attaches one. Without it,
        nothing is journaled.
        """
        self._history = history
        self._portfolio = portfolio
        self._loaded_from = loaded_from
        self._ips_config = ips_config
        self._ips_path = ips_path
        self._ips_load_error = ips_load_error
        self._serializer = serializer
        self._default_exercise_style = default_exercise_style
        self._changelog = PortfolioLogger(name="program_state.changelog")
        self._dirty = False
        # RLock, not Lock: the mutators nest into _mutate_and_save() ->
        # save_if_dirty(), and import_portfolio() nests into both, so a
        # non-reentrant lock would deadlock on the first mutation (#299).
        self._lock = threading.RLock()
        # #355: where the shared state file lives, and what this instance
        # last knew about it — who wrote it, and its mtime at that moment.
        # _own_mtime is updated on every write this instance makes (see
        # _mutate_and_save), so external_write_detected() only fires on a
        # change *this* process didn't make.
        self._state_path = state_path
        self._written_by = written_by
        self._loaded_at = loaded_at
        self._own_mtime = loaded_mtime

    @classmethod
    def load(
        cls,
        export_dir: Path,
        *,
        ips_path: str | Path = Path("config/ips.yaml"),
        default_exercise_style: ExerciseStyle | None = None,
        writer_label: str = "app",
        examples_dir: Path | None = None,
        history_dir: Path | None = None,
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
            examples_dir: The `/design` import picker's second listed
                source (#325), alongside *export_dir* itself. Defaults to
                ``_DEFAULT_EXAMPLES_DIR``; pass an explicit (e.g. empty)
                directory in a test to isolate it from the repo's real
                example portfolios.
            default_exercise_style: Exercise style applied to positions in
                the loaded file that have no explicit ``exercise_style``.
                When ``None`` (the default) and an IPS loaded, this is
                taken from ``ips_config.pricing.exercise_style`` (#295) —
                pass an explicit value only to override the program's own
                policy.
            writer_label: Identifies this process in every export it
                writes from here on (#355) — e.g. ``"app"`` for the live
                worker, ``"import_portfolio_cli"`` for the importer.
                Every history record this instance writes carries it too.
            history_dir: Where the position history lives (#313).
                Defaults to ``export_dir/history``, which is what puts
                it inside the nightly offsite backup.

        Returns:
            A ready-to-use ``ProgramState``.

        """
        resolved_examples_dir = (
            examples_dir if examples_dir is not None else _DEFAULT_EXAMPLES_DIR
        )
        serializer = PortfolioSerializer(
            export_dir=export_dir,
            examples_dir=resolved_examples_dir,
            writer_label=writer_label,
        )
        state_path = export_dir / STATE_FILENAME

        # Policy is read before the book, because the book's valuation date
        # depends on it: `program.timezone` decides which day's close the
        # positions are priced against (#182). Without an IPS the program
        # falls back to the US equity calendar, not to the server's UTC.
        ips_path = Path(ips_path)
        ips_load_error: str | None = None
        try:
            ips_config = load_ips_config(ips_path)
        except IpsConfigError as exc:
            _logger.warning(
                "ips.yaml unavailable, continuing without it: %s",
                exc,
            )
            ips_config = None
            # #385: carried forward, not discarded. IpsConfigError's own
            # messages are already written to be operator-readable
            # (ips_config.py's _require_field / band checks), and the
            # operator meeting this failure is looking at a page, not a
            # terminal — reaching the log meant an SSH hop plus
            # `docker compose logs app` for one str(exc).
            ips_load_error = str(exc)

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
        written_by: str | None = None
        loaded_at: str | None = None
        loaded_mtime: float | None = None
        if state_path.exists():
            result = serializer.import_from_json(
                state_path,
                default_exercise_style=default_exercise_style,
                valuation_date=as_of,
            )
            portfolio = result["portfolio"]
            loaded_from = state_path
            metadata = result.get("metadata") or {}
            written_by = metadata.get("written_by")
            loaded_at = metadata.get("exported_at")
            loaded_mtime = state_path.stat().st_mtime
            # #355: a file written by a different process than this one is
            # exactly the field-test near-miss — surface it at boot, since
            # that's when the wrong value would silently become live.
            if written_by is not None and written_by != writer_label:
                _logger.warning(
                    "Loaded shared program state from %s, written by "
                    "'%s' at %s — not this process ('%s'). If that write "
                    "happened after this worker last saved, this boot "
                    "picked up whatever that other process wrote.",
                    state_path,
                    written_by,
                    loaded_at,
                    writer_label,
                )
            else:
                _logger.info(
                    "Loaded shared program state from %s",
                    state_path,
                )
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
            state_path=state_path,
            ips_path=ips_path,
            ips_load_error=ips_load_error,
            written_by=written_by,
            loaded_at=loaded_at,
            loaded_mtime=loaded_mtime,
            history=HistoryStore(
                history_dir
                if history_dir is not None
                else export_dir / HISTORY_DIRNAME,
            ),
        )

    @property
    def history(self) -> HistoryStore | None:
        """The position-history store this state journals to (#313)."""
        return self._history

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
    def ips_path(self) -> Path:
        """The policy file this instance was loaded with (#385).

        Recorded whether or not it loaded — ``load`` previously took this
        and discarded it, so nothing said *which* file was tried. The
        pages name it when reporting a load failure, since the operator's
        first question is which ``ips.yaml`` this is.
        """
        return self._ips_path

    @property
    def ips_load_error(self) -> str | None:
        """Why ``ips.yaml`` did not load, or ``None`` if it did (#385).

        The ``IpsConfigError`` message itself, carried structurally from
        the ``except`` block in :meth:`load` — never re-derived from log
        text. ``None`` covers both "it loaded" and "no policy file was
        involved at all" (a test constructing this directly); callers
        distinguish those via :attr:`ips_config`.
        """
        return self._ips_load_error

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

    @property
    def state_path(self) -> Path:
        """Where this instance's shared state file lives (#355).

        Set at construction whether or not the file existed yet — this is
        the path a save would write to, not just one it has read from.
        """
        return self._state_path

    @property
    def written_by(self) -> str | None:
        """Who wrote the state file this instance last knew about (#355).

        The ``metadata.written_by`` label from the load, updated after
        every save this instance makes. ``None`` for a fresh book with no
        file yet, or a file that predates this field.
        """
        return self._written_by

    @property
    def loaded_at(self) -> str | None:
        """When the known-about state file was last written (#355).

        The ``metadata.exported_at`` timestamp from the load, updated
        after every save this instance makes. ``None`` for a fresh book.
        """
        return self._loaded_at

    def external_write_detected(self) -> bool:
        """Whether ``state_path`` changed since this instance last knew.

        True when the file's on-disk mtime no longer matches what this
        instance last loaded or wrote — i.e. another process (the CLI
        importer, most likely) has written it since. **Deliberately
        unlocked**, like :attr:`portfolio` (#299/#355): this is a liveness
        signal, not a mutation, so it must stay cheap enough to sit behind
        ``/health`` — one ``Path.stat()``, no lock, no reprice. A stale
        read costs at most one late warning, never a torn book.

        Returns:
            ``False`` if the file doesn't exist, or its mtime matches what
            this instance last recorded. ``True`` otherwise.

        """
        try:
            current_mtime = self._state_path.stat().st_mtime
        except FileNotFoundError:
            return False
        if self._own_mtime is None:
            return True
        return current_mtime != self._own_mtime

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
            # #355: this instance just became the file's most recent
            # writer — record that so a later external_write_detected()
            # only fires on a change this instance didn't make itself.
            mtime = self._state_path.stat().st_mtime
            self._own_mtime = mtime
            self._written_by = self._serializer.writer_label
            self._loaded_at = datetime.fromtimestamp(
                mtime,
                tz=UTC,
            ).isoformat()
            return True

    def export_snapshot(self, filename: str, *, fmt: str = "json") -> Path:
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
            fmt: ``"json"`` (default) or ``"yaml"`` (#325) — YAML matches
                the hand-edited/example files an operator actually diffs
                an export against. The two share one importable shape
                (``PortfolioSerializer._build_export_data``), so which one
                is written is presentation, not a round-trip concern.

        Returns:
            Path to the written file.

        Raises:
            ValueError: ``fmt="yaml"`` but PyYAML isn't installed
                (defensive — it's a main-group dependency, so this
                shouldn't fire in practice).

        """
        with self._lock:
            if fmt == "yaml":
                path = self._serializer.export_to_yaml(
                    self._portfolio,
                    self._changelog,
                    filename=filename,
                )
                if path is None:
                    raise ValueError(
                        "PyYAML not installed; cannot export to YAML.",
                    )
                return path
            return self._serializer.export_to_json(
                self._portfolio,
                self._changelog,
                filename=filename,
            )

    def list_import_candidates(self) -> list[ImportCandidate]:
        """List server-side files `/design`'s import picker can offer.

        Sources: this state's own export directory (autosaves and prior
        snapshot exports) and ``examples_dir`` (bundled example
        portfolios) — the two sources #325 asks for — each via the
        serializer's own directory listing
        (:meth:`PortfolioSerializer.list_available_files`). The live
        autosave file (``STATE_FILENAME``) is excluded: re-importing the
        running book onto itself isn't a meaningful choice. Sorted
        newest-first.

        Read-only, and deliberately takes no lock — same posture as
        :attr:`portfolio` and :meth:`external_write_detected`: a listing
        that's a moment stale costs nothing, since the confirm-gated
        import that follows re-reads the chosen file fresh.
        """
        candidates: list[ImportCandidate] = []
        for directory in (
            self._serializer.export_dir,
            self._serializer.examples_dir,
        ):
            if directory is None:
                continue
            available = self._serializer.list_available_files(directory)
            for path in [*available["json"], *available["yaml"]]:
                if path.name == STATE_FILENAME:
                    continue
                candidates.append(
                    ImportCandidate(
                        path=path,
                        modified_at=datetime.fromtimestamp(
                            path.stat().st_mtime,
                            tz=UTC,
                        ),
                    ),
                )
        candidates.sort(key=lambda c: c.modified_at, reverse=True)
        return candidates

    def _mutate_and_save(self) -> None:
        with self._lock:
            self._dirty = True
            self.save_if_dirty()

    # ── Position history (#313) ─────────────────────────────────────────

    def _timezone(self) -> ZoneInfo | None:
        if self._ips_config is None:
            return None
        return self._ips_config.program.timezone

    def _program_date(self, instant: datetime | None = None) -> date:
        """Return the program trading date, of *instant* or of now."""
        if instant is not None and instant.tzinfo is None:
            return instant.date()
        return program_trading_date(self._timezone(), now=instant).date()

    def _check_history_readable(self) -> None:
        """Fail before mutating if the history cannot take a record."""
        if self._history is not None:
            self._history.load()

    def _journal_and_save(self, records: Sequence[Fill | BookEdit]) -> None:
        """Journal *records* for a mutation already applied, then save.

        Called under the lock, after the in-memory book has changed. See
        the module docstring's "Position history" for why the order is
        mutate, journal, save, and what happens when the journal write
        fails.
        """
        if self._history is not None:
            try:
                self._history.append_events(records)
            except Exception:
                self._revert_unjournaled_change()
                raise
        self._mutate_and_save()

    def _revert_unjournaled_change(self) -> None:
        """Put the book back to its last save after a failed journal write.

        Only when the state file on disk is exactly what this instance
        last wrote or loaded, and nothing was unsaved before: then that
        file *is* the book before the mutation, and reloading it undoes
        the change cleanly. Otherwise reloading would lose something, so
        the change is kept, marked unsaved, and left for
        ``reconcile_book`` to report.

        **Never raises.** This runs inside the caller's ``except``, so a
        raise here would replace the journal error the operator needs to see
        with a reload error, and — worse — skip the ``dirty`` flag below,
        leaving ``/health`` reporting "no unsaved changes" over a book that
        holds one. Any failure to revert falls through to the same
        keep-and-flag path as a revert that was never safe.
        """
        try:
            on_disk: float | None = self._state_path.stat().st_mtime
        except OSError:
            on_disk = None
        if (
            not self._dirty
            and on_disk is not None
            and on_disk == self._own_mtime
        ):
            try:
                result = self._serializer.import_from_json(
                    self._state_path,
                    default_exercise_style=self._default_exercise_style,
                    valuation_date=self._portfolio.valuation_date,
                )
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception(
                    "Reloading the last save to undo an unjournaled change "
                    "failed",
                )
            else:
                self._portfolio = result["portfolio"]
                _logger.error(
                    "Position history write failed; the book was reverted "
                    "to its last save so the two still agree",
                )
                return
        self._dirty = True
        _logger.error(
            "Position history write failed and the book could not be "
            "reverted safely; the change is unsaved and the history does "
            "not record it",
        )

    def _find_position(self, position_id: str) -> tuple[int, OptionPosition]:
        for index, position in enumerate(self._portfolio.positions):
            if position.position_id == position_id:
                return index, position
        raise KeyError(f"no position with id {position_id!r}")

    def _edit(  # pylint: disable=too-many-arguments
        self,
        kind: EditKind,
        *,
        position_id: str | None,
        before: tuple[ContractTerms, int] | None,
        after: tuple[ContractTerms, int] | None,
        detail: str,
    ) -> BookEdit:
        return BookEdit(
            event_id=new_event_id(),
            kind=kind,
            effective_date=self._program_date(),
            recorded_at=program_now(self._timezone()),
            written_by=self._serializer.writer_label,
            position_id=position_id,
            before=before[0] if before else None,
            after=after[0] if after else None,
            quantity_before=before[1] if before else None,
            quantity_after=after[1] if after else None,
            detail=detail,
        )

    def _fill(  # pylint: disable=too-many-arguments
        self,
        kind: FillKind,
        position: OptionPosition,
        *,
        quantity: int,
        price_per_share: float | None,
        fees: float | None,
        trade_date: date,
        reason: CloseReason | None = None,
        roll_id: str | None = None,
        note: str | None = None,
    ) -> Fill:
        return Fill(
            event_id=new_event_id(),
            kind=kind,
            trade_date=trade_date,
            recorded_at=program_now(self._timezone()),
            written_by=self._serializer.writer_label,
            position_id=position.position_id,
            terms=ContractTerms.from_position(position),
            quantity=quantity,
            price_per_share=price_per_share,
            fees=fees,
            reason=reason,
            roll_id=roll_id,
            note=note,
        )

    @staticmethod
    def _lot(position: OptionPosition) -> tuple[ContractTerms, int]:
        return ContractTerms.from_position(position), int(position.quantity)

    @staticmethod
    def _describe_lot(lot: tuple[ContractTerms, int]) -> str:
        terms, quantity = lot
        return f"{quantity:+d} x {terms.describe()}"

    # ── Mutators ────────────────────────────────────────────────────────

    def add_position(  # pylint: disable=too-many-arguments
        self,
        strike_price: float,
        maturity_date: datetime,
        quantity: int,
        option_type: OptionType = OptionType.CALL,
        contract_size: int | None = None,
        volatility: float | None = None,
        exercise_style: ExerciseStyle | None = None,
        entry_spot: float | None = None,
        entry_date: datetime | None = None,
        entry_premium: float | None = None,
        structure_id: str | None = None,
    ) -> OptionPosition:
        """Add a position. See ``OptionPortfolio.add_position``.

        Journaled as an ``OPEN`` fill at ``entry_premium``, dated
        ``entry_date`` (or today), with fees *not captured*: this is the
        existing entry form, which has no fee field. Use
        :meth:`open_position` to record a trade with its fees.
        """
        with self._lock:
            self._check_history_readable()
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
                structure_id=structure_id,
            )
            self._journal_and_save(
                [
                    self._fill(
                        FillKind.OPEN,
                        position,
                        quantity=int(quantity),
                        price_per_share=entry_premium,
                        fees=None,
                        trade_date=self._program_date(entry_date),
                        note="entered through add_position",
                    ),
                ],
            )
            return position

    def update_position(  # pylint: disable=too-many-arguments
        self,
        index: int,
        quantity: int | None = None,
        strike: float | None = None,
        expiry: datetime | None = None,
        option_type: OptionType | None = None,
        contract_size: int | None = None,
        volatility: float | None = None,
        exercise_style: ExerciseStyle | None = None,
        *,
        stamp_as_of: datetime | None = None,
    ) -> None:
        """Update a position by index.

        See ``OptionPortfolio.update_position``.

        The lock makes this operation atomic, but note what it cannot fix:
        *index* was chosen in the browser before the request, so a
        concurrent ``remove_position`` that shifts the list still leaves
        this editing a different leg than the operator picked. That needs
        stable position IDs, not a lock.

        A change to the lot's contract or quantity is journaled as an
        ``AMEND`` book edit, a change with no fill. A volatility-only
        edit changes the marks, not the book, and is not journaled.
        """
        with self._lock:
            self._check_history_readable()
            positions = self._portfolio.positions
            target = positions[index] if 0 <= index < len(positions) else None
            before = self._lot(target) if target is not None else None
            self._portfolio.update_position(
                index,
                quantity=quantity,
                strike=strike,
                expiry=expiry,
                option_type=option_type,
                contract_size=contract_size,
                volatility=volatility,
                exercise_style=exercise_style,
                stamp_as_of=stamp_as_of,
            )
            records: list[Fill | BookEdit] = []
            if target is not None and before is not None:
                after = self._lot(target)
                if after != before:
                    records.append(
                        self._edit(
                            EditKind.AMEND,
                            position_id=target.position_id,
                            before=before,
                            after=after,
                            detail=(
                                f"{self._describe_lot(before)} edited to "
                                f"{self._describe_lot(after)}"
                            ),
                        ),
                    )
            self._journal_and_save(records)

    def set_volatility(
        self,
        volatility: float,
        *,
        stamp_as_of: datetime | None = None,
    ) -> None:
        """Set portfolio volatility. See ``OptionPortfolio.set_volatility``."""
        with self._lock:
            self._portfolio.set_volatility(
                volatility,
                stamp_as_of=stamp_as_of,
            )
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
        valuation_date: datetime | None = None,
        override_custom_volatility: bool = False,
        *,
        stamp_as_of: datetime | None = None,
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
                stamp_as_of=stamp_as_of,
            )
            self._mutate_and_save()

    def mark_inputs_reviewed(
        self,
        *,
        as_of: datetime | None = None,
        confirm: bool = False,
    ) -> None:
        """Assert every hand-entered pricing input is current as of now.

        See ``OptionPortfolio.confirm_current_inputs``. Confirm-gated
        like the destructive mutators below, but for the opposite
        reason: this doesn't destroy data, it *erases a staleness
        signal* — every existing AGING/UNKNOWN entry in the provenance
        ledger (#367) reads FRESH immediately afterward, so it must be a
        deliberate operator act, not a side effect of an unrelated call.

        Args:
            as_of: When this confirmation is deemed to have happened.
                Defaults to ``program_now()``.
            confirm: Must be ``True``.

        Raises:
            ConfirmationRequiredError: If not ``confirm``.

        """
        if not confirm:
            raise ConfirmationRequiredError(
                "mark_inputs_reviewed asserts every pricing input is "
                "current; pass confirm=True",
            )
        with self._lock:
            self._portfolio.confirm_current_inputs(as_of=as_of)
            self._mutate_and_save()

    def record_liquidity(  # pylint: disable=too-many-arguments
        self,
        position_id: str,
        *,
        bid: float,
        ask: float,
        open_interest: int | None,
        observed_at: datetime | None = None,
    ) -> None:
        """Record the operator's quote for one leg (8c, N10).

        See ``OptionPortfolio.record_liquidity``. Not confirm-gated,
        unlike :meth:`mark_inputs_reviewed`: this records new data the
        operator just read; it erases no staleness signal it has not
        replaced with a real observation.
        """
        with self._lock:
            self._portfolio.record_liquidity(
                position_id,
                bid=bid,
                ask=ask,
                open_interest=open_interest,
                observed_at=observed_at,
            )
            self._mutate_and_save()

    def remove_position(self, index: int, *, confirm: bool = False) -> None:
        """Remove a position by index. Destructive — requires confirm=True.

        Journaled as a ``DELETE`` book edit: the lot leaves with no
        proceeds recorded. To record the cash, use :meth:`close_position`
        or :meth:`settle_position` instead.
        """
        if not confirm:
            raise ConfirmationRequiredError(
                "remove_position is destructive; pass confirm=True",
            )
        with self._lock:
            self._check_history_readable()
            positions = self._portfolio.positions
            target = positions[index] if 0 <= index < len(positions) else None
            self._portfolio.remove_position(index)
            records: list[Fill | BookEdit] = []
            if target is not None:
                lot = self._lot(target)
                records.append(
                    self._edit(
                        EditKind.DELETE,
                        position_id=target.position_id,
                        before=lot,
                        after=None,
                        detail=(
                            f"{self._describe_lot(lot)} removed with no "
                            "proceeds recorded"
                        ),
                    ),
                )
            self._journal_and_save(records)

    def clear_positions(self, *, confirm: bool = False) -> None:
        """Remove every position. Destructive — requires confirm=True.

        Journaled as one ``DELETE`` book edit per lot.
        """
        if not confirm:
            raise ConfirmationRequiredError(
                "clear_positions is destructive; pass confirm=True",
            )
        with self._lock:
            self._check_history_readable()
            lots = [
                (position.position_id, self._lot(position))
                for position in self._portfolio.positions
            ]
            self._portfolio.clear_positions()
            self._journal_and_save(
                [
                    self._edit(
                        EditKind.DELETE,
                        position_id=position_id,
                        before=lot,
                        after=None,
                        detail=(
                            f"{self._describe_lot(lot)} removed by clearing "
                            "the book, with no proceeds recorded"
                        ),
                    )
                    for position_id, lot in lots
                ],
            )

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

        Journaled as one ``REPLACE`` book edit: the whole book changed
        with no fill, so lot-level reconciliation restarts at the next
        mark.

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
            self._check_history_readable()
            style = (
                default_exercise_style
                if default_exercise_style is not None
                else self._default_exercise_style
            )
            result = self._serializer.import_portfolio(
                filepath,
                default_exercise_style=style,
            )
            lots_before = len(self._portfolio.positions)
            self._portfolio = result["portfolio"]
            self._journal_and_save(
                [
                    self._edit(
                        EditKind.REPLACE,
                        position_id=None,
                        before=None,
                        after=None,
                        detail=(
                            f"book replaced from {Path(filepath).name}: "
                            f"{lots_before} lots before, "
                            f"{len(self._portfolio.positions)} after"
                        ),
                    ),
                ],
            )

    # ── Trades, recorded with their cash (#313) ─────────────────────────

    def open_position(
        self,
        order: OpenOrder,
        *,
        trade_date: date | None = None,
        roll_id: str | None = None,
        note: str | None = None,
    ) -> OptionPosition:
        """Open a lot and record the trade as an ``OPEN`` fill.

        Args:
            order: The contract, quantity, fill price and fees.
            trade_date: When it traded; today's program date if ``None``.
            roll_id: Links this open to the close it rolls from.
            note: Free text kept with the fill.

        Returns:
            The new position.

        """
        with self._lock:
            self._check_history_readable()
            position = self._add_from_order(order, trade_date=trade_date)
            self._journal_and_save(
                [
                    self._open_fill(
                        position,
                        order,
                        trade_date=trade_date,
                        roll_id=roll_id,
                        note=note,
                    ),
                ],
            )
            return position

    def close_position(  # pylint: disable=too-many-arguments
        self,
        position_id: str,
        *,
        contracts: int,
        price_per_share: float,
        fees: float,
        reason: CloseReason,
        trade_date: date | None = None,
        note: str | None = None,
        confirm: bool = False,
    ) -> None:
        """Close all or part of a lot and record the proceeds.

        Args:
            position_id: The lot.
            contracts: How many contracts to close, as a positive count.
                The direction comes from the lot: closing a long lot
                sells, closing a short lot buys back.
            price_per_share: The fill price.
            fees: Commissions and fees, ``>= 0``.
            reason: ``ROUTINE`` or ``MONETIZATION``: whether the proceeds
                reduce gross carry or are reported as a harvested gain.
            trade_date: When it traded; today's program date if ``None``.
            note: Free text kept with the fill.
            confirm: Must be ``True``; this removes contracts from the book.

        Raises:
            ConfirmationRequiredError: If not ``confirm``.
            KeyError: If no lot has *position_id*.
            ValueError: If *contracts* is not between 1 and the lot size.

        """
        if not confirm:
            raise ConfirmationRequiredError(
                "close_position removes contracts; pass confirm=True",
            )
        with self._lock:
            self._check_history_readable()
            index, position = self._find_position(position_id)
            held = int(position.quantity)
            if not 0 < contracts <= abs(held):
                raise ValueError(
                    f"cannot close {contracts} of a {abs(held)}-contract lot",
                )
            direction = 1 if held > 0 else -1
            fill = self._fill(
                FillKind.CLOSE,
                position,
                quantity=-direction * contracts,
                price_per_share=price_per_share,
                fees=fees,
                trade_date=trade_date or self._program_date(),
                reason=reason,
                note=note,
            )
            if contracts == abs(held):
                self._portfolio.remove_position(index)
            else:
                self._portfolio.update_position(
                    index,
                    quantity=held - direction * contracts,
                )
            self._journal_and_save([fill])

    def settle_position(  # pylint: disable=too-many-arguments
        self,
        position_id: str,
        *,
        settlement_per_share: float,
        fees: float,
        trade_date: date | None = None,
        note: str | None = None,
        confirm: bool = False,
    ) -> None:
        """Settle an expired lot and record the settlement cash.

        SPX options are European and cash-settled, so expiry, exercise and
        assignment are all settlements. A worthless expiry settles at
        ``0.0``. The lot leaves the book.

        Args:
            position_id: The lot.
            settlement_per_share: Intrinsic value per share at the
                settlement price; ``0.0`` when it expired worthless.
            fees: Commissions and fees, ``>= 0``.
            trade_date: The settlement date; today's program date if
                ``None``. Must be on or after the lot's expiry.
            note: Free text kept with the fill.
            confirm: Must be ``True``; this removes the lot from the book.

        Raises:
            ConfirmationRequiredError: If not ``confirm``.
            KeyError: If no lot has *position_id*.
            ValueError: If *trade_date* is before the lot's expiry.

        """
        if not confirm:
            raise ConfirmationRequiredError(
                "settle_position removes the lot; pass confirm=True",
            )
        with self._lock:
            self._check_history_readable()
            index, position = self._find_position(position_id)
            settled_on = trade_date or self._program_date()
            expiry = position.option.maturity_date.date()
            if settled_on < expiry:
                raise ValueError(
                    f"lot expires {expiry}; it cannot settle on {settled_on}",
                )
            fill = self._fill(
                FillKind.SETTLE,
                position,
                quantity=-int(position.quantity),
                price_per_share=settlement_per_share,
                fees=fees,
                trade_date=settled_on,
                reason=CloseReason.ROUTINE,
                note=note,
            )
            self._portfolio.remove_position(index)
            self._journal_and_save([fill])

    def roll_position(  # pylint: disable=too-many-arguments
        self,
        position_id: str,
        *,
        close_price_per_share: float,
        close_fees: float,
        into: OpenOrder,
        reason: CloseReason = CloseReason.ROUTINE,
        trade_date: date | None = None,
        note: str | None = None,
        confirm: bool = False,
    ) -> OptionPosition:
        """Close a whole lot and open its replacement, as two linked fills.

        The handbook records a roll as two events, each at its own fill
        price, even when the broker priced it as one package: the net
        debit can be recovered by subtraction, but the two fills cannot
        be recovered from the net. Both fills share one ``roll_id``.

        Args:
            position_id: The lot being rolled out of.
            close_price_per_share: Its fill price.
            close_fees: Its commissions and fees.
            into: The lot being rolled into, with its own fill and fees.
            reason: The close's reason; a scheduled roll is ``ROUTINE``.
            trade_date: When it traded; today's program date if ``None``.
            note: Free text kept with both fills.
            confirm: Must be ``True``; this removes the old lot.

        Returns:
            The new position.

        Raises:
            ConfirmationRequiredError: If not ``confirm``.
            KeyError: If no lot has *position_id*.

        """
        if not confirm:
            raise ConfirmationRequiredError(
                "roll_position removes the old lot; pass confirm=True",
            )
        with self._lock:
            self._check_history_readable()
            index, old = self._find_position(position_id)
            roll_id = new_event_id()
            traded = trade_date or self._program_date()
            close_fill = self._fill(
                FillKind.CLOSE,
                old,
                quantity=-int(old.quantity),
                price_per_share=close_price_per_share,
                fees=close_fees,
                trade_date=traded,
                reason=reason,
                roll_id=roll_id,
                note=note,
            )
            # Add before removing: if the new lot is refused (an expired
            # maturity, say), nothing has changed yet. Appending leaves
            # the old lot's index where it was.
            new = self._add_from_order(into, trade_date=traded)
            self._portfolio.remove_position(index)
            self._journal_and_save(
                [
                    close_fill,
                    self._open_fill(
                        new,
                        into,
                        trade_date=traded,
                        roll_id=roll_id,
                        note=note,
                    ),
                ],
            )
            return new

    def _add_from_order(
        self,
        order: OpenOrder,
        *,
        trade_date: date | None,
    ) -> OptionPosition:
        today = self._program_date()
        traded = trade_date or today
        entry_date = program_trading_date(
            self._timezone(),
        ).replace(year=traded.year, month=traded.month, day=traded.day)
        return self._portfolio.add_position(
            strike_price=order.strike_price,
            maturity_date=order.maturity_date,
            quantity=order.quantity,
            option_type=order.option_type,
            contract_size=order.contract_size,
            volatility=order.volatility,
            exercise_style=order.exercise_style,
            entry_date=entry_date,
            entry_premium=order.price_per_share,
            structure_id=order.structure_id,
        )

    def _open_fill(
        self,
        position: OptionPosition,
        order: OpenOrder,
        *,
        trade_date: date | None,
        roll_id: str | None,
        note: str | None,
    ) -> Fill:
        return self._fill(
            FillKind.OPEN,
            position,
            quantity=order.quantity,
            price_per_share=order.price_per_share,
            fees=order.fees,
            trade_date=trade_date or self._program_date(),
            roll_id=roll_id,
            note=note,
        )
