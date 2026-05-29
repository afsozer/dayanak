"""Tests for M-36 research watchlist.

Covers:
- Add watch and list
- Run watch detects new docs
- Remove watch
- Invalid name → error
- CLI/MCP imports
"""
from __future__ import annotations

from typing import Any

import pytest

from emsal_mcp.cache import Cache
from emsal_mcp.models import ContentStatus, Document, SearchResult
from emsal_mcp.research_watch import (
    add_watch,
    list_watches,
    remove_watch,
    run_watch,
)


# ---------------------------------------------------------------------------
# Fake source client (no network)
# ---------------------------------------------------------------------------

class _FakeSource:
    """Deterministic fake source for watch tests."""

    source_id = "fake_source"
    name = "Fake Source"
    public = True
    _supports_search = True
    _supports_get_document = True

    def _make_results(self, query: str, limit: int = 3) -> list[SearchResult]:
        results = []
        for i in range(min(limit, 3)):
            results.append(SearchResult(
                source=self.source_id,
                document_id=f"fake-doc-{i+1}",
                title=f"Document {i+1} for '{query}'",
                summary=f"Summary {i+1}",
                court="Fake Court",
                chamber="1. Daire",
                decision_date="2024-06-15",
                content_status=ContentStatus.METADATA_ONLY,
                metadata={},
            ))
        return results

    async def search(self, query: str, limit: int = 10, **kw: Any) -> list[SearchResult]:
        return self._make_results(query, limit)

    async def get_document(self, document_id: str, **kw: Any) -> Document:
        return Document(
            source=self.source_id,
            document_id=document_id,
            title=f"Doc {document_id}",
            court="Fake Court",
            full_text="x" * 200,
            content_status=ContentStatus.FULL_TEXT,
        )

    async def smoke(self, online: bool = False) -> Any:
        from emsal_mcp.models import SourceSmokeResult
        return SourceSmokeResult(source_id=self.source_id)


@pytest.fixture()
def tmp_cache(tmp_path):
    """Provide a temporary Cache instance."""
    db_path = tmp_path / "test_watch.sqlite3"
    c = Cache(db_path)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Tests: add_watch + list_watches
# ---------------------------------------------------------------------------


class TestAddAndListWatches:
    def test_add_watch_basic(self, tmp_cache):
        result = add_watch("test-watch", "tazminat hukuku", cache=tmp_cache)
        assert result["ok"] is True
        assert result["name"] == "test-watch"
        assert result["config"]["query"] == "tazminat hukuku"

    def test_add_watch_with_sources(self, tmp_cache):
        result = add_watch(
            "multi-source", "kira uyuşmazlığı",
            sources=["bedesten", "danistay"],
            fetch_count=10,
            cache=tmp_cache,
        )
        assert result["ok"] is True
        assert result["config"]["sources"] == ["bedesten", "danistay"]
        assert result["config"]["fetch_count"] == 10

    def test_add_watch_with_filters(self, tmp_cache):
        result = add_watch(
            "filtered", "tazminat",
            filters={"court": "Yargıtay"},
            cache=tmp_cache,
        )
        assert result["ok"] is True
        assert result["config"]["filters"] == {"court": "Yargıtay"}

    def test_list_watches_empty(self, tmp_cache):
        result = list_watches(cache=tmp_cache)
        assert result["ok"] is True
        assert result["watches"] == []
        assert result["total"] == 0

    def test_list_watches_after_add(self, tmp_cache):
        add_watch("w1", "query1", cache=tmp_cache)
        add_watch("w2", "query2", cache=tmp_cache)
        result = list_watches(cache=tmp_cache)
        assert result["ok"] is True
        assert result["total"] == 2
        names = {w["name"] for w in result["watches"]}
        assert names == {"w1", "w2"}

    def test_add_watch_duplicate_name(self, tmp_cache):
        add_watch("dup", "first", cache=tmp_cache)
        result = add_watch("dup", "second", cache=tmp_cache)
        assert result["ok"] is False
        assert result["errorCode"] == "WATCH_EXISTS"


# ---------------------------------------------------------------------------
# Tests: run_watch
# ---------------------------------------------------------------------------


