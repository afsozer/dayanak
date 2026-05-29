"""Tests for cross-source deduplication and merge."""
from __future__ import annotations

import json

from emsal_mcp.cache import Cache
from emsal_mcp.dedup import (
    find_duplicates,
    get_dedup_cluster,
    get_dedup_stats,
    merge_cluster,
)
from emsal_mcp.models import ContentStatus, Document


def _make_doc(
    source: str,
    doc_id: str,
    court: str = "Yargitay",
    esas_no: str = "2023/123",
    karar_no: str = "2024/456",
    title: str = "Test Decision",
    content_status: ContentStatus = ContentStatus.METADATA_ONLY,
    full_text: str | None = None,
    markdown: str | None = None,
    source_url: str | None = None,
    retrieved_at: str | None = None,
) -> Document:
    """Helper to create a Document for testing."""
    doc = Document(
        source=source,
        document_id=doc_id,
        title=title,
        court=court,
        esas_no=esas_no,
        karar_no=karar_no,
        content_status=content_status,
        full_text=full_text,
        markdown=markdown,
        source_url=source_url,
    )
    if retrieved_at:
        doc.retrieved_at = retrieved_at
    return doc


class TestFindDuplicates:
    def test_two_docs_same_court_esas_karar_grouped(self, tmp_path):
        """Two docs with same court+esas+karar should be grouped."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", full_text="Some content here")
            doc2 = _make_doc("bedesten", "doc2", full_text="Same decision different source")
            cache.store_document(doc1)
            cache.store_document(doc2)

            result = find_duplicates(cache=cache)

            assert result["ok"] is True
            assert result["clusters_found"] == 1
            assert result["total_duplicates"] == 2
            assert len(result["clusters"]) == 1
            cluster = result["clusters"][0]
            assert len(cluster["members"]) == 2
            member_ids = {m["doc_id"] for m in cluster["members"]}
            assert "doc1" in member_ids
            assert "doc2" in member_ids
        finally:
            cache.close()

    def test_two_docs_different_court_not_grouped(self, tmp_path):
        """Two docs with different courts should NOT be grouped."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", court="Yargitay")
            doc2 = _make_doc("danistay", "doc2", court="Danistay")
            cache.store_document(doc1)
            cache.store_document(doc2)

            result = find_duplicates(cache=cache)

            assert result["ok"] is True
            assert result["clusters_found"] == 0
            assert result["total_duplicates"] == 0
        finally:
            cache.close()

    def test_matching_title_different_esas_no_not_grouped(self, tmp_path):
        """Two docs with matching title but different esas_no should NOT be grouped."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", title="Same Title", esas_no="2023/111")
            doc2 = _make_doc("bedesten", "doc2", title="Same Title", esas_no="2023/222")
            cache.store_document(doc1)
            cache.store_document(doc2)

            result = find_duplicates(cache=cache)

            assert result["ok"] is True
            assert result["clusters_found"] == 0
            assert result["total_duplicates"] == 0
        finally:
            cache.close()

    def test_empty_esas_no_skipped(self, tmp_path):
        """Documents with empty esas_no should not be deduped."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", esas_no="")
            doc2 = _make_doc("bedesten", "doc2", esas_no="")
            cache.store_document(doc1)
            cache.store_document(doc2)

            result = find_duplicates(cache=cache)

            assert result["ok"] is True
            assert result["clusters_found"] == 0
        finally:
            cache.close()

    def test_none_esas_no_skipped(self, tmp_path):
        """Documents with None esas_no should not be deduped."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", esas_no=None)
            doc2 = _make_doc("bedesten", "doc2", esas_no=None)
            cache.store_document(doc1)
            cache.store_document(doc2)

            result = find_duplicates(cache=cache)

            assert result["ok"] is True
            assert result["clusters_found"] == 0
        finally:
            cache.close()

    def test_dry_run_no_db_modifications(self, tmp_path):
        """Dry run should not modify the database."""
        from emsal_mcp.dedup import _ensure_dedup_tables

        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", full_text="Content A")
            doc2 = _make_doc("bedesten", "doc2", full_text="Content B")
            cache.store_document(doc1)
            cache.store_document(doc2)

            # Ensure tables exist so we can query them
            _ensure_dedup_tables(cache.db)

            # Check dedup tables are empty before
            before = cache.db.execute("SELECT COUNT(*) FROM dedup_clusters").fetchone()[0]
            assert before == 0

            result = find_duplicates(cache=cache, dry_run=True)

            assert result["ok"] is True
            assert result["dry_run"] is True
            assert result["clusters_found"] == 1

            # Check dedup tables are still empty after dry_run
            after = cache.db.execute("SELECT COUNT(*) FROM dedup_clusters").fetchone()[0]
            assert after == 0
        finally:
            cache.close()


class TestCanonicalSelection:
    def test_full_text_beats_html_markdown(self, tmp_path):
        """full_text should be selected as canonical over html_markdown."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc(
                "source_a", "doc1",
                content_status=ContentStatus.HTML_MARKDOWN,
                markdown="Some markdown content",
            )
            doc2 = _make_doc(
                "source_b", "doc2",
                content_status=ContentStatus.FULL_TEXT,
                full_text="Some full text content",
            )
            cache.store_document(doc1)
            cache.store_document(doc2)

            result = find_duplicates(cache=cache)

            canonical = result["clusters"][0]["canonical"]
            assert canonical["document_id"] == "doc2"
            assert canonical["source"] == "source_b"
        finally:
            cache.close()

    def test_longer_text_beats_shorter_same_status(self, tmp_path):
        """Longer text should be selected as canonical when content_status is same."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc(
                "source_a", "doc1",
                content_status=ContentStatus.FULL_TEXT,
                full_text="Short",
            )
            doc2 = _make_doc(
                "source_b", "doc2",
                content_status=ContentStatus.FULL_TEXT,
                full_text="This is a much longer document with more content",
            )
            cache.store_document(doc1)
            cache.store_document(doc2)

            result = find_duplicates(cache=cache)

            canonical = result["clusters"][0]["canonical"]
            assert canonical["document_id"] == "doc2"
            assert canonical["source"] == "source_b"
        finally:
            cache.close()

    def test_earlier_retrieved_at_beats_later_tiebreaker(self, tmp_path):
        """Earlier retrieved_at should be selected when content_status and text length are same."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc(
                "source_a", "doc1",
                content_status=ContentStatus.METADATA_ONLY,
                retrieved_at="2024-01-01T00:00:00+00:00",
            )
            doc2 = _make_doc(
                "source_b", "doc2",
                content_status=ContentStatus.METADATA_ONLY,
                retrieved_at="2024-06-01T00:00:00+00:00",
            )
            cache.store_document(doc1)
            cache.store_document(doc2)

            result = find_duplicates(cache=cache)

            canonical = result["clusters"][0]["canonical"]
            assert canonical["document_id"] == "doc1"
            assert canonical["source"] == "source_a"
        finally:
            cache.close()


