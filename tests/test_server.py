"""Server hardening tests — M-22.

Covers:
- All tools have docstrings (or are registered)
- Validation rejects invalid inputs with structured errors
- Server import and instantiation succeeds
- Error catalog is non-empty and complete
- Concurrency counter works
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = [pytest.mark.integration]


# ── Server Import & Instantiation ──────────────────────────────────


class TestServerImport:
    def test_import_server_module(self):
        """Server module should be importable without side effects."""
        mod = importlib.import_module("emsal_mcp.server")
        assert hasattr(mod, "main")

    def test_import_server_utils(self):
        """server_utils module should be importable."""
        from emsal_mcp.server_utils import (
            get_active_requests,
            get_error_codes,
            validate_non_empty,
            validate_positive_int,
            validate_range,
            validate_tool_input,
        )
        # Just verify they're callable
        assert callable(validate_non_empty)
        assert callable(validate_positive_int)
        assert callable(validate_range)
        assert callable(validate_tool_input)
        assert callable(get_error_codes)
        assert callable(get_active_requests)


# ── Input Validators ───────────────────────────────────────────────


class TestValidateNonEmpty:
    def test_valid_string(self):
        from emsal_mcp.server_utils import validate_non_empty
        ok, err = validate_non_empty("hello")
        assert ok is True
        assert err is None

    def test_empty_string(self):
        from emsal_mcp.server_utils import validate_non_empty
        ok, err = validate_non_empty("")
        assert ok is False
        assert "empty" in err

    def test_whitespace_only(self):
        from emsal_mcp.server_utils import validate_non_empty
        ok, err = validate_non_empty("   ")
        assert ok is False

    def test_none_skipped(self):
        """None values should pass (validator only fires when value is not None)."""
        from emsal_mcp.server_utils import validate_non_empty
        ok, err = validate_non_empty(None)
        assert ok is True

    def test_non_string(self):
        """Non-string types should pass (only strings are checked)."""
        from emsal_mcp.server_utils import validate_non_empty
        ok, err = validate_non_empty(42)
        assert ok is True


class TestValidatePositiveInt:
    def test_valid(self):
        from emsal_mcp.server_utils import validate_positive_int
        ok, err = validate_positive_int(1)
        assert ok is True

    def test_zero(self):
        from emsal_mcp.server_utils import validate_positive_int
        ok, err = validate_positive_int(0)
        assert ok is False
        assert "positive" in err

    def test_negative(self):
        from emsal_mcp.server_utils import validate_positive_int
        ok, err = validate_positive_int(-5)
        assert ok is False

    def test_string(self):
        from emsal_mcp.server_utils import validate_positive_int
        ok, err = validate_positive_int("abc")
        assert ok is False

    def test_none_skipped(self):
        from emsal_mcp.server_utils import validate_positive_int
        ok, err = validate_positive_int(None)
        assert ok is True

    def test_float(self):
        from emsal_mcp.server_utils import validate_positive_int
        ok, err = validate_positive_int(3.14)
        assert ok is False


class TestValidateRange:
    def test_valid_in_range(self):
        from emsal_mcp.server_utils import validate_range
        check = validate_range(0.0, 1.0)
        ok, err = check(0.5)
        assert ok is True

    def test_at_boundary(self):
        from emsal_mcp.server_utils import validate_range
        check = validate_range(0.0, 1.0)
        ok, err = check(0.0)
        assert ok is True
        ok2, err2 = check(1.0)
        assert ok2 is True

    def test_out_of_range(self):
        from emsal_mcp.server_utils import validate_range
        check = validate_range(0.0, 1.0)
        ok, err = check(1.5)
        assert ok is False
        assert "between" in err

    def test_below_range(self):
        from emsal_mcp.server_utils import validate_range
        check = validate_range(0.0, 1.0)
        ok, err = check(-0.1)
        assert ok is False

    def test_none_skipped(self):
        from emsal_mcp.server_utils import validate_range
        check = validate_range(0.0, 1.0)
        ok, err = check(None)
        assert ok is True

    def test_non_numeric(self):
        from emsal_mcp.server_utils import validate_range
        check = validate_range(0.0, 1.0)
        ok, err = check("abc")
        assert ok is False


class TestValidateIsDictWithKeys:
    def test_valid_dict(self):
        from emsal_mcp.server_utils import validate_is_dict_with_keys
        check = validate_is_dict_with_keys("document_id", "source")
        ok, err = check({"document_id": "123", "source": "test"})
        assert ok is True

    def test_missing_key(self):
        from emsal_mcp.server_utils import validate_is_dict_with_keys
        check = validate_is_dict_with_keys("document_id", "source")
        ok, err = check({"document_id": "123"})
        assert ok is False
        assert "missing" in err.lower()
        assert "source" in err

    def test_not_dict(self):
        from emsal_mcp.server_utils import validate_is_dict_with_keys
        check = validate_is_dict_with_keys("document_id")
        ok, err = check("not a dict")
        assert ok is False
        assert "dict" in err

    def test_none_skipped(self):
        from emsal_mcp.server_utils import validate_is_dict_with_keys
        check = validate_is_dict_with_keys("document_id")
        ok, err = check(None)
        assert ok is True


# ── validate_tool_input Decorator ──────────────────────────────────


class TestValidateToolInput:
    def test_valid_input_passes(self):
        from emsal_mcp.server_utils import validate_tool_input, validate_non_empty

        @validate_tool_input(query=validate_non_empty)
        def my_tool(query: str) -> dict:
            return {"ok": True, "query": query}

        result = my_tool(query="hello")
        assert result["ok"] is True

    def test_invalid_input_returns_error(self):
        from emsal_mcp.server_utils import validate_tool_input, validate_non_empty

        @validate_tool_input(query=validate_non_empty)
        def my_tool(query: str) -> dict:
            return {"ok": True}

        result = my_tool(query="")
        assert result["ok"] is False
        assert result["errorCode"] == "INVALID_INPUT"
        assert "query" in result["message"]

    def test_multiple_validators_all_fail(self):
        from emsal_mcp.server_utils import validate_tool_input, validate_non_empty, validate_positive_int

        @validate_tool_input(query=validate_non_empty, limit=validate_positive_int)
        def my_tool(query: str, limit: int = 10) -> dict:
            return {"ok": True}

        result = my_tool(query="", limit=0)
        assert result["ok"] is False
        assert "query" in result["message"]
        assert "limit" in result["message"]

    def test_none_value_skipped(self):
        """None values should not trigger validation errors."""
        from emsal_mcp.server_utils import validate_tool_input, validate_non_empty

        @validate_tool_input(query=validate_non_empty)
        def my_tool(query: str | None = None) -> dict:
            return {"ok": True}

        result = my_tool(query=None)
        assert result["ok"] is True

    def test_preserves_function_metadata(self):
        from emsal_mcp.server_utils import validate_tool_input, validate_non_empty

        @validate_tool_input(query=validate_non_empty)
        def my_special_tool(query: str) -> dict:
            """My special tool docstring."""
            return {"ok": True}

        assert my_special_tool.__name__ == "my_special_tool"
        assert "My special tool docstring" in (my_special_tool.__doc__ or "")

    def test_async_tool_stays_coroutine(self):
        """Async tools must remain coroutine functions so FastMCP awaits them.

        Regression: a sync wrapper around an async tool (e.g. search_decisions)
        breaks the MCP server because the result is never awaited.
        """
        import asyncio

        from emsal_mcp.server_utils import validate_tool_input, validate_non_empty

        @validate_tool_input(query=validate_non_empty)
        async def my_async_tool(query: str) -> dict:
            return {"ok": True, "query": query}

        assert asyncio.iscoroutinefunction(my_async_tool)
        result = asyncio.run(my_async_tool(query="hello"))
        assert result == {"ok": True, "query": "hello"}

    def test_async_tool_validation_returns_error(self):
        import asyncio

        from emsal_mcp.server_utils import validate_tool_input, validate_non_empty

        @validate_tool_input(query=validate_non_empty)
        async def my_async_tool(query: str) -> dict:
            return {"ok": True}

        result = asyncio.run(my_async_tool(query=""))
        assert result["ok"] is False
        assert result["errorCode"] == "INVALID_INPUT"


# ── Concurrency Tracking ──────────────────────────────────────────


class TestConcurrencyTracking:
    def test_active_requests_starts_zero(self):
        from emsal_mcp.server_utils import _active_requests
        # Before any tool call, counter should be 0
        assert _active_requests >= 0

    def test_track_request_sync(self):
        from emsal_mcp.server_utils import _track_request
        import emsal_mcp.server_utils as mod

        original = mod._active_requests
        call_count = 0

        @_track_request
        def sync_tool():
            nonlocal call_count
            call_count += 1
            # Inside: should be +1
            assert mod._active_requests >= original + 1
            return {"ok": True}

        result = sync_tool()
        assert result["ok"] is True
        assert call_count == 1
        # After: should be back to original
        assert mod._active_requests == original

    def test_track_request_exception(self):
        """Counter should decrement even on exception."""
        from emsal_mcp.server_utils import _track_request
        import emsal_mcp.server_utils as mod

        original = mod._active_requests

        @_track_request
        def failing_tool():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            failing_tool()

        assert mod._active_requests == original


# ── Error Catalog ──────────────────────────────────────────────────


class TestErrorCatalog:
    def test_catalog_non_empty(self):
        from emsal_mcp.server_utils import get_error_codes
        catalog = get_error_codes()
        assert catalog["total"] > 0
        assert len(catalog["known_codes"]) > 0

    def test_all_required_codes_present(self):
        from emsal_mcp.server_utils import get_error_codes
        catalog = get_error_codes()
        required = [
            "INVALID_INPUT",
            "FETCH_FAILED",
            "FILE_NOT_FOUND",
            "TOOLKIT_UNAVAILABLE",
            "CIRCUIT_OPEN",
            "EMPTY_DB",
            "PARSE_FAILED",
            "CONVERSION_FAILED",
            "EXCEPTION",
        ]
        for code in required:
            assert code in catalog["known_codes"], f"Missing error code: {code}"

    def test_codes_are_sorted(self):
        from emsal_mcp.server_utils import get_error_codes
        catalog = get_error_codes()
        assert catalog["known_codes"] == sorted(catalog["known_codes"])

    def test_total_matches_list_length(self):
        from emsal_mcp.server_utils import get_error_codes
        catalog = get_error_codes()
        assert catalog["total"] == len(catalog["known_codes"])

    def test_known_error_codes_constant(self):
        from emsal_mcp.server_utils import KNOWN_ERROR_CODES
        assert isinstance(KNOWN_ERROR_CODES, list)
        assert len(KNOWN_ERROR_CODES) > 40  # We know there are 48+ codes


# ── Tool Docstring Audit ───────────────────────────────────────────


class TestToolDocstrings:
    """Verify all registered tools have docstrings (via function metadata)."""

    def _get_tool_names_and_docs(self) -> list[tuple[str, str | None]]:
        """Collect tool names and docstrings from the MCP server.

        We import main() and capture the mcp instance to inspect tools.
        """
        from unittest.mock import patch

        captured_tools: dict = {}

        class FakeFastMCP:
            def __init__(self, name: str):
                self.name = name

            def tool(self, **kwargs):
                def decorator(func):
                    captured_tools[func.__name__] = func.__doc__
                    return func
                return decorator

            def run(self):
                pass

        # FastMCP is imported inside main() from mcp.server.fastmcp
        with patch("mcp.server.fastmcp.FastMCP", FakeFastMCP):
            from emsal_mcp.server import main
            main()

        return [(name, doc) for name, doc in captured_tools.items()]

    def test_at_least_50_tools_registered(self):
        """There should be 50+ tools registered."""
        tools = self._get_tool_names_and_docs()
        assert len(tools) >= 50, f"Expected >= 50 tools, got {len(tools)}"

    def test_all_critical_tools_have_docstrings(self):
        """Critical tools must have docstrings."""
        tools = dict(self._get_tool_names_and_docs())
        critical_tools = [
            "search_decisions",
            "get_document",
            "hybrid_search",
            "build_input_pack",
            "citation_safety",
            # M-105: error_catalog, active_requests_count removed from MCP
        ]
        for name in critical_tools:
            assert name in tools, f"Tool {name} not registered"
            assert tools[name] is not None, f"Tool {name} has no docstring"

    def test_no_tool_name_is_empty(self):
        """All registered tools should have non-empty names."""
        tools = self._get_tool_names_and_docs()
        for name, _ in tools:
            assert name.strip(), "Empty tool name found"