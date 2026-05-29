"""Tests for PDF content extraction (M-27)."""
from __future__ import annotations

import tempfile

from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.pdf_extract import (
    PDF_EXTRACT_VERSION,
    extract_pdf_text,
    get_pdf_toolkit_status,
    promote_pdf_to_full_text,
)


class TestExtractPdfText:
    """Tests for extract_pdf_text()."""

    def test_nonexistent_file_returns_error(self):
        result = extract_pdf_text("/nonexistent/file.pdf")
        assert result["ok"] is False
        assert result["errorCode"] == "FILE_NOT_FOUND"
        assert "PDF not found" in result["message"]

    def test_non_pdf_file_returns_error(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("Not a PDF")
            f.flush()
            result = extract_pdf_text(f.name)
            # Should fail gracefully (pypdf will raise)
            assert result["ok"] is False
            assert "warnings" in result

    def test_empty_pdf_returns_fail(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            # Write minimal invalid PDF
            f.write(
                b"%PDF-1.0\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
                b"xref\n0 0\ntrailer\n<< /Size 1 /Root 1 0 R >>\n"
                b"startxref\n0\n%%EOF"
            )
            f.flush()
            result = extract_pdf_text(f.name)
            # Should fail gracefully with warnings
            assert result["ok"] is False
            assert result["text_length"] == 0
            assert isinstance(result["warnings"], list)

    def test_returns_expected_keys(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.0\n")
            f.flush()
            result = extract_pdf_text(f.name)
            assert "ok" in result
            assert "text" in result
            assert "text_length" in result
            assert "method" in result
            assert "warnings" in result

    def test_ocr_flag_accepted(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.0\n")
            f.flush()
            result = extract_pdf_text(f.name, ocr_enabled=True)
            # Should still fail gracefully
            assert result["ok"] is False
            assert isinstance(result["warnings"], list)

    def test_version_string(self):
        assert isinstance(PDF_EXTRACT_VERSION, str)
        assert PDF_EXTRACT_VERSION == "2.2.0"


class TestGetPdfToolkitStatus:
    """Tests for get_pdf_toolkit_status()."""

    def test_returns_expected_keys(self):
        result = get_pdf_toolkit_status()
        assert "ok" in result
        assert "available_tools" in result
        assert "unavailable_tools" in result
        assert isinstance(result["available_tools"], list)
        assert isinstance(result["unavailable_tools"], list)

    def test_ok_is_boolean(self):
        result = get_pdf_toolkit_status()
        assert isinstance(result["ok"], bool)

    def test_all_tools_listed(self):
        result = get_pdf_toolkit_status()
        all_tools = set(result["available_tools"] + result["unavailable_tools"])
        assert all_tools == {"pypdf", "pytesseract", "pdf2image", "pillow"}


class TestPromotePdfToFullText:
    """Tests for promote_pdf_to_full_text()."""

    def test_non_pdf_only_doc_returns_error(self):
        doc = Document(
            source="test",
            document_id="001",
            title="Test",
            content_status=ContentStatus.FULL_TEXT,
            full_text="Some text",
        )
        result = promote_pdf_to_full_text(doc)
        assert result["ok"] is False
        assert "not pdf_only" in result["message"]

    def test_pdf_only_without_source_url_returns_error(self):
        doc = Document(
            source="test",
            document_id="001",
            title="Test",
            content_status=ContentStatus.PDF_LINK_ONLY,
        )
        result = promote_pdf_to_full_text(doc)
        assert result["ok"] is False
        assert result["errorCode"] == "NO_SOURCE_URL"

    def test_pdf_only_with_source_url_returns_not_implemented(self):
        doc = Document(
            source="test",
            document_id="001",
            title="Test",
            content_status=ContentStatus.PDF_LINK_ONLY,
            source_url="https://example.com/doc.pdf",
        )
        result = promote_pdf_to_full_text(doc)
        assert result["ok"] is True
        assert result["promoted"] is False
        assert result["method"] == "not_implemented_download"
        assert "document" in result

    def test_dict_input_accepted(self):
        doc_dict = {
            "source": "test",
            "document_id": "001",
            "title": "Test",
            "content_status": "pdf_link_only",
            "source_url": "https://example.com/doc.pdf",
        }
        result = promote_pdf_to_full_text(doc_dict)
        assert result["ok"] is True
        assert result["promoted"] is False


class TestImports:
    """Test that CLI and MCP imports work."""

    def test_pdf_extract_imports(self):
        from emsal_mcp.pdf_extract import (
            extract_pdf_text,
            get_pdf_toolkit_status,
            promote_pdf_to_full_text,
        )

        assert callable(extract_pdf_text)
        assert callable(get_pdf_toolkit_status)
        assert callable(promote_pdf_to_full_text)
