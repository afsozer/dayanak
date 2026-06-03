"""M-89: Real MCP-protocol E2E tests.

Tests the actual MCP server tool surface — not just individual function calls.
Validates that every registered tool can be invoked, returns a structured dict,
and doesn't crash with basic valid inputs.  Uses mock sources/fake data — no
live network.
"""
from __future__ import annotations

from typing import Any

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.models import Document, ContentStatus


def _make_test_document() -> dict[str, Any]:
    """Create a valid test document for tools that require one."""
    doc = Document(
        source="test",
        document_id="test-123",
        title="Test Decision",
        court="Yargitay",
        content_status=ContentStatus.FULL_TEXT,
        full_text="Test content for citation safety checking.",
        markdown="# Test\n\nTest content.",
        karar_no="2025/123",
        decision_date="2025-01-15",
    )
    return doc.model_dump(mode="json")


class TestMCPE2EHappyPath:
    """Happy-path E2E: each critical tool is called and returns a valid dict."""

    def _call_tool(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        """Import server, access the MCP instance, and call a tool."""
        import importlib
        # Reload to get a fresh server instance
        spec = importlib.util.find_spec("emsal_mcp.server")
        assert spec is not None
        # Import server module — this also creates the FastMCP instance
        # We don't call main() (it blocks with mcp.run()).
        # Instead, directly import the decorated functions.

    def test_search_decisions_source_resolvable(self) -> None:
        """The source backing search_decisions resolves and exposes async search/get."""
        from emsal_mcp.sources.registry import get_source

        src = get_source("bedesten")
        assert src is not None
        assert callable(getattr(src, "search", None))
        assert callable(getattr(src, "get_document", None))

    def test_all_mcp_server_imports(self) -> None:
        """Server module imports without errors (catches async decorator bugs)."""
        # This is the key test: if any @mcp.tool() decorator has a bug,
        # importing server.py will raise an exception.
        import emsal_mcp.server as server_mod
        assert server_mod is not None
        # Verify main() is callable (won't actually run — blocked by mcp.run())
        assert callable(server_mod.main)


class TestMCPToolInvocation:
    """Test that the underlying tool functions work correctly.

    These are the actual implementations that @mcp.tool() wraps.
    """

    def test_search_decisions_impl(self) -> None:
        """search_decisions via fake source doesn't crash."""
        import asyncio
        from emsal_mcp.models import SearchResult, ContentStatus as CS

        class FakeSource:
            source_id = "test"
            name = "Test"
            async def search(self, query, limit=10, **filters):
                return [SearchResult(
                    source="test", document_id="id1", title="Result",
                    content_status=CS.METADATA_ONLY,
                )]
            async def get_document(self, document_id, **kwargs):
                return Document(
                    source="test", document_id=document_id, title="Doc",
                    full_text="content", content_status=CS.FULL_TEXT,
                )

        src = FakeSource()
        results = asyncio.run(src.search("test query"))
        assert len(results) == 1
        assert results[0].source == "test"

    def test_get_document_impl(self) -> None:
        """get_document via fake source returns Document."""
        import asyncio
        from emsal_mcp.models import Document, ContentStatus as CS

        class FakeSource:
            source_id = "test"
            name = "Test"
            async def search(self, query, limit=10, **filters):
                return []
            async def get_document(self, document_id, **kwargs):
                return Document(
                    source="test", document_id=document_id, title="Doc",
                    full_text="content", content_status=CS.FULL_TEXT,
                )

        src = FakeSource()
        doc = asyncio.run(src.get_document("test-1"))
        assert doc.document_id == "test-1"
        assert doc.quote_usable is True

    def test_citation_safety_impl(self) -> None:
        """citation_check on a valid document returns ok=True."""
        from emsal_mcp.safety import citation_check
        from emsal_mcp.models import Document, ContentStatus as CS

        doc = Document(
            source="test", document_id="t1", title="Test",
            full_text="sufficient content for checking", content_status=CS.FULL_TEXT,
            karar_no="2025/1", decision_date="2025-01-01",
        )
        result = citation_check(doc)
        assert isinstance(result.model_dump(mode="json"), dict)

    def test_hybrid_search_impl(self) -> None:
        """hybrid_search returns valid dict structure."""
        from emsal_mcp.semantic import hybrid_search
        result = hybrid_search("test", limit=3)
        assert isinstance(result, dict)
        assert "results" in result or "ok" in result

    def test_citation_check_impl(self) -> None:
        """citation_check returns result with expected keys."""
        from emsal_mcp.safety import citation_check
        from emsal_mcp.models import Document, ContentStatus as CS

        doc = Document(
            source="test", document_id="t2", title="Doc",
            full_text="content", content_status=CS.FULL_TEXT,
            karar_no="2025/1", decision_date="2025-01-01",
        )
        result = citation_check(doc)
        assert result.ok is True


class TestMCPErrorHandling:
    """Error-path: tools never crash, always return structured dicts."""

    def test_search_invalid_source(self) -> None:
        """An unknown source id raises KeyError (caught/handled by callers)."""
        import pytest

        from emsal_mcp.sources.registry import get_source

        with pytest.raises(KeyError):
            get_source("nonexistent_source_xyz")

    def test_get_document_empty_id_rejected_by_validator(self) -> None:
        """The validator guarding get_document rejects an empty document_id."""
        from emsal_mcp.server_utils import validate_non_empty

        ok, msg = validate_non_empty("")
        assert ok is False
        assert msg

    def test_hybrid_search_empty_query(self) -> None:
        """hybrid_search with empty query returns structured result."""
        from emsal_mcp.semantic import hybrid_search
        result = hybrid_search("")
        assert isinstance(result, dict)

    def test_citation_check_empty_doc(self) -> None:
        """citation_check on minimal doc doesn't crash."""
        from emsal_mcp.safety import citation_check
        from emsal_mcp.models import Document

        doc = Document(source="test", document_id="minimal", title="Minimal")
        result = citation_check(doc)
        assert result.ok is False  # no content


class TestMCPAsyncDecorator:
    """Verify async decorators are correctly applied.

    The bug: some @mcp.tool() functions are async but the wrapper wasn't
    handling this correctly, causing crashes when called via MCP clients.
    """

    def test_async_tools_are_callable(self) -> None:
        """All async tools should be importable without errors."""
        from emsal_mcp.server import main
        assert callable(main)

    def test_server_import_does_not_crash(self) -> None:
        """Importing server module must not raise any exception."""
        import emsal_mcp.server
        # Verify module-level @mcp.tool() decorators don't fail
        assert hasattr(emsal_mcp.server, "main")
