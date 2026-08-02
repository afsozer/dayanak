"""Tests for local-corpus search as a discovery tool (Yargı-MCP parity Görev 7).

- related_quotes attached to results
- corpus_coverage metadata
- discovery (not forbidden) positioning

M-110: these used to exercise ``emsal_mcp.facades``, a parallel module that
``server.py`` never imported.  The features were implemented there and nowhere
else, so the tests passed while the live MCP tool returned neither field.  They
now run against the tool the server actually registers.
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


def _search_local_corpus():
    """Return the live ``search_local_corpus`` tool from server.main()."""
    from tests.conftest import capture_registered_tools

    return capture_registered_tools("core")["search_local_corpus"]


class TestEnrichRelatedQuotes:
    """Exercise the enrichment logic via lexical mode over a tiny cache."""

    def test_related_quotes_attached(self, tmp_path, monkeypatch):
        # Point the cache to an isolated DB and populate it with one doc.
        from emsal_mcp.cache import Cache
        from emsal_mcp.models import Document, ContentStatus

        db = tmp_path / "disco.sqlite3"
        monkeypatch.setenv("EMSAL_CACHE_PATH", str(db))
        cache = Cache(db)
        doc = Document(
            source="bedesten", document_id="d1", title="Karar",
            full_text="İşçinin haklı nedenle feshinde kıdem tazminatı hakkı "
                      "doğar ve bu hak zamanaşımına uğrar.",
            content_status=ContentStatus.HTML_MARKDOWN,
            court="Yargıtay", decision_date="2023-01-01",
        )
        cache.store_document(doc)
        cache.close()

        result = _search_local_corpus()(
            query="kıdem tazminatı hakkı",
            mode="lexical",
            limit=5,
        )
        assert result["ok"] is True
        # lexical results come from cache.search_local which returns dicts;
        # enrichment adds related_quotes to each.
        for r in result.get("results", []):
            assert "related_quotes" in r

    def test_corpus_coverage_reported(self, tmp_path, monkeypatch):
        from emsal_mcp.cache import Cache
        from emsal_mcp.models import Document, ContentStatus

        db = tmp_path / "cov.sqlite3"
        monkeypatch.setenv("EMSAL_CACHE_PATH", str(db))
        cache = Cache(db)
        for i, d in enumerate(["2023-01-01", "2024-06-15"]):
            cache.store_document(Document(
                source="bedesten", document_id=f"d{i}", title="K",
                full_text="kıdem tazminatı metni " * 10,
                content_status=ContentStatus.HTML_MARKDOWN,
                decision_date=d,
            ))
        cache.close()

        result = _search_local_corpus()(query="kıdem", mode="lexical", limit=5)
        # coverage should be populated from min/max decision_date
        assert result.get("corpus_coverage") is not None
        assert "2023" in result["corpus_coverage"]

    def test_discovery_docstring_no_forbidden(self):
        """The docstrings no longer forbid local search as research."""
        ds = _search_local_corpus().__doc__ or ""
        # positioning is now "DISCOVERY", not "NOT A RESEARCH TOOL"
        assert "DISCOVERY" in ds.upper()
        assert "⛔" not in ds
