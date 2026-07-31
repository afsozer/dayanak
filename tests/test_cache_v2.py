"""Tests for cache v2 + local search (v0.3)."""
from __future__ import annotations

import hashlib
import json

import pytest

from emsal_mcp.cache import Cache, CACHE_SCHEMA_VERSION

pytestmark = [pytest.mark.integration]
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
        assert stats["documents_legacy"] == 0  # legacy table no longer written
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


class TestFts5MatchExpr:
    """The MATCH builder turns free text into a safe, AND-ed FTS5 expression."""

    def test_terms_are_anded(self):
        from emsal_mcp.cache import _fts5_match_expr
        assert _fts5_match_expr("tahliye taahhüdü geçerlilik") == (
            '"tahliye" AND "taahhüdü" AND "geçerlilik"'
        )

    def test_quoted_span_becomes_a_phrase(self):
        from emsal_mcp.cache import _fts5_match_expr
        assert _fts5_match_expr('"tahliye taahhüdü" geçerlilik') == (
            '"tahliye taahhüdü" AND "geçerlilik"'
        )

    def test_operators_in_user_text_are_neutralised(self):
        """A stray AND/OR/NOT/* must be data, not syntax — otherwise the query
        shape changes or FTS5 raises."""
        from emsal_mcp.cache import _fts5_match_expr
        assert _fts5_match_expr("tazminat AND OR NOT *") == (
            '"tazminat" AND "AND" AND "OR" AND "NOT"'
        )

    def test_punctuation_only_returns_none(self):
        from emsal_mcp.cache import _fts5_match_expr
        assert _fts5_match_expr("!!! ???") is None
        assert _fts5_match_expr("") is None
        assert _fts5_match_expr("   ") is None


