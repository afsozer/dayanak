"""Tests for emsal_mcp.semantic module – v0.11 Semantic/Hybrid Search.

Covers:
  - build_semantic_index
  - semantic_search
  - hybrid_search
  - get_index_status
  - rebuild_index
  - Module constants
  - Edge cases (Turkish chars, empty text, many docs)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from emsal_mcp.cache import Cache

pytestmark = [pytest.mark.integration]
from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.semantic import (
    SEMANTIC_VERSION,
    _compute_tfidf_vectors,
    _expand_query,
    _generate_snippet,
    _load_corpus_idf,
    _load_query_idf,
    _rrf_fusion,
    _strip_turkish_suffix,
    build_semantic_index,
    get_index_status,
    get_index_sync_status,
    hybrid_search,
    hybrid_search_rrf,
    rebuild_index,
    semantic_search,
    update_indexes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_DOCS = [
    {
        "source": "yargitay",
        "document_id": "yg-001",
        "title": "Sözleşme İhlali Hakkında Karar",
        "court": "Yargitay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": (
            "Taraflar arasındaki sözleşme hükümleri ihlal edilmiştir. "
            "Borçlar Kanunu madde 96 uyarınca tazminat talep edilebilir."
        ),
        "markdown": "# Sözleşme İhlali\n\nTaraflar arasındaki sözleşme hükümleri ihlal edilmiştir.",
    },
    {
        "source": "danistay",
        "document_id": "ds-001",
        "title": "İdari Para Cezası İptali",
        "court": "Danistay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": (
            "İdari para cezasının iptali talebiyle açılan davada, "
            "idarenin yetkisiz olduğu anlaşılmıştır. Kabahatler Kanunu kapsamında değerlendirme yapılmıştır."
        ),
        "markdown": "# İdari Para Cezası\n\nİdari para cezasının iptali talebiyle açılan davada...",
    },
    {
        "source": "yargitay",
        "document_id": "yg-002",
        "title": "İş Kazası Tazminat Davası",
        "court": "Yargitay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": (
            "İş kazası sonucu oluşan maddi zararın tazmini istemiyle açılan dava. "
            "İşverenin kusur oranı bilirkişi raporuyla tespit edilmiştir."
        ),
        "markdown": "# İş Kazası\n\nİş kazası sonucu oluşan maddi zarar...",
    },
]


def _make_doc(**overrides) -> Document:
    """Create a test Document with sensible defaults."""
    defaults = {
        "source": "yargitay",
        "document_id": "test-1",
        "title": "Test Decision About Contracts",
        "court": "Yargitay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": "This is a test document about contract law and obligations.",
        "markdown": "Test markdown content about contracts.",
    }
    defaults.update(overrides)
    return Document(**defaults)


def _populate_docs(cache: Cache, docs: list[dict] | None = None) -> None:
    """Store a list of document dicts (or SAMPLE_DOCS) into cache."""
    for doc_data in (docs or SAMPLE_DOCS):
        cache.store_document(Document(**doc_data))


def _build_and_populate(
    cache: Cache, docs: list[dict] | None = None, force_rebuild: bool = False
) -> dict:
    """Store docs and build the semantic index; return the build result."""
    _populate_docs(cache, docs)
    return build_semantic_index(cache=cache, force_rebuild=force_rebuild)


# ===================================================================
# TestBuildSemanticIndex
# ===================================================================


class TestBuildSemanticIndex:
    """Tests for build_semantic_index()."""

    def test_build_index_empty(self, tmp_path: Path) -> None:
        """Build on empty DB should still return ok but warn about no docs."""
        cache = Cache(tmp_path / "empty.sqlite3")
        try:
            result = build_semantic_index(cache=cache)
            assert result["ok"] is True
            assert result["vectors_count"] == 0
            assert result["fts5_row_count"] == 0
            assert result["documents_total"] == 0
            assert result["version"] == SEMANTIC_VERSION
        finally:
            cache.close()

    def test_build_index_with_docs(self, tmp_path: Path) -> None:
        """Store 3 documents, build index, verify counts."""
        cache = Cache(tmp_path / "docs.sqlite3")
        try:
            result = _build_and_populate(cache)
            assert result["ok"] is True
            assert result["documents_total"] == 3
            assert result["vectors_count"] == 3
            assert result["fts5_row_count"] == 3
        finally:
            cache.close()

    def test_force_rebuild(self, tmp_path: Path) -> None:
        """Force rebuild drops and recreates indices."""
        cache = Cache(tmp_path / "force.sqlite3")
        try:
            _build_and_populate(cache)
            # Force rebuild
            result = build_semantic_index(cache=cache, force_rebuild=True)
            assert result["ok"] is True
            assert result["documents_total"] == 3
            assert result["vectors_count"] == 3
            # The warning about dropping indices should be present
            drop_warnings = [w for w in result["warnings"] if "dropped" in w.lower()]
            assert len(drop_warnings) > 0
        finally:
            cache.close()

    def test_build_returns_correct_keys(self, tmp_path: Path) -> None:
        """Verify all expected keys are present in the return dict."""
        cache = Cache(tmp_path / "keys.sqlite3")
        try:
            result = _build_and_populate(cache)
            expected_keys = {
                "ok",
                "fts5_exists",
                "fts5_row_count",
                "vectors_count",
                "documents_total",
                "warnings",
                "recommended_next_steps",
                "version",
            }
            assert expected_keys.issubset(set(result.keys()))
        finally:
            cache.close()

    def test_build_creates_fts5_and_vectors_tables(self, tmp_path: Path) -> None:
        """After build, both FTS5 and search_vectors tables should exist."""
        cache = Cache(tmp_path / "tables.sqlite3")
        try:
            _build_and_populate(cache)
            tables = [
                row[0]
                for row in cache.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "documents_v2_fts" in tables
            assert "search_vectors" in tables
        finally:
            cache.close()

    def test_build_warns_on_textless_docs(self, tmp_path: Path) -> None:
        """Documents without text content should yield a warning about vectors."""
        cache = Cache(tmp_path / "textless.sqlite3")
        try:
            docs = [
                {
                    "source": "test",
                    "document_id": "no-text-1",
                    "title": "No Text Doc",
                    "content_status": ContentStatus.METADATA_ONLY,
                },
            ]
            result = _build_and_populate(cache, docs=docs)
            assert result["ok"] is True
            assert result["vectors_count"] == 0
            text_warnings = [w for w in result["warnings"] if "text content" in w.lower() or "vectors" in w.lower()]
            assert len(text_warnings) > 0
        finally:
            cache.close()


# ===================================================================
# TestSemanticSearch
# ===================================================================


class TestSemanticSearch:
    """Tests for semantic_search()."""

    def test_search_basic(self, tmp_path: Path) -> None:
        """Store docs, build index, search for 'sözleşme' – should find yg-001."""
        cache = Cache(tmp_path / "search_basic.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert result["total_matches"] >= 1
            doc_ids = [r["document_id"] for r in result["results"]]
            assert "yg-001" in doc_ids
        finally:
            cache.close()

    def test_search_scores_descending(self, tmp_path: Path) -> None:
        """Verify results are sorted by score descending."""
        cache = Cache(tmp_path / "scores.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("tazminat", cache=cache)
            assert result["ok"] is True
            scores = [r["score"] for r in result["results"]]
            assert scores == sorted(scores, reverse=True)
        finally:
            cache.close()

    def test_search_empty_query(self, tmp_path: Path) -> None:
        """Empty query returns empty results with a warning."""
        cache = Cache(tmp_path / "empty_q.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("", cache=cache)
            assert result["ok"] is True
            assert result["results"] == []
            assert len(result["warnings"]) > 0
        finally:
            cache.close()

    def test_search_no_docs(self, tmp_path: Path) -> None:
        """Search on empty DB returns ok with empty results and warning."""
        cache = Cache(tmp_path / "no_docs.sqlite3")
        try:
            result = semantic_search("contract", cache=cache)
            assert result["ok"] is True
            assert result["results"] == []
            assert result["total_matches"] == 0
            assert len(result["warnings"]) > 0
        finally:
            cache.close()

    def test_search_with_filters(self, tmp_path: Path) -> None:
        """Filter by source='yargitay' – should exclude danistay docs."""
        cache = Cache(tmp_path / "filter.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search(
                "tazminat", cache=cache, filters={"source": "yargitay"}
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert r["source"] == "yargitay"
        finally:
            cache.close()

    def test_search_limit(self, tmp_path: Path) -> None:
        """limit=2 returns at most 2 results."""
        cache = Cache(tmp_path / "limit.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("tazminat", cache=cache, limit=2)
            assert result["ok"] is True
            assert len(result["results"]) <= 2
        finally:
            cache.close()

    def test_search_result_structure(self, tmp_path: Path) -> None:
        """Each result has expected keys."""
        cache = Cache(tmp_path / "structure.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert len(result["results"]) > 0
            for r in result["results"]:
                assert "document_id" in r
                assert "source" in r
                assert "title" in r
                assert "score" in r
                assert "snippet" in r
                assert "content_status" in r
        finally:
            cache.close()

    def test_search_method_field(self, tmp_path: Path) -> None:
        """method='tfidf_cosine' in return dict."""
        cache = Cache(tmp_path / "method.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("test", cache=cache)
            assert result["ok"] is True
            assert result["method"] == "tfidf_cosine"
        finally:
            cache.close()

    def test_search_version_field(self, tmp_path: Path) -> None:
        """version field is present and correct."""
        cache = Cache(tmp_path / "version.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("test", cache=cache)
            assert result["version"] == SEMANTIC_VERSION
        finally:
            cache.close()

    def test_search_turkish_characters(self, tmp_path: Path) -> None:
        """Turkish characters (ı, ş, ğ, ü, ö, ç) work in search queries."""
        cache = Cache(tmp_path / "turkish.sqlite3")
        try:
            _build_and_populate(cache)
            # Search for a word with Turkish characters present in doc yg-001
            result = semantic_search("iş kazası", cache=cache)
            assert result["ok"] is True
            assert result["total_matches"] >= 1
            doc_ids = [r["document_id"] for r in result["results"]]
            assert "yg-002" in doc_ids
        finally:
            cache.close()


# ===================================================================
# TestHybridSearch
# ===================================================================


class TestHybridSearch:
    """Tests for hybrid_search()."""

    def test_hybrid_basic(self, tmp_path: Path) -> None:
        """Store docs, build index, hybrid search for 'sözleşme'."""
        cache = Cache(tmp_path / "hybrid_basic.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert result["total_matches"] >= 1
            doc_ids = [r["document_id"] for r in result["results"]]
            assert "yg-001" in doc_ids
        finally:
            cache.close()

    def test_hybrid_scores_present(self, tmp_path: Path) -> None:
        """Results have bm25_score, cosine_score, hybrid_score."""
        cache = Cache(tmp_path / "hybrid_scores.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("tazminat", cache=cache)
            assert result["ok"] is True
            assert len(result["results"]) > 0
            for r in result["results"]:
                assert "bm25_score" in r
                assert "cosine_score" in r
                assert "hybrid_score" in r
        finally:
            cache.close()

    def test_hybrid_weight(self, tmp_path: Path) -> None:
        """hybrid_weight parameter is reflected in output."""
        cache = Cache(tmp_path / "hybrid_weight.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("test", cache=cache, hybrid_weight=0.8)
            assert result["ok"] is True
            assert result["hybrid_weight"] == 0.8
        finally:
            cache.close()

    def test_hybrid_empty_query(self, tmp_path: Path) -> None:
        """Empty query returns empty results."""
        cache = Cache(tmp_path / "hybrid_empty.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("", cache=cache)
            assert result["ok"] is True
            assert result["results"] == []
        finally:
            cache.close()

    def test_hybrid_method_field(self, tmp_path: Path) -> None:
        """method='hybrid' in return dict."""
        cache = Cache(tmp_path / "hybrid_method.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("test", cache=cache)
            assert result["ok"] is True
            assert result["method"] == "hybrid"
        finally:
            cache.close()

    def test_hybrid_combined_better(self, tmp_path: Path) -> None:
        """Hybrid search should find relevant results from both BM25 and cosine."""
        cache = Cache(tmp_path / "hybrid_combined.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("tazminat", cache=cache)
            assert result["ok"] is True
            # At least the relevant doc should be found
            assert result["total_matches"] >= 1
            # Top result should have both bm25 and cosine components
            top = result["results"][0]
            assert top["bm25_score"] != 0.0 or top["cosine_score"] != 0.0
        finally:
            cache.close()

    def test_hybrid_no_docs_returns_ok(self, tmp_path: Path) -> None:
        """Hybrid search on empty DB returns ok with warning."""
        cache = Cache(tmp_path / "hybrid_nodocs.sqlite3")
        try:
            result = hybrid_search("contract", cache=cache)
            assert result["ok"] is True
            assert result["results"] == []
            assert len(result["warnings"]) > 0
        finally:
            cache.close()

    def test_hybrid_with_filters(self, tmp_path: Path) -> None:
        """Filter by source='danistay'."""
        cache = Cache(tmp_path / "hybrid_filter.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search(
                "tazminat", cache=cache, filters={"source": "danistay"}
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert r["source"] == "danistay"
        finally:
            cache.close()

    def test_hybrid_limit(self, tmp_path: Path) -> None:
        """limit=1 returns at most 1 result."""
        cache = Cache(tmp_path / "hybrid_limit.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("sözleşme", cache=cache, limit=1)
            assert result["ok"] is True
            assert len(result["results"]) <= 1
        finally:
            cache.close()

    def test_hybrid_result_structure(self, tmp_path: Path) -> None:
        """Each result has expected metadata keys."""
        cache = Cache(tmp_path / "hybrid_struct.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert len(result["results"]) > 0
            for r in result["results"]:
                assert "document_id" in r
                assert "source" in r
                assert "title" in r
                assert "snippet" in r
                assert "content_status" in r
        finally:
            cache.close()

    def test_hybrid_scores_descending(self, tmp_path: Path) -> None:
        """Results sorted by hybrid_score descending."""
        cache = Cache(tmp_path / "hybrid_sort.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("tazminat", cache=cache)
            scores = [r["hybrid_score"] for r in result["results"]]
            assert scores == sorted(scores, reverse=True)
        finally:
            cache.close()

    def test_hybrid_different_weights(self, tmp_path: Path) -> None:
        """Different hybrid_weight values produce different hybrid_scores."""
        cache = Cache(tmp_path / "hybrid_weights.sqlite3")
        try:
            _build_and_populate(cache)
            r1 = hybrid_search("tazminat", cache=cache, hybrid_weight=0.2)
            r2 = hybrid_search("tazminat", cache=cache, hybrid_weight=0.9)
            # Both should find results
            assert r1["ok"] is True
            assert r2["ok"] is True
            # hybrid_weight should be reflected
            assert r1["hybrid_weight"] == 0.2
            assert r2["hybrid_weight"] == 0.9
            # If both have results, the top hybrid_score should differ
            if r1["results"] and r2["results"]:
                s1 = r1["results"][0]["hybrid_score"]
                s2 = r2["results"][0]["hybrid_score"]
                assert s1 != s2
        finally:
            cache.close()


# ===================================================================
# TestGetIndexStatus
# ===================================================================


class TestGetIndexStatus:
    """Tests for get_index_status()."""

    def test_status_empty(self, tmp_path: Path) -> None:
        """Status on empty DB shows zero counts."""
        cache = Cache(tmp_path / "status_empty.sqlite3")
        try:
            result = get_index_status(cache=cache)
            assert result["ok"] is True
            assert result["fts5_exists"] is False
            assert result["vectors_table_exists"] is False
            assert result["total_cached_documents"] == 0
            assert result["vectors_count"] == 0
        finally:
            cache.close()

    def test_status_with_docs(self, tmp_path: Path) -> None:
        """Status shows correct counts after building."""
        cache = Cache(tmp_path / "status_docs.sqlite3")
        try:
            _build_and_populate(cache)
            result = get_index_status(cache=cache)
            assert result["ok"] is True
            assert result["fts5_exists"] is True
            assert result["vectors_table_exists"] is True
            assert result["total_cached_documents"] == 3
            assert result["vectors_count"] == 3
        finally:
            cache.close()

    def test_status_keys(self, tmp_path: Path) -> None:
        """Verifies expected keys in return dict."""
        cache = Cache(tmp_path / "status_keys.sqlite3")
        try:
            result = get_index_status(cache=cache)
            expected_keys = {
                "ok",
                "fts5_exists",
                "fts5_document_count",
                "vectors_table_exists",
                "vectors_count",
                "total_cached_documents",
                "unindexed_documents",
                "warnings",
                "recommended_next_steps",
                "version",
            }
            assert expected_keys.issubset(set(result.keys()))
        finally:
            cache.close()

    def test_status_no_fts5_table(self, tmp_path: Path) -> None:
        """If FTS5 doesn't exist, status reports it via warnings."""
        cache = Cache(tmp_path / "status_nofts5.sqlite3")
        try:
            result = get_index_status(cache=cache)
            assert result["ok"] is True
            assert result["fts5_exists"] is False
            fts5_warnings = [
                w for w in result["warnings"] if "fts5" in w.lower()
            ]
            assert len(fts5_warnings) > 0
        finally:
            cache.close()

    def test_status_unindexed_documents(self, tmp_path: Path) -> None:
        """Unindexed doc count reflects gap between total and vectorized."""
        cache = Cache(tmp_path / "status_unidx.sqlite3")
        try:
            # Store 3 docs, build (all get indexed)
            _build_and_populate(cache)
            # Store one more doc without rebuilding
            cache.store_document(
                _make_doc(document_id="extra-1", full_text="Extra document not yet indexed.")
            )
            result = get_index_status(cache=cache)
            assert result["ok"] is True
            assert result["total_cached_documents"] == 4
            assert result["unindexed_documents"] == 1
        finally:
            cache.close()

    def test_status_version_field(self, tmp_path: Path) -> None:
        """Version field is present and correct."""
        cache = Cache(tmp_path / "status_ver.sqlite3")
        try:
            result = get_index_status(cache=cache)
            assert result["version"] == SEMANTIC_VERSION
        finally:
            cache.close()


