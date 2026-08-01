"""Tests for v0.14 Citation Graph module."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

import json
import tempfile
from pathlib import Path

from emsal_mcp.cache import Cache
from emsal_mcp.citation_graph import (
    build_citation_graph,
    export_graph,
    find_cited_documents,
    find_citing_documents,
    get_citation_graph,
    get_citation_graph_build_progress,
    get_citation_graph_stats,
)
from emsal_mcp.models import ContentStatus, Document


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_doc(**overrides) -> Document:
    """Create a Document with sensible defaults for testing."""
    defaults = {
        "source": "test_source",
        "document_id": "DOC-001",
        "title": "Test Kararı",
        "court": "Yargıtay",
        "chamber": "3. Hukuk Dairesi",
        "decision_date": "2024-06-15",
        "esas_no": "2023/12345",
        "karar_no": "2024/5678",
        "source_url": "https://example.test/doc/001",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": "Yargıtay 3. Hukuk Dairesi E.2023/12345 K.2024/5678 Tarihi: 15.06.2024",
    }
    defaults.update(overrides)
    return Document(**defaults)


def _seed_cache_with_docs(cache: Cache, docs: list[Document]) -> None:
    """Store a list of documents in the cache."""
    for doc in docs:
        cache.store_document(doc)


def _temp_cache() -> tuple[Cache, Path]:
    """Create a temporary cache for testing."""
    tmp = tempfile.mktemp(suffix=".sqlite3")
    cache = Cache(Path(tmp))
    return cache, Path(tmp)


# ---------------------------------------------------------------------------
# Build graph tests
# ---------------------------------------------------------------------------

class TestBuildCitationGraph:
    def test_build_empty_cache(self):
        """Build on empty cache should return ok with 0 edges."""
        cache, path = _temp_cache()
        try:
            result = build_citation_graph(cache=cache)
            assert result["ok"] is True
            assert result["edges_created"] == 0
            assert result["docs_processed"] == 0
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_build_with_no_citations_in_text(self):
        """Build with documents that have no citation patterns."""
        cache, path = _temp_cache()
        try:
            doc = _make_doc(
                document_id="DOC-NO-CITE",
                full_text="Bu metinde herhangi bir hukuki referans bulunmamaktadır.",
            )
            _seed_cache_with_docs(cache, [doc])
            result = build_citation_graph(cache=cache)
            assert result["ok"] is True
            assert result["edges_created"] == 0
            assert result["citations_found"] == 0
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_build_exact_esas_karar_match(self):
        """Build should create high-confidence edge on exact esas+karar match."""
        cache, path = _temp_cache()
        try:
            # Source doc A references doc B's case numbers
            doc_a = _make_doc(
                document_id="DOC-A",
                source="source_a",
                title="Dava Dilekçesi",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2025-01-01",
                esas_no="2025/100",
                karar_no="2025/200",
                full_text=(
                    "Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345, "
                    "Karar No: 2024/5678 tarihli kararına atıfta bulunulmuştur."
                ),
            )
            # Doc B is the referenced decision
            doc_b = _make_doc(
                document_id="DOC-B",
                source="source_b",
                title="Yargıtay Kararı",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2024-06-15",
                esas_no="2023/12345",
                karar_no="2024/5678",
                full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345 Karar No: 2024/5678",
            )
            _seed_cache_with_docs(cache, [doc_a, doc_b])
            result = build_citation_graph(cache=cache)
            assert result["ok"] is True
            assert result["edges_created"] >= 1
            assert result["matches_found"] >= 1

            # Check that the edge has high confidence
            edges = cache.db.execute("SELECT * FROM citation_edges").fetchall()
            assert len(edges) >= 1
            edge = dict(edges[0])
            assert edge["confidence"] == "high"
            assert edge["match_type"] == "exact_esas_karar"
            assert edge["extracted_from"] is not None
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_build_medium_confidence_karar_only(self):
        """Build should create medium-confidence edge on karar_no match."""
        cache, path = _temp_cache()
        try:
            doc_a = _make_doc(
                document_id="DOC-A",
                source="source_a",
                title="Dava Dilekçesi",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2025-01-01",
                esas_no="2025/100",
                karar_no="2025/200",
                full_text=(
                    "Yargıtay 3. Hukuk Dairesi Esas No: 2099/99999, "
                    "Karar No: 2024/5678 tarihli kararına atıfta bulunulmuştur."
                ),
            )
            # Doc B has same karar_no but different esas_no
            doc_b = _make_doc(
                document_id="DOC-B",
                source="source_b",
                title="Yargıtay Kararı",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2024-06-15",
                esas_no="2023/12345",
                karar_no="2024/5678",
                full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345 Karar No: 2024/5678",
            )
            _seed_cache_with_docs(cache, [doc_a, doc_b])
            result = build_citation_graph(cache=cache)
            assert result["ok"] is True
            assert result["edges_created"] >= 1

            edges = cache.db.execute("SELECT * FROM citation_edges").fetchall()
            assert len(edges) >= 1
            assert dict(edges[0])["confidence"] in ("high", "medium")
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_build_idempotent(self):
        """Running build twice should not duplicate edges."""
        cache, path = _temp_cache()
        try:
            doc_a = _make_doc(
                document_id="DOC-A",
                source="source_a",
                title="Dava Dilekçesi",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2025-01-01",
                esas_no="2025/100",
                karar_no="2025/200",
                full_text=(
                    "Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345, "
                    "Karar No: 2024/5678 tarihli kararına atıfta bulunulmuştur."
                ),
            )
            doc_b = _make_doc(
                document_id="DOC-B",
                source="source_b",
                title="Yargıtay Kararı",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2024-06-15",
                esas_no="2023/12345",
                karar_no="2024/5678",
                full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345 Karar No: 2024/5678",
            )
            _seed_cache_with_docs(cache, [doc_a, doc_b])

            build_citation_graph(cache=cache)
            edges_after_first = cache.db.execute("SELECT COUNT(*) FROM citation_edges").fetchone()[0]

            result2 = build_citation_graph(cache=cache)
            edges_after_second = cache.db.execute("SELECT COUNT(*) FROM citation_edges").fetchone()[0]

            assert edges_after_first == edges_after_second
            assert result2["ok"] is True
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_build_limit_docs(self):
        """Build should respect limit_docs parameter."""
        cache, path = _temp_cache()
        try:
            docs = []
            for i in range(5):
                docs.append(_make_doc(
                    document_id=f"DOC-{i}",
                    source="test_source",
                    title=f"Test {i}",
                    court="Yargıtay",
                    chamber="3. Hukuk Dairesi",
                    decision_date="2024-01-01",
                    esas_no=f"2024/{i}",
                    karar_no=f"2024/{i}",
                    full_text=f"Yargıtay 3. Hukuk Dairesi E.2024/{i} K.2024/{i}",
                ))
            _seed_cache_with_docs(cache, docs)

            result = build_citation_graph(cache=cache, limit_docs=2)
            assert result["ok"] is True
            assert result["docs_processed"] <= 2
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_build_no_self_citation(self):
        """Build should not create self-referencing edges."""
        cache, path = _temp_cache()
        try:
            doc = _make_doc(
                document_id="DOC-SELF",
                source="test_source",
                title="Tek Belge",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2024-06-15",
                esas_no="2023/12345",
                karar_no="2024/5678",
                full_text="Yargıtay 3. Hukuk Dairesi E.2023/12345 K.2024/5678",
            )
            _seed_cache_with_docs(cache, [doc])
            result = build_citation_graph(cache=cache)
            assert result["ok"] is True
            # No edges should be created since the only doc references itself
            edges = cache.db.execute("SELECT * FROM citation_edges").fetchall()
            assert len(edges) == 0
        finally:
            cache.close()
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Query graph tests
# ---------------------------------------------------------------------------

class TestGetCitationGraph:
    def _setup_graph(self) -> tuple[Cache, Path]:
        cache, path = _temp_cache()
        doc_a = _make_doc(
            document_id="DOC-A",
            source="source_a",
            title="Dava Dilekçesi",
            court="Yargıtay",
            chamber="3. Hukuk Dairesi",
            decision_date="2025-01-01",
            esas_no="2025/100",
            karar_no="2025/200",
            full_text=(
                "Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345, "
                "Karar No: 2024/5678 tarihli kararına atıfta bulunulmuştur."
            ),
        )
        doc_b = _make_doc(
            document_id="DOC-B",
            source="source_b",
            title="Yargıtay Kararı",
            court="Yargıtay",
            chamber="3. Hukuk Dairesi",
            decision_date="2024-06-15",
            esas_no="2023/12345",
            karar_no="2024/5678",
            full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345 Karar No: 2024/5678",
        )
        _seed_cache_with_docs(cache, [doc_a, doc_b])
        build_citation_graph(cache=cache)
        return cache, path

    def test_get_graph_both(self):
        cache, path = self._setup_graph()
        try:
            result = get_citation_graph("DOC-A", "source_a", cache=cache, direction="both")
            assert result["ok"] is True
            assert "citing" in result
            assert "cited_by" in result
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_get_graph_citing(self):
        cache, path = self._setup_graph()
        try:
            result = get_citation_graph("DOC-B", "source_b", cache=cache, direction="citing")
            assert result["ok"] is True
            assert len(result["citing"]) >= 1
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_get_graph_cited(self):
        cache, path = self._setup_graph()
        try:
            result = get_citation_graph("DOC-A", "source_a", cache=cache, direction="cited")
            assert result["ok"] is True
            assert len(result["cited_by"]) >= 1
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_get_graph_doc_not_found(self):
        cache, path = _temp_cache()
        try:
            result = get_citation_graph("NONEXISTENT", "test", cache=cache)
            assert result["ok"] is False
            assert "errorCode" in result
        finally:
            cache.close()
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Find citing/cited tests
# ---------------------------------------------------------------------------

class TestFindCitingCited:
    def _setup_graph(self) -> tuple[Cache, Path]:
        cache, path = _temp_cache()
        doc_a = _make_doc(
            document_id="DOC-A",
            source="source_a",
            title="Dava Dilekçesi",
            court="Yargıtay",
            chamber="3. Hukuk Dairesi",
            decision_date="2025-01-01",
            esas_no="2025/100",
            karar_no="2025/200",
            full_text=(
                "Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345, "
                "Karar No: 2024/5678 tarihli kararına atıfta bulunulmuştur."
            ),
        )
        doc_b = _make_doc(
            document_id="DOC-B",
            source="source_b",
            title="Yargıtay Kararı",
            court="Yargıtay",
            chamber="3. Hukuk Dairesi",
            decision_date="2024-06-15",
            esas_no="2023/12345",
            karar_no="2024/5678",
            full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345 Karar No: 2024/5678",
        )
        _seed_cache_with_docs(cache, [doc_a, doc_b])
        build_citation_graph(cache=cache)
        return cache, path

    def test_find_citing(self):
        cache, path = self._setup_graph()
        try:
            result = find_citing_documents("DOC-B", "source_b", cache=cache)
            assert result["ok"] is True
            assert result["total"] >= 1
            assert result["citing_documents"][0]["document_id"] == "DOC-A"
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_find_cited(self):
        cache, path = self._setup_graph()
        try:
            result = find_cited_documents("DOC-A", "source_a", cache=cache)
            assert result["ok"] is True
            assert result["total"] >= 1
            assert result["cited_documents"][0]["document_id"] == "DOC-B"
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_find_citing_doc_not_found(self):
        cache, path = _temp_cache()
        try:
            result = find_citing_documents("NONEXISTENT", "test", cache=cache)
            assert result["ok"] is False
            assert "errorCode" in result
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_find_cited_doc_not_found(self):
        cache, path = _temp_cache()
        try:
            result = find_cited_documents("NONEXISTENT", "test", cache=cache)
            assert result["ok"] is False
            assert "errorCode" in result
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_find_citing_limit(self):
        cache, path = self._setup_graph()
        try:
            result = find_citing_documents("DOC-B", "source_b", cache=cache, limit=1)
            assert result["ok"] is True
            assert result["total"] <= 1
        finally:
            cache.close()
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Stats tests
# ---------------------------------------------------------------------------

class TestGraphStats:
    def test_stats_empty(self):
        cache, path = _temp_cache()
        try:
            result = get_citation_graph_stats(cache=cache)
            assert result["ok"] is True
            assert result["total_edges"] == 0
            assert result["total_docs_with_citations"] == 0
            assert result["avg_citations_per_doc"] == 0.0
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_stats_empty_warns_graph_never_built(self):
        """The empty-graph case must be unmistakably labeled 'never built',
        not confused with 'no citations exist'. ok stays True (empty graph
        is a legitimate state, not an error)."""
        cache, path = _temp_cache()
        try:
            result = get_citation_graph_stats(cache=cache)
            assert result["ok"] is True
            assert result["total_edges"] == 0
            assert len(result["warnings"]) >= 1
            assert any("hiç oluşturulmamış" in w for w in result["warnings"])
            assert any(
                "build_citation_graph" in step
                for step in result["recommended_next_steps"]
            )
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_stats_with_edges(self):
        cache, path = _temp_cache()
        try:
            doc_a = _make_doc(
                document_id="DOC-A",
                source="source_a",
                title="Dava Dilekçesi",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2025-01-01",
                esas_no="2025/100",
                karar_no="2025/200",
                full_text=(
                    "Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345, "
                    "Karar No: 2024/5678 tarihli kararına atıfta bulunulmuştur."
                ),
            )
            doc_b = _make_doc(
                document_id="DOC-B",
                source="source_b",
                title="Yargıtay Kararı",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2024-06-15",
                esas_no="2023/12345",
                karar_no="2024/5678",
                full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345 Karar No: 2024/5678",
            )
            _seed_cache_with_docs(cache, [doc_a, doc_b])
            build_citation_graph(cache=cache)

            result = get_citation_graph_stats(cache=cache)
            assert result["ok"] is True
            assert result["total_edges"] >= 1
            assert result["total_docs_with_citations"] >= 2
            assert result["most_cited_docs"] is not None
            assert "confidence_distribution" in result
            # Regression guard: a populated graph must NOT carry the
            # "never built" warning — collapsing these two cases was the bug.
            assert result["warnings"] == []
            assert result["recommended_next_steps"] == []
            # Coverage fields mirroring get_index_status()'s TF-IDF reporting.
            assert result["total_cached_documents"] >= 2
            assert result["documents_in_graph"] >= 2
            assert 0.0 <= result["graph_coverage_ratio"] <= 1.0
            assert result["last_built_at"] is not None
        finally:
            cache.close()
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Import tests (CLI and MCP)
# ---------------------------------------------------------------------------

class TestImports:
    def test_citation_graph_importable(self):
        import emsal_mcp.citation_graph
        assert hasattr(emsal_mcp.citation_graph, "build_citation_graph")
        assert hasattr(emsal_mcp.citation_graph, "export_graph")
        assert hasattr(emsal_mcp.citation_graph, "get_citation_graph")
        assert hasattr(emsal_mcp.citation_graph, "find_citing_documents")
        assert hasattr(emsal_mcp.citation_graph, "find_cited_documents")
        assert hasattr(emsal_mcp.citation_graph, "get_citation_graph_stats")

    def test_server_importable(self):
        from emsal_mcp.server import main
        assert callable(main)

    def test_cli_importable(self):
        from emsal_mcp.cli import app, graph_app
        assert callable(app)
        assert callable(graph_app)


# ---------------------------------------------------------------------------
# No fabrication test
# ---------------------------------------------------------------------------

class TestNoFabrication:
    def test_no_edges_without_cached_match(self):
        """Citations found in text should NOT create edges if no cached docs match."""
        cache, path = _temp_cache()
        try:
            doc = _make_doc(
                document_id="DOC-ORPHAN",
                source="test_source",
                title="Yalnız Belge",
                court="Yargıtay",
                chamber="3. Hukuk Dairesi",
                decision_date="2024-01-01",
                esas_no="2024/100",
                karar_no="2024/200",
                full_text=(
                    "Yargıtay 3. Hukuk Dairesi E.9999/99999 K.9999/99999 "
                    "tarihli kararına atıfta bulunulmuştur."
                ),
            )
            _seed_cache_with_docs(cache, [doc])
            result = build_citation_graph(cache=cache)
            assert result["ok"] is True
            # No edges should be created since there's no matching cached doc
            edges = cache.db.execute("SELECT * FROM citation_edges").fetchall()
            assert len(edges) == 0
        finally:
            cache.close()
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Edge table creation test
# ---------------------------------------------------------------------------

class TestEdgeTable:
    def test_table_created_on_build(self):
        cache, path = _temp_cache()
        try:
            build_citation_graph(cache=cache)
            # Table should exist
            exists = cache.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='citation_edges'"
            ).fetchone()
            assert exists is not None
        finally:
            cache.close()
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Export graph tests (M-39)
# ---------------------------------------------------------------------------

class TestExportGraph:
    def _setup_graph(self) -> tuple[Cache, Path]:
        cache, path = _temp_cache()
        doc_a = _make_doc(
            document_id="DOC-A",
            source="source_a",
            title="Dava Dilekçesi",
            court="Yargıtay",
            chamber="3. Hukuk Dairesi",
            decision_date="2025-01-01",
            esas_no="2025/100",
            karar_no="2025/200",
            full_text=(
                "Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345, "
                "Karar No: 2024/5678 tarihli kararına atıfta bulunulmuştur."
            ),
        )
        doc_b = _make_doc(
            document_id="DOC-B",
            source="source_b",
            title="Yargıtay Kararı",
            court="Yargıtay",
            chamber="3. Hukuk Dairesi",
            decision_date="2024-06-15",
            esas_no="2023/12345",
            karar_no="2024/5678",
            full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345 Karar No: 2024/5678",
        )
        _seed_cache_with_docs(cache, [doc_a, doc_b])
        build_citation_graph(cache=cache)
        return cache, path

    def test_export_json_valid_structure(self):
        """Export as JSON should produce valid node-link structure."""
        cache, path = self._setup_graph()
        try:
            result = export_graph(format="json", cache=cache)
            assert result["ok"] is True
            assert result["format"] == "json"
            data = json.loads(result["export_text"])
            assert "nodes" in data
            assert "edges" in data
            assert isinstance(data["nodes"], list)
            assert isinstance(data["edges"], list)
            assert result["node_count"] >= 2
            assert result["edge_count"] >= 1
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_export_dot_produces_graph_syntax(self):
        """Export as DOT should produce valid Graphviz syntax."""
        cache, path = self._setup_graph()
        try:
            result = export_graph(format="dot", cache=cache)
            assert result["ok"] is True
            assert result["format"] == "dot"
            assert "digraph citations" in result["export_text"]
            assert "->" in result["export_text"]
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_export_mermaid_produces_mermaid_syntax(self):
        """Export as Mermaid should produce valid mermaid syntax."""
        cache, path = self._setup_graph()
        try:
            result = export_graph(format="mermaid", cache=cache)
            assert result["ok"] is True
            assert result["format"] == "mermaid"
            assert "graph LR" in result["export_text"]
            assert "-->" in result["export_text"]
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_export_with_document_id_subgraph(self):
        """Export with document_id should produce sub-graph."""
        cache, path = self._setup_graph()
        try:
            result = export_graph(
                format="json", cache=cache,
                document_id="DOC-A", source="source_a", max_depth=1,
            )
            assert result["ok"] is True
            assert result["sub_graph"] is True
            data = json.loads(result["export_text"])
            doc_ids = {n["document_id"] for n in data["nodes"]}
            assert "DOC-A" in doc_ids
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_export_invalid_format(self):
        """Invalid format should return error."""
        cache, path = _temp_cache()
        try:
            result = export_graph(format="csv", cache=cache)
            assert result["ok"] is False
            assert "errorCode" in result
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_export_empty_graph(self):
        """Export of empty graph should return ok with 0 nodes/edges."""
        cache, path = _temp_cache()
        try:
            result = export_graph(format="json", cache=cache)
            assert result["ok"] is True
            assert result["node_count"] == 0
            assert result["edge_count"] == 0
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_export_empty_graph_warns_never_built(self):
        cache, path = _temp_cache()
        try:
            result = export_graph(format="json", cache=cache)
            assert result["ok"] is True
            assert len(result["warnings"]) >= 1
            assert any("hiç oluşturulmamış" in w for w in result["warnings"])
            assert any(
                "build_citation_graph" in step
                for step in result["recommended_next_steps"]
            )
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_export_populated_graph_no_never_built_warning(self):
        cache, path = self._setup_graph()
        try:
            result = export_graph(format="json", cache=cache)
            assert result["ok"] is True
            assert result["warnings"] == []
            assert result["recommended_next_steps"] == []
        finally:
            cache.close()
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# "Graph never built" vs "no citations for this document" (regression suite)
# ---------------------------------------------------------------------------
#
# The bug this guards against: citation_graph_stats(), get_citation_graph(),
# find_citing_documents(), find_cited_documents() and export_citation_graph()
# all returned ok:true with plain zeros/empties when citation_edges had never
# been populated by build_citation_graph() — indistinguishable from "this
# document legitimately has no citations". These tests exercise all three
# states for the per-document query tools: (1) edge table empty overall,
# (2) edge table populated but the queried doc has no edges, (3) edge table
# populated and the queried doc has edges.

class TestNeverBuiltVsNoCitations:
    def _setup_populated_graph(self) -> tuple[Cache, Path]:
        """Build a graph where DOC-A cites DOC-B, and DOC-C is an isolated
        document with no detectable citations and nothing citing it."""
        cache, path = _temp_cache()
        doc_a = _make_doc(
            document_id="DOC-A",
            source="source_a",
            title="Dava Dilekçesi",
            court="Yargıtay",
            chamber="3. Hukuk Dairesi",
            decision_date="2025-01-01",
            esas_no="2025/100",
            karar_no="2025/200",
            full_text=(
                "Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345, "
                "Karar No: 2024/5678 tarihli kararına atıfta bulunulmuştur."
            ),
        )
        doc_b = _make_doc(
            document_id="DOC-B",
            source="source_b",
            title="Yargıtay Kararı",
            court="Yargıtay",
            chamber="3. Hukuk Dairesi",
            decision_date="2024-06-15",
            esas_no="2023/12345",
            karar_no="2024/5678",
            full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/12345 Karar No: 2024/5678",
        )
        doc_c = _make_doc(
            document_id="DOC-C",
            source="source_c",
            title="İlgisiz Belge",
            court="Danıştay",
            chamber="5. Daire",
            decision_date="2020-01-01",
            esas_no="2020/1",
            karar_no="2020/2",
            full_text="Bu metinde herhangi bir hukuki referans bulunmamaktadır.",
        )
        _seed_cache_with_docs(cache, [doc_a, doc_b, doc_c])
        build_citation_graph(cache=cache)
        return cache, path

    # -- get_citation_graph -------------------------------------------------

    def test_get_citation_graph_empty_table_warns(self):
        cache, path = _temp_cache()
        try:
            doc = _make_doc(document_id="DOC-SOLO", source="solo_src")
            _seed_cache_with_docs(cache, [doc])
            result = get_citation_graph("DOC-SOLO", "solo_src", cache=cache)
            assert result["ok"] is True
            assert len(result["warnings"]) >= 1
            assert any("hiç oluşturulmamış" in w for w in result["warnings"])
            assert any(
                "build_citation_graph" in step
                for step in result["recommended_next_steps"]
            )
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_get_citation_graph_populated_doc_without_citations_no_warning(self):
        """The regression case: an already-built graph where THIS document
        has no edges must not be reported as 'graph never built'."""
        cache, path = self._setup_populated_graph()
        try:
            result = get_citation_graph("DOC-C", "source_c", cache=cache)
            assert result["ok"] is True
            assert result["citing"] == []
            assert result["cited_by"] == []
            assert result["warnings"] == []
            assert result["recommended_next_steps"] == []
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_get_citation_graph_populated_doc_with_citations_no_warning(self):
        cache, path = self._setup_populated_graph()
        try:
            result = get_citation_graph("DOC-A", "source_a", cache=cache, direction="cited")
            assert result["ok"] is True
            assert len(result["cited_by"]) >= 1
            assert result["warnings"] == []
            assert result["recommended_next_steps"] == []
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    # -- find_citing_documents / find_cited_documents ------------------------

    def test_find_citing_documents_empty_table_warns(self):
        cache, path = _temp_cache()
        try:
            doc = _make_doc(document_id="DOC-SOLO", source="solo_src")
            _seed_cache_with_docs(cache, [doc])
            result = find_citing_documents("DOC-SOLO", "solo_src", cache=cache)
            assert result["ok"] is True
            assert any("hiç oluşturulmamış" in w for w in result["warnings"])
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_find_citing_documents_populated_doc_without_citations_no_warning(self):
        cache, path = self._setup_populated_graph()
        try:
            result = find_citing_documents("DOC-C", "source_c", cache=cache)
            assert result["ok"] is True
            assert result["citing_documents"] == []
            assert result["warnings"] == []
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_find_citing_documents_populated_doc_with_citations_no_warning(self):
        cache, path = self._setup_populated_graph()
        try:
            result = find_citing_documents("DOC-B", "source_b", cache=cache)
            assert result["ok"] is True
            assert result["total"] >= 1
            assert result["warnings"] == []
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_find_cited_documents_empty_table_warns(self):
        cache, path = _temp_cache()
        try:
            doc = _make_doc(document_id="DOC-SOLO", source="solo_src")
            _seed_cache_with_docs(cache, [doc])
            result = find_cited_documents("DOC-SOLO", "solo_src", cache=cache)
            assert result["ok"] is True
            assert any("hiç oluşturulmamış" in w for w in result["warnings"])
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_find_cited_documents_populated_doc_without_citations_no_warning(self):
        cache, path = self._setup_populated_graph()
        try:
            result = find_cited_documents("DOC-C", "source_c", cache=cache)
            assert result["ok"] is True
            assert result["cited_documents"] == []
            assert result["warnings"] == []
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_find_cited_documents_populated_doc_with_citations_no_warning(self):
        cache, path = self._setup_populated_graph()
        try:
            result = find_cited_documents("DOC-A", "source_a", cache=cache)
            assert result["ok"] is True
            assert result["total"] >= 1
            assert result["warnings"] == []
        finally:
            cache.close()
            path.unlink(missing_ok=True)

class TestEmptyGraphWordingMatchesHistory:
    """An empty edge table has two distinct causes and the message must not
    contradict the timestamp reported alongside it. The real corpus shows a
    build dated 2026-05-29 that produced zero edges — it ran against a corpus
    of test fixtures — so "hiç oluşturulmamış" would be plainly wrong there."""

    def _cache(self, tmp_path):
        from emsal_mcp.cache import Cache
        from emsal_mcp.citation_graph import _ensure_edge_table
        c = Cache(tmp_path / "t.sqlite3")
        _ensure_edge_table(c)
        return c

    def test_no_build_history_says_never_built(self, tmp_path):
        from emsal_mcp.citation_graph import _graph_build_state
        c = self._cache(tmp_path)
        total, warnings, recs = _graph_build_state(c)
        assert total == 0
        assert "hiç oluşturulmamış" in warnings[0]
        assert recs and "build_citation_graph()" in recs[0]
        c.close()

    def test_prior_build_with_zero_edges_says_so(self, tmp_path):
        from emsal_mcp.citation_graph import _graph_build_state
        c = self._cache(tmp_path)
        c.log("build_citation_graph", {"edges": 0})
        total, warnings, recs = _graph_build_state(c)
        assert total == 0
        assert "hiç oluşturulmamış" not in warnings[0], (
            "contradicts the last_built_at timestamp reported in the same response"
        )
        assert "hiç atıf eşleştirememiş" in warnings[0]
        assert recs and "build_citation_graph()" in recs[0]
        c.close()

    def test_populated_graph_has_no_warning_either_way(self, tmp_path):
        from emsal_mcp.citation_graph import _graph_build_state
        c = self._cache(tmp_path)
        c.log("build_citation_graph", {"edges": 1})
        c.db.execute(
            "INSERT INTO citation_edges(citing_doc_id,citing_source,cited_doc_id,"
            "cited_source,confidence,match_type) VALUES ('A','bedesten','B','bedesten',0.9,'exact')"
        )
        c.db.commit()
        total, warnings, recs = _graph_build_state(c)
        assert total == 1
        assert warnings == [] and recs == []
        c.close()


# ---------------------------------------------------------------------------
# Perf fix (in-memory corpus index replacing per-candidate SQL LIKE scans):
# prove the new matching mechanism produces IDENTICAL edges to the old one,
# and that DB query count no longer scales with candidate count.
# ---------------------------------------------------------------------------
#
# Background: build_citation_graph() used to run one SQL query per citation
# candidate (`esas_no LIKE '%...%'` etc.) — a leading '%' wildcard defeats
# the esas_no/karar_no indexes, forcing a full documents_v2 table scan per
# candidate. Profiled against a 20k-row real-corpus subset, that was >90%
# of build time and made a full 208k-document build take an estimated ~29
# days. The fix replaces per-candidate SQL with a _CorpusIndex built once
# per build (one full pass over documents_v2's metadata columns), matched
# via dict lookups / a k-way merge instead of queries.

def _old_algorithm_edges(cache: Cache, limit_docs: int = 1000) -> set[tuple]:
    """Replica of the pre-fix matching algorithm using the still-present,
    unmodified ``_search_cache_for_match`` (the original per-candidate SQL
    LIKE query) and ``_classify_match`` (unmodified). Exists only so tests
    can prove the new ``_CorpusIndex``-based algorithm in
    ``build_citation_graph`` produces the exact same edges — same
    candidate extraction, same classifiers, only the lookup mechanism
    differs.
    """
    from emsal_mcp.citation import extract_citation_candidates
    from emsal_mcp.citation_graph import _classify_match, _search_cache_for_match

    rows = cache.db.execute(
        """SELECT document_id, source, full_text, markdown FROM documents_v2
           WHERE full_text IS NOT NULL OR markdown IS NOT NULL
           ORDER BY last_accessed_at DESC LIMIT ?""",
        (limit_docs,),
    ).fetchall()
    edges: set[tuple] = set()
    for row in rows:
        doc_id, source = row["document_id"], row["source"]
        text = row["full_text"] or row["markdown"] or ""
        if not text or len(text.strip()) < 20:
            continue
        for cand in extract_citation_candidates(text, limit=10):
            for match_doc in _search_cache_for_match(cache, cand, exclude=(doc_id, source)):
                result = _classify_match(cand, match_doc)
                if result is None:
                    continue
                confidence, match_type = result
                edges.add((doc_id, source, match_doc["document_id"], match_doc["source"], confidence, match_type))
    return edges


def _edges_from_table(cache: Cache) -> set[tuple]:
    rows = cache.db.execute(
        "SELECT citing_doc_id, citing_source, cited_doc_id, cited_source, confidence, match_type "
        "FROM citation_edges"
    ).fetchall()
    return {
        (r["citing_doc_id"], r["citing_source"], r["cited_doc_id"], r["cited_source"], r["confidence"], r["match_type"])
        for r in rows
    }


class TestIndexMatchesSqlReference:
    """Proves the in-memory index produces the same edges as the original
    per-candidate SQL scan, across every match type and the tricky corners:
    a shared common court across many documents (stresses the k-way merge
    / bucket dedup), the 20-result cap, and self-citation exclusion."""

    def _seed_rich_corpus(self, cache: Cache) -> None:
        docs = []

        # (1) exact esas+karar+court -> high confidence
        docs.append(_make_doc(
            document_id="A-CITING", source="s", title="Dilekçe A", court="Yargıtay",
            chamber="3. Hukuk Dairesi", decision_date="2025-01-01",
            esas_no="2025/1", karar_no="2025/2",
            full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/500, Karar No: 2024/600 kararına atıf.",
        ))
        docs.append(_make_doc(
            document_id="A-CITED", source="s", title="Yargıtay Kararı", court="Yargıtay",
            chamber="3. Hukuk Dairesi", decision_date="2024-06-15",
            esas_no="2023/500", karar_no="2024/600",
            full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/500 Karar No: 2024/600",
        ))

        # (2) karar_no only -> medium confidence
        docs.append(_make_doc(
            document_id="B-CITING", source="s", title="Dilekçe B", court="Yargıtay",
            chamber="4. Hukuk Dairesi", decision_date="2025-01-01",
            esas_no="2025/3", karar_no="2025/4",
            full_text="Yargıtay 4. Hukuk Dairesi Esas No: 2099/1, Karar No: 2024/700 kararına atıf.",
        ))
        docs.append(_make_doc(
            document_id="B-CITED", source="s", title="Yargıtay Kararı B", court="Yargıtay",
            chamber="4. Hukuk Dairesi", decision_date="2024-07-01",
            esas_no="2023/999", karar_no="2024/700",
            full_text="Yargıtay 4. Hukuk Dairesi Esas No: 2023/999 Karar No: 2024/700",
        ))

        # (3) court+date only (Danıştay, distinct court from the Yargıtay
        # crowd) -> medium confidence via court_date_match
        docs.append(_make_doc(
            document_id="C-CITING", source="s", title="Dilekçe C", court="Danıştay",
            chamber="5. Daire", decision_date="2025-01-01",
            esas_no="2025/5", karar_no="2025/6",
            full_text="Danıştay 5. Daire 15.03.2024 tarihli kararına atıf.",
        ))
        docs.append(_make_doc(
            document_id="C-CITED", source="s", title="Danıştay Kararı", court="Danıştay",
            chamber="5. Daire", decision_date="2024-03-01",
            esas_no="2024/111", karar_no="2024/222",
            full_text="Danıştay 5. Daire Esas No: 2024/111 Karar No: 2024/222",
        ))

        # (4) title-fuzzy only: court name appears in the target's TITLE,
        # not its court field or esas/karar
        docs.append(_make_doc(
            document_id="D-CITING", source="s", title="Dilekçe D", court="Sayıştay",
            chamber=None, decision_date="2025-01-01",
            esas_no="2025/7", karar_no="2025/8",
            full_text="Sayıştay kararına atıfta bulunulmuştur.",
        ))
        docs.append(_make_doc(
            document_id="D-CITED", source="s", title="Sayıştay Genel Kurulu Kararı Özeti",
            court="Bilinmeyen Kurum", chamber=None, decision_date="2010-01-01",
            esas_no="2010/1", karar_no="2010/2",
            full_text="Bu belgenin metninde Sayıştay geçer.",
        ))

        # (5) self-citation: must not produce an edge
        docs.append(_make_doc(
            document_id="E-SELF", source="s", title="Tek Başına", court="Yargıtay",
            chamber="2. Hukuk Dairesi", decision_date="2024-01-01",
            esas_no="2024/50", karar_no="2024/60",
            full_text="Yargıtay 2. Hukuk Dairesi Esas No: 2024/50 Karar No: 2024/60",
        ))

        # (6) orphan reference: no cached doc matches
        docs.append(_make_doc(
            document_id="F-ORPHAN", source="s", title="Yalnız", court="Yargıtay",
            chamber="1. Hukuk Dairesi", decision_date="2024-01-01",
            esas_no="2024/70", karar_no="2024/80",
            full_text="Yargıtay 1. Hukuk Dairesi Esas No: 9999/99999 Karar No: 9999/99999 kararına atıf.",
        ))

        # Filler: 25 documents that all share the "Yargıtay" court so the
        # court/title bucket for "Yargıtay" is large — stresses the k-way
        # merge and the 20-result cap identically for both algorithms.
        for i in range(25):
            docs.append(_make_doc(
                document_id=f"FILLER-{i}", source="s", title=f"Yargıtay Kararı {i}",
                court="Yargıtay", chamber=f"{i % 9 + 1}. Hukuk Dairesi",
                decision_date=f"202{i % 5}-0{i % 9 + 1}-01",
                esas_no=f"20{i:02d}/{i}", karar_no=f"20{i:02d}/{i + 1000}",
                full_text=f"Yargıtay {i % 9 + 1}. Hukuk Dairesi kararı, sıra {i}.",
            ))

        _seed_cache_with_docs(cache, docs)

    def test_edges_identical_old_vs_new(self):
        cache, path = _temp_cache()
        try:
            self._seed_rich_corpus(cache)

            old = _old_algorithm_edges(cache, limit_docs=1000)

            result = build_citation_graph(cache=cache, limit_docs=1000)
            assert result["ok"] is True
            new = _edges_from_table(cache)

            assert new == old, (
                f"only in old: {old - new}\nonly in new: {new - old}"
            )
            # Sanity: the fixture actually exercises all four match types,
            # not just the trivial empty-set case.
            match_types = {e[5] for e in new}
            assert match_types >= {
                "exact_esas_karar", "karar_no_match", "court_date_match", "title_fuzzy",
            }
            # Self-citation must not appear on either side.
            assert not any(e[0] == e[2] and e[1] == e[3] for e in new)
        finally:
            cache.close()
            path.unlink(missing_ok=True)


class TestQueryCountDoesNotScaleWithCandidates:
    """Spy assertion (not wall-clock, which is flaky): the number of SQL
    statements build_citation_graph() issues must not grow with the number
    of citation candidates extracted — that per-candidate scaling was
    exactly the bug. A wall-clock assertion would pass or fail depending on
    machine load; counting statements via sqlite3's trace callback does
    not."""

    def _select_count(self, cache: Cache) -> int:
        queries: list[str] = []
        cache.db.set_trace_callback(lambda sql: queries.append(sql))
        try:
            result = build_citation_graph(cache=cache)
            assert result["ok"] is True
        finally:
            cache.db.set_trace_callback(None)
        return sum(1 for q in queries if q.strip().upper().startswith("SELECT"))

    def test_select_count_independent_of_candidate_count(self):
        # One document, one citation candidate.
        cache_few, path_few = _temp_cache()
        # Many documents, ten citation candidates in one document (the cap
        # extract_citation_candidates applies) — none of which match
        # anything else in the (otherwise unrelated) corpus, isolating the
        # matching mechanism's own query cost from edge-insert cost.
        cache_many, path_many = _temp_cache()
        try:
            doc_few = _make_doc(
                document_id="FEW", source="s",
                full_text="Yargıtay 3. Hukuk Dairesi Esas No: 2023/1 Karar No: 2024/1 tarihli karara atıf.",
            )
            _seed_cache_with_docs(cache_few, [doc_few])
            select_count_few = self._select_count(cache_few)

            lines = [
                f"Yargıtay {i}. Hukuk Dairesi Esas No: 2023/{i} Karar No: 2024/{i} tarihli karara atıf."
                for i in range(10)
            ]
            doc_many = _make_doc(document_id="MANY", source="s", full_text="\n".join(lines))
            _seed_cache_with_docs(cache_many, [doc_many])
            select_count_many = self._select_count(cache_many)

            assert select_count_many == select_count_few, (
                f"SELECT count scaled with candidate count ({select_count_few} -> "
                f"{select_count_many}); matching should be O(1) SQL queries via the "
                "in-memory index, not one query per candidate"
            )
        finally:
            cache_few.close()
            path_few.unlink(missing_ok=True)
            cache_many.close()
            path_many.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Resumability (resume=True): a full-corpus build that dies partway through
# must not restart from zero, and progress must be observable mid-run.
# ---------------------------------------------------------------------------

class TestResumableBuild:
    def _seed_docs(self, cache: Cache, n: int) -> None:
        docs = []
        for i in range(n):
            docs.append(_make_doc(
                document_id=f"DOC-{i}", source="s", title=f"Karar {i}",
                court="Yargıtay", chamber="3. Hukuk Dairesi",
                decision_date="2024-01-01", esas_no=f"2024/{i}", karar_no=f"2024/{i + 1000}",
                full_text=f"Yargıtay 3. Hukuk Dairesi Esas No: 2024/{i} Karar No: 2024/{i + 1000}",
            ))
        _seed_cache_with_docs(cache, docs)

    def test_resume_false_ignores_checkpoint_state(self):
        """Default (resume=False) behaviour must be untouched by this
        feature: no checkpoint table writes, same single-commit contract
        as before."""
        cache, path = _temp_cache()
        try:
            self._seed_docs(cache, 5)
            result = build_citation_graph(cache=cache)
            assert result["ok"] is True
            exists = cache.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='citation_graph_build_state'"
            ).fetchone()
            # The table may exist (created lazily elsewhere) but must have
            # no row, since resume=False never touches it.
            if exists:
                row = cache.db.execute("SELECT * FROM citation_graph_build_state").fetchone()
                assert row is None
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_resume_picks_up_where_it_left_off(self):
        """Two small resumable calls (limit_docs=3 each) over a 6-document
        corpus must process disjoint documents and, combined, produce the
        same edges as a single resume=True call over the whole corpus."""
        cache_incremental, path_incremental = _temp_cache()
        cache_full, path_full = _temp_cache()
        try:
            self._seed_docs(cache_incremental, 6)
            self._seed_docs(cache_full, 6)

            r1 = build_citation_graph(cache=cache_incremental, resume=True, limit_docs=3)
            assert r1["ok"] is True
            assert r1["docs_processed"] == 3
            assert r1["last_rowid"] > 0

            progress_mid = get_citation_graph_build_progress(cache=cache_incremental)
            assert progress_mid["ok"] is True
            assert progress_mid["status"] == "running"
            assert progress_mid["docs_processed"] == 3

            r2 = build_citation_graph(cache=cache_incremental, resume=True, limit_docs=3)
            assert r2["ok"] is True
            # Cumulative total across both calls, not just this call's slice.
            assert r2["docs_processed"] == 6
            assert r2["remaining_docs"] == 0

            progress_final = get_citation_graph_build_progress(cache=cache_incremental)
            assert progress_final["status"] == "completed"
            assert progress_final["docs_processed"] == 6

            r_full = build_citation_graph(cache=cache_full, resume=True, limit_docs=None)
            assert r_full["ok"] is True
            assert r_full["docs_processed"] == 6

            assert _edges_from_table(cache_incremental) == _edges_from_table(cache_full)
        finally:
            cache_incremental.close()
            path_incremental.unlink(missing_ok=True)
            cache_full.close()
            path_full.unlink(missing_ok=True)

    def test_resume_does_not_reprocess_committed_documents(self):
        """Simulates a crash: a resumable call that only got partway (here,
        forced via limit_docs) must not redo work already committed to
        citation_edges when the next call resumes — total edges after two
        partial calls must equal edges from a single full call, never
        doubled."""
        cache, path = _temp_cache()
        try:
            self._seed_docs(cache, 6)
            build_citation_graph(cache=cache, resume=True, limit_docs=4)
            edges_after_first = cache.db.execute("SELECT COUNT(*) FROM citation_edges").fetchone()[0]

            build_citation_graph(cache=cache, resume=True, limit_docs=4)
            edges_after_second = cache.db.execute("SELECT COUNT(*) FROM citation_edges").fetchone()[0]

            cache_full, path_full = _temp_cache()
            try:
                self._seed_docs(cache_full, 6)
                build_citation_graph(cache=cache_full, resume=True, limit_docs=None)
                edges_full = cache_full.db.execute("SELECT COUNT(*) FROM citation_edges").fetchone()[0]
            finally:
                cache_full.close()
                path_full.unlink(missing_ok=True)

            assert edges_after_second == edges_full
            assert edges_after_second >= edges_after_first
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_progress_not_started_before_any_resumable_build(self):
        cache, path = _temp_cache()
        try:
            progress = get_citation_graph_build_progress(cache=cache)
            assert progress["ok"] is True
            assert progress["status"] == "not_started"
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_progress_callback_invoked(self):
        cache, path = _temp_cache()
        try:
            self._seed_docs(cache, 5)
            calls = []
            build_citation_graph(
                cache=cache, resume=True, limit_docs=None, commit_every=2,
                progress_callback=lambda p: calls.append(p),
            )
            assert len(calls) >= 1
            assert all(c["ok"] for c in calls)
        finally:
            cache.close()
            path.unlink(missing_ok=True)

    def test_resumable_build_bounded_memory_uses_cursor_not_full_fetch(self):
        """Documentation-as-test: the resumable path must select full_text
        via cursor iteration (M-51 idiom), not fetchall() of every row's
        full_text at once. Inspects the source rather than measuring RSS,
        which would be flaky."""
        import inspect
        from emsal_mcp import citation_graph
        src = inspect.getsource(citation_graph._build_citation_graph_resumable)
        assert "fetchall()" not in src
