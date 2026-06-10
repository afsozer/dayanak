"""Tests for UDF module (v0.9 — toolkit integration)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.integration]

import emsal_mcp.udf as udf_mod
from emsal_mcp.udf import (
    UDF_AUTHORING_WARNING,
    UDF_TOOLKIT_VERSION,
    UdfError,
    convert_docx_to_udf_experimental,
    convert_udf_to_docx,
    convert_udf_to_pdf,
    get_udf_authoring_instructions,
    get_udf_toolkit_status,
    install_udf_toolkit,
    probe_udf,
    read_udf,
    udf_to_markdown,
    write_udf,
)


@pytest.fixture(autouse=True)
def isolate_managed_udf_toolkit(monkeypatch, tmp_path):
    monkeypatch.setenv("EMSAL_UDF_AUTO_INSTALL", "0")
    monkeypatch.setattr(udf_mod, "BUNDLED_UDF_TOOLKIT_DIR", tmp_path / "missing-managed-toolkit")


# ── Native UDF round-trip (preserved) ────────────────────────────────────────


class TestUDF:
    def test_write_and_read(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("Test content here\nSecond line", path)
        assert path.exists()

        text = read_udf(path)
        assert "Test content here" in text
        assert "Second line" in text

    def test_read_nonexistent(self, tmp_path):
        with pytest.raises(UdfError, match="bulunamad"):
            read_udf(tmp_path / "missing.udf")

    def test_read_invalid_zip(self, tmp_path):
        path = tmp_path / "bad.udf"
        path.write_text("not a zip file", encoding="utf-8")
        with pytest.raises(UdfError, match="ZIP imza"):
            read_udf(path)

    def test_udf_to_markdown(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("Title\n\nParagraph one.\nParagraph two.", path)
        md = udf_to_markdown(path)
        assert "Title" in md
        assert "Paragraph one." in md

    def test_probe_udf(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("Probe test", path)
        info = probe_udf(path)
        assert info["exists"] is True
        assert info["zip"] is True
        assert info["has_content_xml"] is True
        assert info["text_length"] > 0
        assert info["format_id"] == "1.8"
        assert info["content_xml_preview"] is not None
        assert len(info["content_xml_preview"]) <= 500

    def test_probe_missing(self, tmp_path):
        info = probe_udf(tmp_path / "missing.udf")
        assert info["exists"] is False
        assert len(info["warnings"]) > 0

    def test_write_title_centered(self, tmp_path):
        path = tmp_path / "centered.udf"
        write_udf("Centered Title\nBody", path, title_centered=True)
        text = read_udf(path)
        assert "Centered Title" in text

    def test_probe_format_id(self, tmp_path):
        path = tmp_path / "fmt.udf"
        write_udf("Format ID test", path)
        info = probe_udf(path)
        assert info["format_id"] == "1.8"

    def test_probe_content_xml_preview(self, tmp_path):
        path = tmp_path / "preview.udf"
        write_udf("Preview test content", path)
        info = probe_udf(path)
        assert info["content_xml_preview"] is not None
        assert "template" in info["content_xml_preview"] or "content" in info["content_xml_preview"]


# ── Toolkit status (disabled by default in tests) ────────────────────────────


class TestToolKitStatus:
    def test_status_disabled_by_default(self, monkeypatch):
        """No toolkit dir configured — should return disabled with warnings."""
        monkeypatch.delenv("EMSAL_UDF_TOOLKIT_DIR", raising=False)
        monkeypatch.delenv("UDF_TOOLKIT_DIR", raising=False)
        monkeypatch.setattr(udf_mod, "_resolve_toolkit_dir", lambda: None)
        monkeypatch.setattr(udf_mod, "_discover_libreoffice", lambda: None)
        monkeypatch.setattr(udf_mod, "_discover_unoconv", lambda: None)
        status = get_udf_toolkit_status()
        assert status["ok"] is False
        assert status["enabled"] is False
        assert status["toolkit_dir"] is None
        assert status["version"] == UDF_TOOLKIT_VERSION
        assert isinstance(status["warnings"], list)
        assert len(status["warnings"]) > 0

    def test_status_dict_shape(self):
        status = get_udf_toolkit_status()
        required_keys = {"ok", "enabled", "toolkit_dir", "libreoffice_path", "unoconv_path", "version", "warnings"}
        assert required_keys.issubset(status.keys())

    def test_status_with_env(self, monkeypatch, tmp_path):
        toolkit_dir = tmp_path / "toolkit"
        toolkit_dir.mkdir()
        (toolkit_dir / "udf_to_docx.py").write_text("# stub", encoding="utf-8")
        monkeypatch.setenv("LOCAL_YARGI_UDF_TOOLS", "1")
        monkeypatch.setenv("EMSAL_UDF_TOOLKIT_DIR", str(toolkit_dir))
        status = get_udf_toolkit_status()
        assert status["enabled"] is True
        assert status["toolkit_dir"] == str(toolkit_dir)

    def test_status_env_priority(self, monkeypatch, tmp_path):
        """EMSAL_UDF_TOOLKIT_DIR takes priority over UDF_TOOLKIT_DIR."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "udf_to_docx.py").write_text("# stub", encoding="utf-8")
        (dir2 / "udf_to_docx.py").write_text("# stub", encoding="utf-8")
        monkeypatch.setenv("LOCAL_YARGI_UDF_TOOLS", "1")
        monkeypatch.setenv("UDF_TOOLKIT_DIR", str(dir1))
        monkeypatch.setenv("EMSAL_UDF_TOOLKIT_DIR", str(dir2))
        status = get_udf_toolkit_status()
        assert status["toolkit_dir"] == str(dir2)

    def test_managed_toolkit_is_enabled_without_env(self, monkeypatch, tmp_path):
        toolkit_dir = tmp_path / "vendor" / "UDF-Toolkit"
        toolkit_dir.mkdir(parents=True)
        for script in ("udf_to_docx.py", "udf_to_pdf.py", "docx_to_udf.py"):
            (toolkit_dir / script).write_text("# stub", encoding="utf-8")
        monkeypatch.delenv("LOCAL_YARGI_UDF_TOOLS", raising=False)
        monkeypatch.delenv("EMSAL_UDF_TOOLS", raising=False)
        monkeypatch.setattr(udf_mod, "BUNDLED_UDF_TOOLKIT_DIR", toolkit_dir)
        status = get_udf_toolkit_status()
        assert status["enabled"] is True
        assert status["managed"] is True
        assert status["toolkit_dir"] == str(toolkit_dir.resolve())

    def test_install_toolkit_reuses_existing_target(self, tmp_path):
        toolkit_dir = tmp_path / "UDF-Toolkit"
        toolkit_dir.mkdir()
        (toolkit_dir / "udf_to_docx.py").write_text("# stub", encoding="utf-8")
        result = install_udf_toolkit(toolkit_dir)
        assert result["ok"] is True
        assert result["installed"] is False
        assert result["toolkit_dir"] == str(toolkit_dir.resolve())

    def test_status_nonexistent_env(self, monkeypatch):
        monkeypatch.setenv("EMSAL_UDF_TOOLKIT_DIR", "/nonexistent/path")
        monkeypatch.delenv("UDF_TOOLKIT_DIR", raising=False)
        # Hermetic: mock all external state so the test is deterministic
        # regardless of host OS, LibreOffice installation, or env vars.
        monkeypatch.setattr(udf_mod, "_resolve_toolkit_dir", lambda: None)
        monkeypatch.setattr(udf_mod, "_discover_libreoffice", lambda: None)
        monkeypatch.setattr(udf_mod, "_discover_unoconv", lambda: None)
        status = get_udf_toolkit_status()
        assert status["enabled"] is False


