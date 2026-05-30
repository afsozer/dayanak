"""Tests for cache v2 + local search (v0.3)."""
from __future__ import annotations

import hashlib
import json

from emsal_mcp.cache import Cache, CACHE_SCHEMA_VERSION
from emsal_mcp.models import CachedDocument, ContentStatus, Document


class TestCachedDocumentModel:
    """Test CachedDocument model construction and conversion."""

    def test_from_document(self):
        doc = Document(
            source="test", document_id="123", title="Test",
            full_text="Full content here", content_status=ContentStatus.FULL_TEXT,
            court="Yargıtay", chamber="1. Daire", decision_date="2024-01-01",
            esas_no="2024/1", karar_no="100",
        )
        cached = CachedDocument.from_document(doc)
        assert cached.document_id == "123"
        assert cached.source == "test"
        assert cached.title == "Test"
        assert cached.full_text == "Full content here"
        assert cached.quote_usable is True
        assert cached.draft_usable is True

    def test_to_document_roundtrip(self):
        doc = Document(
            source="test", document_id="456", title="Roundtrip",
            full_text="Test content", content_status=ContentStatus.FULL_TEXT,
            court="Danıştay", decision_date="2024-06-15",
        )
        cached = CachedDocument.from_document(doc)
        restored = cached.to_document()
        assert restored.document_id == "456"
        assert restored.source == "test"
        assert restored.full_text == "Test content"
        assert restored.court == "Danıştay"

    def test_citation_label(self):
        cached = CachedDocument(
            document_id="1", source="test", title="T",
            court="Yargıtay", chamber="2. Daire",
            decision_date="2024-03-01", esas_no="2024/5", karar_no="200",
        )
        label = cached.citation_label()
        assert "Yargıtay" in label
        assert "2024/5" in label
        assert "200" in label

    def test_text_property(self):
        cached = CachedDocument(
            document_id="1", source="test", full_text="ft text",
        )
        assert cached.text == "ft text"
        cached2 = CachedDocument(
            document_id="2", source="test", markdown="md text",
        )
        assert cached2.text == "md text"

    def test_defaults(self):
        cached = CachedDocument(document_id="1", source="test")
        assert cached.content_status == ContentStatus.METADATA_ONLY
        assert cached.quote_usable is False
        assert cached.draft_usable is False
        assert cached.access_count == 0
        assert cached.title is None


