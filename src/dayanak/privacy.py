"""PII detection and redaction for Turkish legal documents — v2.5"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import build_error

PRIVACY_VERSION = "2.5.0"

# Turkish PII patterns
_TC_KIMLIK_RE = re.compile(r"\b[1-9]\d{10}\b")  # 11-digit TCKN
_PHONE_RE = re.compile(
    r"\b(?:0[5-7]\d{2}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}"
    r"|0\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2})\b"
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Common Turkish name patterns (surname + name patterns)
_NAME_RE = re.compile(
    r"\b(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+\s+){1,3}[A-ZÇĞİÖŞÜ][a-zçğıöşü]+\b"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_pii(text: str) -> dict[str, Any]:
    """Scan text for potential PII. Returns findings without modifying text.

    Args:
        text: Input text to scan.

    Returns:
        Dict with ok, findings_count, findings list, risk_level.
    """
    findings: list[dict[str, Any]] = []

    for match in _TC_KIMLIK_RE.finditer(text):
        findings.append({
            "type": "tckn",
            "value": match.group(),
            "start": match.start(),
            "confidence": "high",
        })
    for match in _PHONE_RE.finditer(text):
        findings.append({
            "type": "phone",
            "value": match.group(),
            "start": match.start(),
            "confidence": "medium",
        })
    for match in _EMAIL_RE.finditer(text):
        findings.append({
            "type": "email",
            "value": match.group(),
            "start": match.start(),
            "confidence": "high",
        })

    risk_level = "high" if len(findings) > 3 else ("medium" if findings else "low")

    return {
        "ok": True,
        "findings_count": len(findings),
        "findings": findings,
        "risk_level": risk_level,
        "version": PRIVACY_VERSION,
    }


def redact_pii(text: str) -> dict[str, Any]:
    """Redact PII from text. Returns redacted text (original unchanged).

    Args:
        text: Input text to redact.

    Returns:
        Dict with ok, redacted_text, original_length, redactions_applied, warning.
    """
    redacted = text
    redacted = _TC_KIMLIK_RE.sub("[TCKN_REDACTED]", redacted)
    redacted = _PHONE_RE.sub("[PHONE_REDACTED]", redacted)
    redacted = _EMAIL_RE.sub("[EMAIL_REDACTED]", redacted)

    return {
        "ok": True,
        "redacted_text": redacted,
        "original_length": len(text),
        "redactions_applied": text != redacted,
        "warning": "Redaction applied to COPY — original unmodified.",
        "version": PRIVACY_VERSION,
    }


def audit_privacy(path: str | Path) -> dict[str, Any]:
    """Audit a file or directory for PII.

    Args:
        path: File or directory path to audit.

    Returns:
        Dict with ok, files_scanned, files_with_pii, findings, warning.
    """
    p = Path(path)
    if not p.exists():
        return build_error("FILE_NOT_FOUND", f"Path not found: {p}")

    results: list[dict[str, Any]] = []
    files = [p] if p.is_file() else list(p.rglob("*"))

    for f in files:
        if f.is_file() and f.suffix in (".md", ".txt", ".json", ".docx"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                scan = scan_pii(text)
                if scan["findings_count"] > 0:
                    results.append({
                        "path": str(f),
                        "findings": scan["findings_count"],
                        "risk": scan["risk_level"],
                        "types": list({f["type"] for f in scan["findings"]}),
                    })
            except Exception:
                pass

    return {
        "ok": True,
        "files_scanned": len(files),
        "files_with_pii": len(results),
        "findings": results,
        "warning": "PII audit is heuristic — false positives possible. Manual review required.",
        "version": PRIVACY_VERSION,
    }
