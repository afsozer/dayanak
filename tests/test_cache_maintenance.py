"""Tests for cache maintenance features (M-06): vacuum, orphan cleanup,
integrity check, and auto-migration."""
from __future__ import annotations

import json

from emsal_mcp.cache import Cache, CACHE_SCHEMA_VERSION
from emsal_mcp.models import ContentStatus, Document


class TestCacheVacuum:
    """Test cache vacuum/compaction."""

    def test_vacuum_populated_db(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        for i in range(10):
            doc = Document(
                source="test", document_id=str(i), title=f"Doc {i}",
                full_text="Content " * 100, content_status=ContentStatus.FULL_TEXT,
            )
            cache.store_document(doc)
        cache.db.commit()

        # Delete some rows to create fragmentation
        for i in range(5):
            cache.delete_cached_document(str(i), "test")

        result = cache.vacuum_cache()
        assert result["ok"] is True
        assert result["size_before"] > 0
        assert result["size_after"] > 0
        assert "freed_bytes" in result
        cache.close()

    def test_vacuum_empty_db(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        result = cache.vacuum_cache()
        assert result["ok"] is True
        assert result["size_before"] > 0
        assert result["size_after"] > 0
        cache.close()

    def test_vacuum_logs_history(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        cache.vacuum_cache()
        history = cache.history(limit=10)
        vacuum_entries = [h for h in history if h["action"] == "vacuum_cache"]
        assert len(vacuum_entries) == 1
        assert "size_before" in vacuum_entries[0]["payload"]
        cache.close()


class TestOrphanCleanup:
    """Test orphan row cleanup."""

    def _create_orphans(self, cache: Cache) -> None:
        """Manually insert orphan rows into search_vectors and FTS5."""
        # Insert a document, then delete it to leave orphans
        doc = Document(
            source="test", document_id="orphan_test", title="To Be Deleted",
            full_text="Some text for orphan testing",
            content_status=ContentStatus.FULL_TEXT,
        )
        cache.store_document(doc)

        # Manually insert an orphan into search_vectors
        cache.db.execute(
            "INSERT OR REPLACE INTO search_vectors(document_id, source, vector_json, norm) "
            "VALUES(?, ?, ?, ?)",
            ("nonexistent_doc", "nonexistent_source", "{}", 0.0),
        )
        cache.db.commit()

        # Now delete the original document
        cache.delete_cached_document("orphan_test", "test")

    def test_cleanup_orphans_with_orphans(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        # Ensure search_vectors table exists
        cache.db.execute("""
            CREATE TABLE IF NOT EXISTS search_vectors (
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                norm REAL DEFAULT 0.0,
                indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        cache.db.commit()

        self._create_orphans(cache)

        # Verify orphan exists
        orphans_before = cache.db.execute("""
            SELECT COUNT(*) FROM search_vectors
            WHERE (document_id, source) NOT IN (
                SELECT document_id, source FROM documents_v2
            )
        """).fetchone()[0]
        assert orphans_before > 0

        result = cache.cleanup_orphans()
        assert result["ok"] is True
        assert result["orphans_removed"] >= 1
        assert result["details"]["search_vectors_removed"] >= 1

        # Verify orphan is gone
        orphans_after = cache.db.execute("""
            SELECT COUNT(*) FROM search_vectors
            WHERE (document_id, source) NOT IN (
                SELECT document_id, source FROM documents_v2
            )
        """).fetchone()[0]
        assert orphans_after == 0
        cache.close()

    def test_cleanup_orphans_no_orphans(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        # Ensure search_vectors table exists
        cache.db.execute("""
            CREATE TABLE IF NOT EXISTS search_vectors (
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                norm REAL DEFAULT 0.0,
                indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        cache.db.commit()

        result = cache.cleanup_orphans()
        assert result["ok"] is True
        assert result["orphans_removed"] == 0
        cache.close()

    def test_cleanup_orphans_logs_history(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        cache.db.execute("""
            CREATE TABLE IF NOT EXISTS search_vectors (
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                norm REAL DEFAULT 0.0,
                indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        cache.db.commit()
        cache.cleanup_orphans()
        history = cache.history(limit=10)
        orphan_entries = [h for h in history if h["action"] == "cleanup_orphans"]
        assert len(orphan_entries) == 1
        cache.close()


class TestIntegrityCheck:
    """Test comprehensive integrity checking."""

    def test_integrity_check_all_pass(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(
            source="test", document_id="1", title="Test",
            full_text="Test content for integrity",
            content_status=ContentStatus.FULL_TEXT,
        )
        cache.store_document(doc)
        # Ensure search_vectors exists
        cache.db.execute("""
            CREATE TABLE IF NOT EXISTS search_vectors (
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                norm REAL DEFAULT 0.0,
                indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        cache.db.commit()

        result = cache.check_integrity_full()
        assert result["ok"] is True
        assert result["checks"]["sqlite_integrity"]["ok"] is True
        assert result["checks"]["search_vectors_orphans"]["ok"] is True
        assert result["checks"]["schema_version"]["ok"] is True
        assert result["checks"]["content_hash_consistency"]["ok"] is True
        assert result["checks"]["table_row_counts"]["ok"] is True
        assert len(result["warnings"]) == 0
        cache.close()

    def test_integrity_check_detects_orphans(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        # Ensure search_vectors table exists
        cache.db.execute("""
            CREATE TABLE IF NOT EXISTS search_vectors (
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                norm REAL DEFAULT 0.0,
                indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        # Insert orphan
        cache.db.execute(
            "INSERT OR REPLACE INTO search_vectors(document_id, source, vector_json, norm) "
            "VALUES(?, ?, ?, ?)",
            ("ghost_doc", "ghost_source", "{}", 0.0),
        )
        cache.db.commit()

        result = cache.check_integrity_full()
        assert result["ok"] is False
        assert result["checks"]["search_vectors_orphans"]["ok"] is False
        assert result["checks"]["search_vectors_orphans"]["count"] == 1
        assert any("orphan" in w.lower() for w in result["warnings"])
        cache.close()

    def test_integrity_check_detects_hash_mismatch(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        # Manually insert a doc with wrong hash
        cache.db.execute("""
            INSERT INTO documents_v2(document_id, source, title, content_hash, full_text, content_status)
            VALUES(?, ?, ?, ?, ?, ?)
        """, ("bad_hash", "test", "Bad Hash Doc", "definitely_wrong_hash", "Actual content here", "full_text"))
        cache.db.commit()

        result = cache.check_integrity_full()
        assert result["ok"] is False
        assert result["checks"]["content_hash_consistency"]["ok"] is False
        assert result["checks"]["content_hash_consistency"]["mismatches"] >= 1
        cache.close()

    def test_integrity_check_table_counts(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(
            source="test", document_id="1", title="Test",
            full_text="content", content_status=ContentStatus.FULL_TEXT,
        )
        cache.store_document(doc)
        result = cache.check_integrity_full()
        counts = result["checks"]["table_row_counts"]["counts"]
        assert counts["documents_v2"] == 1
        assert counts["documents"] == 1
        cache.close()

    def test_integrity_check_logs_history(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        cache.check_integrity_full()
        history = cache.history(limit=10)
        integrity_entries = [h for h in history if h["action"] == "check_integrity_full"]
        assert len(integrity_entries) == 1
        cache.close()


class TestSchemaMigration:
    """Test schema version tracking and auto-migration."""

    def test_fresh_db_gets_current_version(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        # schema_meta should record current version
        row = cache.db.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert row is not None
        assert int(row[0]) == CACHE_SCHEMA_VERSION
        # PRAGMA user_version should also match
        assert cache.schema_version == CACHE_SCHEMA_VERSION
        cache.close()

    def test_migration_v2_to_v3(self, tmp_path):
        """Simulate opening a v2 database and verify it migrates to v3."""
        # Create a "v2" database manually
        import sqlite3
        db_path = tmp_path / "v2.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 2")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents_v2 (
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT,
                content_hash TEXT,
                PRIMARY KEY (document_id, source)
            )
        """)
        # No schema_meta table (v2 doesn't have it)
        conn.commit()
        conn.close()

        # Open with Cache — should auto-migrate
        cache = Cache(db_path)
        assert cache.schema_version == CACHE_SCHEMA_VERSION
        row = cache.db.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert row is not None
        assert int(row[0]) == CACHE_SCHEMA_VERSION
        cache.close()

    def test_idempotent_migration(self, tmp_path):
        """Opening an already-migrated DB should be a no-op."""
        cache1 = Cache(tmp_path / "test.sqlite3")
        assert cache1.schema_version == CACHE_SCHEMA_VERSION
        cache1.close()

        cache2 = Cache(tmp_path / "test.sqlite3")
        assert cache2.schema_version == CACHE_SCHEMA_VERSION
        row = cache2.db.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert row is not None
        assert int(row[0]) == CACHE_SCHEMA_VERSION
        cache2.close()

    def test_migration_adds_indexes(self, tmp_path):
        """Verify that migration to v3 creates the expected indexes."""
        # Create a bare v2 database
        import sqlite3
        db_path = tmp_path / "v2_no_idx.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA user_version = 2")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents_v2 (
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT,
                content_hash TEXT,
                PRIMARY KEY (document_id, source)
            )
        """)
        conn.commit()
        conn.close()

        cache = Cache(db_path)
        # Check idx_dv2_content_hash exists (added by v2->v3 migration)
        indexes = [row[0] for row in cache.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='documents_v2'"
        ).fetchall()]
        assert "idx_dv2_content_hash" in indexes
        assert "idx_dv2_source" in indexes
        cache.close()

    def test_schema_version_export_reflects_v3(self, tmp_path):
        """After migration, export_json should report schema_version == 3."""
        cache = Cache(tmp_path / "test.sqlite3")
        doc = Document(
            source="test", document_id="1", title="Test",
            full_text="content", content_status=ContentStatus.FULL_TEXT,
        )
        cache.store_document(doc)
        result = cache.export_json(tmp_path / "export.json")
        assert result["schema_version"] == CACHE_SCHEMA_VERSION
        data = json.loads((tmp_path / "export.json").read_text(encoding="utf-8"))
        assert data["schemaVersion"] == CACHE_SCHEMA_VERSION
        cache.close()


class TestCacheStatsVersion:
    """Test that cache_stats reflects the current schema version."""

    def test_cache_stats_reports_schema_version(self, tmp_path):
        cache = Cache(tmp_path / "test.sqlite3")
        stats = cache.cache_stats()
        assert stats["schema_version"] == CACHE_SCHEMA_VERSION
        cache.close()


class TestCLIImports:
    """Test that CLI commands are importable and the server module loads."""

    def test_cli_cache_compact_importable(self):
        from emsal_mcp.cli import cache_app
        # Verify the command exists on cache_app
        commands = {cmd.name for cmd in cache_app.registered_commands}
        assert "compact" in commands

    def test_cli_cleanup_orphans_importable(self):
        from emsal_mcp.cli import cache_app
        commands = {cmd.name for cmd in cache_app.registered_commands}
        assert "cleanup-orphans" in commands

    def test_cli_integrity_check_importable(self):
        from emsal_mcp.cli import cache_app
        commands = {cmd.name for cmd in cache_app.registered_commands}
        assert "integrity-check" in commands

    def test_server_main_importable(self):
        from emsal_mcp.server import main
        assert callable(main)


class TestMCPSchemaVersionInStats:
    """Test that the MCP cache_vacuum, cache_cleanup_orphans, cache_integrity_check tools
    are registered (import test)."""

    def test_server_imports_clean(self):
        """Verify the server module can be imported without error."""
        import importlib
        import emsal_mcp.server
        importlib.reload(emsal_mcp.server)

    def test_cache_vacuum_method_exists(self):
        assert hasattr(Cache, "vacuum_cache")

    def test_cleanup_orphans_method_exists(self):
        assert hasattr(Cache, "cleanup_orphans")

    def test_check_integrity_full_method_exists(self):
        assert hasattr(Cache, "check_integrity_full")

    def test_ensure_schema_version_method_exists(self):
        assert hasattr(Cache, "_ensure_schema_version")

    def test_cache_schema_version_constant(self):
        assert CACHE_SCHEMA_VERSION == 3


class TestCLIExecution:
    """Test CLI commands execute correctly."""

    def test_cache_compact_command(self, tmp_path):
        from typer.testing import CliRunner
        from emsal_mcp.cli import app

        runner = CliRunner()
        cache_path = tmp_path / "test.sqlite3"
        cache = Cache(cache_path)
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="text", content_status=ContentStatus.FULL_TEXT,
        )
        cache.store_document(doc)
        cache.close()

        result = runner.invoke(
            app, ["cache", "compact", "--cache-path", str(cache_path), "--json"]
        )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["ok"] is True
        assert "size_before" in output
        assert "size_after" in output

    def test_cache_cleanup_orphans_command(self, tmp_path):
        from typer.testing import CliRunner
        from emsal_mcp.cli import app

        runner = CliRunner()
        cache_path = tmp_path / "test.sqlite3"
        cache = Cache(cache_path)
        cache.close()

        result = runner.invoke(
            app, ["cache", "cleanup-orphans", "--cache-path", str(cache_path), "--json"]
        )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["ok"] is True
        assert "orphans_removed" in output

    def test_cache_integrity_check_command(self, tmp_path):
        from typer.testing import CliRunner
        from emsal_mcp.cli import app

        runner = CliRunner()
        cache_path = tmp_path / "test.sqlite3"
        cache = Cache(cache_path)
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="text", content_status=ContentStatus.FULL_TEXT,
        )
        cache.store_document(doc)
        cache.close()

        result = runner.invoke(
            app, ["cache", "integrity-check", "--cache-path", str(cache_path), "--json"]
        )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["ok"] is True
        assert "checks" in output
        assert "warnings" in output
        assert output["checks"]["sqlite_integrity"]["ok"] is True


class TestSyncCache:
    """Test multi-machine cache sync (M-34)."""

    def _make_other_db(self, tmp_path, docs):
        """Helper: create a separate cache DB with the given documents."""
        other = Cache(tmp_path / "other.sqlite3")
        for doc in docs:
            other.store_document(doc)
        other.close()
        return tmp_path / "other.sqlite3"

    def test_sync_empty_other_db(self, tmp_path):
        """Sync with empty other DB -> 0 synced."""
        cache = Cache(tmp_path / "main.sqlite3")
        other_path = self._make_other_db(tmp_path, [])
        result = cache.sync_cache(other_path)
        assert result["ok"] is True
        assert result["synced"] == 0
        assert result["skipped"] == 0
        assert result["total_in_other"] == 0
        cache.close()

    def test_sync_new_documents(self, tmp_path):
        """Sync with new documents -> synced count correct."""
        cache = Cache(tmp_path / "main.sqlite3")
        docs = [
            Document(source="test", document_id="d1", title="Doc 1",
                     full_text="Content 1", content_status=ContentStatus.FULL_TEXT),
            Document(source="test", document_id="d2", title="Doc 2",
                     full_text="Content 2", content_status=ContentStatus.FULL_TEXT),
        ]
        other_path = self._make_other_db(tmp_path, docs)
        result = cache.sync_cache(other_path)
        assert result["ok"] is True
        assert result["synced"] == 2
        assert result["skipped"] == 0
        # Verify docs are now in main DB
        row1 = cache.db.execute(
            "SELECT title FROM documents_v2 WHERE document_id='d1' AND source='test'"
        ).fetchone()
        assert row1 is not None
        assert row1["title"] == "Doc 1"
        cache.close()

    def test_sync_older_version_skipped(self, tmp_path):
        """Sync with older retrieved_at -> skipped (keeps existing)."""
        cache = Cache(tmp_path / "main.sqlite3")
        # Insert doc with newer timestamp
        cache.db.execute("""
            INSERT INTO documents_v2(document_id, source, title, retrieved_at)
            VALUES('d1', 'test', 'Main version', '2026-05-30T12:00:00')
        """)
        cache.db.commit()

        # Create other DB with same doc but older timestamp
        import sqlite3 as _sqlite3
        other_path = tmp_path / "other.sqlite3"
        other = _sqlite3.connect(str(other_path))
        other.execute("PRAGMA user_version = 3")
        other.execute("""
            CREATE TABLE IF NOT EXISTS documents_v2 (
                document_id TEXT NOT NULL, source TEXT NOT NULL,
                title TEXT, court TEXT, chamber TEXT, decision_date TEXT,
                esas_no TEXT, karar_no TEXT, source_url TEXT,
                content_status TEXT DEFAULT 'metadata_only',
                markdown TEXT, full_text TEXT, content_hash TEXT,
                metadata_json TEXT, raw_json TEXT,
                retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                quote_usable INTEGER DEFAULT 0, draft_usable INTEGER DEFAULT 0,
                metadata_confidence TEXT, warnings_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        other.execute("""
            INSERT INTO documents_v2(document_id, source, title, retrieved_at)
            VALUES('d1', 'test', 'Older version', '2026-01-01T00:00:00')
        """)
        other.commit()
        other.close()

        result = cache.sync_cache(other_path)
        assert result["ok"] is True
        assert result["synced"] == 0
        assert result["skipped"] == 1
        # Main version preserved
        row = cache.db.execute(
            "SELECT title FROM documents_v2 WHERE document_id='d1' AND source='test'"
        ).fetchone()
        assert row["title"] == "Main version"
        cache.close()

    def test_sync_newer_version_updates(self, tmp_path):
        """Sync with newer retrieved_at -> updates existing."""
        cache = Cache(tmp_path / "main.sqlite3")
        cache.db.execute("""
            INSERT INTO documents_v2(document_id, source, title, retrieved_at)
            VALUES('d1', 'test', 'Old version', '2026-01-01T00:00:00')
        """)
        cache.db.commit()

        import sqlite3 as _sqlite3
        other_path = tmp_path / "other.sqlite3"
        other = _sqlite3.connect(str(other_path))
        other.execute("PRAGMA user_version = 3")
        other.execute("""
            CREATE TABLE IF NOT EXISTS documents_v2 (
                document_id TEXT NOT NULL, source TEXT NOT NULL,
                title TEXT, court TEXT, chamber TEXT, decision_date TEXT,
                esas_no TEXT, karar_no TEXT, source_url TEXT,
                content_status TEXT DEFAULT 'metadata_only',
                markdown TEXT, full_text TEXT, content_hash TEXT,
                metadata_json TEXT, raw_json TEXT,
                retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                quote_usable INTEGER DEFAULT 0, draft_usable INTEGER DEFAULT 0,
                metadata_confidence TEXT, warnings_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        other.execute("""
            INSERT INTO documents_v2(document_id, source, title, retrieved_at)
            VALUES('d1', 'test', 'Newer version', '2026-06-01T00:00:00')
        """)
        other.commit()
        other.close()

        result = cache.sync_cache(other_path)
        assert result["ok"] is True
        assert result["synced"] == 1
        assert result["skipped"] == 0
        row = cache.db.execute(
            "SELECT title FROM documents_v2 WHERE document_id='d1' AND source='test'"
        ).fetchone()
        assert row["title"] == "Newer version"
        cache.close()

    def test_sync_hash_mismatch_reports_conflict(self, tmp_path):
        """Sync conflict (hash mismatch) -> reports conflict."""
        cache = Cache(tmp_path / "main.sqlite3")
        cache.db.execute("""
            INSERT INTO documents_v2(document_id, source, title, retrieved_at, content_hash)
            VALUES('d1', 'test', 'Main', '2026-01-01T00:00:00', 'hash_abc')
        """)
        cache.db.commit()

        import sqlite3 as _sqlite3
        other_path = tmp_path / "other.sqlite3"
        other = _sqlite3.connect(str(other_path))
        other.execute("PRAGMA user_version = 3")
        other.execute("""
            CREATE TABLE IF NOT EXISTS documents_v2 (
                document_id TEXT NOT NULL, source TEXT NOT NULL,
                title TEXT, court TEXT, chamber TEXT, decision_date TEXT,
                esas_no TEXT, karar_no TEXT, source_url TEXT,
                content_status TEXT DEFAULT 'metadata_only',
                markdown TEXT, full_text TEXT, content_hash TEXT,
                metadata_json TEXT, raw_json TEXT,
                retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                quote_usable INTEGER DEFAULT 0, draft_usable INTEGER DEFAULT 0,
                metadata_confidence TEXT, warnings_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        other.execute("""
            INSERT INTO documents_v2(document_id, source, title, retrieved_at, content_hash)
            VALUES('d1', 'test', 'Updated', '2026-06-01T00:00:00', 'hash_xyz')
        """)
        other.commit()
        other.close()

        result = cache.sync_cache(other_path)
        assert result["ok"] is True
        assert result["conflicts"] == 1
        assert len(result["warnings"]) == 1
        assert "hash mismatch" in result["warnings"][0].lower()
        cache.close()

    def test_sync_nonexistent_file(self, tmp_path):
        """Sync nonexistent file -> FILE_NOT_FOUND error."""
        cache = Cache(tmp_path / "main.sqlite3")
        result = cache.sync_cache(tmp_path / "nonexistent.sqlite3")
        assert result["ok"] is False
        assert result["errorCode"] == "FILE_NOT_FOUND"
        cache.close()

    def test_sync_logs_history(self, tmp_path):
        """Sync action is logged in history."""
        cache = Cache(tmp_path / "main.sqlite3")
        other_path = self._make_other_db(tmp_path, [])
        cache.sync_cache(other_path)
        history = cache.history(limit=10)
        sync_entries = [h for h in history if h["action"] == "sync_cache"]
        assert len(sync_entries) == 1
        assert "other_db_path" in sync_entries[0]["payload"]
        cache.close()

    def test_sync_mixed_new_and_existing(self, tmp_path):
        """Sync a mix of new + existing docs."""
        cache = Cache(tmp_path / "main.sqlite3")
        cache.db.execute("""
            INSERT INTO documents_v2(document_id, source, title, retrieved_at)
            VALUES('existing', 'test', 'Existing', '2026-01-01T00:00:00')
        """)
        cache.db.commit()

        import sqlite3 as _sqlite3
        other_path = tmp_path / "other.sqlite3"
        other = _sqlite3.connect(str(other_path))
        other.execute("PRAGMA user_version = 3")
        other.execute("""
            CREATE TABLE IF NOT EXISTS documents_v2 (
                document_id TEXT NOT NULL, source TEXT NOT NULL,
                title TEXT, court TEXT, chamber TEXT, decision_date TEXT,
                esas_no TEXT, karar_no TEXT, source_url TEXT,
                content_status TEXT DEFAULT 'metadata_only',
                markdown TEXT, full_text TEXT, content_hash TEXT,
                metadata_json TEXT, raw_json TEXT,
                retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                quote_usable INTEGER DEFAULT 0, draft_usable INTEGER DEFAULT 0,
                metadata_confidence TEXT, warnings_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, source)
            )
        """)
        other.execute("""
            INSERT INTO documents_v2(document_id, source, title, retrieved_at)
            VALUES('existing', 'test', 'Same timestamp', '2026-01-01T00:00:00')
        """)
        other.execute("""
            INSERT INTO documents_v2(document_id, source, title, retrieved_at)
            VALUES('brand_new', 'test', 'Brand New', '2026-06-01T00:00:00')
        """)
        other.commit()
        other.close()

        result = cache.sync_cache(other_path)
        assert result["ok"] is True
        assert result["synced"] == 1  # only brand_new
        assert result["skipped"] == 1  # existing skipped (same timestamp)
        cache.close()


class TestCLISyncImport:
    """Test that the CLI sync command is importable."""

    def test_cli_sync_importable(self):
        from emsal_mcp.cli import cache_app
        commands = {cmd.name for cmd in cache_app.registered_commands}
        assert "sync" in commands
