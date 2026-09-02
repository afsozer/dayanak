"""Tests for CLI imports and server tool registration."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

from unittest.mock import MagicMock, patch


def _unwrap_threaded(fn):
    """M-118: sadece ``_tool``un thread sarmalayicisini soy.

    ``server.main()`` sync araclari ``anyio.to_thread.run_sync`` ile
    calistiran async bir sarmalayiciyla kaydediyor; bu testler
    implementasyonu dogrudan cagirdigi icin o tek katman soyulur
    (``inspect.unwrap`` diger dekoratorleri de atlardi).
    """
    if getattr(fn, "__emsal_threaded__", False) or getattr(
        fn, "__emsal_timeout__", False
    ):
        return fn.__wrapped__
    return fn


def _setup_server_mock():
    """Helper: mock FastMCP and return registered tools dict + mock."""
    registered_tools: dict[str, callable] = {}
    mock_mcp = MagicMock()

    def capture_tool():
        """Decorator that captures the registered function."""
        def decorator(fn):
            registered_tools[fn.__name__] = _unwrap_threaded(fn)
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    mock_mcp.run = MagicMock()
    return registered_tools, mock_mcp


def test_cli_imports():
    """Test that CLI module can be imported."""
    from emsal_mcp.cli import app
    assert app is not None


def test_server_imports():
    """Test that server module can be imported."""
    from emsal_mcp import server
    assert hasattr(server, "main")


def test_server_main_registers_tools():
    """Test that server.main() registers all expected MCP tools without crashing.

    Mocks FastMCP.run() so the server doesn't start listening, but all
    tool registrations and function definitions are exercised.
    """
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    # Verify tools are registered.  M-110 deleted every name a core facade
    # already covered (see tool_profile.RETIRED_TOOLS) — this list only names
    # tools that survive.
    expected_tools = [
        "search_decisions", "get_document", "search_local_corpus",
        "search_legislation", "get_legislation", "citation_check",
        "prepare_petition", "export_document", "read_legal_file",
        "list_sources", "research_topic", "health_check",
        "source_smoke", "draft_document", "export_bundle",
        "udf_toolkit_status", "index_status",
        "chamber_overview", "profile_chamber", "chamber_timeline",
        "find_similar_chambers",
    ]
    for tool_name in expected_tools:
        assert tool_name in registered_tools, f"Tool '{tool_name}' not registered"

    # And the retired duplicates really are gone.
    from emsal_mcp.tool_profile import RETIRED_TOOLS

    leftovers = sorted(set(RETIRED_TOOLS) & set(registered_tools))
    assert not leftovers, f"Retired tools still registered: {leftovers}"

    # Verify run was called
    mock_mcp.run.assert_called_once()


def test_server_list_sources_tool():
    """list_sources() replaces the retired source_capabilities tool."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["list_sources"]()
    assert result["ok"] is True
    assert len(result["sources"]) > 0
    for cap in result["sources"]:
        assert "source_id" in cap


def test_server_source_smoke_tool():
    """Test source_smoke MCP tool returns expected structure."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["source_smoke"](online=False)
    assert "ok" in result
    assert "source_count" in result
    assert "sources" in result


def test_server_final_v1_readiness_tool():
    """Test final_v1_readiness is CLI-only, not registered as MCP tool (M-103)."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    assert "final_v1_readiness" not in registered_tools


def test_server_udf_toolkit_status_tool():
    """Test udf_toolkit_status MCP tool returns expected structure."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["udf_toolkit_status"]()
    assert "ok" in result


def test_server_legislation_types_via_list_sources():
    """list_sources(detail="legislation_types") replaces get_legislation_types."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["list_sources"](detail="legislation_types")
    assert result["ok"] is True
    assert len(result["types"]) > 0


def test_server_health_check_tool():
    """health_check() replaces the retired legislation_source_status tool."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["health_check"]()
    assert "ok" in result


def test_server_format_legislation_citation_via_citation_check():
    """citation_check(action="format_legislation") replaces the retired tool."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["citation_check"](
        action="format_legislation",
        document={"title": "Test Kanun", "legislation_no": "7456", "gazette_date": "2023-07-15"},
        style="full",
    )
    assert "formatted_citation" in result


def test_verification_imports():
    """Test that verification module can be imported."""
    from emsal_mcp.verification import (
        check_cache_integrity,
        smoke_test_offline,
        verify_bundle_archive_integrity,
        verify_document_hash_in_cache,
    )
    assert callable(smoke_test_offline)
    assert callable(check_cache_integrity)
    assert callable(verify_bundle_archive_integrity)
    assert callable(verify_document_hash_in_cache)


def test_drafter_imports():
    """Test that drafter module can be imported."""
    from emsal_mcp.drafter import assemble_draft, validate_draft_body
    assert callable(assemble_draft)
    assert callable(validate_draft_body)


def test_smoke_test_offline():
    """Run offline smoke test."""
    from emsal_mcp.verification import smoke_test_offline
    result = smoke_test_offline()
    assert result["ok"] is True
    assert len(result["tests"]) > 0
    for test in result["tests"]:
        assert test["ok"] is True
