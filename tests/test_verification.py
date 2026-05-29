"""Tests for verification module."""
from __future__ import annotations

import json
import zipfile

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


def test_smoke_test_has_required_tests():
    result = smoke_test_offline()
    test_names = [t["name"] for t in result["tests"]]
    assert "imports" in test_names
    assert "model_create" in test_names
    assert "safety_udf_roundtrip" in test_names


def test_smoke_test_all_tests_ok():
    result = smoke_test_offline()
    for test in result["tests"]:
        assert test["ok"] is True, f"Test {test['name']} failed"


def test_check_cache_integrity(tmp_path):
    cache_path = tmp_path / "test.sqlite3"
    result = check_cache_integrity(cache_path)
    assert result["ok"] is True
    # Check WAL mode test passed
    wal_test = next(t for t in result["tests"] if t["name"] == "wal_mode")
    assert wal_test["ok"] is True


def test_check_cache_integrity_tables_exist(tmp_path):
    cache_path = tmp_path / "test.sqlite3"
    result = check_cache_integrity(cache_path)
    tables_test = next(t for t in result["tests"] if t["name"] == "tables_exist")
    assert tables_test["ok"] is True
    assert len(tables_test.get("missing", [])) == 0


def test_check_cache_integrity_set_get(tmp_path):
    cache_path = tmp_path / "test.sqlite3"
    result = check_cache_integrity(cache_path)
    sg_test = next(t for t in result["tests"] if t["name"] == "set_get")
    assert sg_test["ok"] is True


def test_check_cache_integrity_default_path():
    """Test with default cache path (None)."""
    result = check_cache_integrity()
    assert "ok" in result
    assert "tests" in result


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


def test_verify_document_hash_no_content_hash(tmp_path):
    """Document without content_hash should still pass."""
    cache_path = tmp_path / "test.sqlite3"
    doc = Document(
        source="test", document_id="456", title="Test",
        full_text="Some content", content_status=ContentStatus.FULL_TEXT,
        decision_date="2024-01-01",
    )
    # content_hash is None by default
    result = verify_document_hash_in_cache(doc, cache_path)
    assert result["ok"] is True
    assert result.get("hash_match") is True


def test_verify_document_hash_with_explicit_hash(tmp_path):
    """Document with explicit content_hash that matches."""
    import hashlib
    cache_path = tmp_path / "test.sqlite3"
    text = "Exact content for hash."
    doc = Document(
        source="test", document_id="789", title="Test",
        full_text=text, content_status=ContentStatus.FULL_TEXT,
        decision_date="2024-01-01",
    )
    doc.content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    result = verify_document_hash_in_cache(doc, cache_path)
    assert result["ok"] is True
    assert result["hash_match"] is True


def test_verify_document_hash_default_cache_path():
    """Test with default cache path (None)."""
    doc = Document(
        source="test", document_id="999", title="Test",
        full_text="Content", content_status=ContentStatus.FULL_TEXT,
        decision_date="2024-01-01",
    )
    result = verify_document_hash_in_cache(doc)
    assert "ok" in result
    assert "hash_match" in result


def test_verify_document_hash_metadata_only_doc(tmp_path):
    """Metadata-only document should still work."""
    cache_path = tmp_path / "test.sqlite3"
    doc = Document(
        source="test", document_id="md", title="Meta Only",
        content_status=ContentStatus.METADATA_ONLY,
        decision_date="2024-01-01",
    )
    result = verify_document_hash_in_cache(doc, cache_path)
    assert result["ok"] is True


def test_verify_bundle_not_found(tmp_path):
    result = verify_bundle_archive_integrity(tmp_path / "missing.zip")
    assert result["valid"] is False
    assert "error" in result


def test_verify_bundle_valid_zip(tmp_path):
    """Test a valid ZIP with manifest."""
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"version": "1.0", "files": ["a.txt"]}))
        zf.writestr("a.txt", "content")
    result = verify_bundle_archive_integrity(bundle)
    assert result["valid"] is True
    assert "files" in result
    assert "manifest" in result
    assert result["manifest"]["version"] == "1.0"


def test_verify_bundle_valid_zip_no_manifest(tmp_path):
    """Valid ZIP without manifest should still be valid."""
    bundle = tmp_path / "no_manifest.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("data.txt", "content")
    result = verify_bundle_archive_integrity(bundle)
    assert result["valid"] is True
    assert "files" in result


def test_verify_bundle_empty_zip(tmp_path):
    """Empty ZIP is valid."""
    bundle = tmp_path / "empty.zip"
    with zipfile.ZipFile(bundle, "w"):
        pass  # empty archive
    result = verify_bundle_archive_integrity(bundle)
    assert result["valid"] is True


def test_verify_bundle_corrupt_file(tmp_path):
    """Non-ZIP file should fail."""
    bundle = tmp_path / "not_a_zip.zip"
    bundle.write_text("This is not a ZIP file.")
    result = verify_bundle_archive_integrity(bundle)
    assert result["valid"] is False


def test_verify_bundle_with_nested_files(tmp_path):
    """ZIP with nested directory structure."""
    bundle = tmp_path / "nested.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"version": "1.0"}))
        zf.writestr("docs/doc1.md", "# Doc 1")
        zf.writestr("docs/doc2.md", "# Doc 2")
        zf.writestr("data/stats.json", '{"count": 5}')
    result = verify_bundle_archive_integrity(bundle)
    assert result["valid"] is True
    assert len(result["files"]) == 4
