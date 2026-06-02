from __future__ import annotations

import html
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from .models import build_error


class UdfError(ValueError):
    pass


UDF_TOOLKIT_VERSION = "0.9.0"

UDF_AUTHORING_WARNING = (
    "UDF yazımı deneysel kabul edilmeli; resmi kullanım öncesi UYAP Doküman "
    "Editörü'nde manuel round-trip doğrulama yapılmalıdır."
)

DOCX_TO_UDF_EXPERIMENTAL_WARNING = (
    "DOCX -> UDF dönüşümü deneysel ve geri döndürülemez bir işlemdir. "
    "Oluşturulan UDF dosyası UYAP Doküman Editörü'nde manuel olarak "
    "doğrulanmalıdır. Bu dönüşüm UYAP formatına tam uyumluluk garantisi vermez. "
    "Lütfen https://uyap.gov.tr adresinden güncel UYAP Doküman Editörü'nü kullanın."
)


def _resolve_toolkit_dir() -> Optional[Path]:
    """Resolve UDF toolkit directory from environment variables."""
    for env_var in ("EMSAL_UDF_TOOLKIT_DIR", "UDF_TOOLKIT_DIR"):
        val = os.environ.get(env_var, "").strip()
        if val:
            p = Path(val)
            if p.exists():
                return p
    return None


# Injectible hooks so tests can fully hermeticize toolkit detection.
# Replace these in test monkeypatching (no import-time side effects).
_discover_libreoffice = staticmethod(lambda: shutil.which("soffice") or shutil.which("libreoffice") or shutil.which("soffice.exe"))
_discover_unoconv = staticmethod(lambda: shutil.which("unoconv"))


def get_udf_toolkit_status() -> dict:
    """Check whether the external UDF toolkit (libreoffice/unoconv etc.) is available.

    Returns a structured status dict regardless of toolkit presence.
    """
    toolkit_dir = _resolve_toolkit_dir()
    enabled = toolkit_dir is not None
    libreoffice_path = _discover_libreoffice()
    unoconv_path = _discover_unoconv()

    warnings: list[str] = []
    if not enabled:
        if toolkit_dir is not None and not toolkit_dir.exists():
            warnings.append(
                f"UDF toolkit dizini mevcut degil: {toolkit_dir}. "
                "EMSAL_UDF_TOOLKIT_DIR veya UDF_TOOLKIT_DIR ortam degiskeni ile gecerli bir dizin ayarlayin."
            )
        else:
            warnings.append(
                "UDF toolkit dizini ayarlanmamis. "
                "EMSAL_UDF_TOOLKIT_DIR veya UDF_TOOLKIT_DIR ortam degiskeni ile ayarlayin."
            )
    if not libreoffice_path:
        warnings.append("LibreOffice (soffice) PATH'te bulunamadi.")
    if not unoconv_path:
        warnings.append("unoconv PATH'te bulunamadi.")

    return {
        "ok": enabled and (libreoffice_path is not None or unoconv_path is not None),
        "enabled": enabled,
        "toolkit_dir": str(toolkit_dir) if toolkit_dir else None,
        "libreoffice_path": libreoffice_path,
        "unoconv_path": unoconv_path,
        "version": UDF_TOOLKIT_VERSION,
        "warnings": warnings,
    }


def get_udf_authoring_instructions(format: str = "json") -> dict:
    """Return UDF authoring instructions in the requested format.

    Args:
        format: 'json' for structured dict, 'markdown' for human-readable text.

    Returns:
        dict with format, instructions, and key warnings.
    """
    base_steps = [
        "UDF dosyasini dogrudan Python ile olusturabilirsiniz (write_udf).",
        "Olusturulan dosyayi UYAP Doküman Editörü'nde acarak duzeltme yapin.",
        "UYAP Doküman Editörü ile dogrulama zorunludur.",
        "Disclaimer header otomatik olarak eklenir.",
        "Placeholder'lar {{...}} formatinda korunur.",
    ]
    warnings = [
        UDF_AUTHORING_WARNING,
        "Dogrudan UDF olusturmak UYAP formatina tam uyumluluk garantisi vermez.",
    ]

    if format == "markdown":
        md_lines = ["# UDF Authoring Instructions", ""]
        md_lines.append("## Steps")
        for i, step in enumerate(base_steps, 1):
            md_lines.append(f"{i}. {step}")
        md_lines.append("")
        md_lines.append("## Warnings")
        for w in warnings:
            md_lines.append(f"- {w}")
        return {
            "format": "markdown",
            "instructions": "\n".join(md_lines),
            "warnings": warnings,
            "version": UDF_TOOLKIT_VERSION,
        }

    return {
        "format": "json",
        "steps": base_steps,
        "warnings": warnings,
        "version": UDF_TOOLKIT_VERSION,
        "toolkit_status": get_udf_toolkit_status(),
    }


