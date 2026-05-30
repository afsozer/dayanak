"""Tests for v2.5 PII Redaction & Privacy Audit (M-37)."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

import tempfile
from pathlib import Path

from emsal_mcp.privacy import PRIVACY_VERSION, audit_privacy, redact_pii, scan_pii


# ---------------------------------------------------------------------------
# scan_pii tests
# ---------------------------------------------------------------------------

class TestScanPII:
    def test_scan_detects_tckn(self):
        """TCKN (11-digit) should be detected with high confidence."""
        result = scan_pii("TCKN: 12345678901.")
        assert result["ok"] is True
        assert result["findings_count"] >= 1
        tckn_findings = [f for f in result["findings"] if f["type"] == "tckn"]
        assert len(tckn_findings) == 1
        assert tckn_findings[0]["value"] == "12345678901"
        assert tckn_findings[0]["confidence"] == "high"

    def test_scan_detects_phone(self):
        """Turkish mobile phone numbers should be detected."""
        result = scan_pii("Tel: 0532 123 45 67")
        assert result["ok"] is True
        phone_findings = [f for f in result["findings"] if f["type"] == "phone"]
        assert len(phone_findings) >= 1

    def test_scan_detects_email(self):
        """Email addresses should be detected with high confidence."""
        result = scan_pii("Email: test@example.com")
        assert result["ok"] is True
        email_findings = [f for f in result["findings"] if f["type"] == "email"]
        assert len(email_findings) == 1
        assert email_findings[0]["value"] == "test@example.com"
        assert email_findings[0]["confidence"] == "high"

    def test_scan_empty_text_no_findings(self):
        """Empty text should return no findings."""
        result = scan_pii("")
        assert result["ok"] is True
        assert result["findings_count"] == 0
        assert result["findings"] == []
        assert result["risk_level"] == "low"

    def test_scan_no_pii(self):
        """Text without PII should return no findings."""
        result = scan_pii("Bu metinde herhangi bir kişisel bilgi yoktur.")
        assert result["ok"] is True
        assert result["findings_count"] == 0
        assert result["risk_level"] == "low"

    def test_scan_risk_levels(self):
        """Risk level should be high when >3 findings."""
        text = "12345678901, 23456789012, 34567890123, 45678901234, 56789012345"
        result = scan_pii(text)
        assert result["ok"] is True
        assert result["risk_level"] == "high"

    def test_scan_medium_risk(self):
        """Risk level should be medium when 1-3 findings."""
        result = scan_pii("TCKN: 12345678901")
        assert result["ok"] is True
        assert result["risk_level"] == "medium"

    def test_scan_multiple_pii_types(self):
        """Scan should detect multiple PII types in same text."""
        text = "Adım Ali. TCKN: 12345678901. Tel: 05321234567. Email: ali@test.com"
        result = scan_pii(text)
        assert result["ok"] is True
        types_found = {f["type"] for f in result["findings"]}
        assert "tckn" in types_found
        assert "email" in types_found

    def test_scan_has_version(self):
        """Scan result should include version."""
        result = scan_pii("test")
        assert result["version"] == PRIVACY_VERSION


# ---------------------------------------------------------------------------
# redact_pii tests
# ---------------------------------------------------------------------------

class TestRedactPII:
    def test_redact_masks_tckn(self):
        """TCKN should be replaced with [TCKN_REDACTED]."""
        result = redact_pii("TCKN: 12345678901")
        assert result["ok"] is True
        assert "[TCKN_REDACTED]" in result["redacted_text"]
        assert "12345678901" not in result["redacted_text"]
        assert result["redactions_applied"] is True

    def test_redact_masks_phone(self):
        """Phone numbers should be replaced."""
        result = redact_pii("Tel: 05321234567")
        assert result["ok"] is True
        assert "[PHONE_REDACTED]" in result["redacted_text"]

    def test_redact_masks_email(self):
        """Emails should be replaced."""
        result = redact_pii("Email: test@example.com")
        assert result["ok"] is True
        assert "[EMAIL_REDACTED]" in result["redacted_text"]
        assert "test@example.com" not in result["redacted_text"]

    def test_redact_returns_copy(self):
        """Original text should be unchanged."""
        original = "TCKN: 12345678901"
        result = redact_pii(original)
        assert result["ok"] is True
        assert original == "TCKN: 12345678901"  # original unchanged
        assert result["original_length"] == len(original)

    def test_redact_no_pii(self):
        """Text without PII should pass through unchanged."""
        text = "Bu metinde kişisel bilgi yok."
        result = redact_pii(text)
        assert result["ok"] is True
        assert result["redactions_applied"] is False
        assert result["redacted_text"] == text

    def test_redact_empty_text(self):
        """Empty text should produce empty redacted text."""
        result = redact_pii("")
        assert result["ok"] is True
        assert result["redacted_text"] == ""
        assert result["redactions_applied"] is False

    def test_redact_has_warning(self):
        """Redact result should include copy warning."""
        result = redact_pii("test")
        assert "warning" in result
        assert "original unmodified" in result["warning"].lower()


# ---------------------------------------------------------------------------
# audit_privacy tests
# ---------------------------------------------------------------------------

class TestAuditPrivacy:
    def test_audit_scans_directory(self):
        """Audit should scan all supported files in a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # File with PII
            (tmp / "doc1.md").write_text("TCKN: 12345678901", encoding="utf-8")
            # File without PII
            (tmp / "doc2.txt").write_text("Bu dosyada bilgi yok.", encoding="utf-8")
            # Unsupported file type (should be skipped)
            (tmp / "image.png").write_bytes(b"\x89PNG")

            result = audit_privacy(tmp)
            assert result["ok"] is True
            assert result["files_scanned"] >= 2
            assert result["files_with_pii"] >= 1
            assert len(result["findings"]) >= 1
            assert result["findings"][0]["findings"] >= 1

    def test_audit_scans_single_file(self):
        """Audit should scan a single file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("TCKN: 12345678901 ve email: test@test.com")
            tmppath = f.name

        try:
            result = audit_privacy(tmppath)
            assert result["ok"] is True
            assert result["files_scanned"] == 1
            assert result["files_with_pii"] == 1
        finally:
            Path(tmppath).unlink(missing_ok=True)

    def test_audit_nonexistent_path(self):
        """Audit of nonexistent path should return error."""
        result = audit_privacy("/nonexistent/path/to/file.md")
        assert result["ok"] is False
        assert "errorCode" in result

    def test_audit_clean_directory(self):
        """Audit of clean directory should show 0 files_with_pii."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "clean.txt").write_text("Temiz dosya.", encoding="utf-8")
            result = audit_privacy(tmp)
            assert result["ok"] is True
            assert result["files_with_pii"] == 0
            assert result["findings"] == []

    def test_audit_has_warning(self):
        """Audit should include heuristic warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = audit_privacy(tmpdir)
            assert "warning" in result
            assert "heuristic" in result["warning"].lower()

    def test_audit_has_version(self):
        """Audit result should include version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = audit_privacy(tmpdir)
            assert result["version"] == PRIVACY_VERSION


# ---------------------------------------------------------------------------
# CLI / MCP import tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_privacy_importable(self):
        import emsal_mcp.privacy
        assert hasattr(emsal_mcp.privacy, "scan_pii")
        assert hasattr(emsal_mcp.privacy, "redact_pii")
        assert hasattr(emsal_mcp.privacy, "audit_privacy")
        assert hasattr(emsal_mcp.privacy, "PRIVACY_VERSION")

    def test_cli_importable(self):
        from emsal_mcp.cli import app, privacy_app
        assert callable(app)
        assert callable(privacy_app)

    def test_server_importable(self):
        from emsal_mcp.server import main
        assert callable(main)