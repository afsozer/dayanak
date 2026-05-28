"""Tests for cache hash verification."""
from __future__ import annotations

from hashlib import sha256

from emsal_mcp.cache import Cache
from emsal_mcp.models import ContentStatus, Document, InputPack


class TestCacheHashVerification:
    def test_store_and_verify(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        cache = Cache(cache_path)

        text = "Test document content"
        expected_hash = sha256(text.encode("utf-8")).hexdigest()

        doc = Document(
            source="test", document_id="123", title="Test",
            full_text=text, content_status=ContentStatus.FULL_TEXT,
            content_hash=expected_hash,
        )

        cache.store_document(doc)
        retrieved = cache.get_document("123", "test")

        assert retrieved is not None
        assert retrieved.content_hash == expected_hash
        cache.close()

    def test_hash_mismatch(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        cache = Cache(cache_path)

        doc = Document(
            source="test", document_id="123", title="Test",
            full_text="Original content", content_status=ContentStatus.FULL_TEXT,
            content_hash="wrong_hash",
        )

        cache.store_document(doc)
        retrieved = cache.get_document("123", "test")

        # Should return None on hash mismatch
        assert retrieved is None
        cache.close()

    def test_pack_hash(self, tmp_path):
        cache_path = tmp_path / "test.sqlite3"
        cache = Cache(cache_path)

        pack = InputPack(
            matter="Matter", issue="Issue", documents=[],
            safe_citations=[], excluded=[], warnings=[],
        )

        cache.store_pack(pack)
        retrieved = cache.get_pack(pack.id)

        assert retrieved is not None
        assert retrieved.id == pack.id
        cache.close()

