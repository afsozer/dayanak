"""Tests for emsal_mcp.pdf_extractor module — M-27 PDF/Scanned Content Extraction.

Covers:
  - Toolkit availability checks
  - Text-layer extraction from valid PDF bytes
  - Extraction failure with corrupted/invalid PDF
  - OCR opt-in behavior
  - PDF stats reporting
  - Document promotion (upgrade pdf_link_only → full_text)
  - Graceful degradation when deps unavailable
  - Citation-safety invariants preserved
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

from pathlib import Path

from emsal_mcp.pdf_extractor import (
    PDF_EXTRACTOR_VERSION,
    extract_pdf_text,
    extract_pdf_text_from_bytes,
    extract_pdf_text_from_file,
    get_pdf_stats,
    get_pdf_toolkit_status,
    is_ocr_available,
    is_pdf_extraction_available,
    promote_pdf_to_full_text,
    try_upgrade_pdf_document,
    upgrade_all_pdf_documents,
)
from emsal_mcp.cache import Cache
from emsal_mcp.models import ContentStatus, Document


# ---------------------------------------------------------------------------
# Minimal valid PDF for testing
# ---------------------------------------------------------------------------


def _minimal_pdf_bytes() -> bytes:
    """Return a minimal valid PDF with text content."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n"
        b"<< /Type /Catalog /Pages 2 0 R >>\n"
        b"endobj\n"
        b"2 0 obj\n"
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
        b"endobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\n"
        b"endobj\n"
        b"4 0 obj\n"
        b"<< /Length 44 >>\n"
        b"stream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello PDF World) Tj ET\n"
        b"endstream\n"
        b"endobj\n"
        b"5 0 obj\n"
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        b"endobj\n"
        b"xref\n"
        b"0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000291 00000 n \n"
        b"0000000385 00000 n \n"
        b"trailer\n"
        b"<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n"
        b"467\n"
        b"%%EOF"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store_pdf_doc(cache: Cache, doc_id: str = "pdf-1", source: str = "bedesten") -> None:
    """Store a pdf_link_only document in cache for testing."""
    cache.db.execute(
        """INSERT OR REPLACE INTO documents_v2(
            document_id, source, title, content_status, source_url, full_text
        ) VALUES(?, ?, ?, ?, ?, ?)""",
        (
            doc_id,
            source,
            "Test PDF Doc",
            ContentStatus.PDF_LINK_ONLY,
            "https://example.com/test.pdf",
            None,
        ),
    )
    cache.db.commit()


# ===================================================================
# TestToolkitStatus
# ===================================================================


class TestToolkitStatus:
    """Tests for availability checks and toolkit status."""

    def test_version_constant(self) -> None:
        """PDF_EXTRACTOR_VERSION is defined."""
        assert isinstance(PDF_EXTRACTOR_VERSION, str)
        assert PDF_EXTRACTOR_VERSION == "1.0.0"

    def test_availability_functions_dont_raise(self) -> None:
        """Availability checks never raise exceptions."""
        pypdf_ok = is_pdf_extraction_available()
        ocr_ok = is_ocr_available()
        assert isinstance(pypdf_ok, bool)
        assert isinstance(ocr_ok, bool)

    def test_toolkit_status_keys(self) -> None:
        """get_pdf_toolkit_status returns expected keys."""
        result = get_pdf_toolkit_status()
        assert result["ok"] is True
        assert "pypdf_available" in result
        assert "ocr_available" in result
        assert "recommended_install" in result
        assert result["version"] == PDF_EXTRACTOR_VERSION

    def test_toolkit_status_is_jsonable(self) -> None:
        """Toolkit status is JSON-serializable."""
        import json

        result = get_pdf_toolkit_status()
        json.dumps(result)


# ===================================================================
# TestTextLayerExtraction
# ===================================================================


