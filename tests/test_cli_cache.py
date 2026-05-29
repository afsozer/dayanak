"""Tests for CLI cache subcommands and MCP import."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from emsal_mcp.cache import Cache, CACHE_SCHEMA_VERSION
from emsal_mcp.cli import app
from emsal_mcp.models import ContentStatus, Document

runner = CliRunner()


class TestCliCacheSubcommands:
    """Test CLI cache subcommands."""

    def _populate(self, cache_path):
        cache = Cache(cache_path)
        for i in range(3):
            doc = Document(
                source=f"src{i % 2}", document_id=str(i), title=f"Doc {i}",
                full_text=f"Content {i} for testing", content_status=ContentStatus.FULL_TEXT,
                court="Yargıtay", decision_date=f"2024-0{i+1}-01",
            )
            cache.store_document(doc)
        cache.close()

    def test_cache_stats(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        self._populate(cache_path)
        result = runner.invoke(app, ["cache", "stats", "--cache-path", str(cache_path)])
        assert result.exit_code == 0
        assert "schema_version" in result.output
        assert "documents_v2" in result.output
        assert "3" in result.output

    def test_cache_list(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        self._populate(cache_path)
        result = runner.invoke(app, ["cache", "list", "--cache-path", str(cache_path)])
        assert result.exit_code == 0
        assert "Doc 0" in result.output or "document_id" in result.output

    def test_cache_list_with_source_filter(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        self._populate(cache_path)
        result = runner.invoke(
            app, ["cache", "list", "--source", "src0", "--cache-path", str(cache_path)]
        )
        assert result.exit_code == 0

    def test_cache_search_local(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        self._populate(cache_path)
        result = runner.invoke(
            app, ["cache", "search-local", "--query", "Content 1", "--cache-path", str(cache_path)]
        )
        assert result.exit_code == 0
        assert "Content 1" in result.output

    def test_cache_search_local_with_filters(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        self._populate(cache_path)
        result = runner.invoke(
            app, ["cache", "search-local", "--source", "src0", "--court", "Yargıtay",
                  "--cache-path", str(cache_path)]
        )
        assert result.exit_code == 0

    def test_cache_delete(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        self._populate(cache_path)
        result = runner.invoke(
            app, ["cache", "delete", "0", "src0", "--cache-path", str(cache_path)]
        )
        assert result.exit_code == 0
        assert "Deleted" in result.output

    def test_cache_prune(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        cache = Cache(cache_path)
        cache.set("search:old:q:10:1", [{"result": "old"}])
        cache.close()
        result = runner.invoke(
            app, ["cache", "prune", "--max-age-days", "0", "--cache-path", str(cache_path)]
        )
        assert result.exit_code == 0
        assert "Pruned" in result.output

    def test_cache_backup(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        self._populate(cache_path)
        backup = tmp_path / "backup.sqlite3"
        result = runner.invoke(
            app, ["cache", "backup", str(backup), "--cache-path", str(cache_path)]
        )
        assert result.exit_code == 0
        assert backup.exists()
        assert "SHA256" in result.output

    def test_cache_export(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        self._populate(cache_path)
        export = tmp_path / "export.json"
        result = runner.invoke(
            app, ["cache", "export", str(export), "--cache-path", str(cache_path)]
        )
        assert result.exit_code == 0
        assert export.exists()
        data = json.loads(export.read_text(encoding="utf-8"))
        assert data["schemaVersion"] == CACHE_SCHEMA_VERSION
        assert data["documentCount"] == 3
        assert len(data["documents"]) == 3
        assert "Exported 3 documents" in result.output

    def test_cache_import(self, tmp_path):
        # Create export
        cache1_path = tmp_path / "src.sqlite3"
        self._populate(cache1_path)
        export = tmp_path / "export.json"
        cache1 = Cache(cache1_path)
        cache1.export_json(export)
        cache1.close()

        # Import
        cache2_path = tmp_path / "dst.sqlite3"
        result = runner.invoke(
            app, ["cache", "import", str(export), "--cache-path", str(cache2_path)]
        )
        assert result.exit_code == 0
        assert "Imported: 3" in result.output


class TestMcpImports:
    """Test MCP server imports with cache v2 tools."""

    def test_search_local_cache_importable(self):
        from emsal_mcp.server import main
        assert callable(main)

    def test_cache_module_importable(self):
        from emsal_mcp.cache import Cache
        assert callable(Cache)

    def test_cached_document_importable(self):
        from emsal_mcp.models import CachedDocument
        assert CachedDocument is not None


class TestCliGetStoresDocument:
    """Test that CLI get command stores document in cache."""

    def test_get_stores_in_cache(self, tmp_path):
        """Verify get command writes to cache by checking cache contents."""
        from unittest.mock import AsyncMock, patch
        from emsal_mcp.models import Document, ContentStatus

        mock_doc = Document(
            source="test", document_id="cli1", title="CLI Test",
            full_text="CLI content", content_status=ContentStatus.FULL_TEXT,
            court="Test Court", decision_date="2024-01-01",
        )

        with patch("emsal_mcp.cli.get_source") as mock_get_source:
            mock_client = AsyncMock()
            mock_client.get_document = AsyncMock(return_value=mock_doc)
            mock_get_source.return_value = mock_client

            result = runner.invoke(app, ["get", "test", "cli1", "--json"])
            assert result.exit_code == 0
            assert "cli1" in result.output

            # Check default cache has the document
            cache = Cache()
            doc = cache.get_document("cli1", "test")
            assert doc is not None
            assert doc.document_id == "cli1"
            cache.close()
