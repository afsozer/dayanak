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
