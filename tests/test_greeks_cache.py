"""Tests for deltadewa.greeks_cache module."""

import threading
import pytest
from deltadewa.greeks_cache import GreeksCache


class TestGreeksCache:
    """Test cases for GreeksCache."""

    def test_lazy_computation(self):
        """Verify Greeks are only computed when accessed."""
        call_count = 0

        def compute_delta():
            nonlocal call_count
            call_count += 1
            return 0.5

        cache = GreeksCache()
        cache.register("delta", compute_delta)

        assert call_count == 0  # Not computed yet

        result = cache.get("delta")
        assert result == 0.5
        assert call_count == 1  # Computed once

        result = cache.get("delta")
        assert result == 0.5
        assert call_count == 1  # Still 1, used cache

    def test_invalidation(self):
        """Verify invalidation triggers recomputation."""
        call_count = 0

        def compute_delta():
            nonlocal call_count
            call_count += 1
            return 0.5 + call_count * 0.1

        cache = GreeksCache()
        cache.register("delta", compute_delta)

        result1 = cache.get("delta")
        assert call_count == 1

        cache.invalidate_all()

        result2 = cache.get("delta")
        assert call_count == 2
        assert result2 != result1  # Different value after recompute

    def test_compute_all(self):
        """Verify batch computation works."""
        cache = GreeksCache()
        cache.register("delta", lambda: 0.5)
        cache.register("gamma", lambda: 0.1)
        cache.register("vega", lambda: 0.2)

        result = cache.compute_all()

        assert "delta" in result
        assert "gamma" in result
        assert "vega" in result
        assert result["delta"] == 0.5
        assert result["gamma"] == 0.1
        assert result["vega"] == 0.2

    def test_thread_safety(self):
        """Verify concurrent access doesn't cause issues."""

        cache = GreeksCache()
        cache.register("delta", lambda: 0.5)

        results = []

        def get_delta():
            for _ in range(100):
                results.append(cache.get("delta"))

        threads = [threading.Thread(target=get_delta) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 1000
        assert all(r == 0.5 for r in results)

    def test_is_cached(self):
        """Verify is_cached reports correct state."""
        cache = GreeksCache()
        cache.register("delta", lambda: 0.5)

        assert not cache.is_cached("delta")  # Not cached yet

        cache.get("delta")
        assert cache.is_cached("delta")  # Now cached

        cache.invalidate_all()
        assert not cache.is_cached("delta")  # Invalidated

    def test_cache_stats(self):
        """Verify cache_stats returns correct information."""
        cache = GreeksCache()
        cache.register("delta", lambda: 0.5)
        cache.register("gamma", lambda: 0.1)

        stats = cache.cache_stats
        assert "delta" in stats["registered"]
        assert "gamma" in stats["registered"]
        assert "delta" in stats["dirty"]

        cache.get("delta")
        stats = cache.cache_stats
        assert "delta" in stats["cached"]
        assert "delta" not in stats["dirty"]

    def test_key_error_on_unregistered_greek(self):
        """Verify KeyError is raised for unregistered Greeks."""
        cache = GreeksCache()

        with pytest.raises(KeyError, match="Greek 'delta' not registered"):
            cache.get("delta")

    def test_selective_invalidation(self):
        """Verify selective invalidation works."""
        cache = GreeksCache()
        cache.register("delta", lambda: 0.5)
        cache.register("gamma", lambda: 0.1)

        # Cache both
        cache.get("delta")
        cache.get("gamma")

        assert cache.is_cached("delta")
        assert cache.is_cached("gamma")

        # Invalidate only delta
        cache.invalidate({"delta"})

        assert not cache.is_cached("delta")
        assert cache.is_cached("gamma")  # Gamma still cached

    def test_compute_all_caches_results(self):
        """Verify compute_all caches all computed values."""
        call_counts = {"delta": 0, "gamma": 0, "vega": 0}

        def make_counter(name):
            def compute():
                call_counts[name] += 1
                return float(call_counts[name])

            return compute

        cache = GreeksCache()
        cache.register("delta", make_counter("delta"))
        cache.register("gamma", make_counter("gamma"))
        cache.register("vega", make_counter("vega"))

        # First compute_all
        result1 = cache.compute_all()
        assert call_counts["delta"] == 1
        assert call_counts["gamma"] == 1
        assert call_counts["vega"] == 1

        # Second compute_all should use cache
        result2 = cache.compute_all()
        assert call_counts["delta"] == 1  # Not recomputed
        assert call_counts["gamma"] == 1
        assert call_counts["vega"] == 1
        assert result1 == result2
