"""Emsal-mcp PDF Text Extraction – v1.0

Extracts text content from PDF documents (text-layer and optional OCR).
Follows citation-safe invariants: extraction failure → content_status preserved.
No fabrication — only extracts what is verifiably present in the document.

Optional dependencies (lazy-imported):
- pypdf: text-layer extraction (included in [ocr] extra)
- pytesseract + Pillow: OCR for scanned PDFs (included in [ocr] extra)

When dependencies are unavailable, returns structured error — never raises.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from .models import ContentStatus, build_error

logger = logging.getLogger(__name__)

PDF_EXTRACTOR_VERSION = "1.0.0"

# Maximum PDF size to try extracting (10 MB)
_MAX_PDF_BYTES = 10 * 1024 * 1024

# Maximum text chars to extract from a single PDF (500 KB)
_MAX_TEXT_CHARS = 500_000


# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------


def is_pdf_extraction_available() -> bool:
    """Check if pypdf is installed for text-layer extraction."""
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        return False


def is_ocr_available() -> bool:
    """Check if pytesseract and Pillow are installed for OCR."""
    try:
        import pytesseract  # noqa: F401
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Text-layer extraction (pypdf)
# ---------------------------------------------------------------------------


def _get_pypdf():
    """Lazy-import pypdf. Returns module or None."""
    try:
        import pypdf
        return pypdf
    except ImportError:
        return None


def extract_pdf_text_from_bytes(pdf_content: bytes) -> dict[str, Any]:
    """Extract text from PDF bytes using text-layer extraction.

    Uses pypdf to extract text from the PDF's text layer.
    This works on born-digital PDFs, not scanned images.

    Args:
        pdf_content: Raw PDF file bytes.

    Returns:
        Dict with ok, text, page_count, method, warnings.
        On failure, returns structured error dict.
    """
    if len(pdf_content) > _MAX_PDF_BYTES:
        return build_error(
            "PDF_TOO_LARGE",
            f"PDF content exceeds maximum size of {_MAX_PDF_BYTES} bytes.",
            warnings=[f"PDF size: {len(pdf_content)} bytes."],
        )

    pypdf_mod = _get_pypdf()
    if pypdf_mod is None:
        return build_error(
            "PDF_EXTRACTION_UNAVAILABLE",
            "pypdf not installed. Run: pip install emsal-mcp[ocr]",
            recommended_next_steps=[
                "Install pypdf: pip install emsal-mcp[ocr]",
                "Alternatively: pip install pypdf",
            ],
        )

    warnings: list[str] = []
    try:
        reader = pypdf_mod.PdfReader(io.BytesIO(pdf_content))
        page_count = len(reader.pages)

        if page_count == 0:
            warnings.append("PDF has no pages.")
            return _empty_result(warnings=warnings)

        texts: list[str] = []
        total_chars = 0
        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
                if total_chars + len(page_text) > _MAX_TEXT_CHARS:
                    page_text = page_text[:_MAX_TEXT_CHARS - total_chars]
                    warnings.append(
                        f"Text truncated at {_MAX_TEXT_CHARS} chars."
                    )
                    texts.append(page_text)
                    break
                if page_text.strip():
                    texts.append(page_text)
                total_chars += len(page_text)
            except Exception as e:
                logger.debug("PDF page extraction warning: %s", e)

        full_text = "\n\n".join(texts).strip()

        if not full_text:
            warnings.append(
                "No text could be extracted from the text layer. "
                "This PDF may be image-only (scanned). "
                "OCR may help if available — use extract_pdf_text_ocr()."
            )

        return {
            "ok": True,
            "text": full_text,
            "page_count": page_count,
            "chars_extracted": len(full_text),
            "method": "pypdf_text_layer",
            "warnings": warnings,
        }
    except Exception as exc:
        return build_error(
            "PDF_EXTRACTION_FAILED",
            str(exc),
            warnings=[f"pypdf could not read this PDF: {exc}"],
        )


def extract_pdf_text_ocr(pdf_content: bytes, language: str = "tur") -> dict[str, Any]:
    """Extract text from PDF using OCR (pytesseract).

    Converts each PDF page to an image and runs OCR.
    This works on scanned/image-only PDFs where the text layer is empty.

    Args:
        pdf_content: Raw PDF file bytes.
        language: Tesseract language code (default: 'tur' for Turkish).

    Returns:
        Dict with ok, text, page_count, method, warnings.
        On failure, returns structured error dict.
    """
    if not is_ocr_available():
        return build_error(
            "OCR_UNAVAILABLE",
            "pytesseract and Pillow not installed. "
            "Run: pip install emsal-mcp[ocr]",
            recommended_next_steps=[
                "Install OCR deps: pip install emsal-mcp[ocr]",
                "Install Tesseract system package: "
                "https://github.com/UB-Mannheim/tesseract/wiki",
            ],
        )

    try:
        import pytesseract
        # Verify PIL is importable (used by pytesseract internally)
        import PIL  # noqa: F401

        import pdf2image
    except ImportError:
        return build_error(
            "OCR_UNAVAILABLE",
            "pdf2image not installed. Run: pip install emsal-mcp[ocr]",
        )

    if len(pdf_content) > _MAX_PDF_BYTES:
        return build_error(
            "PDF_TOO_LARGE",
            f"PDF content exceeds maximum size of {_MAX_PDF_BYTES} bytes.",
            warnings=[f"PDF size: {len(pdf_content)} bytes."],
        )

    warnings: list[str] = []
    try:
        images = pdf2image.convert_from_bytes(pdf_content, dpi=200)
        page_count = len(images)

        if page_count == 0:
            warnings.append("PDF has no pages.")
            return _empty_result(method="ocr", warnings=warnings)

        texts: list[str] = []
        total_chars = 0
        for i, img in enumerate(images):
            try:
                page_text = pytesseract.image_to_string(img, lang=language)
                if total_chars + len(page_text) > _MAX_TEXT_CHARS:
                    page_text = page_text[:_MAX_TEXT_CHARS - total_chars]
                    warnings.append(
                        f"OCR text truncated at {_MAX_TEXT_CHARS} chars."
                    )
                    texts.append(page_text)
                    break
                if page_text.strip():
                    texts.append(page_text)
                total_chars += len(page_text)
            except Exception as e:
                logger.debug("OCR page %d warning: %s", i + 1, e)

        full_text = "\n\n".join(texts).strip()

        if not full_text:
            warnings.append(
                "OCR produced no recognizable text from this PDF."
            )

        return {
            "ok": True,
            "text": full_text,
            "page_count": page_count,
            "chars_extracted": len(full_text),
            "method": "ocr_pytesseract",
            "ocr_language": language,
            "ocr_confidence": "low",  # OCR always lower confidence
            "warnings": warnings,
        }
    except Exception as exc:
        return build_error(
            "OCR_FAILED",
            str(exc),
            warnings=[f"OCR extraction failed: {exc}"],
        )


# ---------------------------------------------------------------------------
# Smart extraction — tries text-layer first, falls back to OCR
# ---------------------------------------------------------------------------


def extract_pdf_text(
    pdf_content: bytes,
    ocr_enabled: bool = False,
    ocr_language: str = "tur",
) -> dict[str, Any]:
    """Smart PDF text extraction.

    Tries text-layer extraction first (pypdf).
    If that yields no text and OCR is enabled, falls back to OCR.

    Args:
        pdf_content: Raw PDF file bytes.
        ocr_enabled: If True, fall back to OCR when text layer is empty.
        ocr_language: Tesseract language code for OCR.

    Returns:
        Dict with ok, text, page_count, method, warnings.
    """
    # Try text-layer extraction first
    result = extract_pdf_text_from_bytes(pdf_content)

    if not result.get("ok"):
        return result

    text = result.get("text", "")
    if text.strip():
        return result

    # Text layer empty — try OCR if enabled
    if ocr_enabled:
        ocr_result = extract_pdf_text_ocr(pdf_content, language=ocr_language)
        if ocr_result.get("ok"):
            return {
                **ocr_result,
                "warnings": [
                    "OCR used because text layer was empty.",
                    *ocr_result.get("warnings", []),
                ],
            }
        return {**result, "warnings": [*result.get("warnings", []), "OCR failed too."]}

    return result


# ---------------------------------------------------------------------------
# Integration: upgrade cached PDF documents
# ---------------------------------------------------------------------------


def try_upgrade_pdf_document(
    document_id: str,
    source: str,
    cache: Any = None,
    *,
    ocr_enabled: bool = False,
) -> dict[str, Any]:
    """Attempt to extract text from a PDF document and upgrade its content status.

    Only processes documents with content_status='pdf_link_only' and a source_url
    ending in .pdf. Downloads the PDF, extracts text, and if successful, updates
    the document's content_status to FULL_TEXT.

    Citation-safety invariant: if extraction fails, content_status is preserved.

    Args:
        document_id: Document ID to upgrade.
        source: Source identifier.
        cache: Optional Cache instance.
        ocr_enabled: Whether to attempt OCR fallback.

    Returns:
        Dict with ok, upgraded, method, text_length, warnings.
    """
    from .cache import Cache

    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db
        row = db.execute(
            "SELECT * FROM documents_v2 WHERE document_id=? AND source=?",
            (document_id, source),
        ).fetchone()
        if not row:
            return build_error(
                "DOCUMENT_NOT_FOUND",
                f"Document {document_id}:{source} not found in cache.",
            )

        if row["content_status"] != ContentStatus.PDF_LINK_ONLY:
            return {
                "ok": True,
                "upgraded": False,
                "reason": f"Document status is {row['content_status']}, not pdf_link_only.",
                "warnings": [],
            }

        source_url = row["source_url"]
        if not source_url or not str(source_url).lower().endswith(".pdf"):
            return {
                "ok": True,
                "upgraded": False,
                "reason": "Document has no PDF source_url.",
                "warnings": [],
            }

        # Download PDF
        try:
            import httpx

            with httpx.Client(timeout=30.0) as client:
                resp = client.get(str(source_url))
                resp.raise_for_status()
                pdf_bytes = resp.content
        except Exception as exc:
            return build_error(
                "PDF_DOWNLOAD_FAILED",
                f"Failed to download PDF from {source_url}: {exc}",
                warnings=[str(exc)],
            )

        # Extract text
        result = extract_pdf_text(pdf_bytes, ocr_enabled=ocr_enabled)
        if not result.get("ok"):
            return {**result, "upgraded": False}

        text = result.get("text", "")
        if not text.strip():
            return {
                "ok": True,
                "upgraded": False,
                "reason": "No extractable text found in PDF.",
                "warnings": result.get("warnings", []),
            }

        # Update document — upgrade to FULL_TEXT with extracted content
        import hashlib

        content_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

        db.execute(
            """
            UPDATE documents_v2
            SET full_text = ?, content_status = ?, content_hash = ?,
                metadata_confidence = 'low'
            WHERE document_id = ? AND source = ?
            """,
            (text, ContentStatus.FULL_TEXT, content_hash, document_id, source),
        )
        db.commit()

        return {
            "ok": True,
            "upgraded": True,
            "method": result.get("method"),
            "text_length": len(text),
            "content_hash": content_hash,
            "warnings": [
                "PDF text extracted, content upgraded to full_text. "
                "Confidence set to 'low' — verify before quoting.",
                *result.get("warnings", []),
            ],
        }
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


def upgrade_all_pdf_documents(
    cache: Any = None,
    *,
    source: str | None = None,
    limit: int = 50,
    ocr_enabled: bool = False,
) -> dict[str, Any]:
    """Try to upgrade all pdf_link_only documents in the cache.

    Iterates through pdf_link_only documents, downloads each PDF, extracts
    text, and upgrades successful ones to full_text.

    Args:
        cache: Optional Cache instance.
        source: Optional filter by source.
        limit: Maximum documents to process.
        ocr_enabled: Whether to attempt OCR fallback.

    Returns:
        Dict with ok, processed, upgraded, failed, warnings.
    """
    from .cache import Cache

    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db
        query = (
            "SELECT document_id, source FROM documents_v2 "
            "WHERE content_status = 'pdf_link_only' AND source_url IS NOT NULL"
        )
        params = []
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " LIMIT ?"
        params.append(limit)

        rows = db.execute(query, params).fetchall()

        processed = 0
        upgraded = 0
        failed = 0
        all_warnings: list[str] = []

        for row in rows:
            processed += 1
            result = try_upgrade_pdf_document(
                row["document_id"],
                row["source"],
                cache=c,
                ocr_enabled=ocr_enabled,
            )
            if result.get("upgraded"):
                upgraded += 1
            if not result.get("ok"):
                failed += 1
            all_warnings.extend(result.get("warnings", []))

        return {
            "ok": True,
            "processed": processed,
            "upgraded": upgraded,
            "failed": failed,
            "skipped": processed - upgraded - failed,
            "warnings": all_warnings[:20],  # cap at 20
        }
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


def get_pdf_stats(cache: Any = None) -> dict[str, Any]:
    """Report PDF document statistics from the cache.

    Returns counts of pdf_link_only documents and their upgrade potential.

    Args:
        cache: Optional Cache instance.

    Returns:
        Dict with ok, pdf_link_only_count, source_distribution, version.
    """
    from .cache import Cache

    own_cache = cache is None
    c = cache or Cache()
    try:
        db = c.db

        total_pdf = db.execute(
            "SELECT COUNT(*) FROM documents_v2 WHERE content_status = 'pdf_link_only'"
        ).fetchone()[0]

        sources = db.execute(
            "SELECT source, COUNT(*) as cnt FROM documents_v2 "
            "WHERE content_status = 'pdf_link_only' "
            "GROUP BY source ORDER BY cnt DESC"
        ).fetchall()

        has_url = db.execute(
            "SELECT COUNT(*) FROM documents_v2 "
            "WHERE content_status = 'pdf_link_only' AND source_url IS NOT NULL"
        ).fetchone()[0]

        return {
            "ok": True,
            "pdf_link_only_count": total_pdf,
            "with_source_url": has_url,
            "without_source_url": max(0, total_pdf - has_url),
            "source_distribution": [dict(r) for r in sources],
            "pypdf_available": is_pdf_extraction_available(),
            "ocr_available": is_ocr_available(),
            "version": PDF_EXTRACTOR_VERSION,
        }
    finally:
        if own_cache:
            try:
                c.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_result(
    method: str = "pypdf_text_layer",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "text": "",
        "page_count": 0,
        "chars_extracted": 0,
        "method": method,
        "warnings": warnings or [],
    }


# ---------------------------------------------------------------------------
# Path-based extraction (CLI integration)
# ---------------------------------------------------------------------------


def extract_pdf_text_from_file(
    file_path: str,
    ocr_enabled: bool = False,
) -> dict[str, Any]:
    """Extract text from a PDF file on disk.

    Convenience wrapper for CLI usage — reads file, delegates to extract_pdf_text.

    Args:
        file_path: Path to PDF file.
        ocr_enabled: Whether to fall back to OCR.

    Returns:
        Dict with ok, text, page_count, method, warnings.
    """
    from pathlib import Path

    p = Path(file_path)
    if not p.exists():
        return build_error("FILE_NOT_FOUND", f"PDF file not found: {file_path}")
    try:
        pdf_bytes = p.read_bytes()
    except Exception as exc:
        return build_error("FILE_READ_ERROR", str(exc))
    return extract_pdf_text(pdf_bytes, ocr_enabled=ocr_enabled)


def get_pdf_toolkit_status() -> dict[str, Any]:
    """Report PDF extraction toolkit availability.

    Returns:
        Dict with ok, pypdf_available, ocr_available, version.
    """
    return {
        "ok": True,
        "pypdf_available": is_pdf_extraction_available(),
        "ocr_available": is_ocr_available(),
        "recommended_install": "pip install emsal-mcp[ocr]",
        "version": PDF_EXTRACTOR_VERSION,
    }


def promote_pdf_to_full_text(
    document: dict[str, Any],
    ocr_enabled: bool = False,
) -> dict[str, Any]:
    """Promote a pdf_only Document dict to full_text if possible.

    Extracts text from the document's pdf_url and returns the enriched dict.
    Does NOT modify the cache — caller must store if desired.

    Args:
        document: Document dict with document_id, source, pdf_url/source_url fields.
        ocr_enabled: Whether to attempt OCR.

    Returns:
        Dict with ok, document (enriched), upgraded, warnings.
    """

    source_url = document.get("source_url") or document.get("pdf_url")
    if not source_url or not str(source_url).lower().endswith(".pdf"):
        return {
            "ok": True,
            "upgraded": False,
            "document": document,
            "reason": "No PDF URL found in document.",
            "warnings": [],
        }

    try:
        import httpx

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(str(source_url))
            resp.raise_for_status()
            pdf_bytes = resp.content
    except Exception as exc:
        return build_error(
            "PDF_DOWNLOAD_FAILED",
            f"Failed to download PDF: {exc}",
            upgraded=False,
            document=document,
        )

    result = extract_pdf_text(pdf_bytes, ocr_enabled=ocr_enabled)
    if not result.get("ok"):
        return {**result, "upgraded": False, "document": document}

    text = result.get("text", "")
    if not text.strip():
        return {
            "ok": True,
            "upgraded": False,
            "document": document,
            "reason": "No extractable text found.",
            "warnings": result.get("warnings", []),
        }

    import hashlib

    content_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    enriched = dict(document)
    enriched["full_text"] = text
    enriched["content_status"] = str(ContentStatus.FULL_TEXT)
    enriched["content_hash"] = content_hash
    enriched["metadata_confidence"] = "low"

    return {
        "ok": True,
        "upgraded": True,
        "document": enriched,
        "method": result.get("method"),
        "text_length": len(text),
        "warnings": [
            "PDF text extracted. Confidence set to 'low' — verify before quoting.",
            *result.get("warnings", []),
        ],
    }
