"""Batch pricer for efficient portfolio valuation across scenario grids."""

import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime as dt
from typing import Any

import numpy as np

from deltadewa.clock import days_between
from deltadewa.constants import FDGridResolution, OptionType
from deltadewa.portfolio.position import OptionPosition
from deltadewa.valuation import OptionValuation
from deltadewa.warnings import ClosedFormAccuracyWarning


class BatchPricer:
    """Efficient batch pricer for portfolio valuation across scenario grids.

    Optimizes portfolio valuation by:


    1. **Caching** ``OptionValuation`` instances per ``(position, date)``
       — reduces QuantLib environment constructions from PxSxT to PxT,
       where P=positions, S=spot scenarios, T=time points.
    2. **Closed-form engine** (optional) — swap the FD grid for the
       Bjerksund-Stensland 2002 analytic approximation, giving ~10-20x
       faster per-call pricing with <1% error on near-ATM options.
       A :class:`~deltadewa.warnings.ClosedFormAccuracyWarning` is emitted
       once per position that falls into a known low-accuracy regime.
    3. **Thread-parallel position sweeps** (optional) — each position's
       spot sweep is independent, so ``ThreadPoolExecutor`` parallelises
       across positions.

    Choosing a pricing mode
    -----------------------
    ``use_closed_form=False, max_workers=1`` (defaults):
        Original behaviour. Most accurate; no concurrency.

    ``use_closed_form=True, max_workers=1``:
        ~10-20x faster per call; suitable when accuracy can be relaxed.
        Recommended for large scenario grids.

    ``use_closed_form=False, max_workers=N``:
        Parallel FD sweeps. Good when accuracy must be preserved and
        multiple CPU cores are available.

    ``use_closed_form=True, max_workers=N``:
        Maximum throughput. Recommended for stress scenario sweeps.

    Thread safety note
    ------------------
    The global ``Settings.instance().evaluationDate`` **is** touched inside
    worker threads: every ``OptionValuation`` construction sets it
    unconditionally (``valuation.py``'s ``_setup_quantlib()``), and
    ``_get_or_create_cached_option()`` constructs on a cache miss from
    inside ``_sweep_parallel``/``_sweep_parallel_greeks``, unsynchronized.

    What actually makes this safe: every worker spawned by one
    ``portfolio_values_at()``/``portfolio_greeks_at()`` call is invoked with
    the *same* ``valuation_date`` argument — the date is a call parameter,
    not per-position — so the unsynchronized writes are concurrent but
    idempotent, every writer stores the identical value. This class does
    nothing to prevent two *different* calls (different ``valuation_date``s)
    from running concurrently against the same ``BatchPricer`` instance;
    that would race for real. No current caller does this —
    ``PortfolioAnalyzer.scenario_grid()`` sweeps its time points
    sequentially on the main thread, one ``portfolio_*_at()`` call at a
    time — but nothing in this class enforces it.

    Post-construction, ``update_spot_price()`` — the actual per-spot sweep
    call inside worker threads — is pure ``SimpleQuote.setValue()``, with
    no QuantLib global side-effects, matching the original claim for that
    part of the hot path.

    One further hazard the above doesn't cover: ``OptionValuation``'s
    numeric theta fallback (``_compute_theta``, used when the engine's
    analytic ``theta()`` raises ``RuntimeError``) bumps the global
    evaluationDate forward by a day mid-computation and restores it —
    unlike delta/gamma/rho's fallbacks, which bump a local ``SimpleQuote``
    and touch no global state. That branch is unreachable with the FD,
    closed-form, and analytic engines this class currently selects
    (verified directly against each), so it does not fire in practice
    today. If a future engine change makes it reachable, it would race the
    same way this note used to deny — and, independently of the race, it
    currently returns a wrong answer even single-threaded (#266):
    the term structures built in ``_setup_quantlib()`` use a fixed
    reference date baked in at construction, not a live read of
    ``Settings.instance().evaluationDate()``, so bumping the global
    afterward does not reprice the option at all.
    """

    def __init__(
        self,
        positions: list[OptionPosition],
        risk_free_rate: float,
        dividend_yield: float,
        underlying_quantity: float,
        grid_resolution: FDGridResolution = FDGridResolution.FAST,
        use_closed_form: bool = False,
        max_workers: int = 1,
    ) -> None:
        """Initialize batch pricer.

        Args:
            positions: list of option positions to price.
            risk_free_rate: Risk-free interest rate (annualized).
            dividend_yield: Dividend yield (annualized).
            underlying_quantity: Quantity of underlying shares in portfolio.
            grid_resolution: Finite difference grid resolution for pricing.
                Ignored when ``use_closed_form=True``. For batch pricing
                across many scenarios, ``FDGridResolution.FAST`` balances
                speed and accuracy. Use ``PRECISE`` for high-precision
                single-position pricing.
            use_closed_form: If ``True``, use the Bjerksund-Stensland 2002
                closed-form approximation for American options instead of the
                FD grid. Approximately 10-20x faster per price call with <1%
                typical error for near-ATM options. A
                :class:`~deltadewa.warnings.ClosedFormAccuracyWarning` is
                emitted once per position in a known low-accuracy regime
                (deep ITM, short-dated put, very high volatility). European
                positions always use the analytic engine regardless of this
                flag.
            max_workers: Number of threads for parallel position pricing.
                ``1`` (default) disables threading and preserves the original
                sequential behaviour. Values > 1 parallelise the per-position
                spot sweep using ``ThreadPoolExecutor``.

        """
        self.positions = positions
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield
        self.underlying_quantity = underlying_quantity
        self.grid_resolution = grid_resolution
        self.use_closed_form = use_closed_form
        self.max_workers = max(1, max_workers)

        # Cache: (position_index, valuation_date) -> OptionValuation
        self._cache: dict[tuple[int, dt], OptionValuation] = {}
        # Protects both _cache reads/writes across threads
        self._cache_lock = threading.Lock()

    # Valid greek names — matches OptionValuation public methods
    _VALID_GREEKS: frozenset[str] = frozenset(
        {"price", "delta", "gamma", "vega", "theta", "rho"},
    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def portfolio_values_at(
        self,
        spots: np.ndarray[Any, np.dtype[Any]],
        valuation_date: dt,
    ) -> np.ndarray[Any, np.dtype[Any]]:
        """Calculate portfolio values at multiple spot prices for a given date.

        For each position, checks if a cached OptionValuation exists for the
        given valuation_date. If cached and date matches, reuses it; otherwise
        builds a new one and caches it.

        For expired positions (days_to_maturity <= 0), uses vectorized NumPy
        intrinsic value calculation. For live positions, sweeps across spots
        using ``update_spot_price()`` (cheap ``SimpleQuote.setValue()``, no
        engine rebuild).

        When ``max_workers > 1``, live positions are priced in parallel using
        ``ThreadPoolExecutor``; expired positions are always handled
        sequentially with NumPy vectorisation.

        Args:
            spots: Array of spot prices to evaluate.
            valuation_date: Valuation date for pricing.

        Returns:
            Array of total portfolio values (options + underlying) at each spot.

        """
        portfolio_values = np.zeros(len(spots))

        # Underlying position value (always vectorized)
        portfolio_values += self.underlying_quantity * spots

        # Partition positions into expired / live
        expired, live = self._partition_positions(valuation_date)

        # --- Expired: vectorized intrinsic value ---
        for _pos_idx, position in expired:
            if position.option.option_type == OptionType.CALL:
                intrinsic = np.maximum(0, spots - position.option.strike_price)
            else:
                intrinsic = np.maximum(0, position.option.strike_price - spots)
            portfolio_values += (
                intrinsic * position.quantity * position.contract_size
            )

        if not live:
            return portfolio_values

        # --- Live: sequential or parallel spot sweep ---
        if self.max_workers == 1:
            for pos_idx, position in live:
                opt, is_new = self._get_or_create_cached_option(
                    pos_idx,
                    position,
                    valuation_date,
                )
                # Emit warning in main thread for newly constructed options
                # only (cache miss). Use the construction-time snapshot —
                # spot_price will be mutated during the sweep below.
                if is_new:
                    msg = (
                        opt._construction_accuracy_warning  # pylint: disable=protected-access
                    )
                    if msg:
                        warnings.warn(
                            msg,
                            ClosedFormAccuracyWarning,
                            stacklevel=2,
                        )
                pos_values = self._sweep_spots(opt, spots)
                portfolio_values += (
                    pos_values * position.quantity * position.contract_size
                )
        else:
            portfolio_values = self._sweep_parallel(
                live,
                spots,
                valuation_date,
                portfolio_values,
            )

        return portfolio_values

    def clear_cache(self) -> None:
        """Clear the internal cache of OptionValuation instances."""
        with self._cache_lock:
            self._cache.clear()

    def portfolio_greeks_at(  # pylint: disable=too-many-branches
        self,
        spots: np.ndarray[Any, np.dtype[Any]],
        valuation_date: dt,
        greeks: tuple[str, ...] = ("delta", "gamma", "vega", "theta"),
    ) -> dict[str, np.ndarray[Any, np.dtype[Any]]]:
        """Calculate portfolio Greeks at multiple spot prices for a given date.

        Reuses the same (position, date) cache as portfolio_values_at().
        After the initial QuantLib construction (P x T total across all calls),
        each spot sweep uses only SimpleQuote.setValue() — no engine rebuilds.

        The underlying position contributes delta=underlying_quantity,
        gamma=vega=theta=rho=0 at every spot.

        "net_delta" is not a separate greek name — callers requesting "delta"
        already receive net delta (options delta + underlying_quantity).

        Args:
            spots: Array of spot prices.
            valuation_date: Valuation date.
            greeks: tuple of Greek names to compute. Each must be one of:
                "price", "delta", "gamma", "vega", "theta", "rho".
                Defaults to ("delta", "gamma", "vega", "theta").

        Returns:
            dict mapping each requested greek name (plus "price") to a
            1-D NumPy array of portfolio totals at each spot price, scaled
            by quantity x contract_size. The "delta" array includes the
            underlying position (underlying_quantity * 1.0 per spot).

        Raises:
            ValueError: If any name in greeks is not a valid Greek.

        """
        invalid = set(greeks) - self._VALID_GREEKS
        if invalid:
            raise ValueError(
                f"Unknown greek(s): {invalid!r}. "
                f"Valid names: {sorted(self._VALID_GREEKS)}",
            )

        n = len(spots)
        # Initialize result arrays
        result: dict[str, np.ndarray[Any, np.dtype[Any]]] = {
            name: np.zeros(n) for name in greeks
        }
        if "price" not in result:
            result["price"] = np.zeros(n)

        # Underlying contributions: delta += underlying_quantity, price +=
        # underlying_quantity * spots
        if "delta" in result:
            result["delta"] += self.underlying_quantity
        result["price"] += self.underlying_quantity * spots

        # Partition expired / live (same logic as portfolio_values_at)
        expired, live = self._partition_positions(valuation_date)

        # Expired positions: vectorized intrinsic price; binary delta; all
        # other Greeks zero
        for _pos_idx, position in expired:
            mult = position.quantity * position.contract_size
            if position.option.option_type == OptionType.CALL:
                if "price" in result:
                    result["price"] += (
                        np.maximum(0, spots - position.option.strike_price)
                        * mult
                    )
                if "delta" in result:
                    result["delta"] += (
                        spots > position.option.strike_price
                    ).astype(
                        float,
                    ) * mult
            else:
                if "price" in result:
                    result["price"] += (
                        np.maximum(0, position.option.strike_price - spots)
                        * mult
                    )
                if "delta" in result:
                    result["delta"] += (
                        -(spots < position.option.strike_price).astype(float)
                        * mult
                    )
            # gamma / vega / theta / rho are zero at expiry — arrays already
            # zero

        if not live:
            return result

        # Request only the greeks the caller asked for (price is always
        # collected)
        requested = tuple(g for g in greeks if g != "price")

        # --- Live: sequential or parallel Greek sweep ---
        if self.max_workers == 1:
            for pos_idx, position in live:
                opt, is_new = self._get_or_create_cached_option(
                    pos_idx,
                    position,
                    valuation_date,
                )
                if is_new:
                    msg = (
                        opt._construction_accuracy_warning  # pylint: disable=protected-access
                    )
                    if msg:
                        warnings.warn(
                            msg,
                            ClosedFormAccuracyWarning,
                            stacklevel=2,
                        )

                mult = position.quantity * position.contract_size
                per_contract = self._sweep_spots_and_greeks(
                    opt,
                    spots,
                    requested,
                )

                result["price"] += per_contract["price"] * mult
                for name in requested:
                    result[name] += per_contract[name] * mult
        else:
            result = self._sweep_parallel_greeks(
                live,
                spots,
                valuation_date,
                requested,
                result,
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_create_cached_option(
        self,
        pos_idx: int,
        position: OptionPosition,
        valuation_date: dt,
    ) -> tuple[OptionValuation, bool]:
        """Return a cached OptionValuation, creating one if absent.

        Returns a ``(opt, is_new)`` tuple where ``is_new`` is ``True`` when
        the option was just constructed (cache miss) and ``False`` on a cache
        hit.  Callers should emit the accuracy warning only on a cache miss so
        that the warning fires exactly once per position per valuation date,
        not on every subsequent call with the same date.

        Construction-time warnings are suppressed here; callers are
        responsible for emitting them via ``_construction_accuracy_warning``.
        This keeps warning emission on the main thread and out of worker
        threads, where ``__warningregistry__`` races can cause missed warnings.
        """
        cache_key = (pos_idx, valuation_date)

        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key], False

        # Suppress the warning during construction; the caller emits it.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ClosedFormAccuracyWarning)
            opt = OptionValuation(
                spot_price=position.option.spot_price,
                strike_price=position.option.strike_price,
                maturity_date=position.option.maturity_date,
                volatility=position.option.volatility,
                risk_free_rate=self.risk_free_rate,
                dividend_yield=self.dividend_yield,
                option_type=position.option.option_type,
                valuation_date=valuation_date,
                exercise_style=position.exercise_style,
                grid_resolution=self.grid_resolution,
                use_closed_form=self.use_closed_form,
            )

        with self._cache_lock:
            if cache_key not in self._cache:
                self._cache[cache_key] = opt
            return self._cache[cache_key], True

    @staticmethod
    def _sweep_spots(
        opt: OptionValuation,
        spots: np.ndarray[Any, np.dtype[Any]],
    ) -> np.ndarray[Any, np.dtype[Any]]:
        """Sweep a single OptionValuation across an array of spot prices.

        Returns an array of per-contract prices (before scaling by quantity
        and contract_size).
        """
        prices = np.empty(len(spots))
        for i, spot in enumerate(spots):
            opt.update_spot_price(spot)
            prices[i] = opt.price()
        return prices

    @staticmethod
    def _sweep_spots_and_greeks(
        opt: OptionValuation,
        spots: np.ndarray[Any, np.dtype[Any]],
        greek_names: tuple[str, ...],
    ) -> dict[str, np.ndarray[Any, np.dtype[Any]]]:
        """Sweep spot prices, collecting price and any requested Greeks.

        Calls update_spot_price() once per spot (cheap SimpleQuote.setValue()),
        then reads each Greek from the GreeksCache — no QuantLib rebuild.

        Returns a dict with keys from greek_names plus "price", each mapping
        to an array of per-contract values of length len(spots).
        """
        n = len(spots)
        arrays: dict[str, np.ndarray[Any, np.dtype[Any]]] = {
            name: np.empty(n) for name in greek_names
        }
        arrays["price"] = np.empty(n)

        for i, spot in enumerate(spots):
            opt.update_spot_price(spot)
            arrays["price"][i] = opt.price()
            for name in greek_names:
                arrays[name][i] = getattr(opt, name)()

        return arrays

    def _sweep_parallel(
        self,
        live_positions: list[tuple[int, OptionPosition]],
        spots: np.ndarray[Any, np.dtype[Any]],
        valuation_date: dt,
        portfolio_values: np.ndarray[Any, np.dtype[Any]],
    ) -> np.ndarray[Any, np.dtype[Any]]:
        """Price live positions in parallel and accumulate results.

        Each position's spot sweep runs in a separate thread. Results are
        accumulated into ``portfolio_values`` under a lock.

        Warning strategy
        ----------------
        ``warnings.warn()`` and ``__warningregistry__`` are not thread-safe.
        Worker threads therefore *collect* any accuracy warning message via
        ``OptionValuation._closed_form_accuracy_message()`` (pure computation,
        no warning machinery) and return it to the main thread, which emits
        the warning once per position after all workers have finished.
        """
        result_lock = threading.Lock()
        # Collects (pos_idx, message_or_None) from each worker in order.
        warning_messages: list[tuple[int, str | None]] = []
        wm_lock = threading.Lock()

        def _price_position(pos_idx: int, position: OptionPosition) -> None:
            opt, is_new = self._get_or_create_cached_option(
                pos_idx,
                position,
                valuation_date,
            )
            # Use the construction-time snapshot —
            # _closed_form_accuracy_messag() would give the wrong result here
            # since spot_price changes during the sweep below. Only collect the
            # message on a cache miss so the warning fires exactly once per
            # position per valuation date.
            # would give the wrong result here since spot_price changes during
            # the sweep below.  Only collect the message on a cache miss so
            # the warning fires exactly once per position per valuation date.
            msg = (
                opt._construction_accuracy_warning  # pylint: disable=protected-access
                if is_new
                else None
            )
            with wm_lock:
                warning_messages.append((pos_idx, msg))

            pos_values = self._sweep_spots(opt, spots)
            scaled = pos_values * position.quantity * position.contract_size
            with result_lock:
                portfolio_values[:] += scaled

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(_price_position, pos_idx, position): pos_idx
                for pos_idx, position in live_positions
            }
            for future in as_completed(futures):
                future.result()  # re-raise any worker exception

        # Emit deferred warnings from the main thread, one per position that
        # needs one.  Sorted by pos_idx for deterministic ordering.
        warning_messages.sort(key=lambda x: x[0])
        for _pos_idx, msg in warning_messages:
            if msg:
                warnings.warn(msg, ClosedFormAccuracyWarning, stacklevel=2)

        return portfolio_values

    def _sweep_parallel_greeks(
        self,
        live_positions: list[tuple[int, OptionPosition]],
        spots: np.ndarray[Any, np.dtype[Any]],
        valuation_date: dt,
        requested: tuple[str, ...],
        result: dict[str, np.ndarray[Any, np.dtype[Any]]],
    ) -> dict[str, np.ndarray[Any, np.dtype[Any]]]:
        """Calc Greeks for live positions in parallel and accumulate results.

        Mirrors ``_sweep_parallel`` but uses ``_sweep_spots_and_greeks`` as the
        inner sweep and accumulates into a ``dict[str, np.ndarray]`` rather than
        a flat value array.

        Warning strategy is identical to ``_sweep_parallel``: worker threads
        collect the accuracy warning message (pure computation, no warning
        machinery) and the main thread emits it after all workers finish.

        Args:
            live_positions: ``(pos_idx, position)`` pairs to price in parallel.
            spots: Array of spot prices.
            valuation_date: Valuation date.
            requested: Greek names to compute (must not include ``"price"`` —
                price is always collected).
            result: Pre-initialised result dict (modified in-place and
            returned).

        Returns:
            ``result`` with each Greek and ``"price"`` arrays accumulated.

        """
        result_lock = threading.Lock()
        # Collects (pos_idx, message_or_None) from each worker in order.
        warning_messages: list[tuple[int, str | None]] = []
        wm_lock = threading.Lock()

        def _greek_position(pos_idx: int, position: OptionPosition) -> None:
            opt, is_new = self._get_or_create_cached_option(
                pos_idx,
                position,
                valuation_date,
            )
            msg = (
                opt._construction_accuracy_warning  # pylint: disable=protected-access
                if is_new
                else None
            )
            with wm_lock:
                warning_messages.append((pos_idx, msg))

            mult = position.quantity * position.contract_size
            per_contract = self._sweep_spots_and_greeks(opt, spots, requested)

            with result_lock:
                result["price"] += per_contract["price"] * mult
                for name in requested:
                    result[name] += per_contract[name] * mult

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(_greek_position, pos_idx, position): pos_idx
                for pos_idx, position in live_positions
            }
            for future in as_completed(futures):
                future.result()  # re-raise any worker exception

        # Emit deferred warnings from the main thread, one per position that
        # needs one. Sorted by pos_idx for deterministic ordering.
        warning_messages.sort(key=lambda x: x[0])
        for _pos_idx, msg in warning_messages:
            if msg:
                warnings.warn(msg, ClosedFormAccuracyWarning, stacklevel=2)

        return result

    def _partition_positions(
        self,
        valuation_date: dt,
    ) -> tuple[
        list[tuple[int, OptionPosition]],
        list[tuple[int, OptionPosition]],
    ]:
        """Partition positions into (expired, live) by maturity date.

        A position is expired when ``days_to_maturity <= 0`` relative to
        ``valuation_date``.  Expired positions are priced at intrinsic value
        only; live positions are swept through the QuantLib engine.

        Returns:
            ``(expired, live)`` — each a list of ``(pos_idx, position)`` pairs
            in their original enumeration order.

        """
        expired: list[tuple[int, OptionPosition]] = []
        live: list[tuple[int, OptionPosition]] = []
        for pos_idx, position in enumerate(self.positions):
            days = days_between(valuation_date, position.option.maturity_date)
            if days <= 0:
                expired.append((pos_idx, position))
            else:
                live.append((pos_idx, position))
        return expired, live
