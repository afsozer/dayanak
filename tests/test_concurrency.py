"""Tests for emsal_mcp.concurrency module — M-29 Async Concurrency."""
from __future__ import annotations

import asyncio

from emsal_mcp.concurrency import (
    get_concurrency_status,
    run_concurrently,
)


class TestConcurrencyBasic:
    """Basic concurrency tests - no live network."""

    async def _identity(self, x: int) -> int:
        await asyncio.sleep(0.001)  # simulate async work
        return x

    async def _failing(self, msg: str) -> int:
        await asyncio.sleep(0.001)
        raise RuntimeError(msg)

    def test_get_concurrency_status(self) -> None:
        """Status reports expected keys."""
        status = get_concurrency_status()
        assert status["ok"] is True
        assert "max_concurrency" in status
        assert isinstance(status["max_concurrency"], int)
        assert status["max_concurrency"] >= 1

    def test_run_concurrently_all_succeed(self) -> None:
        """All coroutines succeed → all results returned."""
        coros = [self._identity(i) for i in range(5)]
        results = asyncio.run(run_concurrently(coros, max_concurrency=2))
        assert len(results) == 5
        assert results == [0, 1, 2, 3, 4]

    def test_run_concurrently_partial_failure(self) -> None:
        """One failure does not abort the batch."""
        coros = [
            self._identity(1),
            self._identity(2),
            self._failing("boom"),
            self._identity(4),
        ]
        results = asyncio.run(run_concurrently(coros, max_concurrency=2))
        assert len(results) == 4
        # First two succeed
        assert results[0] == 1
        assert results[1] == 2
        # Third is an Exception
        assert isinstance(results[2], Exception)
        # Fourth succeeds despite earlier failure
        assert results[3] == 4

    def test_run_concurrently_empty(self) -> None:
        """Empty coros list returns empty results."""
        results = asyncio.run(run_concurrently([]))
        assert results == []

    def test_run_concurrently_custom_limit(self) -> None:
        """Custom max_concurrency is respected."""
        coros = [self._identity(i) for i in range(3)]
        results = asyncio.run(run_concurrently(coros, max_concurrency=1))
        assert len(results) == 3


class TestConcurrencyImports:
    """Module importability."""

    def test_import_clean(self) -> None:
        from emsal_mcp.concurrency import (
            get_concurrency_status,
            run_concurrently,
            run_document_fetches,
            run_source_searches,
        )
        assert callable(get_concurrency_status)
        assert callable(run_concurrently)
        assert callable(run_document_fetches)
        assert callable(run_source_searches)