def read_udf(path: str | Path) -> str:
    """Read and extract text content from a UYAP UDF file.

    Args:
        path: Path to the UDF file (ZIP archive with content.xml).

    Returns:
        Extracted text content from the UDF.

    Raises:
        UdfError: If the file is missing, not a valid ZIP, or lacks content.xml.
    """
    p = Path(path)
    if not p.exists():
        raise UdfError(f"UDF bulunamadı: {p}")
    if p.read_bytes()[:2] != b"PK":
        raise UdfError("Geçersiz UDF: ZIP imzası yok")
    with zipfile.ZipFile(p) as zf:
        if "content.xml" not in zf.namelist():
            raise UdfError("Geçersiz UDF: content.xml yok")
        xml = zf.read("content.xml").decode("utf-8", errors="ignore")
    m = re.search(r"<content>\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*</content>", xml)
    if m:
        return m.group(1).strip()
    chunks = re.findall(r"<content[^>]*>([\s\S]*?)</content>", xml)
    text = "\n".join(chunks) if chunks else re.sub(r"<[^>]+>", " ", xml)
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


def udf_to_markdown(path: str | Path) -> str:
    """Convert a UDF file content to formatted markdown with paragraph breaks.

    Args:
        path: Path to the UDF file.

    Returns:
        Markdown string with paragraphs separated by double newlines.
    """
    lines = [ln.strip() for ln in read_udf(path).splitlines()]
    paragraphs: list[str] = []
    cur: list[str] = []
    for line in lines:
        if not line:
            if cur:
                paragraphs.append(" ".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        paragraphs.append(" ".join(cur))
    return "\n\n".join(paragraphs)


def write_udf(text: str, out_path: str | Path, *, title_centered: bool = False) -> Path:
    """Write a simple UYAP UDF (format_id=1.8). Caller must verify in UYAP editor."""
    out = Path(out_path)
    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    pool = "\n".join(paragraphs)
    offset = 0
    elements: list[str] = []
    for idx, para in enumerate(paragraphs):
        length = len(para) + (1 if idx < len(paragraphs) - 1 else 0)
        align = "1" if idx == 0 and title_centered else "3"
        attrs = ' bold="true"' if idx == 0 and title_centered else ""
        elements.append(f'<paragraph Alignment="{align}" LineSpacing="0.14999998"><content startOffset="{offset}" length="{length}"{attrs} /></paragraph>')
        offset += length
    xml = f'''<?xml version="1.0" encoding="UTF-8" ?>
<template format_id="1.8">
<content><![CDATA[{pool}]]></content>
<properties><pageFormat mediaSizeName="1" leftMargin="56.69" rightMargin="56.69" topMargin="56.69" bottomMargin="56.69" paperOrientation="1" headerFOffset="20.0" footerFOffset="20.0" /></properties>
<elements resolver="hvl-default">
{''.join(elements)}
</elements>
<styles><style name="default" description="Gecerli" family="Dialog" size="12" bold="false" italic="false" /><style name="hvl-default" family="Times New Roman" size="12" description="Govde" /></styles>
</template>'''
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.xml", xml.encode("utf-8"))
    return out


def probe_udf(path: str | Path) -> dict:
    """Probe a UDF file for structure, format, and content metadata."""
    p = Path(path)
    info: dict = {
        "path": str(p),
        "exists": p.exists(),
        "zip": False,
        "has_content_xml": False,
        "format_id": None,
        "content_xml_preview": None,
        "text_length": 0,
        "warnings": [],
    }
    if not p.exists():
        info["warnings"].append(f"File not found: {p}")
        return info
    try:
        with zipfile.ZipFile(p) as zf:
            info["zip"] = True
            info["has_content_xml"] = "content.xml" in zf.namelist()
            if info["has_content_xml"]:
                xml = zf.read("content.xml").decode("utf-8", errors="ignore")
                m = re.search(r'<template[^>]+format_id=["\']([^"\']+)', xml)
                info["format_id"] = m.group(1) if m else None
                # Provide a truncated preview of content.xml
                info["content_xml_preview"] = xml[:500] if len(xml) > 500 else xml
                info["text_length"] = len(read_udf(p))
            else:
                info["warnings"].append("content.xml not found inside UDF archive")
    except Exception as e:
        info["warnings"].append(str(e))
    return info


# ── Safe wrappers ───────────────────────────────────────────────────────────


def _toolkit_unavailable(action: str) -> dict:
    """Return a structured error dict when toolkit is disabled/missing."""
    status = get_udf_toolkit_status()
    return build_error(
        "TOOLKIT_UNAVAILABLE",
        "UDF toolkit is not available. Set EMSAL_UDF_TOOLKIT_DIR or "
        "UDF_TOOLKIT_DIR environment variable, or install LibreOffice.",
        action=action,
        toolkit_status=status,
        recommended_next_steps=[
            "Set EMSAL_UDF_TOOLKIT_DIR environment variable.",
            "Install LibreOffice and ensure soffice is on PATH.",
        ],
    )


def convert_udf_to_docx(file_path: str | Path, out_path: str | Path | None = None) -> dict:
    """Convert a UDF file to DOCX using external toolkit (LibreOffice).

    If toolkit is disabled or missing, returns a structured error dict
    instead of raising.
    """
    action = "convert_udf_to_docx"
    status = get_udf_toolkit_status()
    if not status["ok"]:
        return _toolkit_unavailable(action)

    src = Path(file_path)
    if not src.exists():
        return build_error("FILE_NOT_FOUND", f"UDF file not found: {src}", action=action)

    out = Path(out_path) if out_path else src.with_suffix(".docx")
    try:
        soffice = status["libreoffice_path"]
        if soffice:
            import subprocess

            result = subprocess.run(
                [soffice, "--headless", "--convert-to", "docx", "--outdir", str(out.parent), str(src)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return build_error(
                    "CONVERSION_FAILED",
                    result.stderr.strip() or "LibreOffice conversion failed",
                    action=action,
                    stdout=result.stdout.strip(),
                )
            # LibreOffice may name the output differently; find the generated docx
            generated = out.parent / (src.stem + ".docx")
            return {
                "ok": True,
                "action": action,
                "out_path": str(generated),
                "file_size": generated.stat().st_size if generated.exists() else 0,
                "warning": UDF_AUTHORING_WARNING,
            }
        return _toolkit_unavailable(action)
    except Exception as e:
        return build_error("EXCEPTION", str(e), action=action)


def convert_udf_to_pdf(file_path: str | Path, out_path: str | Path | None = None) -> dict:
    """Convert a UDF file to PDF using external toolkit (LibreOffice).

    If toolkit is disabled or missing, returns a structured error dict.
    """
    action = "convert_udf_to_pdf"
    status = get_udf_toolkit_status()
    if not status["ok"]:
        return _toolkit_unavailable(action)

    src = Path(file_path)
    if not src.exists():
        return build_error("FILE_NOT_FOUND", f"UDF file not found: {src}", action=action)

    out = Path(out_path) if out_path else src.with_suffix(".pdf")
    try:
        soffice = status["libreoffice_path"]
        if soffice:
            import subprocess

            result = subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out.parent), str(src)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return build_error(
                    "CONVERSION_FAILED",
                    result.stderr.strip() or "LibreOffice conversion failed",
                    action=action,
                    stdout=result.stdout.strip(),
                )
            generated = out.parent / (src.stem + ".pdf")
            return {
                "ok": True,
                "action": action,
                "out_path": str(generated),
                "file_size": generated.stat().st_size if generated.exists() else 0,
            }
        return _toolkit_unavailable(action)
    except Exception as e:
        return build_error("EXCEPTION", str(e), action=action)


def convert_docx_to_udf_experimental(
    file_path: str | Path,
    out_path: str | Path | None = None,
    experimental: bool = False,
) -> dict:
    """Convert a DOCX file to UDF format (experimental).

    Requires experimental=True. Always includes UYAP manual round-trip warning.
    If toolkit is disabled or missing, returns a structured error dict.
    """
    action = "convert_docx_to_udf_experimental"
    if not experimental:
        return build_error(
            "EXPERIMENTAL_REQUIRED",
            "DOCX -> UDF conversion requires experimental=True. "
            "This operation is irreversible and may not produce fully UYAP-compatible files.",
            action=action,
            warning=DOCX_TO_UDF_EXPERIMENTAL_WARNING,
        )

    status = get_udf_toolkit_status()
    if not status["ok"]:
        return _toolkit_unavailable(action)

    src = Path(file_path)
    if not src.exists():
        return build_error("FILE_NOT_FOUND", f"DOCX file not found: {src}", action=action)

    out = Path(out_path) if out_path else src.with_suffix(".udf")
    try:
        # Attempt text extraction from DOCX (which is a ZIP with word/document.xml)
        try:
            with zipfile.ZipFile(src) as zf:
                if "word/document.xml" in zf.namelist():
                    doc_xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
                    # Extract text between <w:t> tags
                    text_chunks = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", doc_xml)
                    text = "\n".join(text_chunks) if text_chunks else ""
                else:
                    text = ""
        except Exception:
            text = ""

        if not text.strip():
            return build_error(
                "EMPTY_DOCUMENT",
                "Could not extract text from DOCX file or document is empty.",
                action=action,
            )

        write_udf(text, out)
        return {
            "ok": True,
            "action": action,
            "out_path": str(out),
            "file_size": out.stat().st_size if out.exists() else 0,
            "warning": DOCX_TO_UDF_EXPERIMENTAL_WARNING,
            "experimental": True,
            "text_length": len(text),
        }
    except Exception as e:
        return build_error("EXCEPTION", str(e), action=action)
