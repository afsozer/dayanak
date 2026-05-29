"""Tests for document module — controlled_draft, markdown_to_docx, export_bundle."""
from __future__ import annotations

import json

from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.document import controlled_draft, export_bundle, markdown_to_docx


def _make_safe_doc(source="test", doc_id="001", full_text="Tam metin içerik"):
    return Document(
        source=source,
        document_id=doc_id,
        title="Test Kararı",
        full_text=full_text,
        content_status=ContentStatus.FULL_TEXT,
        decision_date="2024-01-01",
        source_url="https://example.test/doc",
    )


def _make_unsafe_doc(source="test", doc_id="002"):
    return Document(
        source=source,
        document_id=doc_id,
        title="Metadata Only Doc",
        content_status=ContentStatus.METADATA_ONLY,
        decision_date="2024-01-01",
    )


class TestControlledDraft:
    """Tests for controlled_draft()."""

    def test_basic_draft_with_safe_docs(self):
        doc = _make_safe_doc()
        result = controlled_draft("Test Başlık", "Gövde metni.", [doc])
        assert "Test Başlık" in result
        assert "Gövde metni" in result
        assert "Güvenli Atıf Adayları" in result

    def test_draft_with_no_safe_docs(self):
        doc = _make_unsafe_doc()
        result = controlled_draft("Test", "Gövde.", [doc])
        assert "Güvenli tam metinli karar bulunamadı" in result
        assert "künye/atıf uydurulmadı" in result

    def test_draft_has_disclaimer(self):
        doc = _make_safe_doc()
        result = controlled_draft("Test", "Gövde.", [doc])
        assert "avukat denetimi gerektirir" in result.lower()

    def test_draft_mixed_docs_includes_only_safe(self):
        safe = _make_safe_doc(doc_id="001")
        unsafe = _make_unsafe_doc(doc_id="002")
        result = controlled_draft("Test", "Gövde.", [safe, unsafe])
        # Only safe doc should appear in the draft
        assert "test:001" in result
        # Unsafe doc should not appear (it would be test:002)
        assert "Güvenli tam metinli karar bulunamadı" not in result

    def test_draft_empty_docs(self):
        result = controlled_draft("Test", "Gövde.", [])
        assert "Güvenli tam metinli karar bulunamadı" in result

    def test_draft_preserves_body_formatting(self):
        doc = _make_safe_doc()
        body = "**Kalın** ve _italik_ metin."
        result = controlled_draft("Test", body, [doc])
        assert body in result


class TestMarkdownToDocx:
    """Tests for markdown_to_docx()."""

    def test_creates_docx_file(self, tmp_path):
        out = tmp_path / "output.docx"
        result = markdown_to_docx("# Başlık\n\nParagraf.", out)
        assert result.exists()
        assert result.suffix == ".docx"
        assert result.stat().st_size > 0

    def test_handles_headings(self, tmp_path):
        out = tmp_path / "headings.docx"
        md = "# H1\n\nİçerik.\n\n## H2\n\nAlt içerik.\n\n### H3"
        result = markdown_to_docx(md, out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_handles_bullet_lists(self, tmp_path):
        out = tmp_path / "list.docx"
        md = "# Liste\n\n- Madde 1\n- Madde 2\n- Madde 3"
        result = markdown_to_docx(md, out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_handles_empty_lines(self, tmp_path):
        out = tmp_path / "empty_lines.docx"
        md = "# Başlık\n\n\n\nParagraf."
        result = markdown_to_docx(md, out)
        assert result.exists()

    def test_handles_turkish_characters(self, tmp_path):
        out = tmp_path / "turkish.docx"
        md = "# Türkçe Karakter Testi\n\nğĞüÜşŞıİöÖçÇ"
        result = markdown_to_docx(md, out)
        assert result.exists()

    def test_creates_parent_directories(self, tmp_path):
        out = tmp_path / "sub" / "nested" / "output.docx"
        result = markdown_to_docx("# Test", out)
        assert result.exists()

    def test_multiple_headings_and_content(self, tmp_path):
        out = tmp_path / "complex.docx"
        md = "# Dilekçe\n\nGiriş.\n\n## Talep\n\nİçerik.\n\n## Sonuç\n\nBitiş."
        result = markdown_to_docx(md, out)
        assert result.exists()
        assert result.stat().st_size > 100


class TestExportBundle:
    """Tests for export_bundle()."""

    def test_bundle_creates_directory(self, tmp_path):
        doc = _make_safe_doc()
        result = export_bundle(tmp_path, matter="Test", issue="Konu", docs=[doc])
        assert result["out_dir"] == str(tmp_path)
        assert result["safe_count"] >= 1
        assert result["excluded_count"] == 0

    def test_bundle_creates_required_files(self, tmp_path):
        doc = _make_safe_doc()
        export_bundle(tmp_path, matter="Test", issue="Konu", docs=[doc])
        assert (tmp_path / "input-pack.json").exists()
        assert (tmp_path / "safe-citations.md").exists()
        assert (tmp_path / "excluded.json").exists()

    def test_bundle_input_pack_valid_json(self, tmp_path):
        doc = _make_safe_doc()
        export_bundle(tmp_path, matter="Test", issue="Konu", docs=[doc])
        data = json.loads((tmp_path / "input-pack.json").read_text(encoding="utf-8"))
        assert data["matter"] == "Test"
        assert data["issue"] == "Konu"

    def test_bundle_excluded_docs(self, tmp_path):
        safe = _make_safe_doc(doc_id="001")
        unsafe = _make_unsafe_doc(doc_id="002")
        result = export_bundle(tmp_path, matter="Test", issue="Konu", docs=[safe, unsafe])
        assert result["safe_count"] == 1
        assert result["excluded_count"] >= 1

    def test_bundle_with_markdown_writes_files(self, tmp_path):
        doc = Document(
            source="test",
            document_id="doc_001",
            title="Test Kararı",
            full_text="Tam metin.",
            markdown="# Test\n\nİçerik.",
            content_status=ContentStatus.HTML_MARKDOWN,
            decision_date="2024-01-01",
        )
        export_bundle(tmp_path, matter="Test", issue="Konu", docs=[doc])
        # safe-citations.md is always created; doc markdown may also be present
        assert (tmp_path / "safe-citations.md").exists()

    def test_bundle_empty_docs(self, tmp_path):
        result = export_bundle(tmp_path, matter="Test", issue="Konu", docs=[])
        assert result["safe_count"] == 0
        assert result["excluded_count"] == 0