class TestTextLayerExtraction:
    """Tests for extract_pdf_text_from_bytes and extract_pdf_text."""

    def test_extract_from_valid_pdf(self) -> None:
        """Extraction from a minimal valid PDF returns text."""
        pdf_bytes = _minimal_pdf_bytes()
        result = extract_pdf_text_from_bytes(pdf_bytes)
        if is_pdf_extraction_available():
            assert result["ok"] is True
            # The minimal PDF has "Hello PDF World" in the text layer
            assert "text" in result
            assert "page_count" in result
            assert result["method"] == "pypdf_text_layer"
            assert isinstance(result["warnings"], list)
        else:
            # Graceful degradation when pypdf not installed
            assert result["ok"] is False
            assert "PDF_EXTRACTION_UNAVAILABLE" in result.get("errorCode", "")

    def test_extract_empty_bytes(self) -> None:
        """Extraction from empty bytes fails gracefully."""
        result = extract_pdf_text_from_bytes(b"")
        if is_pdf_extraction_available():
            assert result["ok"] is False  # Invalid PDF
        else:
            assert result["ok"] is False

    def test_extract_corrupted_pdf(self) -> None:
        """Extraction from corrupted PDF data fails gracefully."""
        result = extract_pdf_text_from_bytes(b"not a pdf at all")
        # Always fails regardless of pypdf availability
        assert result["ok"] is False

    def test_extract_pdf_text_wrapper(self) -> None:
        """extract_pdf_text delegates correctly."""
        pdf_bytes = _minimal_pdf_bytes()
        result = extract_pdf_text(pdf_bytes)
        # Either works if pypdf installed, or returns error if not — never crashes
        assert "ok" in result
        if result["ok"]:
            assert "text" in result

    def test_extract_pdf_text_no_ocr(self) -> None:
        """extract_pdf_text without OCR does NOT call OCR."""
        pdf_bytes = _minimal_pdf_bytes()
        result = extract_pdf_text(pdf_bytes, ocr_enabled=False)
        assert result.get("method") != "ocr_pytesseract"

    def test_extract_pdf_text_with_ocr_flag(self) -> None:
        """extract_pdf_text with OCR enabled but empty text may try OCR."""
        pdf_bytes = _minimal_pdf_bytes()
        result = extract_pdf_text(pdf_bytes, ocr_enabled=True)
        # Either pypdf succeeded or OCR was attempted — no crash
        assert "ok" in result

    def test_extract_large_pdf_rejected(self) -> None:
        """PDF content exceeding max size returns error."""
        large = b"X" * (11 * 1024 * 1024)  # 11 MB
        result = extract_pdf_text_from_bytes(large)
        assert result["ok"] is False
        assert "PDF_TOO_LARGE" in result.get("errorCode", "")

    def test_warnings_present(self) -> None:
        """Result dict always contains a list for warnings (or error for unavailable)."""
        result = extract_pdf_text_from_bytes(b"not pdf")
        if result["ok"]:
            assert "warnings" in result
            assert isinstance(result["warnings"], list)
        else:
            # Error dict from build_error — either warnings or recommended_next_steps present
            assert "errorCode" in result


# ===================================================================
# TestFileBasedExtraction
# ===================================================================


class TestFileBasedExtraction:
    """Tests for extract_pdf_text_from_file."""

    def test_file_not_found(self) -> None:
        """Non-existent file returns error."""
        result = extract_pdf_text_from_file("/nonexistent/path/file.pdf")
        assert result["ok"] is False
        assert "FILE_NOT_FOUND" in result.get("errorCode", "")

    def test_from_existing_file(self, tmp_path: Path) -> None:
        """Extraction from a real PDF file on disk."""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_minimal_pdf_bytes())
        result = extract_pdf_text_from_file(str(pdf_path))
        # Either succeeds or fails depending on pypdf availability — no crash
        assert "ok" in result
        if result["ok"] and result.get("text"):
            assert len(result["text"]) > 0


# ===================================================================
# TestPDFStats
# ===================================================================


class TestPDFStats:
    """Tests for get_pdf_stats."""

    def test_empty_cache(self, tmp_path: Path) -> None:
        """Stats on empty cache shows zero counts."""
        cache = Cache(tmp_path / "pdf_stats_empty.sqlite3")
        try:
            result = get_pdf_stats(cache=cache)
            assert result["ok"] is True
            assert result["pdf_link_only_count"] == 0
            assert result["with_source_url"] == 0
            assert result["without_source_url"] == 0
        finally:
            cache.close()

    def test_stats_with_pdf_docs(self, tmp_path: Path) -> None:
        """Stats reflect pdf_link_only documents."""
        cache = Cache(tmp_path / "pdf_stats_docs.sqlite3")
        try:
            _store_pdf_doc(cache, "pdf-1")
            _store_pdf_doc(cache, "pdf-2")
            result = get_pdf_stats(cache=cache)
            assert result["ok"] is True
            assert result["pdf_link_only_count"] == 2
            assert result["with_source_url"] == 2
        finally:
            cache.close()

    def test_stats_recognizes_availability(self, tmp_path: Path) -> None:
        """Stats reports toolkit availability truthfully."""
        cache = Cache(tmp_path / "pdf_stats_avail.sqlite3")
        try:
            result = get_pdf_stats(cache=cache)
            assert "pypdf_available" in result
            assert "ocr_available" in result
            assert isinstance(result["pypdf_available"], bool)
            assert isinstance(result["ocr_available"], bool)
        finally:
            cache.close()


# ===================================================================
# TestDocumentPromotion
# ===================================================================


