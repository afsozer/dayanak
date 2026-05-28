"""Tests for verification module."""
from __future__ import annotations

from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.verification import (
    check_cache_integrity,
    smoke_test_offline,
    verify_bundle_archive_integrity,
    verify_document_hash_in_cache,
)


def test_smoke_test_offline():
    result = smoke_test_offline()
    assert result["ok"] is True
    assert len(result["tests"]) > 0


def test_check_cache_integrity(tmp_path):
    cache_path = tmp_path / "test.sqlite3"
    result = check_cache_integrity(cache_path)
    assert result["ok"] is True
    # Check WAL mode test passed
    wal_test = next(t for t in result["tests"] if t["name"] == "wal_mode")
    assert wal_test["ok"] is True


def test_verify_document_hash_in_cache(tmp_path):
    cache_path = tmp_path / "test.sqlite3"
    doc = Document(
        source="test", document_id="123", title="Test",
        full_text="Test content", content_status=ContentStatus.FULL_TEXT,
        decision_date="2024-01-01",
    )
    result = verify_document_hash_in_cache(doc, cache_path)
    assert result["ok"] is True
    assert result["hash_match"] is True


def test_verify_bundle_not_found(tmp_path):
    result = verify_bundle_archive_integrity(tmp_path / "missing.zip")
    assert result["valid"] is False