class TestGetDedupCluster:
    def test_cluster_lookup_by_document_id(self, tmp_path):
        """Should find cluster by document_id."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1")
            doc2 = _make_doc("bedesten", "doc2")
            cache.store_document(doc1)
            cache.store_document(doc2)

            # Build clusters first
            find_duplicates(cache=cache)

            result = get_dedup_cluster("doc1", "yargitay", cache=cache)

            assert result["ok"] is True
            assert result["in_cluster"] is True
            assert result["cluster_id"] is not None
            assert result["canonical"] is not None
            assert len(result["all_members"]) == 2
        finally:
            cache.close()

    def test_document_not_in_cluster(self, tmp_path):
        """Document not in any cluster should return in_cluster=False."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", esas_no="999/999", karar_no="888/888")
            cache.store_document(doc1)

            result = get_dedup_cluster("doc1", "yargitay", cache=cache)

            assert result["ok"] is True
            assert result["in_cluster"] is False
            assert result["cluster_id"] is None
        finally:
            cache.close()


class TestDedupStats:
    def test_stats_computation(self, tmp_path):
        """Stats should correctly compute clusters and duplicates."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", full_text="Content A")
            doc2 = _make_doc("bedesten", "doc2", full_text="Content B")
            doc3 = _make_doc("yargitay", "doc3", esas_no="999/999", karar_no="888/888")
            cache.store_document(doc1)
            cache.store_document(doc2)
            cache.store_document(doc3)

            find_duplicates(cache=cache)

            result = get_dedup_stats(cache=cache)

            assert result["ok"] is True
            assert result["total_clusters"] == 1
            assert result["total_duplicate_docs"] == 2
        finally:
            cache.close()


class TestMergeCluster:
    def test_merge_enriches_canonical(self, tmp_path):
        """Merge should add alternative source URLs to canonical metadata."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", source_url="https://yargitay.gov.tr/doc1")
            doc2 = _make_doc("bedesten", "doc2", source_url="https://bedesten.gov.tr/doc2")
            cache.store_document(doc1)
            cache.store_document(doc2)

            # Build clusters
            find_result = find_duplicates(cache=cache)
            cluster_id = find_result["clusters"][0]["cluster_id"]

            result = merge_cluster(cluster_id, cache=cache)

            assert result["ok"] is True
            assert result["members_merged"] >= 1

            # Verify canonical metadata was updated
            doc_row = cache.db.execute(
                "SELECT metadata_json FROM documents_v2 WHERE document_id='doc1' AND source='yargitay'"
            ).fetchone()
            meta = json.loads(doc_row[0])
            assert "alternative_source_urls" in meta
            assert len(meta["alternative_source_urls"]) >= 1
        finally:
            cache.close()

    def test_merge_nonexistent_cluster(self, tmp_path):
        """Merge of nonexistent cluster should return error."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            result = merge_cluster("nonexistent-cluster-id", cache=cache)

            assert result["ok"] is False
            assert "errorCode" in result
        finally:
            cache.close()


class TestBuildIdempotence:
    def test_find_duplicates_idempotent(self, tmp_path):
        """Running find_duplicates twice should not create duplicate clusters."""
        cache = Cache(tmp_path / "test.sqlite3")
        try:
            doc1 = _make_doc("yargitay", "doc1", full_text="Content A")
            doc2 = _make_doc("bedesten", "doc2", full_text="Content B")
            cache.store_document(doc1)
            cache.store_document(doc2)

            result1 = find_duplicates(cache=cache)
            result2 = find_duplicates(cache=cache)

            assert result1["ok"] is True
            assert result2["ok"] is True
            # Both should find the same clusters (INSERT OR IGNORE keeps them unique)
            assert result1["clusters_found"] == result2["clusters_found"]
        finally:
            cache.close()


class TestImports:
    def test_cli_imports(self):
        """CLI module should import without errors."""
        from emsal_mcp.cli import app
        assert app is not None

    def test_mcp_imports(self):
        """Server module should import without errors."""
        from emsal_mcp.server import main
        assert callable(main)

    def test_dedup_module_imports(self):
        """Dedup module should import without errors."""
        from emsal_mcp.dedup import find_duplicates, get_dedup_cluster, get_dedup_stats, merge_cluster
        assert callable(find_duplicates)
        assert callable(get_dedup_cluster)
        assert callable(get_dedup_stats)
        assert callable(merge_cluster)