class TestDocumentPromotion:
    """Tests for promote_pdf_to_full_text."""

    def test_no_pdf_url(self) -> None:
        """Promotion without PDF URL returns unchanged."""
        doc = {
            "document_id": "test-1",
            "source": "bedesten",
            "title": "No URL Doc",
            "content_status": "pdf_link_only",
            "source_url": "https://example.com/file.html",
        }
        result = promote_pdf_to_full_text(doc)
        assert result["ok"] is True
        assert result["upgraded"] is False

    def test_upgrade_cannot_download(self) -> None:
        """Promotion with invalid URL fails gracefully."""
        doc = {
            "document_id": "test-2",
            "source": "bedesten",
            "title": "Bad URL Doc",
            "content_status": "pdf_link_only",
            "source_url": "https://invalid.example.com/nonexistent.pdf",
        }
        result = promote_pdf_to_full_text(doc)
        # Should return error (download fails) but not crash
        assert "ok" in result
        if not result["ok"]:  # download failed — expected
            assert "PDF_DOWNLOAD_FAILED" in result.get("errorCode", "")

    def test_promotion_preserves_original_keys(self) -> None:
        """Failed promotion returns the original document."""
        doc = {
            "document_id": "test-3",
            "source": "bedesten",
            "title": "Test Doc",
            "content_status": "pdf_link_only",
            "source_url": "https://example.com/file.pdf",
        }
        result = promote_pdf_to_full_text(doc)
        assert "document" in result
        # Original keys are preserved
        for key in doc:
            assert key in result["document"]


# ===================================================================
# TestUpgradeInCache
# ===================================================================


class TestUpgradeInCache:
    """Tests for try_upgrade_pdf_document and upgrade_all_pdf_documents."""

    def test_document_not_found(self, tmp_path: Path) -> None:
        """Upgrading non-existent document returns error."""
        cache = Cache(tmp_path / "tg_nf.sqlite3")
        try:
            result = try_upgrade_pdf_document(
                "nonexistent", "bedesten", cache=cache
            )
            assert result["ok"] is False
            assert "DOCUMENT_NOT_FOUND" in result.get("errorCode", "")
        finally:
            cache.close()

    def test_not_pdf_status(self, tmp_path: Path) -> None:
        """Upgrading a non-pdf document is skipped."""
        cache = Cache(tmp_path / "tg_notpdf.sqlite3")
        try:
            cache.store_document(
                Document(
                    document_id="ft-1",
                    source="bedesten",
                    title="Full Text Doc",
                    content_status=ContentStatus.FULL_TEXT,
                    full_text="Some content",
                    source_url="https://example.com/file.pdf",
                )
            )
            result = try_upgrade_pdf_document("ft-1", "bedesten", cache=cache)
            assert result["ok"] is True
            assert result["upgraded"] is False
        finally:
            cache.close()

    def test_upgrade_all_empty_cache(self, tmp_path: Path) -> None:
        """upgrade_all on empty cache returns zero."""
        cache = Cache(tmp_path / "tg_all_empty.sqlite3")
        try:
            result = upgrade_all_pdf_documents(cache=cache)
            assert result["ok"] is True
            assert result["processed"] == 0
            assert result["upgraded"] == 0
        finally:
            cache.close()

    def test_upgrade_all_no_pdf_docs(self, tmp_path: Path) -> None:
        """upgrade_all with only full_text docs skips them."""
        cache = Cache(tmp_path / "tg_all_no_pdf.sqlite3")
        try:
            cache.store_document(
                Document(
                    document_id="full-1",
                    source="bedesten",
                    title="Full Text",
                    content_status=ContentStatus.FULL_TEXT,
                    full_text="text here",
                )
            )
            result = upgrade_all_pdf_documents(cache=cache)
            assert result["ok"] is True
            assert result["processed"] == 0
        finally:
            cache.close()


# ===================================================================
# TestCitationSafetyInvariants
# ===================================================================


class TestCitationSafetyInvariants:
    """Tests that citation-safety invariants are preserved."""

    def test_failed_extraction_preserves_status(self, tmp_path: Path) -> None:
        """When extraction fails, document content_status is unchanged."""
        cache = Cache(tmp_path / "inv_preserve.sqlite3")
        try:
            _store_pdf_doc(cache, "pdf-inv-1")
            # Verify it's pdf_link_only
            status_before = cache.db.execute(
                "SELECT content_status FROM documents_v2 WHERE document_id='pdf-inv-1'"
            ).fetchone()[0]
            assert status_before == ContentStatus.PDF_LINK_ONLY

            # try_upgrade will attempt download — will fail in test (no network)
            try_upgrade_pdf_document("pdf-inv-1", "bedesten", cache=cache)

            # Status should still be pdf_link_only (extraction failed but no corruption)
            status_after = cache.db.execute(
                "SELECT content_status FROM documents_v2 WHERE document_id='pdf-inv-1'"
            ).fetchone()[0]
            # Download failed so status should be unchanged
            assert status_after == ContentStatus.PDF_LINK_ONLY
        finally:
            cache.close()

    def test_empty_result_has_no_fabricated_text(self) -> None:
        """Empty extraction never returns fabricated text."""
        result = extract_pdf_text(b"not valid pdf", ocr_enabled=False)
        if result.get("ok"):
            # If ok, text should be empty or "" — never fabricated
            assert result.get("text", "") == ""
        else:
            # Error is acceptable too
            pass

    def test_ocr_only_when_enabled(self) -> None:
        """OCR is never called unless explicitly enabled."""
        # ocr_enabled=False is the default — verify no OCR path
        result = extract_pdf_text(b"not pdf", ocr_enabled=False)
        # Method should not be OCR
        assert result.get("method") != "ocr_pytesseract"