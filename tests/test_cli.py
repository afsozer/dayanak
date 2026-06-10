"""Tests for CLI imports and server tool registration."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

from unittest.mock import MagicMock, patch


def _setup_server_mock():
    """Helper: mock FastMCP and return registered tools dict + mock."""
    registered_tools: dict[str, callable] = {}
    mock_mcp = MagicMock()

    def capture_tool():
        """Decorator that captures the registered function."""
        def decorator(fn):
            registered_tools[fn.__name__] = fn
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

    # Verify core tools are registered
    expected_tools = [
        "search_decisions", "get_document", "source_capabilities", "source_smoke",
        "citation_safety", "build_input_pack", "draft_document", "export_bundle",
        "read_udf", "write_udf", "udf_toolkit_status",
        # M-105: install_udf_toolkit_tool removed from MCP
        "search_local_cache",
        # M-105: get_cache_stats, list_cached_documents removed from MCP
        "format_legal_citation", "verify_legal_citation",
        "search_legislation", "get_legislation_document",
        # M-105: build_semantic_index, rebuild_search_index removed from MCP
        "semantic_search",
        "hybrid_search", "index_status",
        "chamber_overview", "profile_chamber", "chamber_timeline",
        "find_similar_chambers",
    ]
    for tool_name in expected_tools:
        assert tool_name in registered_tools, f"Tool '{tool_name}' not registered"

    # Verify run was called
    mock_mcp.run.assert_called_once()


def test_server_source_capabilities_tool():
    """Test source_capabilities MCP tool returns expected structure."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["source_capabilities"]()
    assert isinstance(result, list)
    assert len(result) > 0
    for cap in result:
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


def test_server_get_legislation_types_tool():
    """Test get_legislation_types MCP tool returns expected structure."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["get_legislation_types"]()
    assert isinstance(result, list)
    assert len(result) > 0


def test_server_legislation_source_status_tool():
    """Test legislation_source_status MCP tool returns expected structure."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["legislation_source_status"]()
    assert "ok" in result


def test_server_format_legislation_citation_tool():
    """Test format_legislation_citation MCP tool returns expected structure."""
    registered_tools, mock_mcp = _setup_server_mock()

    with patch("mcp.server.fastmcp.FastMCP", return_value=mock_mcp):
        from emsal_mcp.server import main
        main()

    result = registered_tools["format_legislation_citation"](
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
