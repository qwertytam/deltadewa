"""Batch pricer for efficient portfolio valuation across scenario grids."""

import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime as dt

import numpy as np

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
    Only ``SimpleQuote.setValue()`` is called inside worker threads — a
    pure in-process value write with no QuantLib global side-effects.
    The global ``Settings.instance().evaluationDate`` is never touched
    inside workers, so threading is safe here.
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
            positions: List of option positions to price.
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def portfolio_values_at(
        self,
        spots: np.ndarray,
        valuation_date: dt,
    ) -> np.ndarray:
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
        expired: list[tuple[int, OptionPosition]] = []
        live: list[tuple[int, OptionPosition]] = []
        for pos_idx, position in enumerate(self.positions):
            days_to_maturity = (position.option.maturity_date - valuation_date).days
            if days_to_maturity <= 0:
                expired.append((pos_idx, position))
            else:
                live.append((pos_idx, position))

        # --- Expired: vectorized intrinsic value ---
        for _pos_idx, position in expired:
            if position.option.option_type == OptionType.CALL:
                intrinsic = np.maximum(0, spots - position.option.strike_price)
            else:
                intrinsic = np.maximum(0, position.option.strike_price - spots)
            portfolio_values += intrinsic * position.quantity * position.contract_size

        if not live:
            return portfolio_values

        # --- Live: sequential or parallel spot sweep ---
        if self.max_workers == 1:
            for pos_idx, position in live:
                opt = self._get_or_create_cached_option(
                    pos_idx,
                    position,
                    spots,
                    valuation_date,
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_create_cached_option(
        self,
        pos_idx: int,
        position: OptionPosition,
        spots: np.ndarray,
        valuation_date: dt,
    ) -> OptionValuation:
        """Return a cached OptionValuation, creating one if absent.

        When ``use_closed_form=True``, any
        :class:`~deltadewa.warnings.ClosedFormAccuracyWarning` emitted
        during construction is captured and re-emitted exactly once per
        unique message — not once per spot price in the sweep.
        """
        cache_key = (pos_idx, valuation_date)

        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        # Construct outside the lock (expensive QuantLib setup).
        # Capture any ClosedFormAccuracyWarnings so they fire once per
        # position, not once per spot in the outer sweep.
        caught: list[warnings.WarningMessage] = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            opt = OptionValuation(
                spot_price=float(spots[0]),
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

        # Double-checked locking: another thread may have inserted while
        # we were constructing outside the lock.
        with self._cache_lock:
            if cache_key not in self._cache:
                self._cache[cache_key] = opt

        # Re-emit captured warnings exactly once (deduplicated by message)
        seen: set[str] = set()
        for w in caught:
            msg_key = str(w.message)
            if msg_key not in seen:
                seen.add(msg_key)
                warnings.warn_explicit(
                    message=w.message,
                    category=w.category,
                    filename=w.filename,
                    lineno=w.lineno,
                    source=w.source,
                )

        with self._cache_lock:
            return self._cache[cache_key]

    @staticmethod
    def _sweep_spots(opt: OptionValuation, spots: np.ndarray) -> np.ndarray:
        """Sweep a single OptionValuation across an array of spot prices.

        Returns an array of per-contract prices (before scaling by quantity
        and contract_size).
        """
        prices = np.empty(len(spots))
        for i, spot in enumerate(spots):
            opt.update_spot_price(spot)
            prices[i] = opt.price()
        return prices

    def _sweep_parallel(
        self,
        live_positions: list[tuple[int, OptionPosition]],
        spots: np.ndarray,
        valuation_date: dt,
        portfolio_values: np.ndarray,
    ) -> np.ndarray:
        """Price live positions in parallel and accumulate results.

        Each position's spot sweep runs in a separate thread. Results are
        accumulated into ``portfolio_values`` under a lock.
        """
        result_lock = threading.Lock()

        def _price_position(pos_idx: int, position: OptionPosition) -> None:
            opt = self._get_or_create_cached_option(
                pos_idx,
                position,
                spots,
                valuation_date,
            )
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

        return portfolio_values
