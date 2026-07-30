"""MCP server hardening utilities — input validation, error catalog, concurrency tracking.

Added in M-22.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from .models import build_error

# ── Input Validators ────────────────────────────────────────────────


def validate_non_empty(value: Any) -> tuple[bool, str | None]:
    """Check that a string value is not empty or whitespace-only."""
    if isinstance(value, str) and not value.strip():
        return False, "must not be empty"
    return True, None


def validate_positive_int(value: Any) -> tuple[bool, str | None]:
    """Check that a value is a positive integer (>= 1)."""
    if value is not None and (not isinstance(value, int) or value < 1):
        return False, "must be a positive integer"
    return True, None


def validate_range(min_val: float, max_val: float) -> Callable[[Any], tuple[bool, str | None]]:
    """Return a validator that checks value is within [min_val, max_val]."""

    def _check(value: Any) -> tuple[bool, str | None]:
        if value is not None:
            try:
                v = float(value)
            except (TypeError, ValueError):
                return False, f"must be a number between {min_val} and {max_val}"
            if v < min_val or v > max_val:
                return False, f"must be between {min_val} and {max_val}"
        return True, None

    return _check


def validate_is_dict_with_keys(*required_keys: str) -> Callable[[Any], tuple[bool, str | None]]:
    """Check that a value is a dict containing all required keys."""

    def _check(value: Any) -> tuple[bool, str | None]:
        if value is not None:
            if not isinstance(value, dict):
                return False, "must be a dict"
            missing = [k for k in required_keys if k not in value]
            if missing:
                return False, f"missing required fields: {', '.join(missing)}"
        return True, None

    return _check


# ── Validation Decorator ───────────────────────────────────────────


def validate_tool_input(**validators: Callable[[Any], tuple[bool, str | None]]) -> Callable:
    """Decorator that validates MCP tool input parameters.

    ``validators`` maps parameter names to validator functions.
    Each validator returns ``(is_valid: bool, error_msg: str | None)``.

    Usage::

        @mcp.tool()
        @validate_tool_input(query=validate_non_empty, limit=validate_positive_int)
        async def search_decisions(source: str, query: str, limit: int = 10):
            ...
    """

    def decorator(func: Callable) -> Callable:
        import asyncio

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                errors: list[str] = []
                for param, validator in validators.items():
                    value = kwargs.get(param)
                    is_valid, err_msg = validator(value)
                    if not is_valid and value is not None:
                        errors.append(f"{param}: {err_msg}")
                if errors:
                    return build_error("INVALID_INPUT", "; ".join(errors))
                return await func(*args, **kwargs)

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                errors: list[str] = []
                for param, validator in validators.items():
                    value = kwargs.get(param)
                    is_valid, err_msg = validator(value)
                    if not is_valid and value is not None:
                        errors.append(f"{param}: {err_msg}")
                if errors:
                    return build_error("INVALID_INPUT", "; ".join(errors))
                return func(*args, **kwargs)

            return sync_wrapper

    return decorator


# ── Concurrency Tracking ───────────────────────────────────────────

_active_requests: int = 0  # informational counter — single-user design


def _track_request(func: Callable) -> Callable:
    """Lightweight wrapper that tracks active request count (informational)."""

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        global _active_requests
        _active_requests += 1
        try:
            return await func(*args, **kwargs)
        finally:
            _active_requests -= 1

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        global _active_requests
        _active_requests += 1
        try:
            return func(*args, **kwargs)
        finally:
            _active_requests -= 1

    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def get_active_requests() -> int:
    """Return the current number of active requests (informational)."""
    return _active_requests


# ── Error Surface Catalog ──────────────────────────────────────────

# All known error codes used in build_error() calls across the codebase.
# Keep in sync when adding new error codes.
KNOWN_ERROR_CODES: list[str] = sorted([
    "ANALYTICS_RECORD_FAILED",
    "ARGUMENT_MAP_MISSING",
    "CHAMBER_NOT_FOUND",
    "CHECK_FAILED",
    "CIRCUIT_OPEN",
    "CLUSTER_NOT_FOUND",
    "CONVERSION_FAILED",
    "DB_OPEN_FAILED",
    "DB_QUERY_FAILED",
    "DEDUP_FAILED",
    "DEDUP_LOOKUP_FAILED",
    "DEDUP_STATS_FAILED",
    "DOC_NOT_FOUND",
    "DOCUMENT_NOT_FOUND",
    "DRAFT_DIR_NOT_FOUND",
    "DRAFT_NOT_FOUND",
    "EMBEDDING_BACKEND_UNAVAILABLE",
    "EMBEDDING_INDEX_FAILED",
    "EMBEDDING_SEARCH_FAILED",
    "EMBEDDING_STATUS_FAILED",
    "EMPTY_DB",
    "EMPTY_DOCUMENT",
    "EXCEPTION",
    "FETCH_FAILED",
    "FILE_NOT_FOUND",
    "FILE_READ_ERROR",
    "FUZZY_DEDUP_FAILED",
    "GRAPH_BUILD_FAILED",
    "GRAPH_EXPORT_FAILED",
    "GRAPH_QUERY_FAILED",
    "GRAPH_STATS_FAILED",
    "INCREMENTAL_INDEX_FAILED",
    "INDEX_BUILD_FAILED",
    "INDEX_QUERY_FAILED",
    "INDEX_SYNC_STATUS_FAILED",
    "INTEGRITY_CHECK_FAILED",
    "INVALID_BUMP_FLAGS",
    "INVALID_COURT_TYPE",
    "INVALID_FORMAT",
    "INVALID_HYBRID_WEIGHT",
    "INVALID_INPUT",
    "INVALID_NAME",
    "INVALID_QUERY",
    "MERGE_FAILED",
    "MISSING_CRITERION",
    "NOT_A_DIRECTORY",
    "NO_CHAMBERS_AVAILABLE",
    "NO_CHAMBERS_FOUND",
    "NO_DOCUMENTS_FOUND",
    "NO_ISSUES",
    "NO_KEYWORDS",
    "OCR_FAILED",
    "OCR_UNAVAILABLE",
    "ORPHAN_CLEANUP_FAILED",
    "PACK_NOT_FOUND",
    "PARSE_FAILED",
    "PDF_DOWNLOAD_FAILED",
    "PDF_EXTRACTION_FAILED",
    "PDF_EXTRACTION_UNAVAILABLE",
    "PDF_TOO_LARGE",
    "READ_ERROR",
    "SEARCH_FAILED",
    "SOURCE_NOT_FOUND",
    "SOURCE_UPSTREAM_ERROR",
    "TABLE_NOT_FOUND",
    "TEMPLATE_NOT_FOUND",
    "TOOLKIT_UNAVAILABLE",
    "VACUUM_FAILED",
    "VERSION_DIR_ERROR",
    "VERSION_PARSE_FAILED",
    "WATCH_ADD_FAILED",
    "WATCH_EXISTS",
    "WATCH_LIST_FAILED",
    "WATCH_NOT_FOUND",
    "WATCH_REMOVE_FAILED",
    "WATCH_RUN_FAILED",
])


def get_error_codes() -> dict[str, Any]:
    """Return the full error code catalog used in the project.

    Each entry includes the code, a representative message pattern,
    the modules where it is used, and a recommended action.
    """
    catalog: dict[str, dict[str, Any]] = {
        "ANALYTICS_RECORD_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["search_analytics"],
            "action": "Verify cache DB is writable.",
        },
        "ARGUMENT_MAP_MISSING": {
            "message_pattern": "Argument map not found",
            "modules": ["argument"],
            "action": "Run petition pack generation first.",
        },
        "CHAMBER_NOT_FOUND": {
            "message_pattern": "Chamber not found",
            "modules": ["chamber"],
            "action": "Verify chamber name matches a cached record.",
        },
        "CHECK_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["exporter", "release"],
            "action": "Inspect the specific check that failed; may be transient.",
        },
        "CIRCUIT_OPEN": {
            "message_pattern": "Circuit breaker open for source",
            "modules": ["sources/base"],
            "action": "Wait for the circuit to close or reset manually.",
        },
        "CLUSTER_NOT_FOUND": {
            "message_pattern": "Cluster {id} not found",
            "modules": ["dedup"],
            "action": "Run find_duplicates first to identify clusters.",
        },
        "CONVERSION_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["exporter", "udf"],
            "action": "Check toolkit availability (LibreOffice for DOCX/PDF).",
        },
        "DB_OPEN_FAILED": {
            "message_pattern": "Cannot open cache DB",
            "modules": ["cache"],
            "action": "Verify DB file permissions and path.",
        },
        "DB_QUERY_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["chamber"],
            "action": "Check cache DB integrity; may need rebuild.",
        },
        "DEDUP_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["dedup"],
            "action": "Check cache DB state and dedup parameters.",
        },
        "DEDUP_LOOKUP_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["dedup"],
            "action": "Verify document_id exists in cache.",
        },
        "DEDUP_STATS_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["dedup"],
            "action": "Check cache DB schema integrity.",
        },
        "DOC_NOT_FOUND": {
            "message_pattern": "Belge bulunamadı: {source}:{document_id}",
            "modules": ["citation_graph"],
            "action": "Verify the document exists in the specified source.",
        },
        "DOCUMENT_NOT_FOUND": {
            "message_pattern": "Document not found",
            "modules": ["pdf_extractor"],
            "action": "Check the document ID and source.",
        },
        "DRAFT_DIR_NOT_FOUND": {
            "message_pattern": "Draft directory not found",
            "modules": ["draft_diff"],
            "action": "Verify the draft directory path exists.",
        },
        "DRAFT_NOT_FOUND": {
            "message_pattern": "Draft not found",
            "modules": ["draft_diff"],
            "action": "Verify the draft file path exists.",
        },
        "EMBEDDING_BACKEND_UNAVAILABLE": {
            "message_pattern": "Embedding provider unavailable",
            "modules": ["semantic"],
            "action": "Install fastembed or use local-hash-v1 provider.",
        },
        "EMBEDDING_INDEX_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["semantic"],
            "action": "Check embedding provider availability and DB state.",
        },
        "EMBEDDING_SEARCH_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["semantic"],
            "action": "Ensure embedding index is built; check provider.",
        },
        "EMBEDDING_STATUS_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["semantic"],
            "action": "Check DB accessibility and embedding_vectors table.",
        },
        "EMPTY_DB": {
            "message_pattern": "Belge icerigi mevcut degil",
            "modules": ["chamber", "legislation"],
            "action": "Populate cache with documents first.",
        },
        "EMPTY_DOCUMENT": {
            "message_pattern": "UDF document is empty",
            "modules": ["udf"],
            "action": "Provide a non-empty UDF file.",
        },
        "EXCEPTION": {
            "message_pattern": "str(e)",
            "modules": ["udf"],
            "action": "Unexpected error; check UDF toolkit installation.",
        },
        "FETCH_FAILED": {
            "message_pattern": "Belge alinamadi / Kaynak bulunamadi",
            "modules": ["legislation"],
            "action": "Check source availability and document ID.",
        },
        "FILE_NOT_FOUND": {
            "message_pattern": "File not found: {path}",
            "modules": ["cache", "citation", "exporter", "pdf_extractor", "privacy", "udf"],
            "action": "Verify the file path exists and is readable.",
        },
        "FILE_READ_ERROR": {
            "message_pattern": "str(exc)",
            "modules": ["pdf_extractor"],
            "action": "Check file permissions and encoding.",
        },
        "FUZZY_DEDUP_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["dedup"],
            "action": "Ensure embedding index is built for fuzzy matching.",
        },
        "GRAPH_BUILD_FAILED": {
            "message_pattern": "Citation graph olusturulamadi",
            "modules": ["citation_graph"],
            "action": "Check cache DB has documents with citation metadata.",
        },
        "GRAPH_EXPORT_FAILED": {
            "message_pattern": "Graf disa aktarilamadi",
            "modules": ["citation_graph"],
            "action": "Check output format support and permissions.",
        },
        "GRAPH_QUERY_FAILED": {
            "message_pattern": "Sorgu basarisiz",
            "modules": ["citation_graph"],
            "action": "Verify document_id and source parameters.",
        },
        "GRAPH_STATS_FAILED": {
            "message_pattern": "Istatistik alinamadi",
            "modules": ["citation_graph"],
            "action": "Check citation_graph DB tables exist.",
        },
        "INCREMENTAL_INDEX_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["semantic"],
            "action": "Check DB state and retry full rebuild.",
        },
        "INDEX_BUILD_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["semantic"],
            "action": "Check DB permissions and schema.",
        },
        "INDEX_QUERY_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["semantic"],
            "action": "Check DB accessibility.",
        },
        "INDEX_SYNC_STATUS_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["semantic"],
            "action": "Check DB state and index tables.",
        },
        "INTEGRITY_CHECK_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["cache"],
            "action": "Check cache DB file integrity.",
        },
        "INVALID_BUMP_FLAGS": {
            "message_pattern": "Invalid bump flags",
            "modules": ["release"],
            "action": "Provide exactly one of --major, --minor, --patch.",
        },
        "INVALID_FORMAT": {
            "message_pattern": "Unknown format: {format}",
            "modules": ["citation_graph", "exporter"],
            "action": "Use a supported format (json, dot, mermaid, etc.).",
        },
        "INVALID_HYBRID_WEIGHT": {
            "message_pattern": "hybrid_weight must be between 0.0 and 1.0",
            "modules": ["semantic"],
            "action": "Set hybrid_weight to a value in [0.0, 1.0].",
        },
        "INVALID_INPUT": {
            "message_pattern": "param: must not be empty / must be a positive integer",
            "modules": ["citation", "exporter", "legislation", "server_utils"],
            "action": "Check input parameters against documented constraints.",
        },
        "INVALID_NAME": {
            "message_pattern": "Watch name must not be empty",
            "modules": ["research_watch"],
            "action": "Provide a non-empty watch name.",
        },
        "INVALID_QUERY": {
            "message_pattern": "Watch query must not be empty",
            "modules": ["research_watch"],
            "action": "Provide a non-empty research query.",
        },
        "MERGE_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["dedup"],
            "action": "Check cluster state; may need manual intervention.",
        },
        "NOT_A_DIRECTORY": {
            "message_pattern": "Not a directory",
            "modules": ["draft_diff"],
            "action": "Provide a directory path, not a file.",
        },
        "NO_CHAMBERS_AVAILABLE": {
            "message_pattern": "No chambers available",
            "modules": ["chamber"],
            "action": "Cache has no chamber data; run a search first.",
        },
        "NO_CHAMBERS_FOUND": {
            "message_pattern": "No chambers found",
            "modules": ["chamber"],
            "action": "Check court filter matches cached records.",
        },
        "NO_DOCUMENTS_FOUND": {
            "message_pattern": "No documents found",
            "modules": ["chamber"],
            "action": "Broaden search criteria or populate cache.",
        },
        "NO_ISSUES": {
            "message_pattern": "No issues provided",
            "modules": ["petition"],
            "action": "Provide at least one issue for multi-issue pack.",
        },
        "NO_KEYWORDS": {
            "message_pattern": "No keywords",
            "modules": ["chamber"],
            "action": "Provide keywords for chamber profiling.",
        },
        "OCR_FAILED": {
            "message_pattern": "OCR processing failed",
            "modules": ["pdf_extractor"],
            "action": "Check OCR dependencies (pypdf, pillow).",
        },
        "OCR_UNAVAILABLE": {
            "message_pattern": "OCR not available",
            "modules": ["pdf_extractor"],
            "action": "Install pypdf and pillow for OCR support.",
        },
        "ORPHAN_CLEANUP_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["cache"],
            "action": "Check DB state; may need manual VACUUM.",
        },
        "PACK_NOT_FOUND": {
            "message_pattern": "petition-pack.json not found",
            "modules": ["argument", "exporter", "petition"],
            "action": "Run petition pack generation first.",
        },
        "PARSE_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["chamber"],
            "action": "Check data format of chamber records.",
        },
        "PDF_DOWNLOAD_FAILED": {
            "message_pattern": "PDF download failed",
            "modules": ["pdf_extractor"],
            "action": "Check network connectivity and URL validity.",
        },
        "PDF_EXTRACTION_FAILED": {
            "message_pattern": "PDF extraction failed",
            "modules": ["pdf_extractor"],
            "action": "Check PDF file integrity and toolkit.",
        },
        "PDF_EXTRACTION_UNAVAILABLE": {
            "message_pattern": "PDF extraction unavailable",
            "modules": ["pdf_extractor"],
            "action": "Install pypdf for PDF text extraction.",
        },
        "PDF_TOO_LARGE": {
            "message_pattern": "PDF too large",
            "modules": ["pdf_extractor"],
            "action": "Reduce PDF file size or increase limit.",
        },
        "READ_ERROR": {
            "message_pattern": "Cannot read {path}",
            "modules": ["draft_diff"],
            "action": "Check file permissions and encoding.",
        },
        "SEARCH_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["semantic"],
            "action": "Check query syntax and index status.",
        },
        "SOURCE_NOT_FOUND": {
            "message_pattern": "Source not found",
            "modules": ["calibrate"],
            "action": "Verify source_id is registered.",
        },
        "TABLE_NOT_FOUND": {
            "message_pattern": "Table not found",
            "modules": ["cache"],
            "action": "Rebuild cache schema.",
        },
        "TEMPLATE_NOT_FOUND": {
            "message_pattern": "Template not found",
            "modules": ["templates"],
            "action": "Use list_templates to see available templates.",
        },
        "TOOLKIT_UNAVAILABLE": {
            "message_pattern": "Toolkit not available",
            "modules": ["exporter", "udf"],
            "action": "Install LibreOffice for DOCX/PDF conversion.",
        },
        "VACUUM_FAILED": {
            "message_pattern": "str(exc)",
            "modules": ["cache"],
            "action": "Check DB file permissions; try manual VACUUM.",
        },
        "VERSION_DIR_ERROR": {
            "message_pattern": "Version directory error",
            "modules": ["draft_diff"],
            "action": "Check output directory permissions.",
        },
        "VERSION_PARSE_FAILED": {
            "message_pattern": "Version parse failed",
            "modules": ["release"],
            "action": "Verify version format (MAJOR.MINOR.PATCH).",
        },
        "WATCH_ADD_FAILED": {
            "message_pattern": "Failed to add watch",
            "modules": ["research_watch"],
            "action": "Check watch name uniqueness and parameters.",
        },
        "WATCH_EXISTS": {
            "message_pattern": "Watch already exists",
            "modules": ["research_watch"],
            "action": "Use a different name or remove existing watch.",
        },
        "WATCH_LIST_FAILED": {
            "message_pattern": "Failed to list watches",
            "modules": ["research_watch"],
            "action": "Check watch storage file permissions.",
        },
        "WATCH_NOT_FOUND": {
            "message_pattern": "Watch not found",
            "modules": ["research_watch"],
            "action": "Verify watch name; use list to see available watches.",
        },
        "WATCH_REMOVE_FAILED": {
            "message_pattern": "Failed to remove watch",
            "modules": ["research_watch"],
            "action": "Check watch storage file permissions.",
        },
        "WATCH_RUN_FAILED": {
            "message_pattern": "Failed to run watch",
            "modules": ["research_watch"],
            "action": "Check source availability and network connectivity.",
        },
    }

    return {
        "known_codes": KNOWN_ERROR_CODES,
        "total": len(KNOWN_ERROR_CODES),
        "catalog": catalog,
    }


# ── Long text pagination (Yargı-MCP parity Görev 4) ──────────────────────────

_MAX_PAGE_CHARS = 40_000


def split_markdown_for_pagination(
    text: str,
    page_number: int = 1,
    max_chars: int = _MAX_PAGE_CHARS,
) -> dict[str, Any]:
    """Split long markdown into pages at paragraph boundaries.

    Never cuts mid-paragraph.  Pages are built by accumulating paragraphs
    (``\\n\\n+`` separators) until adding the next one would exceed
    ``max_chars``.

    When a single paragraph exceeds ``max_chars``, it is further split at
    sentence boundaries (``. ! ?`` followed by whitespace) as a fallback;
    if that still produces overlong chunks, a word-boundary split is used.

    Args:
        text: The full markdown/plain-text body.
        page_number: 1-indexed page to return.
        max_chars: Maximum characters per page (default 40_000).

    Returns:
        Dict with ``markdown`` (the requested page), ``current_page``,
        ``total_pages``, and ``total_chars``.
    """
    if not text or not text.strip():
        return {
            "markdown": text or "",
            "current_page": 1,
            "total_pages": 1,
            "total_chars": len(text or ""),
        }

    total_chars = len(text)

    # Short enough → single page.
    if total_chars <= max_chars:
        return {
            "markdown": text,
            "current_page": 1,
            "total_pages": 1,
            "total_chars": total_chars,
        }

    # Phase 1: split at paragraph boundaries.
    raw_paragraphs = _split_paragraphs(text)

    # Phase 2: flatten any single paragraph that is still too long.
    paragraphs: list[str] = []
    for p in raw_paragraphs:
        if len(p) <= max_chars:
            paragraphs.append(p)
        else:
            # One giant paragraph — split at sentence boundaries.
            sentences = _split_sentences(p)
            for s in sentences:
                if len(s) <= max_chars:
                    paragraphs.append(s)
                else:
                    # Single sentence still too long → forced word-boundary split.
                    paragraphs.extend(_split_forced(s, max_chars))

    # Phase 3: build pages from paragraphs.
    pages: list[str] = []
    current = ""
    for para in paragraphs:
        gap = 2 if current else 0  # "\n\n" separator
        if len(current) + gap + len(para) <= max_chars:
            current = (current + "\n\n" + para) if current else para
        else:
            if current:
                pages.append(current)
            current = para
    if current:
        pages.append(current)

    total_pages = len(pages)
    page = max(1, min(page_number, total_pages))

    return {
        "markdown": pages[page - 1],
        "current_page": page,
        "total_pages": total_pages,
        "total_chars": total_chars,
    }


def _split_paragraphs(text: str) -> list[str]:
    """Split text at double-newline boundaries (paragraphs)."""
    import re
    parts = re.split(r"\n\n+", text)
    return [p for p in parts if p] or [text]


def _split_sentences(text: str) -> list[str]:
    """Split text at sentence boundaries (``. ! ?`` + whitespace)."""
    import re
    # Split after .!? followed by whitespace, keeping the punctuation on the left.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p] or [text]


def _split_forced(text: str, max_chars: int) -> list[str]:
    """Brute-force split at word boundaries.  Last-resort fallback."""
    words = text.split()
    if not words:
        return [text]
    chunks: list[str] = []
    current = ""
    for w in words:
        gap = 1 if current else 0
        if len(current) + gap + len(w) > max_chars and current:
            chunks.append(current)
            current = w
        else:
            current = (current + " " + w) if current else w
    if current:
        chunks.append(current)
    return chunks or [text]
