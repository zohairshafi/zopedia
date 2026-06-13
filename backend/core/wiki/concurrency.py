"""Parallel execution primitives for wiki engine operations.

Provides ThreadPoolExecutor-based parallelism for independent per-item
LLM calls within a single method. Never parallelizes across methods.

Shared mutable state (page files, index files) is protected by per-page
locks and a global index lock.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

# Per-page locks for safe concurrent writes to the same wiki page file.
_page_locks: dict[str, threading.Lock] = {}
_page_locks_lock = threading.Lock()

# Global lock to serialize _rebuild_index / _rebuild_index_godnodes /
# _rebuild_index_concise / _sync_godnodes_other calls.
_index_lock = threading.Lock()


def _default_workers() -> int:
    return int(os.environ.get("ZOPEDIA_WIKI_PARALLEL_WORKERS", "8"))


def run_parallel(
    items: list[T],
    fn: Callable[[T], R],
    max_workers: int | None = None,
    description: str = "",
) -> list[R]:
    """Run ``fn(item)`` for every item using a thread pool.

    Returns results in the same order as *items*.  Items whose *fn* raises
    are logged (with full traceback) and excluded from the result list.

    When *max_workers* is ``None`` the value of the
    ``ZOPEDIA_WIKI_PARALLEL_WORKERS`` env var is used (default 8).
    A value <= 1 or a single-item list falls back to sequential execution.
    """
    if max_workers is None:
        max_workers = _default_workers()

    if max_workers <= 1 or len(items) <= 1:
        results: list[R] = []
        for item in items:
            try:
                results.append(fn(item))
            except Exception:
                logger.error(
                    "Parallel task failed (%s): item=%s",
                    description,
                    item,
                    exc_info=True,
                )
        return results

    indexed_results: dict[int, R] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as executor:
        future_to_index = {
            executor.submit(fn, item): idx for idx, item in enumerate(items)
        }
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                indexed_results[idx] = future.result()
            except Exception:
                logger.error(
                    "Parallel task failed (%s): item=%s",
                    description,
                    items[idx],
                    exc_info=True,
                )

    return [indexed_results[i] for i in sorted(indexed_results)]


def page_lock(rel_path: str) -> threading.Lock:
    """Return (or create) a per-relative-path lock for safe concurrent file writes.

    ``rel_path`` is a wiki-relative path like ``"sources/my-page"`` or
    ``"analysis/my-page"``.  The lock is reused across the process lifetime.
    """
    normalized = rel_path.replace("\\", "/").strip("/")
    with _page_locks_lock:
        if normalized not in _page_locks:
            _page_locks[normalized] = threading.Lock()
        return _page_locks[normalized]


def index_lock() -> threading.Lock:
    """Global lock that serializes all index-rebuild operations."""
    return _index_lock
