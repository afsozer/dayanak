"""Shared test fixtures for emsal-mcp test suite (M-54).

Provides session-scoped cache fixtures to avoid repeated Cache() construction.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_real_cache():
    """Redirect the default Cache() path to a throwaway DB for the whole session.

    Some tests construct a no-arg Cache() (default path). Without this, they
    would read/write the user's REAL corpus (~/.emsal-mcp/cache.sqlite3),
    polluting it with test rows and risking lock contention with other
    processes. Honors the EMSAL_CACHE_PATH override added in cache.py.
    """
    with tempfile.TemporaryDirectory(prefix="emsal_realcache_") as d:
        prev = os.environ.get("EMSAL_CACHE_PATH")
        os.environ["EMSAL_CACHE_PATH"] = str(Path(d) / "isolated_cache.sqlite3")
        try:
            yield
        finally:
            if prev is None:
                os.environ.pop("EMSAL_CACHE_PATH", None)
            else:
                os.environ["EMSAL_CACHE_PATH"] = prev


@pytest.fixture(scope="session", autouse=True)
def _set_full_profile():
    """Ensure existing tests run with the full MCP tool surface (M-97).

    New tests (test_tool_surface.py) override this per-test with
    os.environ["EMSAL_TOOL_PROFILE"] = "core" when testing core profile.
    """
    prev = os.environ.get("EMSAL_TOOL_PROFILE")
    os.environ["EMSAL_TOOL_PROFILE"] = "full"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("EMSAL_TOOL_PROFILE", None)
        else:
            os.environ["EMSAL_TOOL_PROFILE"] = prev


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


def _unwrap_threaded(fn):
    """M-118: sadece ``_tool``un thread sarmalayicisini soy.

    ``inspect.unwrap`` butun ``__wrapped__`` zincirini soyar; bazi araclar
    zaten ``validate_tool_input`` gibi dekoratorlerle sarili oldugu icin bu
    onlarin davranisini da atlardi.  Isaretli tek katmani soyuyoruz (M-119: async araclardaki zaman
    siniri sarmalayicisi da ayni sekilde isaretli).
    """
    if getattr(fn, "__emsal_threaded__", False) or getattr(
        fn, "__emsal_timeout__", False
    ):
        return fn.__wrapped__
    return fn


def capture_registered_tools(profile: str = "full") -> dict:
    """Return ``{tool_name: fn}`` for the tools ``server.main()`` registers.

    Deliberately does NOT purge ``emsal_mcp.*`` from ``sys.modules`` first.
    A purge re-creates every class object, so a Pydantic model imported by an
    earlier test no longer passes ``isinstance`` against the reloaded one —
    which silently broke unrelated test modules that happened to run after.
    It also throws away any monkeypatch a caller just applied, so patches must
    be installed BEFORE calling this.
    """
    import os
    import sys
    from unittest.mock import MagicMock, patch

    registered: dict = {}
    mock_mcp = MagicMock()
    mock_mcp._tool_manager = MagicMock()
    mock_mcp._tool_manager._tools = {}

    def capture_tool(name=None, **kw):
        def decorator(fn):
            # M-118: ``_tool`` sync araclari ``anyio.to_thread`` sarmalayicisiyla
            # kaydediyor.  Testler tasima katmanini degil implementasyonu
            # cagiriyor, o yuzden o tek katmani soyuyoruz.
            registered[name or getattr(fn, "__name__", "unknown")] = _unwrap_threaded(fn)
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    mock_mcp.run = MagicMock()

    prev = os.environ.get("EMSAL_TOOL_PROFILE")
    os.environ["EMSAL_TOOL_PROFILE"] = profile
    try:
        with patch(
            "mcp.server.fastmcp.FastMCP", return_value=mock_mcp
        ), patch.object(sys.stdin, "isatty", return_value=False):
            import emsal_mcp.server

            emsal_mcp.server.main()
    finally:
        if prev is None:
            os.environ.pop("EMSAL_TOOL_PROFILE", None)
        else:
            os.environ["EMSAL_TOOL_PROFILE"] = prev
    return registered
