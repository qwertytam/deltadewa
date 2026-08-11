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
"""

from __future__ import annotations

import logging
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

    @classmethod
    def load(
        cls,
        export_dir: Path,
        *,
        ips_path: Path = Path("config/ips.yaml"),
        default_exercise_style: ExerciseStyle | None = None,
    ) -> ProgramState:
        """Load the shared program state from ``export_dir``.

        Reads ``export_dir/program_state.json`` if present; otherwise starts
        an empty book and says so via a log record — startup never
        fabricates an empty portfolio silently.

        Args:
            export_dir: Directory holding the shared state file (and where
                autosaves are written).
            ips_path: Path to the hedge program policy file. If missing or
                invalid, ``ips_config`` is ``None`` and loading still
                succeeds — this never raises for that reason.
            default_exercise_style: Exercise style applied to positions in
                the loaded file that have no explicit ``exercise_style``.

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
        """The live, shared portfolio."""
        return self._portfolio

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
        """
        return self._dirty

    @property
    def loaded_from(self) -> Path | None:
        """The state file this instance was loaded from, or ``None``."""
        return self._loaded_from

    def save_if_dirty(self) -> bool:
        """Atomically persist to ``exports/program_state.json`` if dirty.

        Returns:
            Whether a write happened.

        """
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

        Args:
            filename: Name of the file to write under this state's
                export directory. Should not be ``STATE_FILENAME`` — a
                snapshot is a separate artifact, not the autosave slot.

        Returns:
            Path to the written file.

        """
        return self._serializer.export_to_json(
            self._portfolio,
            self._changelog,
            filename=filename,
        )

    def _mutate_and_save(self) -> None:
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
        """
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
        self._portfolio.set_volatility(volatility)
        self._mutate_and_save()

    def set_underlying_quantity(self, underlying_quantity: float) -> None:
        """Set underlying quantity.

        See ``OptionPortfolio.set_underlying_quantity``.
        """
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
        self._portfolio.remove_position(index)
        self._mutate_and_save()

    def clear_positions(self, *, confirm: bool = False) -> None:
        """Remove every position. Destructive — requires confirm=True."""
        if not confirm:
            raise ConfirmationRequiredError(
                "clear_positions is destructive; pass confirm=True",
            )
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

        Args:
            filepath: Path to a JSON or YAML portfolio export.
            default_exercise_style: Exercise style applied to positions with
                no explicit ``exercise_style``. Defaults to the style this
                ``ProgramState`` was loaded with.
            confirm: Must be ``True`` if ``dirty`` is currently ``True``.

        Raises:
            ConfirmationRequiredError: If ``dirty`` and not ``confirm``.

        """
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