class TestSearchLocalUsesFts5:
    """Regression: search_local used to run the MATCH, discard the rowids, and
    let `full_text LIKE '%<whole query>%'` decide.  Multi-word queries could
    then only match a contiguous substring, so a normal keyword query returned
    nothing after a full-table scan."""

    def _populate(self, cache):
        docs = [
            Document(
                source="bedesten", document_id="b1", title="Yargıtay Kararı",
                full_text=(
                    "Davacı tahliye talebinde bulunmuştur. Kiracının verdiği "
                    "taahhüdü geçerli sayılmıştır. Taahhüdün geçerlilik "
                    "şartları tartışılmıştır."
                ),
                court="Yargıtay", content_status=ContentStatus.FULL_TEXT,
            ),
            Document(
                source="bedesten", document_id="b2", title="Danıştay Kararı",
                full_text="İmar planına karşı açılan iptal davası reddedilmiştir.",
                court="Danıştay", content_status=ContentStatus.FULL_TEXT,
            ),
        ]
        for doc in docs:
            cache.store_document(doc)
        # The FTS5 table is created by the semantic layer, not by Cache itself.
        from emsal_mcp.semantic import _ensure_fts5
        _ensure_fts5(cache.db)

    def test_scattered_terms_match(self, tmp_path):
        """The terms appear in the document but never adjacent — exactly the
        case the old LIKE path could not find."""
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate(cache)
        assert cache._has_fts5()
        results = cache.search_local("tahliye taahhüdü geçerlilik şartları")
        assert [r["document_id"] for r in results] == ["b1"]
        cache.close()

    def test_contiguous_like_would_have_failed(self, tmp_path):
        """Pin the reason: the whole query is not a substring of the text."""
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate(cache)
        row = cache.db.execute(
            "SELECT COUNT(*) FROM documents_v2 WHERE full_text LIKE ?",
            ("%tahliye taahhüdü geçerlilik şartları%",),
        ).fetchone()[0]
        assert row == 0, "if this matches, the regression test proves nothing"
        assert cache.search_local("tahliye taahhüdü geçerlilik şartları")
        cache.close()

    def test_missing_term_excludes_document(self, tmp_path):
        """AND semantics: every term must be present."""
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate(cache)
        assert cache.search_local("tahliye kamulaştırma") == []
        cache.close()

    def test_diacritics_folded_by_the_index(self, tmp_path):
        """tokenize='unicode61 remove_diacritics 2' — unlike Bedesten, the
        local index matches diacritic-stripped input."""
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate(cache)
        assert [r["document_id"] for r in cache.search_local("taahhudu gecerlilik")] == ["b1"]
        cache.close()

    def test_metadata_filters_still_apply_on_the_fts_path(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._populate(cache)
        assert cache.search_local("tahliye", court="Danıştay") == []
        assert len(cache.search_local("tahliye", court="Yargıtay")) == 1
        cache.close()

    def test_falls_back_to_like_without_an_index(self, tmp_path):
        """No FTS5 table — metadata-only and substring search must still work."""
        cache = Cache(tmp_path / "test.sqlite3")
        docs = [Document(
            source="bedesten", document_id="b1", title="Yargıtay Kararı",
            full_text="Kıdem tazminatı hesabı", court="Yargıtay",
            content_status=ContentStatus.FULL_TEXT,
        )]
        for doc in docs:
            cache.store_document(doc)
        assert not cache._has_fts5()
        assert len(cache.search_local("Kıdem tazminatı")) == 1
        assert len(cache.search_local(query="", court="Yargıtay")) == 1
        cache.close()


class TestPurgeSyntheticDocuments:
    """Test fixtures once leaked into the real 208k-document corpus and, being
    ~40 characters each, ranked first in vector search for real queries. The
    purge must remove them without touching legitimately-empty rows."""

    def _seed(self, cache):
        docs = [
            # Leaked fixtures: synthetic id, no source_url.
            Document(source="yargitay", document_id="yg-004",
                     title="İşçi Alacakları Davası",
                     full_text="İşçi alacakları kıdem tazminatı iş kanunu...",
                     content_status=ContentStatus.FULL_TEXT),
            Document(source="danistay", document_id="ds-001",
                     title="İdari Para Cezası İptal Davası",
                     full_text="İdari para cezası kabahatler kanunu...",
                     content_status=ContentStatus.METADATA_ONLY),
            # Real but empty: metadata-only crawl rows keep their source_url.
            Document(source="uyap_arsiv", document_id="uyap:16082400",
                     title="Yargıtay Kararı", esas_no="2004/6-198",
                     source_url="https://emsal.uyap.gov.tr/getDokuman?id=16082400",
                     content_status=ContentStatus.METADATA_ONLY),
            Document(source="aym", document_id="BB/2021/30620",
                     title="AYM 2021/30620",
                     source_url="https://kararlarbilgibankasi.anayasa.gov.tr/BB/2021/30620",
                     content_status=ContentStatus.METADATA_ONLY),
            # Real and full.
            Document(source="bedesten", document_id="1115295500",
                     title="Yargıtay Kararı | 7. Hukuk Dairesi",
                     full_text="x" * 900,
                     source_url="https://mevzuat.adalet.gov.tr/ictihat/1115295500",
                     content_status=ContentStatus.FULL_TEXT),
        ]
        for doc in docs:
            cache.store_document(doc)

    def test_finds_only_the_fixtures(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._seed(cache)
        found = {d["document_id"] for d in cache.find_synthetic_documents()}
        assert found == {"yg-004", "ds-001"}
        cache.close()

    def test_empty_but_real_rows_are_kept(self, tmp_path):
        """The AYM row has zero characters but a genuine source_url. Purging on
        text length alone would delete it along with ~2700 UYAP rows."""
        cache = Cache(tmp_path / "test.sqlite3")
        self._seed(cache)
        cache.purge_synthetic_documents(dry_run=False)
        survivors = {
            r[0] for r in cache.db.execute("SELECT document_id FROM documents_v2").fetchall()
        }
        assert "BB/2021/30620" in survivors
        assert "uyap:16082400" in survivors
        assert "1115295500" in survivors
        cache.close()

    def test_dry_run_changes_nothing(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._seed(cache)
        before = cache.db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
        res = cache.purge_synthetic_documents()  # dry_run defaults to True
        assert res["dry_run"] is True
        assert res["matched"] == 2
        assert res["deleted"]["documents_v2"] == 0
        assert cache.db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0] == before
        cache.close()

    def test_purge_removes_rows_and_derived_indexes(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._seed(cache)
        from emsal_mcp.semantic import (
            _ensure_embedding_vectors,
            _ensure_fts5,
            _ensure_search_vectors,
        )
        _ensure_fts5(cache.db)
        _ensure_search_vectors(cache.db)
        _ensure_embedding_vectors(cache.db)
        cache.db.execute(
            "INSERT INTO search_vectors(document_id, source, vector_json, norm) "
            "VALUES ('yg-004','yargitay','{\"a\": 1.0}', 1.0)"
        )
        cache.db.execute(
            "INSERT INTO embedding_vectors(document_id, source, provider_id, vector, norm, dim) "
            "VALUES ('yg-004','yargitay','p', X'00', 1.0, 1)"
        )
        cache.db.commit()

        res = cache.purge_synthetic_documents(dry_run=False)
        assert res["ok"] is True
        assert res["deleted"]["documents_v2"] == 2
        assert res["deleted"]["search_vectors"] == 1
        assert res["deleted"]["embedding_vectors"] == 1

        left = {r[0] for r in cache.db.execute("SELECT document_id FROM documents_v2").fetchall()}
        assert "yg-004" not in left and "ds-001" not in left
        assert cache.db.execute(
            "SELECT COUNT(*) FROM search_vectors WHERE document_id='yg-004'"
        ).fetchone()[0] == 0
        assert cache.db.execute(
            "SELECT COUNT(*) FROM embedding_vectors WHERE document_id='yg-004'"
        ).fetchone()[0] == 0
        cache.close()

    def test_fixture_no_longer_matches_search(self, tmp_path):
        """The concrete regression: 'kıdem tazminatı' must not surface yg-004."""
        cache = Cache(tmp_path / "test.sqlite3")
        self._seed(cache)
        from emsal_mcp.semantic import _ensure_fts5
        _ensure_fts5(cache.db)
        assert any(r["document_id"] == "yg-004" for r in cache.search_local("kıdem tazminatı"))
        cache.purge_synthetic_documents(dry_run=False)
        assert not any(
            r["document_id"] == "yg-004" for r in cache.search_local("kıdem tazminatı")
        )
        cache.close()

    def test_purge_is_idempotent(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        self._seed(cache)
        cache.purge_synthetic_documents(dry_run=False)
        second = cache.purge_synthetic_documents(dry_run=False)
        assert second["matched"] == 0
        assert second["deleted"]["documents_v2"] == 0
        cache.close()