class TestCacheV2Schema:
    """Test that v2 schema creates correctly."""

    def test_creates_documents_v2_table(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        tables = [row[0] for row in cache.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "documents_v2" in tables
        assert "documents" in tables  # legacy preserved
        cache.close()

    def test_v2_indexes_created(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        indexes = [row[0] for row in cache.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='documents_v2'"
        ).fetchall()]
        assert "idx_dv2_source" in indexes
        assert "idx_dv2_court" in indexes
        assert "idx_dv2_decision_date" in indexes
        cache.close()


class TestCacheV2DocumentStore:
    """Test document storage in v2 table."""

    def test_store_and_retrieve_document(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        text = "Test document content for v2"
        expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc = Document(
            source="test", document_id="123", title="Test",
            full_text=text, content_status=ContentStatus.FULL_TEXT,
            content_hash=expected_hash,
            court="Yargıtay", chamber="1. Daire",
            decision_date="2024-01-01", esas_no="2024/1", karar_no="100",
        )
        cache.store_document(doc)
        # Verify v2 table - first read returns access_count=0 (increment happens after)
        cached = cache.get_cached_document("123", "test")
        assert cached is not None
        assert cached.document_id == "123"
        assert cached.full_text == text
        assert cached.content_hash == expected_hash
        assert cached.court == "Yargıtay"
        # Second read: access_count was incremented to 1 after first get
        cached2 = cache.get_cached_document("123", "test")
        assert cached2.access_count == 1
        cache.close()

    def test_store_document_updates_access_count(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="text", content_status=ContentStatus.FULL_TEXT,
        )
        cache.store_document(doc)
        # get_cached_document increments access_count after reading
        cache.get_cached_document("1", "test")  # reads 0, increments to 1
        cache.get_cached_document("1", "test")  # reads 1, increments to 2
        cached = cache.get_cached_document("1", "test")  # reads 2, increments to 3
        assert cached.access_count == 2  # value at time of read
        cache.close()

    def test_get_document_hash_verification(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        text = "Content to hash"
        expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc = Document(
            source="test", document_id="123", title="Test",
            full_text=text, content_status=ContentStatus.FULL_TEXT,
            content_hash=expected_hash,
        )
        cache.store_document(doc)
        # Correct hash
        retrieved = cache.get_document("123", "test")
        assert retrieved is not None
        assert retrieved.content_hash == expected_hash
        cache.close()

    def test_get_document_hash_mismatch_returns_none(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(
            source="test", document_id="123", title="Test",
            full_text="Original content", content_status=ContentStatus.FULL_TEXT,
            content_hash="wrong_hash_value",
        )
        cache.store_document(doc)
        retrieved = cache.get_document("123", "test")
        assert retrieved is None
        cache.close()

    def test_get_cached_document_not_found(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        assert cache.get_cached_document("nonexistent", "test") is None
        cache.close()


class TestCacheV2LocalSearch:
    """Test local search over cached documents."""

    def _populate_cache(self, cache: Cache) -> None:
        docs = [
            Document(source="yargitay", document_id="y1", title="Yargıtay Kararı 1",
                     full_text="Ceza hukukunda mahkumiyet kararı", court="Yargıtay",
                     chamber="1. Daire", decision_date="2024-01-15", esas_no="2024/1",
                     karar_no="100", content_status=ContentStatus.FULL_TEXT),
            Document(source="yargitay", document_id="y2", title="Yargıtay Kararı 2",
                     full_text="Hukuk hukukunda tazminat davası", court="Yargıtay",
                     chamber="2. Daire", decision_date="2024-03-20", esas_no="2024/5",
                     karar_no="200", content_status=ContentStatus.FULL_TEXT),
            Document(source="danistay", document_id="d1", title="Danıştay Kararı",
                     full_text="İdari dava sonucu iptal", court="Danıştay",
                     chamber="İdari Dava Daireleri", decision_date="2024-06-01",
                     esas_no="2024/10", karar_no="300",
                     content_status=ContentStatus.HTML_MARKDOWN),
            Document(source="aym", document_id="a1", title="AYM Kararı",
                     full_text="Anayasa aykırılık tespiti", court="Anayasa Mahkemesi",
                     decision_date="2024-09-10",
                     content_status=ContentStatus.HTML_MARKDOWN),
            # Non-usable documents (metadata only / no text)
            Document(source="uyusmazlik", document_id="u1", title="Uyuşmazlık PDF",
                     content_status=ContentStatus.PDF_LINK_ONLY, source_url="https://example.com"),
            Document(source="sayistay", document_id="s1", title="Sayıştay Metadata",
                     content_status=ContentStatus.METADATA_ONLY),
        ]
        for doc in docs:
            cache.store_document(doc)

    def test_search_by_query(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local("tazminat")
        assert len(results) == 1
        assert results[0]["document_id"] == "y2"
        assert "tazminat" in results[0]["snippet"].lower()
        cache.close()

    def test_search_by_source_filter(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(source="yargitay")
        assert len(results) == 2
        assert all(r["source"] == "yargitay" for r in results)
        cache.close()

    def test_search_by_court_filter(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(court="Danıştay")
        assert len(results) == 1
        assert results[0]["source"] == "danistay"
        cache.close()

    def test_search_by_chamber_filter(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(chamber="1. Daire")
        assert len(results) == 1
        assert results[0]["esas_no"] == "2024/1"
        cache.close()

    def test_search_by_date_filter(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(date="2024-06")
        assert len(results) == 1
        assert results[0]["document_id"] == "d1"
        cache.close()

    def test_search_by_esas_no(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(esas_no="2024/10")
        assert len(results) == 1
        assert results[0]["karar_no"] == "300"
        cache.close()

    def test_search_by_karar_no(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(karar_no="200")
        assert len(results) == 1
        assert results[0]["esas_no"] == "2024/5"
        cache.close()

    def test_search_by_document_id(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(document_id="y1")
        assert len(results) == 1
        assert results[0]["title"] == "Yargıtay Kararı 1"
        cache.close()

    def test_search_by_content_status(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(content_status="html_markdown")
        assert len(results) == 2
        cache.close()

    def test_search_by_quote_usable(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        # FULL_TEXT and HTML_MARKDOWN with text are quote_usable (4 docs)
        results = cache.search_local(quote_usable=True)
        assert len(results) == 4
        cache.close()

    def test_search_by_draft_usable(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        # Same as quote_usable (4 docs)
        results = cache.search_local(draft_usable=True)
        assert len(results) == 4
        cache.close()

    def test_search_sort_decision_date_desc(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(sort="decision_date_desc")
        dates = [r["decision_date"] for r in results if r["decision_date"]]
        assert dates == sorted(dates, reverse=True)
        cache.close()

    def test_search_sort_decision_date_asc(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(sort="decision_date_asc")
        dates = [r["decision_date"] for r in results if r["decision_date"]]
        assert dates == sorted(dates)
        cache.close()

    def test_search_sort_fetched_at_desc(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(sort="fetched_at_desc")
        assert len(results) == 6
        cache.close()

    def test_search_limit(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(limit=2)
        assert len(results) == 2
        cache.close()

    def test_search_no_results(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local("nonexistent_xyz")
        assert len(results) == 0
        cache.close()

    def test_search_combined_filters(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local(source="yargitay", court="Yargıtay", chamber="2. Daire")
        assert len(results) == 1
        assert results[0]["document_id"] == "y2"
        cache.close()

    def test_search_snippet_generation(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local("tazminat", snippet_length=50)
        assert len(results) == 1
        snippet = results[0]["snippet"]
        assert "tazminat" in snippet.lower()
        cache.close()

    def test_search_empty_query_returns_all(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate_cache(cache)
        results = cache.search_local("")
        assert len(results) == 6
        cache.close()


class TestCacheMaintenance:
    """Test cache maintenance operations."""

    def test_cache_stats(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(source="test", document_id="1", title="T",
                       full_text="text", content_status=ContentStatus.FULL_TEXT)
        cache.store_document(doc)
        stats = cache.cache_stats()
        assert stats["schema_version"] == 4
        assert stats["documents_v2"] == 1
        assert stats["documents_legacy"] == 1
        assert stats["db_path"] == str(tmp_path / "test.sqlite3")
        assert stats["db_size_bytes"] > 0
        cache.close()

    def test_list_cached_documents(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        for i in range(5):
            doc = Document(source=f"src{i}", document_id=str(i), title=f"Doc {i}",
                           full_text="text", content_status=ContentStatus.FULL_TEXT)
            cache.store_document(doc)
        docs = cache.list_cached_documents()
        assert len(docs) == 5
        docs_filtered = cache.list_cached_documents(source="src2")
        assert len(docs_filtered) == 1
        cache.close()

    def test_delete_cached_document(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(source="test", document_id="1", title="T",
                       full_text="text", content_status=ContentStatus.FULL_TEXT)
        cache.store_document(doc)
        deleted = cache.delete_cached_document("1", "test")
        assert deleted is True
        assert cache.get_cached_document("1", "test") is None
        cache.close()

    def test_delete_nonexistent_returns_false(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        deleted = cache.delete_cached_document("nope", "test")
        assert deleted is False
        cache.close()

    def test_prune_search_cache(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        cache.set("search:test:q:10:1", [{"result": "data"}])
        # Insert an entry with an old timestamp directly
        cache.db.execute(
            "INSERT OR REPLACE INTO cache(key, value, created_at) VALUES(?, ?, datetime('now', '-60 days'))",
            ("search:old:q:10:1", json.dumps([{"result": "old"}])),
        )
        cache.db.commit()
        count = cache.prune_search_cache(max_age_days=30)
        assert count >= 1
        cache.close()

    def test_backup_cache(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(source="test", document_id="1", title="T",
                       full_text="text", content_status=ContentStatus.FULL_TEXT)
        cache.store_document(doc)
        backup = cache.backup_cache(tmp_path / "backup.sqlite3")
        assert backup.exists()
        assert backup.stat().st_size > 0
        cache.close()

    def test_export_json(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(source="test", document_id="1", title="T",
                       full_text="text", content_status=ContentStatus.FULL_TEXT)
        cache.store_document(doc)
        result = cache.export_json(tmp_path / "export.json")
        export_file = tmp_path / "export.json"
        assert export_file.exists()
        assert result["document_count"] == 1
        assert result["sha256"]
        assert result["schema_version"] == CACHE_SCHEMA_VERSION
        data = json.loads(export_file.read_text(encoding="utf-8"))
        assert data["schemaVersion"] == CACHE_SCHEMA_VERSION
        assert "exportedAt" in data
        assert data["documentCount"] == 1
        assert data["includeMarkdown"] is True
        assert len(data["documents"]) == 1
        assert data["documents"][0]["document_id"] == "1"
        assert "sha256" in data
        cache.close()

    def test_import_json(self, tmp_path):
        # First cache: export
        cache1 = Cache(tmp_path / "test1.sqlite3")
        doc = Document(source="test", document_id="1", title="Imported",
                       full_text="import content", content_status=ContentStatus.FULL_TEXT)
        cache1.store_document(doc)
        cache1.export_json(tmp_path / "export.json")
        cache1.close()

        # Second cache: import
        cache2 = Cache(tmp_path / "test2.sqlite3")
        result = cache2.import_json(tmp_path / "export.json")
        assert result["imported"] == 1
        assert result["skipped"] == 0
        assert result["errors"] == 0
        cached = cache2.get_cached_document("1", "test")
        assert cached is not None
        assert cached.title == "Imported"
        cache2.close()

    def test_import_json_legacy_list_format(self, tmp_path):
        """Test backward-compatible import from old list-only format."""
        legacy_data = [
            {
                "document_id": "legacy1",
                "source": "test",
                "title": "Legacy Doc",
                "full_text": "legacy content",
                "content_status": "full_text",
            }
        ]
        export_file = tmp_path / "legacy_export.json"
        export_file.write_text(json.dumps(legacy_data), encoding="utf-8")

        cache = Cache(tmp_path / "test.sqlite3")
        result = cache.import_json(export_file)
        assert result["imported"] == 1
        assert result["skipped"] == 0
        cached = cache.get_cached_document("legacy1", "test")
        assert cached is not None
        assert cached.title == "Legacy Doc"
        cache.close()

    def test_import_json_hash_mismatch_skips(self, tmp_path):
        """Test that import skips documents with mismatched content_hash."""
        data = [
            {
                "document_id": "bad_hash",
                "source": "test",
                "title": "Bad Hash Doc",
                "full_text": "actual content",
                "content_hash": "definitely_wrong_hash",
                "content_status": "full_text",
            },
            {
                "document_id": "good_doc",
                "source": "test",
                "title": "Good Doc",
                "full_text": "good content",
                "content_status": "full_text",
            },
        ]
        export_file = tmp_path / "hash_export.json"
        export_file.write_text(json.dumps(data), encoding="utf-8")

        cache = Cache(tmp_path / "test.sqlite3")
        result = cache.import_json(export_file)
        assert result["imported"] == 1
        assert result["skipped"] == 1
        assert result["errors"] == 0
        assert cache.get_cached_document("bad_hash", "test") is None
        assert cache.get_cached_document("good_doc", "test") is not None
        cache.close()

    def test_delete_cached_document_logs_history(self, tmp_path):
        """Test that delete_cached_document logs to history audit."""
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(source="test", document_id="1", title="T",
                       full_text="text", content_status=ContentStatus.FULL_TEXT)
        cache.store_document(doc)
        cache.delete_cached_document("1", "test")
        history = cache.history(limit=10)
        delete_entries = [h for h in history if h["action"] == "delete_cached_document"]
        assert len(delete_entries) == 1
        assert delete_entries[0]["payload"]["document_id"] == "1"
        cache.close()

    def test_prune_search_cache_logs_history(self, tmp_path):
        """Test that prune_search_cache logs to history audit."""
        cache = Cache(tmp_path / "test.sqlite3")
        cache.set("search:old:q:10:1", [{"result": "old"}])
        cache.db.execute(
            "INSERT OR REPLACE INTO cache(key, value, created_at) VALUES(?, ?, datetime('now', '-60 days'))",
            ("search:old2:q:10:1", json.dumps([{"result": "old2"}])),
        )
        cache.db.commit()
        cache.prune_search_cache(max_age_days=30)
        history = cache.history(limit=10)
        prune_entries = [h for h in history if h["action"] == "prune_search_cache"]
        assert len(prune_entries) == 1
        assert prune_entries[0]["payload"]["pruned_count"] >= 1
        cache.close()

    def test_prune_search_cache_only_affects_search_cache(self, tmp_path):
        """Test that prune only removes search:* keys, not other cache entries."""
        cache = Cache(tmp_path / "test.sqlite3")
        # Insert a non-search key with old timestamp
        cache.db.execute(
            "INSERT OR REPLACE INTO cache(key, value, created_at) VALUES(?, ?, datetime('now', '-60 days'))",
            ("doc:old:thing", json.dumps({"data": "old"})),
        )
        cache.db.commit()
        cache.prune_search_cache(max_age_days=30)
        # Non-search key should survive
        assert cache.get("doc:old:thing") == {"data": "old"}
        cache.close()

    def test_backup_cache_with_metadata(self, tmp_path):
        """Test backup_cache_with_metadata returns sha256 and stats."""
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(source="test", document_id="1", title="T",
                       full_text="text", content_status=ContentStatus.FULL_TEXT)
        cache.store_document(doc)
        result = cache.backup_cache_with_metadata(tmp_path / "backup.sqlite3")
        assert "backup_path" in result
        assert "sha256" in result
        assert len(result["sha256"]) == 64  # sha256 hex length
        assert result["schema_version"] == CACHE_SCHEMA_VERSION
        assert result["documents_v2"] == 1
        assert result["db_size_bytes"] > 0
        # Verify the backup file exists and hash matches
        import hashlib as hl
        backup_file = tmp_path / "backup.sqlite3"
        assert backup_file.exists()
        actual_hash = hl.sha256(backup_file.read_bytes()).hexdigest()
        assert actual_hash == result["sha256"]
        cache.close()

    def test_schema_version_idempotent(self, tmp_path):
        """Test that schema_version is set idempotently across reopens."""
        cache1 = Cache(tmp_path / "test.sqlite3")
        assert cache1.schema_version == CACHE_SCHEMA_VERSION
        cache1.close()
        # Reopen same DB
        cache2 = Cache(tmp_path / "test.sqlite3")
        assert cache2.schema_version == CACHE_SCHEMA_VERSION
        cache2.close()