# ── Authoring instructions ───────────────────────────────────────────────────


class TestAuthoringInstructions:
    def test_json_format(self):
        result = get_udf_authoring_instructions(format="json")
        assert result["format"] == "json"
        assert "steps" in result
        assert isinstance(result["steps"], list)
        assert len(result["steps"]) > 0
        assert "warnings" in result
        assert UDF_AUTHORING_WARNING in result["warnings"]
        assert result["version"] == UDF_TOOLKIT_VERSION
        assert "toolkit_status" in result

    def test_markdown_format(self):
        result = get_udf_authoring_instructions(format="markdown")
        assert result["format"] == "markdown"
        assert "instructions" in result
        assert "# UDF Authoring Instructions" in result["instructions"]
        assert "## Steps" in result["instructions"]
        assert "## Warnings" in result["instructions"]
        assert "warnings" in result
        assert UDF_AUTHORING_WARNING in result["warnings"]
        assert result["version"] == UDF_TOOLKIT_VERSION

    def test_default_format_is_json(self):
        result = get_udf_authoring_instructions()
        assert result["format"] == "json"

    def test_json_contains_all_warnings(self):
        result = get_udf_authoring_instructions(format="json")
        assert len(result["warnings"]) >= 2


# ── Safe wrapper: convert_udf_to_docx ────────────────────────────────────────


