"""Lazy-loading Greeks cache with automatic invalidation."""

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import RLock
from typing import Any


@dataclass
class GreeksCache:
    """Thread-safe, lazy-loading cache for option Greeks.

    Each Greek is computed only when first accessed and cached until
    invalidation. The cache is invalidated when market conditions change.
    """

    _compute_funcs: dict[str, Callable[[], float]] = field(default_factory=dict)
    _cache: dict[str, float] = field(default_factory=dict)
    _dirty: set = field(
        default_factory=lambda: {
            "delta",
            "gamma",
            "vega",
            "theta",
            "rho",
            "price",
        },
    )
    _lock: RLock = field(default_factory=RLock)

    def register(self, name: str, compute_func: Callable[[], float]) -> None:
        """Register a Greek computation function."""
        with self._lock:
            self._compute_funcs[name] = compute_func
            self._dirty.add(name)

    def get(self, name: str) -> float:
        """Get a Greek value, computing if necessary (lazy evaluation)."""
        with self._lock:
            if name in self._dirty or name not in self._cache:
                if name not in self._compute_funcs:
                    raise KeyError(f"Greek '{name}' not registered")
                self._cache[name] = self._compute_funcs[name]()
                self._dirty.discard(name)
            return self._cache[name]

    def invalidate(self, names: set | None = None) -> None:
        """Mark Greeks as needing recomputation."""
        with self._lock:
            if names is None:
                self._dirty = set(self._compute_funcs.keys())
            else:
                self._dirty.update(names)

    def invalidate_all(self) -> None:
        """Mark all Greeks as dirty and clear cache."""
        with self._lock:
            self._dirty = set(self._compute_funcs.keys())
            self._cache.clear()

    def is_cached(self, name: str) -> bool:
        """Check if a Greek is currently cached and valid."""
        with self._lock:
            return name in self._cache and name not in self._dirty

    def compute_all(self) -> dict[str, float]:
        """Compute all registered Greeks and return as dictionary.

        Efficient for batch operations - reduced lock overhead.
        """
        with self._lock:
            result = {}
            for name in self._compute_funcs:
                if name in self._dirty or name not in self._cache:
                    self._cache[name] = self._compute_funcs[name]()
                    self._dirty.discard(name)
                result[name] = self._cache[name]
            return result

    @property
    def cache_stats(self) -> dict[str, Any]:
        """Return cache statistics for monitoring/debugging."""
        with self._lock:
            return {
                "registered": list(self._compute_funcs.keys()),
                "cached": list(self._cache.keys()),
                "dirty": list(self._dirty),
            }
