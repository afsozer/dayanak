"""M-97: Tool surface profile tests.

Verifies:
- Core profile exposes exactly 14 tools (M-98 snapshot).
- Full profile tool count >= previous snapshot (regression guard).
- EMSAL_TOOL_PROFILE env var controls registration.
"""
from __future__ import annotations

import os
import inspect
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.integration]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _capture_tools(profile: str) -> dict[str, object]:
    """Mock FastMCP, call main(), return {tool_name: function} dict."""
    registered: dict[str, object] = {}
    mock_mcp = MagicMock()
    mock_mcp._tool_manager = MagicMock()
    mock_mcp._tool_manager._tools = {}

    # We need add_tool because _tool() delegates to mcp.tool() which calls mcp.add_tool()
    def capture_add_tool(fn, name=None, **kw):
        tool_name = name or getattr(fn, "__name__", "unknown")
        registered[tool_name] = fn
        mock_mcp._tool_manager._tools[tool_name] = fn
        return None

    def capture_tool(name=None, **kw):
        if callable(name):
            raise TypeError("The @tool decorator was used incorrectly.")
        def decorator(fn):
            tool_name = name or getattr(fn, "__name__", "unknown")
            registered[tool_name] = fn
            mock_mcp._tool_manager._tools[tool_name] = fn
            return fn
        return decorator

    mock_mcp.add_tool = capture_add_tool
    mock_mcp.tool = capture_tool
    mock_mcp.run = MagicMock()
    # Save/restore env to avoid cross-test contamination
    prev_profile = os.environ.get("EMSAL_TOOL_PROFILE")
    os.environ["EMSAL_TOOL_PROFILE"] = profile
    try:
        with patch(
            "mcp.server.fastmcp.FastMCP", return_value=mock_mcp
        ), patch.object(sys.stdin, "isatty", return_value=False):
            # Force fresh import by clearing all emsal_mcp modules
            for key in list(sys.modules.keys()):
                if key.startswith("emsal_mcp."):
                    del sys.modules[key]
            if "emsal_mcp" in sys.modules:
                del sys.modules["emsal_mcp"]
            import emsal_mcp.server
            emsal_mcp.server.main()
    finally:
        if prev_profile is None:
            os.environ.pop("EMSAL_TOOL_PROFILE", None)
        else:
            os.environ["EMSAL_TOOL_PROFILE"] = prev_profile

    return registered


def _closure_var(fn: object, name: str) -> object:
    freevars = getattr(fn, "__code__").co_freevars
    closure = getattr(fn, "__closure__") or ()
    values = dict(zip(freevars, (cell.cell_contents for cell in closure), strict=False))
    return values[name]


# ── M-98: Core profile snapshot ───────────────────────────────────────────────

CORE_TOOLS = [
    "search_decisions",
    "get_document",
    "search_local_corpus",
    "search_legislation",
    "get_legislation",
    "research_topic",
    "citation_check",
    "prepare_petition",
    "export_document",
    "read_legal_file",
    "list_sources",
    "legal_research_guide",
    "load_extended_tools",
    "health_check",
]


class TestCoreProfile:
    """Core profile: exactly 14 tools."""

    def test_core_profile_exact_count(self) -> None:
        tools = _capture_tools("core")
        assert len(tools) == 14, (
            f"Expected 14 core tools, got {len(tools)}: {sorted(tools.keys())}"
        )

    def test_core_profile_matches_snapshot(self) -> None:
        tools = _capture_tools("core")
        actual = sorted(tools.keys())
        expected = sorted(CORE_TOOLS)
        assert actual == expected, (
            f"Core tool mismatch.\nExpected: {expected}\nActual:   {actual}"
        )

    def test_core_profile_every_tool_has_docstring(self) -> None:
        tools = _capture_tools("core")
        for name, fn in tools.items():
            assert fn.__doc__, f"Tool '{name}' missing docstring"

    def test_core_profile_token_budget_under_20000_chars(self) -> None:
        tools = _capture_tools("core")
        total = 0
        for name, fn in tools.items():
            total += len(name)
            total += len(inspect.getdoc(fn) or "")
            total += len(str(inspect.signature(fn)))
        assert total < 20_000

    def test_load_extended_tools_registers_category_idempotently(self) -> None:
        tools = _capture_tools("core")
        before = len(tools)

        result = tools["load_extended_tools"](["cache_admin"])

        assert result["ok"] is True
        assert len(tools) > before
        assert "get_cache_stats" in tools
        assert callable(tools["get_cache_stats"])
        assert result["loaded_tools"]

        second = tools["load_extended_tools"](["cache_admin"])

        assert second["ok"] is True
        assert "get_cache_stats" in second["already_loaded"]

    def test_load_extended_tools_invalid_category_is_structured_error(self) -> None:
        tools = _capture_tools("core")

        result = tools["load_extended_tools"](["not_a_category"])

        assert result["ok"] is False
        assert result["errorCode"] == "INVALID_INPUT"
        assert "valid_categories" in result

    def test_load_extended_tools_registration_failure_reports_errors(self) -> None:
        tools = _capture_tools("core")
        mcp = _closure_var(tools["load_extended_tools"], "mcp")
        original_tool = mcp.tool

        def failing_tool(*args, **kwargs):
            def decorator(fn):
                if getattr(fn, "__name__", "") == "get_cache_stats":
                    raise RuntimeError("registration failed")
                return original_tool(*args, **kwargs)(fn)
            return decorator

        mcp.tool = failing_tool

        result = tools["load_extended_tools"](["cache_admin"])

        assert result["ok"] is False
        assert {"tool": "get_cache_stats", "error": "registration failed"} in result["errors"]
        assert "get_cache_stats" not in result["loaded_tools"]


class TestFullProfile:
    """Full profile: all tools (>= 131, regression guard)."""

    FULL_TOOL_COUNT_SNAPSHOT = 131

    def test_full_profile_count_meets_snapshot(self) -> None:
        tools = _capture_tools("full")
        assert len(tools) >= self.FULL_TOOL_COUNT_SNAPSHOT, (
            f"Expected >= {self.FULL_TOOL_COUNT_SNAPSHOT} tools in full profile, "
            f"got {len(tools)}"
        )

    def test_full_profile_includes_all_core_tools(self) -> None:
        tools = _capture_tools("full")
        for name in CORE_TOOLS:
            assert name in tools, f"Core tool '{name}' missing from full profile"


class TestProfileEnvVar:
    """EMSAL_TOOL_PROFILE env var correctly controls registration."""

    def test_core_vs_full_counts_differ(self) -> None:
        tools_core = _capture_tools("core")
        tools_full = _capture_tools("full")
        assert len(tools_full) > len(tools_core), (
            f"Full ({len(tools_full)}) should have more tools than core ({len(tools_core)})"
        )

    def test_invalid_profile_falls_back_to_core(self) -> None:
        tools = _capture_tools("garbage")
        assert len(tools) == 14, f"Invalid profile should fallback to 14 core, got {len(tools)}"
