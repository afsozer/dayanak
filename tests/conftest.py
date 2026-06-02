"""Shared test fixtures for emsal-mcp test suite (M-54).

Provides session-scoped cache fixtures to avoid repeated Cache() construction.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def session_tmp_dir():
    """Session-scoped temporary directory for all tests."""
    with tempfile.TemporaryDirectory(prefix="emsal_test_") as d:
        yield Path(d)


@pytest.fixture(scope="session")
def session_cache_path(session_tmp_dir):
    """Path to a session-scoped SQLite cache DB."""
    return session_tmp_dir / "session_cache.sqlite3"


@pytest.fixture(scope="session")
def session_cache(session_cache_path):
    """A Cache instance that persists for the entire test session.

    Tests that only READ from an empty cache should use this fixture.
    Tests that WRITE should use a per-test cache via tmp_path instead.
    """
    from emsal_mcp.cache import Cache
    cache = Cache(session_cache_path)
    yield cache
    cache.db.close()


@pytest.fixture(scope="module")
def module_tmp_dir():
    """Module-scoped temporary directory."""
    with tempfile.TemporaryDirectory(prefix="emsal_mod_") as d:
        yield Path(d)


@pytest.fixture(scope="function")
def fresh_cache(tmp_path):
    """A fresh Cache instance per test function (isolated DB)."""
    from emsal_mcp.cache import Cache
    cache = Cache(tmp_path / "test.sqlite3")
    yield cache
    cache.db.close()
