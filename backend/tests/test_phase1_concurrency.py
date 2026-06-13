"""Phase 1 tests: concurrency primitives (run_parallel, page_lock, index_lock).

These tests validate correctness of the ThreadPoolExecutor-based parallel
execution utilities without requiring a full wiki environment.
"""

from __future__ import annotations

import time
from backend.core.wiki.concurrency import run_parallel, page_lock, index_lock


def _square(n: int) -> int:
    return n * n


def _slow_double(n: int) -> int:
    time.sleep(0.05 * (n % 3))  # staggered sleep to test order preservation
    return n * 2


def _failing_on_negative(n: int) -> int:
    if n < 0:
        raise ValueError(f"negative input: {n}")
    return n


# -- run_parallel ---------------------------------------------------------


def test_run_parallel_sequential_fallback_single_item():
    """Single-item list runs sequentially regardless of max_workers."""
    result = run_parallel([5], _square, max_workers=8, description="test")
    assert result == [25]


def test_run_parallel_sequential_fallback_workers_le_1():
    """max_workers <= 1 forces sequential path."""
    result = run_parallel([1, 2, 3], _square, max_workers=1, description="test")
    assert result == [1, 4, 9]


def test_run_parallel_empty_list():
    """Empty input returns empty list."""
    result = run_parallel([], _square)
    assert result == []


def test_run_parallel_all_success_parallel():
    """Parallel execution returns all results."""
    inputs = [1, 2, 3, 4, 5]
    result = run_parallel(inputs, _square, max_workers=4, description="test")
    assert sorted(result) == [1, 4, 9, 16, 25]


def test_run_parallel_preserves_order():
    """Results are returned in the same order as input items."""
    inputs = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    result = run_parallel(inputs, _slow_double, max_workers=4, description="test")
    assert result == [i * 2 for i in inputs]


def test_run_parallel_with_failures():
    """Failed items are excluded from results; successes are preserved."""
    inputs = [1, -2, 3, -4, 5]
    result = run_parallel(inputs, _failing_on_negative, max_workers=4, description="test")
    assert result == [1, 3, 5]


def test_run_parallel_all_failures():
    """When every item fails, result is an empty list."""
    inputs = [-1, -2, -3]
    result = run_parallel(inputs, _failing_on_negative, max_workers=4, description="test")
    assert result == []


def test_run_parallel_max_workers_respected():
    """Thread pool executes with max_workers=2 and completes correctly."""
    def _identity(x: int) -> int:
        time.sleep(0.01)
        return x

    result = run_parallel([10, 20, 30, 40], _identity, max_workers=2, description="test")
    assert result == [10, 20, 30, 40]


# -- page_lock ------------------------------------------------------------


def test_page_lock_same_path_returns_same_lock():
    """page_lock deduplicates by normalized path."""
    lock1 = page_lock("sources/my-page")
    lock2 = page_lock("sources/my-page")
    assert lock1 is lock2


def test_page_lock_normalizes_path():
    """Different representations of the same path return the same lock."""
    lock1 = page_lock("sources/my-page")
    lock2 = page_lock("/sources/my-page")
    lock3 = page_lock("sources/my-page/")
    assert lock1 is lock2
    assert lock1 is lock3


def test_page_lock_different_paths_return_different_locks():
    """Distinct paths get distinct locks."""
    lock_a = page_lock("sources/page-a")
    lock_b = page_lock("sources/page-b")
    assert lock_a is not lock_b


# -- index_lock -----------------------------------------------------------


def test_index_lock_singleton():
    """index_lock always returns the same global lock."""
    lock1 = index_lock()
    lock2 = index_lock()
    assert lock1 is lock2