# ===================================================================
# TestRebuildIndex
# ===================================================================


class TestRebuildIndex:
    """Tests for rebuild_index()."""

    def test_rebuild_basic(self, tmp_path: Path) -> None:
        """Build, store more docs, rebuild – counts should update."""
        cache = Cache(tmp_path / "rebuild_basic.sqlite3")
        try:
            _build_and_populate(cache)
            # Add one more doc
            cache.store_document(
                _make_doc(
                    document_id="extra-2",
                    source="danistay",
                    title="Extra Decision",
                    full_text="This is an extra document about labor law.",
                )
            )
            result = rebuild_index(cache=cache)
            assert result["ok"] is True
            assert result["documents_total"] == 4
            assert result["vectors_count"] == 4
        finally:
            cache.close()

    def test_rebuild_returns_status(self, tmp_path: Path) -> None:
        """Returns same structure as build_semantic_index."""
        cache = Cache(tmp_path / "rebuild_struct.sqlite3")
        try:
            _build_and_populate(cache)
            result = rebuild_index(cache=cache)
            expected_keys = {
                "ok",
                "fts5_exists",
                "fts5_row_count",
                "vectors_count",
                "documents_total",
                "warnings",
                "recommended_next_steps",
                "version",
            }
            assert expected_keys.issubset(set(result.keys()))
            assert result["ok"] is True
        finally:
            cache.close()

    def test_rebuild_drops_and_recreates(self, tmp_path: Path) -> None:
        """Rebuild drops existing triggers and recreates them."""
        cache = Cache(tmp_path / "rebuild_drop.sqlite3")
        try:
            _build_and_populate(cache)
            result = rebuild_index(cache=cache)
            # Should have the 'dropped' warning
            drop_warnings = [w for w in result["warnings"] if "dropped" in w.lower()]
            assert len(drop_warnings) > 0
            # Tables should still exist after rebuild
            tables = [
                row[0]
                for row in cache.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "documents_v2_fts" in tables
            assert "search_vectors" in tables
        finally:
            cache.close()


# ===================================================================
# TestModuleConstants
# ===================================================================


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_version(self) -> None:
        """SEMANTIC_VERSION equals '0.13.0'."""
        assert SEMANTIC_VERSION == "0.13.0"


# ===================================================================
# TestEdgeCases
# ===================================================================


class TestEdgeCases:
    """Tests for edge cases and special inputs."""

    def test_documents_with_special_chars(self, tmp_path: Path) -> None:
        """Documents with Turkish characters work correctly.

        Uses 3 docs so that a word appearing in only some docs gets IDF > 0.
        """
        cache = Cache(tmp_path / "special_chars.sqlite3")
        try:
            docs = [
                {
                    "source": "yargitay",
                    "document_id": "tr-1",
                    "title": "Türkçe Karar: ğüşöçı",
                    "court": "Yargıtay",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": (
                        "Bu belge Türkçe özel karakterler içermektedir: "
                        "ğüşöçı İĞÜŞÖÇI harfleri test edilmektedir."
                    ),
                    "markdown": "Türkçe test markdown.",
                },
                {
                    "source": "danistay",
                    "document_id": "tr-2",
                    "title": "Başka Bir Türkçe Karar",
                    "court": "Danistay",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": (
                        "Türkçe karakter kullanımı önemlidir. "
                        "Ülkemizde ğüşöçı harfleri günlük hayatta sıkça kullanılır."
                    ),
                    "markdown": "Türkçe karakter belgesi.",
                },
                {
                    "source": "yargitay",
                    "document_id": "tr-3",
                    "title": "İngilizce Karar",
                    "court": "Yargıtay",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": (
                        "This document is about international trade law "
                        "and cross-border commercial disputes."
                    ),
                    "markdown": "English language decision.",
                },
            ]
            _build_and_populate(cache, docs=docs)
            # "ğüşöçı" appears only in tr-1 and tr-2, not tr-3,
            # so with n=3, df=2, IDF = log(3/2) > 0
            result = semantic_search("ğüşöçı", cache=cache)
            assert result["ok"] is True
            assert result["total_matches"] >= 1
            doc_ids = [r["document_id"] for r in result["results"]]
            assert "tr-1" in doc_ids
            # Hybrid should also work
            result2 = hybrid_search("ğüşöçı", cache=cache)
            assert result2["ok"] is True
            assert result2["total_matches"] >= 1
        finally:
            cache.close()

    def test_many_documents(self, tmp_path: Path) -> None:
        """Store 20 docs, verify search still works."""
        cache = Cache(tmp_path / "many_docs.sqlite3")
        try:
            docs = []
            for i in range(20):
                docs.append({
                    "source": "yargitay" if i % 2 == 0 else "danistay",
                    "document_id": f"md-{i:03d}",
                    "title": f"Document {i} about {'contract' if i % 3 == 0 else 'labor' if i % 3 == 1 else 'tort'} law",
                    "court": "Yargitay" if i % 2 == 0 else "Danistay",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": (
                        f"This is document number {i}. "
                        f"It discusses {'contract' if i % 3 == 0 else 'labor' if i % 3 == 1 else 'tort'} "
                        f"law principles in Turkish legal system."
                    ),
                    "markdown": f"# Document {i}\n\nLegal content.",
                })
            _build_and_populate(cache, docs=docs)

            # Verify all indexed
            status = get_index_status(cache=cache)
            assert status["total_cached_documents"] == 20
            assert status["vectors_count"] == 20

            # Search should still work
            result = semantic_search("contract", cache=cache)
            assert result["ok"] is True
            assert result["total_matches"] > 0

            result2 = hybrid_search("contract", cache=cache)
            assert result2["ok"] is True
            assert result2["total_matches"] > 0
        finally:
            cache.close()

    def test_documents_without_text(self, tmp_path: Path) -> None:
        """Documents with empty full_text and markdown are handled gracefully."""
        cache = Cache(tmp_path / "no_text.sqlite3")
        try:
            docs = [
                {
                    "source": "test",
                    "document_id": "nt-1",
                    "title": "No Text Document",
                    "content_status": ContentStatus.METADATA_ONLY,
                    # full_text and markdown are None by default
                },
                {
                    "source": "test",
                    "document_id": "nt-2",
                    "title": "Another No Text",
                    "full_text": "",
                    "markdown": "",
                    "content_status": ContentStatus.METADATA_ONLY,
                },
            ]
            _build_and_populate(cache, docs=docs)
            status = get_index_status(cache=cache)
            assert status["total_cached_documents"] == 2
            assert status["vectors_count"] == 0

            # Searches should return empty results
            result = semantic_search("anything", cache=cache)
            assert result["ok"] is True
            assert result["results"] == []

            result2 = hybrid_search("anything", cache=cache)
            assert result2["ok"] is True
            assert result2["results"] == []
        finally:
            cache.close()

    def test_mixed_content_statuses(self, tmp_path: Path) -> None:
        """Mix of FULL_TEXT and METADATA_ONLY docs handled correctly."""
        cache = Cache(tmp_path / "mixed_status.sqlite3")
        try:
            docs = [
                {
                    "source": "yargitay",
                    "document_id": "ms-1",
                    "title": "Full Text Doc",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "This document has full text about contracts and agreements.",
                    "court": "Yargitay",
                },
                {
                    "source": "danistay",
                    "document_id": "ms-2",
                    "title": "Metadata Only Doc",
                    "content_status": ContentStatus.METADATA_ONLY,
                },
                {
                    "source": "danistay",
                    "document_id": "ms-3",
                    "title": "Another Full Text Doc",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "This document discusses labor law and employee rights in detail.",
                    "court": "Danistay",
                },
            ]
            _build_and_populate(cache, docs=docs)
            status = get_index_status(cache=cache)
            assert status["total_cached_documents"] == 3
            assert status["vectors_count"] == 2  # Only the full_text docs

            # Search should find only the full_text docs
            result = semantic_search("contracts", cache=cache)
            assert result["ok"] is True
            assert result["total_matches"] >= 1
            doc_ids = [r["document_id"] for r in result["results"]]
            assert "ms-1" in doc_ids
            assert "ms-2" not in doc_ids
        finally:
            cache.close()

    def test_search_after_rebuild_with_new_docs(self, tmp_path: Path) -> None:
        """After rebuild, new documents should be searchable."""
        cache = Cache(tmp_path / "rebuild_new.sqlite3")
        try:
            _build_and_populate(cache)
            # Add a new doc and rebuild
            cache.store_document(
                _make_doc(
                    document_id="new-doc-1",
                    source="danistay",
                    title="New Decision About Tax Law",
                    full_text="Tax law enforcement requires strict compliance with regulations.",
                )
            )
            rebuild_index(cache=cache)
            # Search for the new doc's content
            result = semantic_search("tax law", cache=cache)
            assert result["ok"] is True
            doc_ids = [r["document_id"] for r in result["results"]]
            assert "new-doc-1" in doc_ids
        finally:
            cache.close()

    def test_get_index_status_after_partial_index(self, tmp_path: Path) -> None:
        """Status correctly reports unindexed documents."""
        cache = Cache(tmp_path / "partial_index.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            # Add one more doc without rebuilding
            cache.store_document(
                _make_doc(
                    document_id="late-1",
                    source="danistay",
                    title="Late Document",
                    full_text="This document was added after index was built.",
                )
            )
            status = get_index_status(cache=cache)
            assert status["total_cached_documents"] == 4
            assert status["vectors_count"] == 3
            assert status["unindexed_documents"] == 1
        finally:
            cache.close()

    def test_hybrid_search_single_doc(self, tmp_path: Path) -> None:
        """Hybrid search with a single document."""
        cache = Cache(tmp_path / "single_doc.sqlite3")
        try:
            docs = [
                {
                    "source": "test",
                    "document_id": "only-1",
                    "title": "Only Document",
                    "court": "Test Court",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "This is the only document about intellectual property law.",
                },
            ]
            _build_and_populate(cache, docs=docs)
            result = hybrid_search("intellectual property", cache=cache)
            assert result["ok"] is True
            assert len(result["results"]) == 1
            assert result["results"][0]["document_id"] == "only-1"
        finally:
            cache.close()

    def test_semantic_search_with_court_filter(self, tmp_path: Path) -> None:
        """Filter by court name in semantic search."""
        cache = Cache(tmp_path / "court_filter.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search(
                "tazminat", cache=cache, filters={"court": "Yargitay"}
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert "Yargitay" in (r.get("court") or "")
        finally:
            cache.close()

    def test_hybrid_search_with_content_status_filter(self, tmp_path: Path) -> None:
        """Filter by content_status in hybrid search."""
        cache = Cache(tmp_path / "cs_filter.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            result = hybrid_search(
                "tazminat",
                cache=cache,
                filters={"content_status": "full_text"},
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert r["content_status"] == "full_text"
        finally:
            cache.close()

    def test_search_no_common_tokens(self, tmp_path: Path) -> None:
        """Query with tokens not in any document returns empty results."""
        cache = Cache(tmp_path / "no_common.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("xyzzyplugh", cache=cache)
            assert result["ok"] is True
            assert result["results"] == []
        finally:
            cache.close()

    def test_hybrid_no_common_tokens(self, tmp_path: Path) -> None:
        """Hybrid search with tokens not in any document returns empty results."""
        cache = Cache(tmp_path / "hybrid_no_common.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("xyzzyplugh", cache=cache)
            assert result["ok"] is True
            assert result["results"] == []
        finally:
            cache.close()

    def test_rebuild_index_preserves_documents(self, tmp_path: Path) -> None:
        """Rebuild does not delete the actual document data."""
        cache = Cache(tmp_path / "rebuild_preserve.sqlite3")
        try:
            _build_and_populate(cache)
            rebuild_index(cache=cache)
            # All documents should still be in documents_v2
            count = cache.db.execute(
                "SELECT COUNT(*) FROM documents_v2"
            ).fetchone()[0]
            assert count == 3
        finally:
            cache.close()

    def test_build_semantic_index_no_cache_creates_own(self) -> None:
        """Calling without a cache parameter should still work (creates own)."""
        result = build_semantic_index(cache=None)
        assert result["ok"] is True
        # own_cache is True, connection closed in finally block

    def test_semantic_search_no_cache_creates_own(self) -> None:
        """Calling without a cache parameter should still work (uses persistent cache)."""
        result = semantic_search("test", cache=None)
        assert isinstance(result, dict)  # doesn't crash

    def test_hybrid_search_no_cache_creates_own(self) -> None:
        """Calling without a cache parameter should still work (uses persistent cache)."""
        result = hybrid_search("test", cache=None)
        assert isinstance(result, dict)  # doesn't crash

    def test_get_index_status_no_cache_creates_own(self) -> None:
        """Calling without a cache parameter should still work."""
        result = get_index_status(cache=None)
        assert result["ok"] is True

    def test_rebuild_index_no_cache_creates_own(self) -> None:
        """Calling without a cache parameter should still work."""
        result = rebuild_index(cache=None)
        assert result["ok"] is True

    def test_multiple_build_calls_are_idempotent(self, tmp_path: Path) -> None:
        """Calling build_semantic_index multiple times is safe."""
        cache = Cache(tmp_path / "idempotent.sqlite3")
        try:
            _populate_docs(cache)
            r1 = build_semantic_index(cache=cache)
            r2 = build_semantic_index(cache=cache)
            assert r1["ok"] is True
            assert r2["ok"] is True
            assert r2["documents_total"] == r1["documents_total"]
        finally:
            cache.close()

    def test_search_with_unicode_full_text(self, tmp_path: Path) -> None:
        """Documents with Arabic, Chinese, or other Unicode in full_text."""
        cache = Cache(tmp_path / "unicode.sqlite3")
        try:
            docs = [
                {
                    "source": "test",
                    "document_id": "uni-1",
                    "title": "Unicode Document",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "Document about日本法 and عربي law principles.",
                },
            ]
            _build_and_populate(cache, docs=docs)
            result = semantic_search("日本法", cache=cache)
            assert result["ok"] is True
        finally:
            cache.close()


# ===================================================================
# TestTurkishQueryExpansion
# ===================================================================


class TestTurkishQueryExpansion:
    """Tests for _expand_query() and _strip_turkish_suffix()."""

    def test_expand_query_basic(self) -> None:
        """'sözleşmelerin' should expand to include 'sözleşme' variant."""
        expanded = _expand_query("sözleşmelerin")
        assert "sözleşmelerin" in expanded
        # Should include at least one stemmed form
        assert len(expanded) > 1

    def test_expand_query_preserves_original(self) -> None:
        """Original tokens are always present in expanded result."""
        expanded = _expand_query("tazminat")
        assert "tazminat" in expanded

    def test_expand_query_empty(self) -> None:
        """Empty query returns empty list."""
        expanded = _expand_query("")
        assert expanded == []

    def test_expand_query_english(self) -> None:
        """English words expand to just themselves (no Turkish suffixes)."""
        expanded = _expand_query("contract")
        assert "contract" in expanded
        # English word shouldn't produce Turkish stems
        assert len(expanded) == 1

    def test_expand_query_multiple_words(self) -> None:
        """Multi-word query expands each word."""
        expanded = _expand_query("sözleşme hükümleri")
        assert "sözleşme" in expanded
        assert "hükümleri" in expanded
        assert len(expanded) > 2

    def test_strip_turkish_suffix_plural(self) -> None:
        """Plural suffix '-ler'/'-lar' is stripped."""
        stems = _strip_turkish_suffix("kararlar")
        assert "karar" in stems

    def test_strip_turkish_suffix_genitive(self) -> None:
        """Genitive suffix '-nın'/'-nin' is stripped."""
        stems = _strip_turkish_suffix("sözleşmenin")
        assert "sözleşme" in stems

    def test_strip_turkish_suffix_dative(self) -> None:
        """Dative suffix '-a'/'-e' is stripped (heuristic, may leave buffer consonant)."""
        stems = _strip_turkish_suffix("mahkemeye")
        # 'mahkemeye' -> strip 'e' -> 'mahkemey' (heuristic: buffer consonant remains)
        assert len(stems) > 0
        # At minimum, some suffix was stripped
        assert stems[0] != "mahkemeye" or len(stems) > 1

    def test_strip_turkish_suffix_ablative(self) -> None:
        """Ablative suffix '-dan'/'-den' is stripped."""
        stems = _strip_turkish_suffix("karardan")
        assert "karar" in stems

    def test_strip_turkish_suffix_accusative(self) -> None:
        """Accusative suffix '-ı'/'-i' is stripped."""
        stems = _strip_turkish_suffix("kararı")
        assert "karar" in stems

    def test_strip_turkish_suffix_verb_mak(self) -> None:
        """Verb infinitive '-mak'/'-mek' is stripped."""
        stems = _strip_turkish_suffix("etmek")
        # 'etmek' -> 'et' after stripping -mek
        assert "et" in stems

    def test_strip_turkish_suffix_short_word(self) -> None:
        """Words shorter than 3 chars are not stripped."""
        stems = _strip_turkish_suffix("ve")
        assert stems == ["ve"]

    def test_expand_query_deduplication(self) -> None:
        """No duplicate terms in expanded output."""
        expanded = _expand_query("kararlardan")
        assert len(expanded) == len(set(expanded))

    def test_expand_query_in_search(self, tmp_path: Path) -> None:
        """Query expansion helps FTS5 find documents with suffixed forms (hybrid search)."""
        cache = Cache(tmp_path / "expand_search.sqlite3")
        try:
            docs = [
                {
                    "source": "yargitay",
                    "document_id": "exp-1",
                    "title": "Sözleşme Kararı",
                    "court": "Yargitay",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "Bu kararda sözleşme hükümleri değerlendirilmiştir.",
                },
                {
                    "source": "yargitay",
                    "document_id": "exp-2",
                    "title": "Başka Karar",
                    "court": "Yargitay",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "İş kazası tazminat davası hakkında karar.",
                },
            ]
            _build_and_populate(cache, docs=docs)
            # hybrid_search uses FTS5 with expanded query — suffixed form finds base
            result = hybrid_search("sözleşmelerin", cache=cache)
            assert result["ok"] is True
            assert result["total_matches"] >= 1
            doc_ids = [r["document_id"] for r in result["results"]]
            assert "exp-1" in doc_ids
        finally:
            cache.close()


# ===================================================================
# TestSnippetHighlighting
# ===================================================================


class TestSnippetHighlighting:
    """Tests for _generate_snippet() with highlighting."""

    def test_highlight_returns_tuple(self) -> None:
        """_generate_snippet returns (snippet, was_highlighted) tuple."""
        text = "Taraflar arasındaki sözleşme hükümleri ihlal edilmiştir."
        snippet, hl = _generate_snippet(text, "sözleşme")
        assert isinstance(snippet, str)
        assert isinstance(hl, bool)

    def test_highlight_markers_present(self) -> None:
        """Matching terms get **...** markers."""
        text = "Taraflar arasındaki sözleşme hükümleri ihlal edilmiştir."
        snippet, hl = _generate_snippet(text, "sözleşme")
        assert "**sözleşme**" in snippet or "**Sözleşme**" in snippet

    def test_highlight_no_match(self) -> None:
        """Non-matching query returns no highlights."""
        text = "Taraflar arasındaki sözleşme hükümleri ihlal edilmiştir."
        snippet, hl = _generate_snippet(text, "tazminat")
        assert "**" not in snippet
        assert hl is False

    def test_highlight_empty_text(self) -> None:
        """Empty text returns empty snippet."""
        snippet, hl = _generate_snippet("", "query")
        assert snippet == ""
        assert hl is False

    def test_highlight_empty_query(self) -> None:
        """Empty query returns truncated text, no highlight."""
        text = "A" * 300
        snippet, hl = _generate_snippet(text, "")
        assert "**" not in snippet
        assert hl is False

    def test_highlight_disabled(self) -> None:
        """highlight=False disables highlighting."""
        text = "Taraflar arasındaki sözleşme hükümleri ihlal edilmiştir."
        snippet, hl = _generate_snippet(text, "sözleşme", highlight=False)
        assert "**" not in snippet
        assert hl is False

    def test_highlight_in_search_result(self, tmp_path: Path) -> None:
        """Search results contain highlighted snippets."""
        cache = Cache(tmp_path / "hl_search.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert len(result["results"]) > 0
            # At least one result should have highlighting
            snippets = [r["snippet"] for r in result["results"]]
            assert any("**" in s for s in snippets)
        finally:
            cache.close()

    def test_highlight_case_insensitive(self) -> None:
        """Highlighting works regardless of case."""
        text = "Sözleşme hükümleri SözleşmeMETNİNDE yer almaktadır."
        snippet, hl = _generate_snippet(text, "sözleşme")
        assert hl is True
        assert "**" in snippet


# ===================================================================
# TestHybridWeightValidation
# ===================================================================


class TestHybridWeightValidation:
    """Tests for hybrid_weight boundary validation."""

    def test_weight_0_0_valid(self, tmp_path: Path) -> None:
        """hybrid_weight=0.0 (pure semantic) is accepted."""
        cache = Cache(tmp_path / "w0.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("test", cache=cache, hybrid_weight=0.0)
            assert result["ok"] is True
            assert result["hybrid_weight"] == 0.0
        finally:
            cache.close()

    def test_weight_1_0_valid(self, tmp_path: Path) -> None:
        """hybrid_weight=1.0 (pure BM25) is accepted."""
        cache = Cache(tmp_path / "w1.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("test", cache=cache, hybrid_weight=1.0)
            assert result["ok"] is True
            assert result["hybrid_weight"] == 1.0
        finally:
            cache.close()

    def test_weight_negative_invalid(self) -> None:
        """hybrid_weight=-0.1 returns error."""
        result = hybrid_search("test", hybrid_weight=-0.1)
        assert result["ok"] is False
        assert "INVALID_HYBRID_WEIGHT" in result.get("errorCode", "")

    def test_weight_over_1_invalid(self) -> None:
        """hybrid_weight=1.1 returns error."""
        result = hybrid_search("test", hybrid_weight=1.1)
        assert result["ok"] is False
        assert "INVALID_HYBRID_WEIGHT" in result.get("errorCode", "")

    def test_weight_boundary_0(self) -> None:
        """Exactly 0.0 is valid."""
        result = hybrid_search("test", hybrid_weight=0.0)
        assert result["ok"] is True

    def test_weight_boundary_1(self) -> None:
        """Exactly 1.0 is valid."""
        result = hybrid_search("test", hybrid_weight=1.0)
        assert result["ok"] is True


# ===================================================================
# TestNewResultFields
# ===================================================================


class TestNewResultFields:
    """Tests for expanded_query_terms and snippet_highlighted fields."""

    def test_semantic_search_has_expanded_terms(self, tmp_path: Path) -> None:
        """semantic_search returns expanded_query_terms."""
        cache = Cache(tmp_path / "exp_terms.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert "expanded_query_terms" in result
            assert isinstance(result["expanded_query_terms"], list)
            assert len(result["expanded_query_terms"]) >= 1
        finally:
            cache.close()

    def test_semantic_search_has_snippet_highlighted(self, tmp_path: Path) -> None:
        """semantic_search returns snippet_highlighted."""
        cache = Cache(tmp_path / "exp_hl.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert "snippet_highlighted" in result
            assert isinstance(result["snippet_highlighted"], bool)
        finally:
            cache.close()

    def test_hybrid_search_has_expanded_terms(self, tmp_path: Path) -> None:
        """hybrid_search returns expanded_query_terms."""
        cache = Cache(tmp_path / "hyb_exp.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert "expanded_query_terms" in result
            assert isinstance(result["expanded_query_terms"], list)
        finally:
            cache.close()

    def test_hybrid_search_has_snippet_highlighted(self, tmp_path: Path) -> None:
        """hybrid_search returns snippet_highlighted."""
        cache = Cache(tmp_path / "hyb_hl.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert "snippet_highlighted" in result
            assert isinstance(result["snippet_highlighted"], bool)
        finally:
            cache.close()

    def test_empty_search_returns_expanded_terms(self) -> None:
        """Empty search still returns expanded_query_terms."""
        result = hybrid_search("")
        assert result["ok"] is True
        assert result["expanded_query_terms"] == []

    def test_invalid_weight_returns_expanded_terms(self) -> None:
        """Invalid hybrid_weight error still includes new fields."""
        result = hybrid_search("test", hybrid_weight=2.0)
        assert result["ok"] is False
        assert "expanded_query_terms" in result
        assert "snippet_highlighted" in result


# ===================================================================
# TestPerSourceFilter
# ===================================================================


class TestPerSourceFilter:
    """Tests for per-source filter support in hybrid search."""

    def test_hybrid_source_filter(self, tmp_path: Path) -> None:
        """Filter by source='yargitay' in hybrid search."""
        cache = Cache(tmp_path / "per_src.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search(
                "tazminat", cache=cache, filters={"source": "yargitay"}
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert r["source"] == "yargitay"
        finally:
            cache.close()

    def test_hybrid_court_filter(self, tmp_path: Path) -> None:
        """Filter by court='Danistay' in hybrid search."""
        cache = Cache(tmp_path / "per_court.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search(
                "tazminat", cache=cache, filters={"court": "Danistay"}
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert "Danistay" in (r.get("court") or "")
        finally:
            cache.close()

    def test_hybrid_chamber_filter(self, tmp_path: Path) -> None:
        """Filter by chamber in hybrid search."""
        cache = Cache(tmp_path / "per_chamber.sqlite3")
        try:
            docs = [
                {
                    "source": "yargitay",
                    "document_id": "ch-1",
                    "title": "Karar 1",
                    "court": "Yargitay",
                    "chamber": "1. Hukuk Dairesi",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "Tazminat davası 1. Hukuk Dairesi kararı.",
                },
                {
                    "source": "yargitay",
                    "document_id": "ch-2",
                    "title": "Karar 2",
                    "court": "Yargitay",
                    "chamber": "2. Hukuk Dairesi",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "Tazminat davası 2. Hukuk Dairesi kararı.",
                },
            ]
            _build_and_populate(cache, docs=docs)
            result = hybrid_search(
                "tazminat",
                cache=cache,
                filters={"chamber": "1. Hukuk Dairesi"},
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert "1. Hukuk Dairesi" in (r.get("chamber") or "")
        finally:
            cache.close()

    def test_hybrid_combined_filters(self, tmp_path: Path) -> None:
        """Multiple filters applied together."""
        cache = Cache(tmp_path / "per_combined.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search(
                "tazminat",
                cache=cache,
                filters={"source": "yargitay", "court": "Yargitay"},
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert r["source"] == "yargitay"
                assert "Yargitay" in (r.get("court") or "")
        finally:
            cache.close()

    def test_semantic_source_filter(self, tmp_path: Path) -> None:
        """Filter by source='danistay' in semantic search."""
        cache = Cache(tmp_path / "per_sem_src.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search(
                "tazminat", cache=cache, filters={"source": "danistay"}
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert r["source"] == "danistay"
        finally:
            cache.close()

    def test_semantic_court_filter(self, tmp_path: Path) -> None:
        """Filter by court in semantic search."""
        cache = Cache(tmp_path / "per_sem_court.sqlite3")
        try:
            _build_and_populate(cache)
            result = semantic_search(
                "tazminat", cache=cache, filters={"court": "Danistay"}
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert "Danistay" in (r.get("court") or "")
        finally:
            cache.close()

    def test_no_results_with_strict_filter(self, tmp_path: Path) -> None:
        """Filter that matches no docs returns empty results."""
        cache = Cache(tmp_path / "per_strict.sqlite3")
        try:
            _build_and_populate(cache)
            result = hybrid_search(
                "tazminat",
                cache=cache,
                filters={"source": "nonexistent_source"},
            )
            assert result["ok"] is True
            assert result["results"] == []
        finally:
            cache.close()

    def test_filter_quote_usable(self, tmp_path: Path) -> None:
        """Filter by quote_usable flag."""
        cache = Cache(tmp_path / "per_quote.sqlite3")
        try:
            docs = [
                {
                    "source": "yargitay",
                    "document_id": "qu-1",
                    "title": "Quote Usable Doc",
                    "court": "Yargitay",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "Tazminat kararı alıntılanabilir.",
                    "quote_usable": True,
                },
                {
                    "source": "yargitay",
                    "document_id": "qu-2",
                    "title": "Not Quote Usable",
                    "court": "Yargitay",
                    "content_status": ContentStatus.FULL_TEXT,
                    "full_text": "Tazminat kararı alıntılanamaz.",
                    "quote_usable": False,
                },
            ]
            _build_and_populate(cache, docs=docs)
            result = hybrid_search(
                "tazminat", cache=cache, filters={"quote_usable": True}
            )
            assert result["ok"] is True
            for r in result["results"]:
                assert r["quote_usable"] is True
        finally:
            cache.close()


# ===================================================================
# TestUpdateIndexes (M-26)
# ===================================================================


class TestUpdateIndexes:
    """Tests for update_indexes() incremental indexing."""

    def test_update_indexes_empty_db(self, tmp_path: Path) -> None:
        """update_indexes on empty DB returns ok with zero updates."""
        cache = Cache(tmp_path / "upd_empty.sqlite3")
        try:
            result = update_indexes(cache=cache)
            assert result["ok"] is True
            assert result["tfidf_updated"] == 0
            assert result["dense_updated"] == 0
        finally:
            cache.close()

    def test_update_indexes_processes_new_documents(self, tmp_path: Path) -> None:
        """update_indexes indexes documents not yet in search_vectors."""
        cache = Cache(tmp_path / "upd_new.sqlite3")
        try:
            _populate_docs(cache)
            result = update_indexes(cache=cache)
            assert result["ok"] is True
            assert result["tfidf_updated"] == 3
        finally:
            cache.close()

    def test_update_indexes_skips_unchanged(self, tmp_path: Path) -> None:
        """Second call skips documents already indexed (same content_hash)."""
        cache = Cache(tmp_path / "upd_skip.sqlite3")
        try:
            _populate_docs(cache)
            r1 = update_indexes(cache=cache)
            assert r1["tfidf_updated"] == 3
            # Second call — same docs, should skip
            r2 = update_indexes(cache=cache)
            assert r2["ok"] is True
            # All 3 already indexed, should be 0 new
            assert r2["tfidf_updated"] == 0
        finally:
            cache.close()

    def test_update_indexes_new_doc_after_initial(self, tmp_path: Path) -> None:
        """After initial index, a newly stored doc gets indexed incrementally."""
        cache = Cache(tmp_path / "upd_after.sqlite3")
        try:
            _populate_docs(cache)
            r1 = update_indexes(cache=cache)
            assert r1["tfidf_updated"] == 3
            # Add new doc
            cache.store_document(
                _make_doc(
                    document_id="upd-new-1",
                    source="danistay",
                    title="New Incremental Doc",
                    full_text="This is a new document about tax compliance and regulations.",
                )
            )
            r2 = update_indexes(cache=cache)
            assert r2["ok"] is True
            assert r2["tfidf_updated"] == 1
        finally:
            cache.close()

    def test_update_indexes_with_provider(self, tmp_path: Path) -> None:
        """update_indexes with provider updates dense embeddings too."""
        cache = Cache(tmp_path / "upd_provider.sqlite3")
        try:
            _populate_docs(cache)
            result = update_indexes(cache=cache, provider="local-hash-v1")
            assert result["ok"] is True
            assert result["tfidf_updated"] == 3
            assert result["dense_updated"] == 3
        finally:
            cache.close()

    def test_update_indexes_returns_expected_keys(self, tmp_path: Path) -> None:
        """Result dict has all expected keys."""
        cache = Cache(tmp_path / "upd_keys.sqlite3")
        try:
            _populate_docs(cache)
            result = update_indexes(cache=cache)
            expected_keys = {"ok", "tfidf_updated", "dense_updated", "skipped", "warnings"}
            assert expected_keys.issubset(set(result.keys()))
        finally:
            cache.close()

    def test_update_indexes_no_cache_creates_own(self) -> None:
        """Calling without a cache parameter should still work."""
        result = update_indexes(cache=None)
        assert result["ok"] is True

    def test_update_indexes_textless_docs_skipped(self, tmp_path: Path) -> None:
        """Documents without text content are not indexed."""
        cache = Cache(tmp_path / "upd_textless.sqlite3")
        try:
            docs = [
                {
                    "source": "test",
                    "document_id": "upd-nt-1",
                    "title": "No Text Doc",
                    "content_status": ContentStatus.METADATA_ONLY,
                },
            ]
            _populate_docs(cache, docs=docs)
            result = update_indexes(cache=cache)
            assert result["ok"] is True
            assert result["tfidf_updated"] == 0
        finally:
            cache.close()

    def test_update_indexes_searchable_after_update(self, tmp_path: Path) -> None:
        """Documents indexed via update_indexes are searchable."""
        cache = Cache(tmp_path / "upd_search.sqlite3")
        try:
            _populate_docs(cache)
            update_indexes(cache=cache)
            result = hybrid_search("sözleşme", cache=cache)
            assert result["ok"] is True
            assert result["total_matches"] >= 1
            doc_ids = [r["document_id"] for r in result["results"]]
            assert "yg-001" in doc_ids
        finally:
            cache.close()

    def test_update_indexes_orphan_cleanup_called(self, tmp_path: Path) -> None:
        """update_indexes calls cleanup_orphans after update."""
        cache = Cache(tmp_path / "upd_orphan.sqlite3")
        try:
            _populate_docs(cache)
            result = update_indexes(cache=cache)
            assert result["ok"] is True
            # Verify no orphans exist after update
            sv_count = cache.db.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]
            doc_count = cache.db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
            assert sv_count == doc_count
        finally:
            cache.close()


# ===================================================================
# TestGetIndexSyncStatus (M-26)
# ===================================================================


class TestGetIndexSyncStatus:
    """Tests for get_index_sync_status()."""

    def test_sync_status_empty_db(self, tmp_path: Path) -> None:
        """Sync status on empty DB shows zero counts."""
        cache = Cache(tmp_path / "sync_empty.sqlite3")
        try:
            result = get_index_sync_status(cache=cache)
            assert result["ok"] is True
            assert result["total_documents"] == 0
            assert result["tfidf_indexed"] == 0
            assert result["dense_indexed"] == 0
            assert result["tfidf_out_of_sync"] == 0
            assert result["dense_out_of_sync"] == 0
        finally:
            cache.close()

    def test_sync_status_all_indexed(self, tmp_path: Path) -> None:
        """After full index, all counts match."""
        cache = Cache(tmp_path / "sync_all.sqlite3")
        try:
            _build_and_populate(cache)
            result = get_index_sync_status(cache=cache)
            assert result["ok"] is True
            assert result["total_documents"] == 3
            assert result["tfidf_indexed"] == 3
            assert result["tfidf_out_of_sync"] == 0
        finally:
            cache.close()

    def test_sync_status_partial_index(self, tmp_path: Path) -> None:
        """Unindexed docs reported as out-of-sync."""
        cache = Cache(tmp_path / "sync_partial.sqlite3")
        try:
            _populate_docs(cache)
            build_semantic_index(cache=cache)
            # Add more docs without re-indexing
            cache.store_document(
                _make_doc(
                    document_id="sync-extra-1",
                    source="danistay",
                    title="Extra Doc",
                    full_text="Extra document for sync status testing.",
                )
            )
            result = get_index_sync_status(cache=cache)
            assert result["ok"] is True
            assert result["total_documents"] == 4
            assert result["tfidf_indexed"] == 3
            assert result["tfidf_out_of_sync"] == 1
        finally:
            cache.close()

    def test_sync_status_dense_indexed(self, tmp_path: Path) -> None:
        """Dense index count reflects embedding_vectors entries."""
        cache = Cache(tmp_path / "sync_dense.sqlite3")
        try:
            _populate_docs(cache)
            update_indexes(cache=cache, provider="local-hash-v1")
            result = get_index_sync_status(cache=cache)
            assert result["ok"] is True
            assert result["dense_indexed"] == 3
            assert result["dense_out_of_sync"] == 0
        finally:
            cache.close()

    def test_sync_status_returns_expected_keys(self, tmp_path: Path) -> None:
        """Result dict has all expected keys."""
        cache = Cache(tmp_path / "sync_keys.sqlite3")
        try:
            result = get_index_sync_status(cache=cache)
            expected_keys = {
                "ok",
                "total_documents",
                "tfidf_indexed",
                "dense_indexed",
                "tfidf_out_of_sync",
                "dense_out_of_sync",
            }
            assert expected_keys.issubset(set(result.keys()))
        finally:
            cache.close()

    def test_sync_status_no_cache_creates_own(self) -> None:
        """Calling without a cache parameter should still work."""
        result = get_index_sync_status(cache=None)
        assert result["ok"] is True

    def test_sync_status_textless_docs_not_counted(self, tmp_path: Path) -> None:
        """Documents without text are not counted in total_documents."""
        cache = Cache(tmp_path / "sync_textless.sqlite3")
        try:
            docs = [
                {
                    "source": "test",
                    "document_id": "sync-nt-1",
                    "title": "No Text",
                    "content_status": ContentStatus.METADATA_ONLY,
                },
            ]
            _populate_docs(cache, docs=docs)
            result = get_index_sync_status(cache=cache)
            assert result["ok"] is True
            assert result["total_documents"] == 0
            assert result["tfidf_out_of_sync"] == 0
        finally:
            cache.close()

    def test_sync_status_after_update_indexes(self, tmp_path: Path) -> None:
        """After update_indexes, out-of-sync count drops to zero."""
        cache = Cache(tmp_path / "sync_after_upd.sqlite3")
        try:
            _populate_docs(cache)
            # Before update — all out of sync
            status_before = get_index_sync_status(cache=cache)
            assert status_before["tfidf_out_of_sync"] == 3
            # After update — all in sync
            update_indexes(cache=cache)
            status_after = get_index_sync_status(cache=cache)
            assert status_after["tfidf_out_of_sync"] == 0
            assert status_after["tfidf_indexed"] == 3
        finally:
            cache.close()


# ===========================================================================
# M-69: Reciprocal Rank Fusion (RRF) Tests
# ===========================================================================


class TestRRFFusionUnit:
    """Unit tests for _rrf_fusion()."""

    def _make_result(self, doc_id: str, source: str = "test", title: str = "") -> dict:
        return {
            "document_id": doc_id,
            "source": source,
            "title": title,
            "score": 0.0,
        }

    def test_two_rankers_perfect_overlap(self):
        """When both rankers return same docs in same order, RRF score decreases by rank."""
        bm25 = [self._make_result("a"), self._make_result("b"), self._make_result("c")]
        tfidf = [self._make_result("a"), self._make_result("b"), self._make_result("c")]
        result = _rrf_fusion(bm25, tfidf, None, limit=3)
        assert len(result) == 3
        # "a" gets top score from both rankers → highest RRF
        assert result[0]["document_id"] == "a"
        assert result[1]["document_id"] == "b"
        assert result[2]["document_id"] == "c"
        assert result[0]["rrf_score"] > result[1]["rrf_score"] > result[2]["rrf_score"]

    def test_two_rankers_different_order(self):
        """Documents ranked differently — first-position doc in bm25 ranks higher."""
        bm25 = [self._make_result("a"), self._make_result("b"), self._make_result("c")]
        tfidf = [self._make_result("c"), self._make_result("b"), self._make_result("a")]
        result = _rrf_fusion(bm25, tfidf, None, limit=3)
        assert len(result) == 3
        # a (rank 0 bm25 + rank 2 tfidf) and c (rank 2 bm25 + rank 0 tfidf)
        # have identical RRF scores — stable sort keeps insertion order
        assert result[0]["document_id"] == "a"
        assert result[1]["document_id"] == "c"
        assert result[2]["document_id"] == "b"

    def test_three_rankers_with_dense(self):
        """Three rankers including dense produce correct fusion."""
        bm25 = [self._make_result("x"), self._make_result("y")]
        tfidf = [self._make_result("y"), self._make_result("x")]
        dense = [self._make_result("z"), self._make_result("y")]
        result = _rrf_fusion(bm25, tfidf, dense, limit=3)
        assert len(result) == 3
        # "y" appears in all 3 rankers → highest RRF
        assert result[0]["document_id"] == "y"
        all_ids = {r["document_id"] for r in result}
        assert all_ids == {"x", "y", "z"}

    def test_empty_rankers(self):
        """All rankers empty → empty result."""
        result = _rrf_fusion([], [], None, limit=5)
        assert result == []

    def test_single_ranker(self):
        """One ranker → returns its results with RRF scores."""
        bm25 = [self._make_result("a"), self._make_result("b")]
        result = _rrf_fusion(bm25, [], None, limit=2)
        assert len(result) == 2
        assert result[0]["document_id"] == "a"
        assert result[1]["document_id"] == "b"
        for r in result:
            assert "rrf_score" in r
            assert r["rrf_score"] > 0

    def test_empty_dense_list(self):
        """Empty dense list is treated same as None."""
        bm25 = [self._make_result("a")]
        tfidf = [self._make_result("a")]
        result_none = _rrf_fusion(bm25, tfidf, None, limit=5)
        result_empty = _rrf_fusion(bm25, tfidf, [], limit=5)
        assert result_none[0]["rrf_score"] == result_empty[0]["rrf_score"]

    def test_limit_smaller_than_merged(self):
        """RRF respects the limit parameter."""
        bm25 = [self._make_result(str(i)) for i in range(10)]
        tfidf = [self._make_result(str(i)) for i in range(10)]
        result = _rrf_fusion(bm25, tfidf, None, limit=3)
        assert len(result) == 3

    def test_duplicate_in_ranker_gets_higher_score(self):
        """Same document appearing in both rankers gets higher RRF than unique docs."""
        bm25 = [
            self._make_result("a"),
            self._make_result("unique_bm25"),
            self._make_result("b"),
        ]
        tfidf = [
            self._make_result("b"),
            self._make_result("unique_tfidf"),
            self._make_result("a"),
        ]
        result = _rrf_fusion(bm25, tfidf, None, limit=4)
        # Docs appearing in both (a, b) should rank higher than unique ones
        overlap_ids = [r["document_id"] for r in result[:2]]
        # a and b should be in top 2 (they appear in both rankers)
        assert set(overlap_ids) == {"a", "b"}

    def test_preserves_metadata(self):
        """RRF preserves title and other metadata from the first occurrence."""
        bm25 = [{"document_id": "a", "source": "test", "title": "Decision A", "court": "Yargitay"}]
        tfidf = [{"document_id": "a", "source": "test", "title": "Overridden", "court": "Danistay"}]
        result = _rrf_fusion(bm25, tfidf, None, limit=1)
        assert result[0]["title"] == "Decision A"
        assert result[0]["court"] == "Yargitay"


class TestHybridSearchRRF:
    """Integration tests for hybrid_search_rrf()."""

    def test_basic_search_returns_rrf_method(self, tmp_path: Path) -> None:
        cache = Cache(tmp_path / "rrf_basic.sqlite3")
        _populate_docs(cache)
        build_semantic_index(cache=cache, force_rebuild=True)
        try:
            result = hybrid_search_rrf("sözleşme", limit=5, cache=cache)
            assert result["ok"] is True
            assert result["method"] == "rrf"
            assert "rrf_k" in result
            assert result["rrf_k"] == 60
            assert result["dense_included"] is False
            assert len(result["results"]) > 0
            for r in result["results"]:
                assert "rrf_score" in r
                assert "document_id" in r
                assert "source" in r
        finally:
            cache.close()

    def test_search_with_dense_included(self, tmp_path: Path) -> None:
        """RRF with dense embeddings (LocalHashProvider) should work."""
        cache = Cache(tmp_path / "rrf_dense.sqlite3")
        _populate_docs(cache)
        build_semantic_index(cache=cache, force_rebuild=True)
        from emsal_mcp.semantic import build_embedding_index

        build_embedding_index(cache=cache)
        try:
            result = hybrid_search_rrf(
                "sözleşme", limit=5, cache=cache, include_dense=True
            )
            assert result["ok"] is True
            assert result["method"] == "rrf"
            assert result["dense_included"] is True
            assert result["dense_provider"] == "local-hash-v1"
        finally:
            cache.close()

    def test_empty_cache_returns_empty(self, tmp_path: Path) -> None:
        """RRF on empty cache returns ok with empty results."""
        cache = Cache(tmp_path / "rrf_empty.sqlite3")
        try:
            result = hybrid_search_rrf("test", limit=5, cache=cache)
            assert result["ok"] is True
            assert result["results"] == []
            assert result["total_matches"] == 0
        finally:
            cache.close()

    def test_deterministic(self, tmp_path: Path) -> None:
        """RRF results are deterministic for same input."""
        cache = Cache(tmp_path / "rrf_det.sqlite3")
        _populate_docs(cache)
        build_semantic_index(cache=cache, force_rebuild=True)
        try:
            r1 = hybrid_search_rrf("tazminat", limit=5, cache=cache)
            r2 = hybrid_search_rrf("tazminat", limit=5, cache=cache)
            assert r1["ok"] is True
            assert r2["ok"] is True
            assert len(r1["results"]) == len(r2["results"])
            for res1, res2 in zip(r1["results"], r2["results"]):
                assert res1["rrf_score"] == res2["rrf_score"]
                assert res1["document_id"] == res2["document_id"]
        finally:
            cache.close()

    def test_limit_respected(self, tmp_path: Path) -> None:
        """RRF respects the limit parameter."""
        cache = Cache(tmp_path / "rrf_limit.sqlite3")
        _populate_docs(cache)
        build_semantic_index(cache=cache, force_rebuild=True)
        try:
            result = hybrid_search_rrf("hukuk", limit=2, cache=cache)
            assert result["ok"] is True
            assert len(result["results"]) <= 2
        finally:
            cache.close()

    def test_no_duplicate_results(self, tmp_path: Path) -> None:
        """RRF fusion should not produce duplicate results."""
        cache = Cache(tmp_path / "rrf_dup.sqlite3")
        _populate_docs(cache)
        build_semantic_index(cache=cache, force_rebuild=True)
        try:
            result = hybrid_search_rrf("hukuk", limit=10, cache=cache)
            assert result["ok"] is True
            ids = [
                (r["document_id"], r["source"]) for r in result["results"]
            ]
            assert len(ids) == len(set(ids)), f"Duplicates found: {ids}"
        finally:
            cache.close()

    def test_rrf_fusion_vs_linear_different_results(self, tmp_path: Path) -> None:
        """RRF and linear fusion may produce different rankings."""
        cache = Cache(tmp_path / "rrf_vs_lin.sqlite3")
        _populate_docs(cache)
        build_semantic_index(cache=cache, force_rebuild=True)
        try:
            rrf = hybrid_search_rrf("sözleşme", limit=5, cache=cache)
            lin = hybrid_search("sözleşme", limit=5, cache=cache, dense_weight=0.0)
            assert rrf["ok"] is True
            assert lin["ok"] is True
            # Both should return results (ordering may differ)
            assert len(rrf["results"]) > 0
            assert len(lin["results"]) > 0
            # Method markers differ
            assert rrf["method"] == "rrf"
            assert lin["method"] == "hybrid"
        finally:
            cache.close()


# ===================================================================
# TestTfidfIdfConsistency (M-108 fix: frozen, shared IDF snapshot)
# ===================================================================


class TestTfidfIdfConsistency:
    """Vectors written across separate _compute_tfidf_vectors() calls must
    share one IDF basis, and search_vectors must never be silently wiped by
    a bounded batch. This pins the bug found live: a single
    `_compute_tfidf_vectors(db, limit=1000)` call had been deleting the
    entire search_vectors table (112,692 rows) before writing back only its
    own batch-local-IDF vectors.
    """

    def _docs_with_shared_term(self) -> list[dict]:
        # "sözleşme" appears in every doc so its DF/IDF depends on the WHOLE
        # corpus size, not on whichever subset a given batch happens to see.
        return [
            {
                "source": "yargitay",
                "document_id": f"batch-doc-{i}",
                "title": f"Sözleşme Kararı {i}",
                "content_status": ContentStatus.FULL_TEXT,
                "full_text": f"sözleşme sözleşme madde {i} tazminat",
            }
            for i in range(6)
        ]

    def test_two_batches_share_idf_basis(self, tmp_path: Path) -> None:
        """A doc written in batch 1 and a doc written in batch 2 must use
        the identical IDF for a term they both contain."""
        cache = Cache(tmp_path / "two_batches.sqlite3")
        try:
            _populate_docs(cache, docs=self._docs_with_shared_term())
            db = cache.db

            written_first = _compute_tfidf_vectors(db, limit=2)
            assert written_first == 2
            first_stats = _load_corpus_idf(db)
            assert first_stats is not None
            idf_after_batch1, n_docs_after_batch1 = first_stats

            written_second = _compute_tfidf_vectors(db, limit=0)
            assert written_second == 4  # the remaining 4 docs
            second_stats = _load_corpus_idf(db)
            assert second_stats is not None
            idf_after_batch2, n_docs_after_batch2 = second_stats

            # The IDF snapshot itself must not have been recomputed between
            # calls — same n_docs, same idf values (batch 2 reused it).
            assert n_docs_after_batch1 == n_docs_after_batch2
            assert idf_after_batch1 == idf_after_batch2

            rows = {
                doc_id: (vjson, norm)
                for doc_id, vjson, norm in db.execute(
                    "SELECT document_id, vector_json, norm FROM search_vectors"
                ).fetchall()
            }
            assert len(rows) == 6  # nothing was deleted between batches

            vec_batch1 = json.loads(rows["batch-doc-0"][0])
            vec_batch2 = json.loads(rows["batch-doc-5"][0])
            term = "sözleşme"
            assert term in vec_batch1 and term in vec_batch2

            # tf(sözleşme) is identical in both docs (2 occurrences / 5 tokens)
            # so if the two vectors' weight for this shared term differs,
            # the IDF used to write them differed too.
            assert vec_batch1[term] == pytest.approx(vec_batch2[term])

        finally:
            cache.close()

    def test_bounded_batch_never_deletes_existing_vectors(self, tmp_path: Path) -> None:
        """Calling _compute_tfidf_vectors with a small limit repeatedly must
        accumulate vectors, never wipe previously-written ones."""
        cache = Cache(tmp_path / "no_wipe.sqlite3")
        try:
            _populate_docs(cache, docs=self._docs_with_shared_term())
            db = cache.db

            total_written = 0
            for _ in range(10):  # more calls than needed; extra calls are no-ops
                total_written += _compute_tfidf_vectors(db, limit=1)
                count = db.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]
                assert count == total_written  # monotonic, never shrinks

            final_count = db.execute("SELECT COUNT(*) FROM search_vectors").fetchone()[0]
            assert final_count == 6
        finally:
            cache.close()

    def test_query_idf_matches_write_time_snapshot(self, tmp_path: Path) -> None:
        """_load_query_idf() must return the exact snapshot vectors were
        written under, not an approximation reconstructed from the table."""
        cache = Cache(tmp_path / "query_idf.sqlite3")
        try:
            _build_and_populate(cache, docs=self._docs_with_shared_term())
            db = cache.db
            snapshot = _load_corpus_idf(db)
            assert snapshot is not None
            query_idf = _load_query_idf(db)
            assert query_idf == snapshot[0]
        finally:
            cache.close()

    def test_legacy_vectors_without_stats_are_healed(self, tmp_path: Path) -> None:
        """A search_vectors table populated by the OLD batch-scoped code
        (rows present, no tfidf_corpus_stats snapshot) is exactly the
        signature of the live incident. The next call must not mix those
        untrustworthy rows with newly-written ones — it should wipe and
        rebuild cleanly under one snapshot."""
        cache = Cache(tmp_path / "legacy_heal.sqlite3")
        try:
            _populate_docs(cache, docs=self._docs_with_shared_term())
            db = cache.db

            # Simulate the legacy state directly: a stray, bogus vector row
            # with NO tfidf_corpus_stats table/row backing it.
            db.execute(
                "CREATE TABLE IF NOT EXISTS search_vectors ("
                "document_id TEXT NOT NULL, source TEXT NOT NULL, "
                "vector_json TEXT NOT NULL, norm REAL DEFAULT 0.0, "
                "indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY (document_id, source))"
            )
            db.execute(
                "INSERT INTO search_vectors(document_id, source, vector_json, norm) "
                "VALUES ('bogus-legacy-doc', 'yargitay', '{\"x\": 99.0}', 99.0)"
            )
            db.commit()
            stats_exists_before = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tfidf_corpus_stats'"
            ).fetchone()
            assert stats_exists_before is None

            written = _compute_tfidf_vectors(db, limit=0)
            assert written == 6  # all 6 real docs, freshly written

            remaining_ids = {
                r[0] for r in db.execute("SELECT document_id FROM search_vectors").fetchall()
            }
            assert "bogus-legacy-doc" not in remaining_ids
            assert len(remaining_ids) == 6

            stats_row = db.execute(
                "SELECT n_docs FROM tfidf_corpus_stats WHERE id = 1"
            ).fetchone()
            assert stats_row is not None
            assert stats_row[0] == 6
        finally:
            cache.close()


class TestBatchedVectorScoring:
    """Dense search must not scale by a Python loop over every vector.

    Measured on the real corpus (1,327,036 vectors), the row-at-a-time version
    took ~951s per query: pure-Python dot products plus one metadata SELECT for
    every positively scoring row.  Batched numpy scoring brought the same query
    to ~110s and returns the same ranking.
    """

    def _seed(self, cache, n: int, dim: int = 8):
        import random
        import struct

        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.semantic import _ensure_embedding_vectors

        _ensure_embedding_vectors(cache.db)
        vectors = {}
        for i in range(n):
            cache.store_document(Document(
                source="s", document_id=f"D{i}", title=f"Karar {i}",
                content_status=ContentStatus.FULL_TEXT, full_text="metin",
            ))
            # Distinct per document: a periodic pattern would tie many
            # vectors at the same score and make the ranking comparison
            # depend on tie-break order rather than on the maths.
            rng = random.Random(i)
            vec = [rng.uniform(0.1, 1.0) for _ in range(dim)]
            norm = sum(v * v for v in vec) ** 0.5
            vectors[f"D{i}"] = (vec, norm)
            cache.db.execute(
                "INSERT OR REPLACE INTO embedding_vectors "
                "(document_id, source, provider_id, chunk_index, dim, vector, norm) "
                "VALUES (?,?,?,?,?,?,?)",
                (f"D{i}", "s", "testprov", 0, dim,
                 struct.pack(f"{dim}f", *vec), norm),
            )
        cache.db.commit()
        return vectors

    def _naive_top(self, vectors, q_vec, q_norm, k):
        """Reference implementation: the loop the batched version replaced."""
        out = []
        for doc_id, (vec, norm) in vectors.items():
            dot = sum(q_vec[i] * vec[i] for i in range(len(q_vec)))
            denom = q_norm * norm
            score = dot / denom if denom > 0 else 0.0
            if score > 0:
                out.append((round(score, 6), doc_id))
        out.sort(key=lambda t: (-t[0], t[1]))
        return out[:k]

    def test_ranking_matches_the_naive_loop(self, tmp_path):
        from emsal_mcp.cache import Cache
        from emsal_mcp.semantic import _score_vectors_batched

        cache = Cache(tmp_path / "vec.sqlite3")
        try:
            vectors = self._seed(cache, 300)
            q_vec = [1.0, 0.2, 0.9, 0.3, 0.7, 0.1, 0.4, 0.6]
            q_norm = sum(v * v for v in q_vec) ** 0.5

            got = _score_vectors_batched(
                cache.db, "testprov", q_vec, q_norm, limit=10,
            )
            expected = self._naive_top(vectors, q_vec, q_norm, 10)

            assert [r["document_id"] for r in got[:10]] == [e[1] for e in expected]
            # numpy scores in float32, the reference loop in Python float64 —
            # compare within tolerance rather than bit-for-bit.
            for r, e in zip(got[:10], expected, strict=True):
                assert abs(r["score"] - e[0]) < 1e-5
        finally:
            cache.close()

    def test_batching_does_not_change_results(self, tmp_path, monkeypatch):
        """A batch smaller than the corpus must give the same answer."""
        from emsal_mcp import semantic
        from emsal_mcp.cache import Cache

        cache = Cache(tmp_path / "vec2.sqlite3")
        try:
            self._seed(cache, 250)
            q_vec = [0.9, 0.1, 0.5, 0.2, 0.8, 0.3, 0.6, 0.4]
            q_norm = sum(v * v for v in q_vec) ** 0.5

            monkeypatch.setattr(semantic, "_EMBED_SCAN_BATCH", 10_000)
            one_shot = semantic._score_vectors_batched(
                cache.db, "testprov", q_vec, q_norm, limit=5)

            monkeypatch.setattr(semantic, "_EMBED_SCAN_BATCH", 17)
            many_batches = semantic._score_vectors_batched(
                cache.db, "testprov", q_vec, q_norm, limit=5)

            assert [r["document_id"] for r in one_shot[:5]] == \
                   [r["document_id"] for r in many_batches[:5]]
        finally:
            cache.close()

    def test_metadata_is_not_queried_once_per_vector(self, tmp_path):
        from emsal_mcp.cache import Cache
        from emsal_mcp.semantic import _score_vectors_batched

        cache = Cache(tmp_path / "vec3.sqlite3")
        try:
            self._seed(cache, 400)
            q_vec = [1.0] * 8
            q_norm = sum(v * v for v in q_vec) ** 0.5

            calls = {"documents_v2": 0}

            def tracer(sql: str) -> None:
                if "documents_v2" in sql:
                    calls["documents_v2"] += 1

            cache.db.set_trace_callback(tracer)
            try:
                _score_vectors_batched(
                    cache.db, "testprov", q_vec, q_norm, limit=10)
            finally:
                cache.db.set_trace_callback(None)

            assert calls["documents_v2"] <= 2, (
                f"{calls['documents_v2']} metadata queries for 400 vectors — "
                f"this is the per-row lookup that made the real corpus unusable"
            )
        finally:
            cache.close()

    def test_dimension_mismatch_rows_are_skipped(self, tmp_path):
        """Vectors from another provider/dim must not corrupt the reshape."""
        import struct

        from emsal_mcp.cache import Cache
        from emsal_mcp.semantic import _score_vectors_batched

        cache = Cache(tmp_path / "vec4.sqlite3")
        try:
            self._seed(cache, 20, dim=8)
            cache.db.execute(
                "INSERT OR REPLACE INTO embedding_vectors "
                "(document_id, source, provider_id, chunk_index, dim, vector, norm) "
                "VALUES ('X','s','testprov',0,4,?,1.0)",
                (struct.pack("4f", 1.0, 1.0, 1.0, 1.0),),
            )
            cache.db.commit()

            q_vec = [1.0] * 8
            q_norm = sum(v * v for v in q_vec) ** 0.5
            got = _score_vectors_batched(
                cache.db, "testprov", q_vec, q_norm, limit=5)

            assert got
            assert "X" not in [r["document_id"] for r in got]
        finally:
            cache.close()

    def test_no_vectors_returns_empty_not_error(self, tmp_path):
        from emsal_mcp.cache import Cache
        from emsal_mcp.semantic import _score_vectors_batched

        cache = Cache(tmp_path / "vec5.sqlite3")
        try:
            from emsal_mcp.semantic import _ensure_embedding_vectors
            _ensure_embedding_vectors(cache.db)
            assert _score_vectors_batched(
                cache.db, "yok", [1.0] * 8, 1.0, limit=5) == []
        finally:
            cache.close()


class TestEmbeddingTableSupportsChunks:
    """Documents are chunked before embedding, so one document owns many rows.

    ``chunk_index`` existed only in the live database — the desktop batch job
    created it — and appeared nowhere in this codebase.  A fresh install got a
    primary key of (document_id, source, provider_id), which holds exactly one
    vector per document and silently overwrites every chunk but the last.  One
    real decision in the corpus has 1,798 chunks.
    """

    def test_fresh_table_has_chunk_index_in_the_primary_key(self, tmp_path):
        from emsal_mcp.cache import Cache
        from emsal_mcp.semantic import (
            _ensure_embedding_vectors,
            embedding_table_supports_chunks,
        )

        cache = Cache(tmp_path / "fresh.sqlite3")
        try:
            _ensure_embedding_vectors(cache.db)
            assert embedding_table_supports_chunks(cache.db) is True
        finally:
            cache.close()

    def test_two_chunks_of_one_document_both_survive(self, tmp_path):
        import struct

        from emsal_mcp.cache import Cache
        from emsal_mcp.semantic import _ensure_embedding_vectors

        cache = Cache(tmp_path / "chunks.sqlite3")
        try:
            _ensure_embedding_vectors(cache.db)
            for idx in range(3):
                cache.db.execute(
                    "INSERT OR REPLACE INTO embedding_vectors "
                    "(document_id, source, provider_id, chunk_index, dim, "
                    " vector, norm) VALUES ('D1','s','p',?,4,?,1.0)",
                    (idx, struct.pack("4f", float(idx), 1.0, 1.0, 1.0)),
                )
            cache.db.commit()
            n = cache.db.execute(
                "SELECT COUNT(*) FROM embedding_vectors WHERE document_id='D1'"
            ).fetchone()[0]
            assert n == 3, "chunks collapsed onto one row"
        finally:
            cache.close()

    def test_legacy_table_is_detected_and_gets_the_column(self, tmp_path):
        from emsal_mcp.cache import Cache
        from emsal_mcp.semantic import (
            _ensure_embedding_vectors,
            embedding_table_supports_chunks,
        )

        cache = Cache(tmp_path / "legacy.sqlite3")
        try:
            cache.db.execute("DROP TABLE IF EXISTS embedding_vectors")
            cache.db.execute("""
                CREATE TABLE embedding_vectors (
                    document_id TEXT NOT NULL, source TEXT NOT NULL,
                    provider_id TEXT NOT NULL, dim INTEGER NOT NULL,
                    vector BLOB NOT NULL, norm REAL DEFAULT 0.0,
                    indexed_at DATETIME, content_hash TEXT,
                    PRIMARY KEY (document_id, source, provider_id))
            """)
            cache.db.commit()

            assert embedding_table_supports_chunks(cache.db) is False
            _ensure_embedding_vectors(cache.db)

            cols = {r[1] for r in cache.db.execute(
                "PRAGMA table_info(embedding_vectors)")}
            assert "chunk_index" in cols, "legacy table left unreadable"
            # The narrow key survives until a rebuild — report it honestly
            # rather than pretending chunked writes will work.
            assert embedding_table_supports_chunks(cache.db) is False
        finally:
            cache.close()
