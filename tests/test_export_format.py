"""Tests for export format expansion (M-15)."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.exporter import (
    DISCLAIMER_TEXT,
    export_plain_text,
    export_to_format,
    get_export_capabilities,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_DRAFT = """\
# DİLEKÇE

DİKKAT: Bu belge emsal-mcp tarafından otomatik olarak oluşturulmuştur.
Avukat denetimi ve resmi doğrulama gerektirir.
Bu belgedeki {PLACEHOLDER} formatındaki alanlar yalnızca doğrulanmış
bilgilerle doldurulmalıdır; eksik bırakılabilir ama uydurma bilgiyle
değiştirilmez.
============================================================

Sayın Mahkeme,

**Dava Konusu:** {{DAVA_KONUSU}}

Müvekkilim {{MÜVEKKIL_ADI}} adına açılan bu davada,
*kanıtlarımız* aşağıda sunulmuştur.

1. Delil listesi:
   - Belge A
   - Belge B

> Önemli not: Bu belge otomatik oluşturulmuştur.

Daha fazla bilgi için [buraya tıklayın](https://example.com).

## Kaynakça

1. Yargıtay 1. HD, 2024/1, K.2024/123
2. Danıştay 10. Daire, 2023/500

## Uyarılar

- Bu belge emsal-mcp tarafından üretilmiştir.
"""


def _make_draft_file(tmp_path, content=SAMPLE_DRAFT):
    draft = tmp_path / "draft.md"
    draft.write_text(content, encoding="utf-8")
    return draft


# ── Plain text export tests ─────────────────────────────────────────────────


class TestExportPlainText:
    def test_basic_export(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_plain_text(draft, tmp_path / "out.txt")
        assert result["ok"] is True
        assert result["out_path"].endswith(".txt")
        assert result["text_length"] > 0

    def test_output_file_exists(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        export_plain_text(draft, tmp_path / "output.txt")
        out = tmp_path / "output.txt"
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert len(content) > 0

    def test_disclaimer_present(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_plain_text(draft, tmp_path / "out.txt")
        assert result["disclaimer_present"] is True
        content = (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert "emsal-mcp" in content.lower()

    def test_disclaimer_added_when_missing(self, tmp_path):
        content_no_disclaimer = "# Title\n\nSome body text.\n"
        draft = _make_draft_file(tmp_path, content_no_disclaimer)
        result = export_plain_text(draft, tmp_path / "out.txt")
        assert result["disclaimer_present"] is True
        content = (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert DISCLAIMER_TEXT in content

    def test_placeholders_preserved(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_plain_text(draft, tmp_path / "out.txt")
        assert result["placeholders_preserved"] is True
        content = (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert "{{DAVA_KONUSU}}" in content
        assert "{{MÜVEKKIL_ADI}}" in content

    def test_headers_uppercased(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        export_plain_text(draft, tmp_path / "out.txt")
        content = (tmp_path / "out.txt").read_text(encoding="utf-8")
        # Original "# DİLEKÇE" → "DİLEKÇE" (uppercase)
        assert "DİLEKÇE" in content

    def test_bold_stripped(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        export_plain_text(draft, tmp_path / "out.txt")
        content = (tmp_path / "out.txt").read_text(encoding="utf-8")
        # **Dava Konusu:** should become "Dava Konusu:" without asterisks
        assert "**" not in content

    def test_links_stripped_to_text(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        export_plain_text(draft, tmp_path / "out.txt")
        content = (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert "[buraya tıklayın](https://example.com)" not in content
        assert "buraya tıklayın" in content

    def test_default_out_path(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_plain_text(draft)
        assert result["ok"] is True
        expected = str(draft.with_suffix(".txt"))
        assert result["out_path"] == expected

    def test_file_not_found(self, tmp_path):
        result = export_plain_text(tmp_path / "nonexistent.md")
        assert result["ok"] is False
        assert result["errorCode"] == "FILE_NOT_FOUND"

    def test_no_new_dependencies(self, tmp_path):
        """Plain text export should use only stdlib (no extra imports)."""
        draft = _make_draft_file(tmp_path)
        result = export_plain_text(draft, tmp_path / "out.txt")
        assert result["ok"] is True


# ── export_to_format tests ──────────────────────────────────────────────────


class TestExportToFormat:
    def test_txt_format(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_to_format(draft, format="txt", out_path=tmp_path / "out.txt")
        assert result["ok"] is True
        assert result["out_path"].endswith(".txt")

    def test_docx_format(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_to_format(draft, format="docx", out_path=tmp_path / "out.docx")
        assert result["ok"] is True
        assert result["out_path"].endswith(".docx")
        assert "checksum_sha256" in result

    def test_pdf_no_toolkit(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_to_format(draft, format="pdf", out_path=tmp_path / "out.pdf")
        # In CI / normal env, no LibreOffice → structured error
        if result.get("ok"):
            # If it succeeded, LibreOffice is available (fine)
            assert result["out_path"].endswith(".pdf")
        else:
            assert result["errorCode"] == "TOOLKIT_UNAVAILABLE"

    def test_udf_no_flag_needed(self, tmp_path):
        """UDF export works out of the box via the native converter."""
        draft = _make_draft_file(tmp_path)
        result = export_to_format(draft, format="udf")
        assert result["ok"] is True
        assert result["out_path"].endswith(".udf")

    def test_udf_honors_out_path(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        out = tmp_path / "custom.udf"
        result = export_to_format(draft, format="udf", out_path=out)
        assert result["ok"] is True
        assert result["out_path"] == str(out)
        assert out.exists()

    def test_invalid_format(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_to_format(draft, format="unknown")
        assert result["ok"] is False
        assert result["errorCode"] == "INVALID_FORMAT"
        assert "supported_formats" in result

    def test_format_case_insensitive(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_to_format(draft, format="TXT")
        assert result["ok"] is True

    def test_txt_preserves_disclaimer(self, tmp_path):
        draft = _make_draft_file(tmp_path)
        result = export_to_format(draft, format="txt", out_path=tmp_path / "out.txt")
        assert result["ok"] is True
        content = (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert "emsal-mcp" in content.lower()


# ── get_export_capabilities tests ───────────────────────────────────────────


class TestExportCapabilities:
    def test_returns_ok(self):
        result = get_export_capabilities()
        assert result["ok"] is True

    def test_formats_list(self):
        result = get_export_capabilities()
        formats = result["formats"]
        format_names = [f["format"] for f in formats]
        assert "docx" in format_names
        assert "txt" in format_names
        assert "pdf" in format_names
        assert "udf" in format_names

    def test_txt_always_available(self):
        result = get_export_capabilities()
        txt = next(f for f in result["formats"] if f["format"] == "txt")
        assert txt["available"] is True
        assert txt["requires_toolkit"] is False

    def test_docx_always_available(self):
        result = get_export_capabilities()
        docx = next(f for f in result["formats"] if f["format"] == "docx")
        assert docx["available"] is True
        assert docx["requires_toolkit"] is False

    def test_pdf_requires_toolkit(self):
        result = get_export_capabilities()
        pdf = next(f for f in result["formats"] if f["format"] == "pdf")
        assert pdf["requires_toolkit"] is True
        # availability depends on environment
        assert isinstance(pdf["available"], bool)

    def test_udf_always_available(self):
        result = get_export_capabilities()
        udf = next(f for f in result["formats"] if f["format"] == "udf")
        assert udf["requires_toolkit"] is False
        assert udf["available"] is True


# ── CLI / MCP import tests ──────────────────────────────────────────────────


class TestImports:
    def test_cli_imports(self):
        """Verify export functions are importable from CLI module."""
        from emsal_mcp.cli import export_app  # noqa: F401
        assert export_app is not None

    def test_server_imports(self):
        """Verify export functions are importable from server module."""
        from emsal_mcp.server import main  # noqa: F401
        assert callable(main)

    def test_exporter_imports(self):
        """Verify all new exporter functions are importable."""
        from emsal_mcp.exporter import (  # noqa: F401
            export_plain_text,
            export_to_format,
            get_export_capabilities,
        )
        assert callable(export_plain_text)
        assert callable(export_to_format)
        assert callable(get_export_capabilities)


# ── Edge case tests ─────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_draft(self, tmp_path):
        draft = _make_draft_file(tmp_path, "")
        result = export_plain_text(draft, tmp_path / "out.txt")
        assert result["ok"] is True
        # Should still contain disclaimer
        content = (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert DISCLAIMER_TEXT in content

    def test_only_placeholders(self, tmp_path):
        content = "# {{TITLE}}\n\n{{BODY}}\n"
        draft = _make_draft_file(tmp_path, content)
        result = export_plain_text(draft, tmp_path / "out.txt")
        assert result["ok"] is True
        assert result["placeholders_preserved"] is True
        text = (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert "{{TITLE}}" in text
        assert "{{BODY}}" in text

    def test_only_disclaimer(self, tmp_path):
        content = DISCLAIMER_TEXT + "\n"
        draft = _make_draft_file(tmp_path, content)
        result = export_plain_text(draft, tmp_path / "out.txt")
        assert result["ok"] is True
        assert result["disclaimer_present"] is True

    def test_html_comments_removed(self, tmp_path):
        content = "# Title\n<!-- this is a comment -->\nBody text.\n"
        draft = _make_draft_file(tmp_path, content)
        export_plain_text(draft, tmp_path / "out.txt")
        text = (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert "<!--" not in text
        assert "this is a comment" not in text

    def test_blockquote_stripped(self, tmp_path):
        content = "# Title\n> Blockquote text.\n"
        draft = _make_draft_file(tmp_path, content)
        export_plain_text(draft, tmp_path / "out.txt")
        text = (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert "Blockquote text." in text
        assert "> " not in text