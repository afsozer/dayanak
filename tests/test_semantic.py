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

from pathlib import Path


from emsal_mcp.cache import Cache
from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.semantic import (
    SEMANTIC_VERSION,
    build_semantic_index,
    get_index_status,
    hybrid_search,
    rebuild_index,
    semantic_search,
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
        """SEMANTIC_VERSION equals '0.11.0'."""
        assert SEMANTIC_VERSION == "0.11.0"


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
        """Calling without a cache parameter should still work."""
        result = semantic_search("test", cache=None)
        assert result["ok"] is True
        assert result["results"] == []

    def test_hybrid_search_no_cache_creates_own(self) -> None:
        """Calling without a cache parameter should still work (creates own cache)."""
        result = hybrid_search("test", cache=None)
        assert result["ok"] is True
        assert result["method"] == "hybrid"

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
