"""Concurrency & Connection Pooling for Emsal-mcp – v1.0

Adds semaphore-based parallel execution for batch operations.
Conservative by default — respects single-user design assumption.
Integrates with circuit breaker (M-17) and retry (M-18).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, TypeVar

from .config import config

logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from synchronous code, event-loop safe.

    When called from within an already-running event loop (e.g. inside the
    MCP server's asyncio loop), ``asyncio.run()`` raises
    ``RuntimeError: This event loop is already running``.

    This helper detects the situation and uses a background thread with its
    own event loop to execute the coroutine, avoiding the conflict.
    When no loop is running (CLI context), it simply delegates to
    ``asyncio.run()``.
    """
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We are inside a running event loop (MCP server).
        # Spawn a new loop in a worker thread.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


# Global semaphore for concurrency control
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-initialize the concurrency semaphore."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(config.max_concurrency)
    return _semaphore


def get_concurrency_status() -> dict[str, Any]:
    """Report concurrency settings and current state.

    Returns:
        Dict with ok, max_concurrency, available_slots.
    """
    sem = _get_semaphore()
    available = sem._value  # type: ignore[attr-defined]
    return {
        "ok": True,
        "max_concurrency": config.max_concurrency,
        "available_slots": available,
        "note": "Conservative default — single-user design preserved.",
    }


async def run_concurrently(
    coros: list[Coroutine[Any, Any, T]],
    *,
    max_concurrency: int | None = None,
) -> list[T | Exception]:
    """Run multiple coroutines concurrently with a semaphore cap.

    Each coroutine runs under the global semaphore. Exceptions are
    caught per-coroutine and returned as Exception values — this
    allows partial success (some succeed, some fail) without aborting
    the entire batch.

    Args:
        coros: List of coroutines to execute.
        max_concurrency: Override the default max concurrency.

    Returns:
        List of results. Each element is either the return value
        or an Exception if that coroutine failed.
    """
    limit = max_concurrency or config.max_concurrency
    sem = asyncio.Semaphore(limit)

    async def _run_one(coro: Coroutine[Any, Any, T]) -> T | Exception:
        async with sem:
            try:
                return await coro
            except Exception as exc:
                logger.debug("Concurrent task failed: %s", exc)
                return exc

    return await asyncio.gather(*[_run_one(c) for c in coros])


async def run_document_fetches(
    fetch_tasks: list[tuple[Callable[..., Any], str, str]],
    *,
    max_concurrency: int | None = None,
) -> list[Any]:
    """Run multiple document fetch operations concurrently.

    Specialized convenience for batch document fetching in research_topic.
    Each task is a tuple of (get_document_fn, source_id, document_id).

    Args:
        fetch_tasks: List of (async_get_document_fn, source, doc_id) tuples.
        max_concurrency: Override concurrency limit.

    Returns:
        List of fetch results (Document or Exception).
    """
    coros = [fn(doc_id) for fn, src_id, doc_id in fetch_tasks]
    return await run_concurrently(coros, max_concurrency=max_concurrency)


async def run_source_searches(
    search_tasks: list[tuple[Callable[..., Any], str, str]],
    *,
    max_concurrency: int | None = None,
) -> list[Any]:
    """Run multiple source search operations concurrently.

    Each task is a tuple of (search_fn, source_id, query).

    Args:
        search_tasks: List of (async_search_fn, source_id, query) tuples.
        max_concurrency: Override concurrency limit.

    Returns:
        List of search results.
    """
    coros = [fn(query) for fn, src_id, query in search_tasks]
    return await run_concurrently(coros, max_concurrency=max_concurrency)