class TestRunWatch:
    def test_run_watch_not_found(self, tmp_cache):
        result = run_watch("nonexistent", cache=tmp_cache)
        assert result["ok"] is False
        assert result["errorCode"] == "WATCH_NOT_FOUND"

    def test_run_watch_detects_new_docs(self, tmp_cache):
        add_watch("run-test", "test query", sources=["fake_source"], cache=tmp_cache)
        fake = _FakeSource()
        result = run_watch(
            "run-test", cache=tmp_cache,
            sources_override={"fake_source": fake},
        )
        assert result["ok"] is True
        assert result["name"] == "run-test"
        assert "diff_report" in result
        assert result["diff_report"]["total_results"] == 3
        # First run: all documents are "new"
        assert result["diff_report"]["new_document_count"] == 3

    def test_run_watch_second_run_fewer_new(self, tmp_cache):
        add_watch("run2", "query", sources=["fake_source"], cache=tmp_cache)
        fake = _FakeSource()

        # First run — all docs are new
        result1 = run_watch("run2", cache=tmp_cache, sources_override={"fake_source": fake})
        assert result1["ok"] is True
        assert result1["diff_report"]["new_document_count"] == 3

        # Second run — same docs → no new docs
        result2 = run_watch("run2", cache=tmp_cache, sources_override={"fake_source": fake})
        assert result2["ok"] is True
        assert result2["diff_report"]["new_document_count"] == 0

    def test_run_watch_updates_last_run_at(self, tmp_cache):
        add_watch("lr-test", "q", sources=["fake_source"], cache=tmp_cache)
        fake = _FakeSource()

        # Before run
        listing = list_watches(cache=tmp_cache)
        assert listing["watches"][0]["last_run_at"] is None

        run_watch("lr-test", cache=tmp_cache, sources_override={"fake_source": fake})

        listing = list_watches(cache=tmp_cache)
        assert listing["watches"][0]["last_run_at"] is not None


# ---------------------------------------------------------------------------
# Tests: remove_watch
# ---------------------------------------------------------------------------


class TestRemoveWatch:
    def test_remove_watch_basic(self, tmp_cache):
        add_watch("to-remove", "query", cache=tmp_cache)
        result = remove_watch("to-remove", cache=tmp_cache)
        assert result["ok"] is True
        assert result["removed"] is True

        listing = list_watches(cache=tmp_cache)
        assert listing["total"] == 0

    def test_remove_watch_not_found(self, tmp_cache):
        result = remove_watch("ghost", cache=tmp_cache)
        assert result["ok"] is False
        assert result["errorCode"] == "WATCH_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tests: invalid input
# ---------------------------------------------------------------------------


class TestInvalidInput:
    def test_empty_name_rejected(self, tmp_cache):
        result = add_watch("", "query", cache=tmp_cache)
        assert result["ok"] is False
        assert result["errorCode"] == "INVALID_NAME"

    def test_whitespace_name_rejected(self, tmp_cache):
        result = add_watch("   ", "query", cache=tmp_cache)
        assert result["ok"] is False
        assert result["errorCode"] == "INVALID_NAME"

    def test_empty_query_rejected(self, tmp_cache):
        result = add_watch("my-watch", "", cache=tmp_cache)
        assert result["ok"] is False
        assert result["errorCode"] == "INVALID_QUERY"

    def test_remove_empty_name(self, tmp_cache):
        result = remove_watch("", cache=tmp_cache)
        assert result["ok"] is False
        assert result["errorCode"] == "INVALID_NAME"


# ---------------------------------------------------------------------------
# Tests: CLI/MCP imports
# ---------------------------------------------------------------------------


class TestImports:
    def test_cli_imports(self):
        """CLI module should import without error."""
        from emsal_mcp.cli import (
            watch_add,
            watch_list,
            watch_remove,
            watch_run,
        )
        assert callable(watch_add)
        assert callable(watch_list)
        assert callable(watch_remove)
        assert callable(watch_run)

    def test_research_watch_imports(self):
        """research_watch module should export all public functions."""
        from emsal_mcp.research_watch import add_watch, list_watches, remove_watch, run_watch
        assert callable(add_watch)
        assert callable(list_watches)
        assert callable(remove_watch)
        assert callable(run_watch)

    def test_server_imports(self):
        """server module should be importable (MCP tools registered)."""
        # Just verify the module-level imports don't fail
        import emsal_mcp.server  # noqa: F401
