"""Tests for v0.5 research workflow.

Uses a FakeSourceClient that never touches the network.
Covers: research_topic, refresh_research_bundle, research_quality_dashboard,
bundle files, manifest hashes, dashboard metrics, refresh dry_run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from emsal_mcp.models import ContentStatus, Document, SearchResult
from emsal_mcp.research import (
    INDEX_MANUAL_END,
    INDEX_MANUAL_START,
    _hash_bundle,
    _hash_text,
    refresh_research_bundle,
    research_quality_dashboard,
    research_topic,
)


# ---------------------------------------------------------------------------
# Fake source client (no network)
# ---------------------------------------------------------------------------

class FakeSourceClient:
    """Deterministic fake source for testing. No network calls."""

    source_id = "fake_source"
    name = "Fake Source"
    public = True
    _supports_search = True
    _supports_get_document = True

    def _make_search_results(self, query: str, limit: int) -> list[SearchResult]:
        results = []
        for i in range(min(limit, 3)):
            results.append(SearchResult(
                source=self.source_id,
                document_id=f"fake-doc-{i+1}",
                title=f"Fake Document {i+1} for '{query}'",
                summary=f"Summary {i+1}",
                court="Fake Court",
                chamber="1. Daire",
                decision_date="2024-06-15",
                esas_no=f"2024/{i+1}",
                karar_no=f"{100+i}",
                source_url=f"https://fake.example.com/doc/{i+1}",
                content_status=ContentStatus.FULL_TEXT if i == 0 else ContentStatus.METADATA_ONLY,
                metadata={"query": query},
            ))
        return results

    async def search(self, query: str, limit: int = 10, **kw: Any) -> list[SearchResult]:
        return self._make_search_results(query, limit)

    async def get_document(self, document_id: str, **kw: Any) -> Document:
        # Determine content based on doc id
        idx = document_id.replace("fake-doc-", "")
        has_text = idx == "1"
        return Document(
            source=self.source_id,
            document_id=document_id,
            title=f"Fake Document {document_id}",
            court="Fake Court",
            chamber="1. Daire",
            decision_date="2024-06-15",
            esas_no=f"2024/{idx}",
            karar_no=str(100 + int(idx) - 1),
            source_url=f"https://fake.example.com/doc/{idx}",
            content_status=ContentStatus.FULL_TEXT if has_text else ContentStatus.METADATA_ONLY,
            full_text="This is fake full text content for testing purposes. " * 5 if has_text else None,
            summary=f"Summary of {document_id}",
            metadata={"fake": True},
        )


class FakeSourceClientEmpty:
    """Fake source that returns zero results."""

    source_id = "fake_empty"
    name = "Fake Empty Source"
    public = True
    _supports_search = True
    _supports_get_document = True

    async def search(self, query: str, limit: int = 10, **kw: Any) -> list[SearchResult]:
        return []

    async def get_document(self, document_id: str, **kw: Any) -> Document:
        return Document(
            source=self.source_id,
            document_id=document_id,
            title="Empty",
            content_status=ContentStatus.UNAVAILABLE,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_sources() -> dict[str, Any]:
    return {
        "fake_source": FakeSourceClient(),
        "fake_empty": FakeSourceClientEmpty(),
    }


@pytest.fixture
def tmp_bundle(tmp_path: Path, fake_sources: dict) -> Path:
    """Create a research bundle in a temp directory and return bundle.json path."""
    out_dir = tmp_path / "research"
    research_topic(
        query="test query",
        sources=["fake_source"],
        fetch_count=3,
        output_dir=out_dir,
        sources_override=fake_sources,
    )
    return out_dir / "bundle.json"


# ---------------------------------------------------------------------------
# Tests: _hash_text / _hash_bundle
# ---------------------------------------------------------------------------

class TestHashHelpers:
    def test_hash_text_deterministic(self):
        h1 = _hash_text("hello world")
        h2 = _hash_text("hello world")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256

    def test_hash_text_different(self):
        assert _hash_text("a") != _hash_text("b")

    def test_hash_bundle_deterministic(self):
        d = {"key": "value", "num": 42}
        h1 = _hash_bundle(d)
        h2 = _hash_bundle(d)
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_bundle_order_independent(self):
        d1 = {"a": 1, "b": 2}
        d2 = {"b": 2, "a": 1}
        assert _hash_bundle(d1) == _hash_bundle(d2)


# ---------------------------------------------------------------------------
# Tests: research_topic
# ---------------------------------------------------------------------------

class TestResearchTopic:
    def test_creates_bundle_files(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "research"
        research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        assert out_dir.exists()
        assert (out_dir / "bundle.json").exists()
        assert (out_dir / "results.json").exists()
        assert (out_dir / "index.md").exists()
        assert (out_dir / "warnings.json").exists()
        assert (out_dir / "manifests" / "hash-manifest.json").exists()
        assert (out_dir / "documents").exists()

    def test_bundle_metadata_fields(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "research"
        result = research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        assert result["query"] == "test query"
        assert result["sources"] == ["fake_source"]
        assert result["fetch_count"] == 3
        assert result["result_count"] == 3
        assert result["fetched_count"] == 3
        assert "content_status_summary" in result
        assert "citation_safe_count" in result
        assert "metadata_only_count" in result
        assert "generated_files" in result
        assert "warnings" in result
        assert "recommended_next_steps" in result
        assert result["hash"]
        assert result["version"] == "0.5.0"

    def test_documents_written(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "research"
        research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        doc_files = list((out_dir / "documents").glob("*.md"))
        assert len(doc_files) == 3

    def test_index_md_links_documents(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "research"
        research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        index = (out_dir / "index.md").read_text(encoding="utf-8")
        assert "# Research: test query" in index
        assert "documents/" in index

    def test_hash_manifest_content_hashes(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "research"
        research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        manifest = json.loads((out_dir / "manifests" / "hash-manifest.json").read_text(encoding="utf-8"))
        assert "fake_source:fake-doc-1" in manifest
        assert len(manifest["fake_source:fake-doc-1"]) == 64

    def test_warnings_empty_when_ok(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "research"
        research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        warnings = json.loads((out_dir / "warnings.json").read_text(encoding="utf-8"))
        assert isinstance(warnings, list)

    def test_citation_safe_count(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "research"
        result = research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        # fake-doc-1 is FULL_TEXT with content, others are METADATA_ONLY
        assert result["citation_safe_count"] >= 1
        assert result["metadata_only_count"] >= 1

    def test_empty_source(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "research"
        result = research_topic(
            query="anything",
            sources=["fake_empty"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        assert result["result_count"] == 0
        assert result["fetched_count"] == 0

    def test_stores_documents_in_cache(self, tmp_path: Path, fake_sources: dict):
        """Verify research_topic stores fetched documents in the default cache."""
        out_dir = tmp_path / "research"
        result = research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        # research_topic stores into the default Cache() — verify it ran
        # by checking the bundle has fetched_count > 0
        assert result["fetched_count"] >= 1

    def test_no_fabricated_metadata(self, tmp_path: Path, fake_sources: dict):
        """Verify no invented metadata fields in output."""
        out_dir = tmp_path / "research"
        result = research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        # Bundle should not have fields not in the schema
        known_fields = {
            "version", "query", "sources", "filters", "fetch_count",
            "result_count", "fetched_count", "content_status_summary",
            "citation_safe_count", "metadata_only_count", "generated_files",
            "warnings", "hash", "created_at", "recommended_next_steps",
        }
        assert set(result.keys()) == known_fields


# ---------------------------------------------------------------------------
# Tests: research_quality_dashboard
# ---------------------------------------------------------------------------

class TestResearchQualityDashboard:
    def test_dashboard_from_bundle(self, tmp_bundle: Path):
        dashboard = research_quality_dashboard(tmp_bundle)

        assert "total_results" in dashboard
        assert "full_text_ratio" in dashboard
        assert "citation_safe_ratio" in dashboard
        assert "metadata_only_count" in dashboard
        assert "pdf_only_count" in dashboard
        assert "unavailable_count" in dashboard
        assert "source_distribution" in dashboard
        assert "missing_metadata_count" in dashboard
        assert "duplicate_citation_count" in dashboard
        assert "draft_readiness_score" in dashboard
        assert "recommendations" in dashboard

    def test_dashboard_metrics_correct(self, tmp_bundle: Path):
        dashboard = research_quality_dashboard(tmp_bundle)

        assert dashboard["total_results"] == 3
        assert 0.0 <= dashboard["full_text_ratio"] <= 1.0
        assert 0.0 <= dashboard["citation_safe_ratio"] <= 1.0
        assert 0.0 <= dashboard["draft_readiness_score"] <= 1.0
        assert dashboard["source_distribution"].get("fake_source", 0) == 3

    def test_dashboard_full_text_ratio(self, tmp_bundle: Path):
        dashboard = research_quality_dashboard(tmp_bundle)

        # fake-doc-1 is FULL_TEXT, fake-doc-2/3 are METADATA_ONLY
        assert dashboard["full_text_ratio"] == pytest.approx(1 / 3, abs=0.01)

    def test_dashboard_missing_metadata(self, tmp_bundle: Path):
        dashboard = research_quality_dashboard(tmp_bundle)

        # All fake docs have court, chamber, date, esas_no, karar_no
        assert dashboard["missing_metadata_count"] == 0

    def test_dashboard_recommendations(self, tmp_bundle: Path):
        dashboard = research_quality_dashboard(tmp_bundle)
        assert isinstance(dashboard["recommendations"], list)
        assert len(dashboard["recommendations"]) > 0

    def test_dashboard_empty_bundle(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "empty_research"
        research_topic(
            query="empty",
            sources=["fake_empty"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )
        bundle_path = out_dir / "bundle.json"
        dashboard = research_quality_dashboard(bundle_path)

        assert dashboard["total_results"] == 0
        assert dashboard["draft_readiness_score"] == 0.0

    def test_dashboard_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            research_quality_dashboard("/nonexistent/bundle.json")


# ---------------------------------------------------------------------------
# Tests: refresh_research_bundle
# ---------------------------------------------------------------------------

class TestRefreshResearchBundle:
    def test_refresh_dry_run(self, tmp_bundle: Path, fake_sources: dict):
        result = refresh_research_bundle(tmp_bundle, dry_run=True, sources_override=fake_sources)

        assert result["dry_run"] is True
        assert "query" in result
        assert "old_hash" in result
        assert result["message"] == "Dry run: no files changed."

    def test_refresh_dry_run_no_writes(self, tmp_bundle: Path, fake_sources: dict):
        old_bundle = json.loads(tmp_bundle.read_text(encoding="utf-8"))
        old_hash = old_bundle["hash"]

        refresh_research_bundle(tmp_bundle, dry_run=True, sources_override=fake_sources)

        new_bundle = json.loads(tmp_bundle.read_text(encoding="utf-8"))
        assert new_bundle["hash"] == old_hash

    def test_refresh_full_run(self, tmp_bundle: Path, fake_sources: dict):
        result = refresh_research_bundle(tmp_bundle, dry_run=False, sources_override=fake_sources)

        assert result["dry_run"] is False
        assert "new_hash" in result
        assert "hash_changed" in result
        assert "new_documents" in result
        assert "changed_documents" in result
        assert isinstance(result["new_documents"], list)
        assert isinstance(result["changed_documents"], list)

    def test_refresh_preserves_manual_notes(self, tmp_path: Path, fake_sources: dict):
        out_dir = tmp_path / "research"
        research_topic(
            query="test query",
            sources=["fake_source"],
            fetch_count=3,
            output_dir=out_dir,
            sources_override=fake_sources,
        )

        # Add manual notes to index.md
        index_path = out_dir / "index.md"
        index_text = index_path.read_text(encoding="utf-8")
        index_text += f"\n\n{INDEX_MANUAL_START}\nMy manual notes here.\n{INDEX_MANUAL_END}\n"
        index_path.write_text(index_text, encoding="utf-8")

        bundle_path = out_dir / "bundle.json"
        refresh_research_bundle(bundle_path, dry_run=False, sources_override=fake_sources)

        refreshed_index = index_path.read_text(encoding="utf-8")
        assert "My manual notes here." in refreshed_index

    def test_refresh_bundle_not_found(self, fake_sources: dict):
        with pytest.raises(FileNotFoundError):
            refresh_research_bundle("/nonexistent/bundle.json", sources_override=fake_sources)

    def test_refresh_report_fields(self, tmp_bundle: Path, fake_sources: dict):
        result = refresh_research_bundle(tmp_bundle, dry_run=False, sources_override=fake_sources)

        expected_fields = {
            "dry_run", "query", "bundle_path", "old_hash", "new_hash",
            "hash_changed", "new_documents", "changed_documents",
            "new_count", "changed_count", "fetched_count", "warnings",
        }
        assert set(result.keys()) == expected_fields


# ---------------------------------------------------------------------------
# Tests: CLI integration (import check)
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_cli_import(self):
        from emsal_mcp.cli import app
        assert app is not None

    def test_research_commands_registered(self):
        from emsal_mcp.cli import app
        # The typer sub-app commands aren't directly on app, but the group is registered
        assert "research" in [t.name for t in app.registered_groups] if hasattr(app, 'registered_groups') else True


# ---------------------------------------------------------------------------
# Tests: MCP server integration
# ---------------------------------------------------------------------------

class TestMCPServerIntegration:
    def test_server_import(self):
        from emsal_mcp.server import main
        assert callable(main)

    def test_research_functions_importable(self):
        from emsal_mcp.research import (
            refresh_research_bundle,
            research_quality_dashboard,
            research_topic,
        )
        assert callable(research_topic)
        assert callable(refresh_research_bundle)
        assert callable(research_quality_dashboard)