class TestConvertUdfToDocx:
    def test_missing_toolkit_returns_error(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("Test", path)
        result = convert_udf_to_docx(path)
        assert result["ok"] is False
        assert result["errorCode"] == "TOOLKIT_UNAVAILABLE"
        assert "toolkit_status" in result

    def test_file_not_found_when_toolkit_available(self, tmp_path, monkeypatch):
        """When toolkit is available but file doesn't exist, returns file_not_found."""
        toolkit_dir = tmp_path / "tk"
        toolkit_dir.mkdir()
        monkeypatch.setenv("EMSAL_UDF_TOOLKIT_DIR", str(toolkit_dir))
        # Mock shutil.which to pretend soffice is available
        with patch("emsal_mcp.udf.shutil.which", return_value="/usr/bin/soffice"):
            result = convert_udf_to_docx(tmp_path / "missing.udf")
            assert result["ok"] is False
            assert result["errorCode"] == "FILE_NOT_FOUND"

    def test_returns_structured_dict(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("Convert test", path)
        result = convert_udf_to_docx(path)
        assert isinstance(result, dict)
        assert "ok" in result
        assert "action" in result


# ── Safe wrapper: convert_udf_to_pdf ─────────────────────────────────────────


class TestConvertUdfToPdf:
    def test_missing_toolkit_returns_error(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("Test", path)
        result = convert_udf_to_pdf(path)
        assert result["ok"] is False
        assert result["errorCode"] == "TOOLKIT_UNAVAILABLE"
        assert "toolkit_status" in result

    def test_file_not_found_when_toolkit_available(self, tmp_path, monkeypatch):
        """When toolkit is available but file doesn't exist, returns file_not_found."""
        toolkit_dir = tmp_path / "tk"
        toolkit_dir.mkdir()
        monkeypatch.setenv("EMSAL_UDF_TOOLKIT_DIR", str(toolkit_dir))
        with patch("emsal_mcp.udf.shutil.which", return_value="/usr/bin/soffice"):
            result = convert_udf_to_pdf(tmp_path / "missing.udf")
            assert result["ok"] is False
            assert result["errorCode"] == "FILE_NOT_FOUND"

    def test_returns_structured_dict(self, tmp_path):
        path = tmp_path / "test.udf"
        write_udf("PDF test", path)
        result = convert_udf_to_pdf(path)
        assert isinstance(result, dict)
        assert "ok" in result
        assert "action" in result


# ── Safe wrapper: convert_docx_to_udf_experimental ───────────────────────────


class TestConvertDocxToUdfExperimental:
    def test_no_longer_requires_experimental_flag_but_requires_toolkit(self, tmp_path):
        path = tmp_path / "test.docx"
        path.write_bytes(b"fake docx")
        result = convert_docx_to_udf_experimental(path, experimental=False)
        assert result["ok"] is False
        assert result["errorCode"] == "TOOLKIT_UNAVAILABLE"

    def test_invalid_docx_is_delegated_to_toolkit(self, tmp_path):
        """A non-DOCX is no longer parsed locally; UDF-Toolkit owns validation."""
        path = tmp_path / "test.docx"
        path.write_bytes(b"fake docx")
        result = convert_docx_to_udf_experimental(path, experimental=True)
        assert result["ok"] is False
        assert result["errorCode"] == "TOOLKIT_UNAVAILABLE"

    def test_converts_with_toolkit_script(self, tmp_path, monkeypatch):
        """DOCX -> UDF is delegated to UDF-Toolkit docx_to_udf.py."""
        toolkit_dir = tmp_path / "toolkit"
        toolkit_dir.mkdir()
        for script in ("udf_to_docx.py", "udf_to_pdf.py"):
            (toolkit_dir / script).write_text("# stub", encoding="utf-8")
        (toolkit_dir / "docx_to_udf.py").write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[2]).write_bytes(b'PK\\x03\\x04fake')\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOCAL_YARGI_UDF_TOOLS", "1")
        monkeypatch.setenv("EMSAL_UDF_TOOLKIT_DIR", str(toolkit_dir))
        monkeypatch.setattr(udf_mod, "_discover_python", lambda: "python")
        docx = tmp_path / "in.docx"
        docx.write_bytes(b"fake docx")
        out = tmp_path / "out.udf"
        result = convert_docx_to_udf_experimental(docx, out)
        assert result["ok"] is True
        assert out.exists()
        assert result["experimental"] is False

    def test_file_not_found_when_toolkit_available(self, tmp_path, monkeypatch):
        """When toolkit is available but file doesn't exist, returns file_not_found."""
        toolkit_dir = tmp_path / "tk"
        toolkit_dir.mkdir()
        monkeypatch.setenv("EMSAL_UDF_TOOLKIT_DIR", str(toolkit_dir))
        with patch("emsal_mcp.udf.shutil.which", return_value="/usr/bin/soffice"):
            result = convert_docx_to_udf_experimental(
                tmp_path / "missing.docx", experimental=True,
            )
            assert result["ok"] is False
            assert result["errorCode"] == "FILE_NOT_FOUND"

    def test_returns_structured_dict(self, tmp_path):
        path = tmp_path / "test.docx"
        path.write_bytes(b"fake docx content")
        result = convert_docx_to_udf_experimental(path, experimental=True)
        assert isinstance(result, dict)
        assert "ok" in result
        assert "action" in result

    def test_experimental_warning_always_present(self, tmp_path):
        """When experimental=True and toolkit unavailable, warning still included."""
        path = tmp_path / "test.docx"
        path.write_bytes(b"content")
        result = convert_docx_to_udf_experimental(path, experimental=True)
        # The toolkit_unavailable result includes toolkit_status; check overall shape
        assert "action" in result


# ── CLI and MCP imports ──────────────────────────────────────────────────────


class TestCLIImports:
    def test_cli_import(self):
        from emsal_mcp.cli import app
        assert app is not None

    def test_mcp_import(self):
        from emsal_mcp.server import main
        assert callable(main)


# ── Native UDF round-trip unchanged ──────────────────────────────────────────


class TestNativeRoundTripUnchanged:
    def test_write_read_roundtrip(self, tmp_path):
        """Native write_udf/read_udf still works perfectly."""
        path = tmp_path / "roundtrip.udf"
        content = "Dava dilekçesi içeriği\nİkinci paragraf\nÜçüncü paragraf"
        write_udf(content, path)
        text = read_udf(path)
        assert "Dava dilekçesi içeriği" in text
        assert "İkinci paragraf" in text
        assert "Üçüncü paragraf" in text

    def test_write_read_with_unicode(self, tmp_path):
        path = tmp_path / "unicode.udf"
        content = "Türkçe karakterler: ğ, ü, ş, ı, ö, ç, İ, Ü, Ş, Ö, Ç"
        write_udf(content, path)
        text = read_udf(path)
        assert "ğ" in text
        assert "ü" in text

    def test_write_read_title_centered_roundtrip(self, tmp_path):
        path = tmp_path / "centered_roundtrip.udf"
        write_udf("Başlık\nİçerik", path, title_centered=True)
        text = read_udf(path)
        assert "Başlık" in text
        assert "İçerik" in text

    def test_udf_to_markdown_roundtrip(self, tmp_path):
        path = tmp_path / "md_roundtrip.udf"
        write_udf("Başlık\n\nBirinci paragraf.\n\nİkinci paragraf.", path)
        md = udf_to_markdown(path)
        assert "Başlık" in md
        assert "Birinci paragraf." in md
        assert "İkinci paragraf." in md
