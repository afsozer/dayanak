from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ContentStatus(StrEnum):
    FULL_TEXT = "full_text"
    HTML_MARKDOWN = "html_markdown"
    PDF_LINK_ONLY = "pdf_link_only"
    METADATA_ONLY = "metadata_only"
    UNAVAILABLE = "unavailable"


class SafetyState(StrEnum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    UNKNOWN = "unknown"


class SourceStatus(StrEnum):
    """Operational status of a data source.

    Values align with roadmap/local-yargi classification:
    stable, partial, experimental, unavailable.
    """
    STABLE = "stable"
    PARTIAL = "partial"
    EXPERIMENTAL = "experimental"
    UNAVAILABLE = "unavailable"


class CachedDocument(BaseModel):
    """Extended document model for cache v2 with rich metadata and access tracking.

    Preserves full backward compatibility with Document via source+document_id identity.
    """

    # Identity
    document_id: str
    source: str

    # Content
    title: str | None = None
    court: str | None = None
    chamber: str | None = None
    decision_date: str | None = None
    esas_no: str | None = None
    karar_no: str | None = None
    source_url: str | None = None
    content_status: ContentStatus = ContentStatus.METADATA_ONLY
    markdown: str | None = None
    full_text: str | None = None
    content_hash: str | None = None
    metadata_json: str | None = None
    raw_json: str | None = None

    # Access tracking
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_accessed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    access_count: int = 0

    # Usability flags
    quote_usable: bool = False
    draft_usable: bool = False
    metadata_confidence: Literal["high", "medium", "low"] | None = None
    warnings_json: str | None = None

    @property
    def text(self) -> str:
        return self.full_text or self.markdown or ""

    @classmethod
    def from_document(cls, doc: Document) -> "CachedDocument":
        """Create a CachedDocument from a Document model."""
        return cls(
            document_id=doc.document_id,
            source=doc.source,
            title=doc.title,
            court=doc.court,
            chamber=doc.chamber,
            decision_date=doc.decision_date,
            esas_no=doc.esas_no,
            karar_no=doc.karar_no,
            source_url=doc.source_url,
            content_status=doc.content_status,
            markdown=doc.markdown,
            full_text=doc.full_text,
            content_hash=doc.content_hash,
            metadata_json=json.dumps(doc.metadata, ensure_ascii=False, default=str) if doc.metadata else None,
            raw_json=json.dumps(doc.raw, ensure_ascii=False, default=str) if doc.raw is not None else None,
            retrieved_at=doc.retrieved_at,
            quote_usable=doc.quote_usable,
            draft_usable=doc.draft_usable,
            metadata_confidence=doc.metadata_confidence,
        )

    def to_document(self) -> Document:
        """Convert back to Document model."""
        return Document(
            source=self.source,
            document_id=self.document_id,
            title=self.title or "",
            court=self.court,
            chamber=self.chamber,
            decision_date=self.decision_date,
            esas_no=self.esas_no,
            karar_no=self.karar_no,
            source_url=self.source_url,
            content_status=self.content_status,
            markdown=self.markdown,
            full_text=self.full_text,
            content_hash=self.content_hash,
            retrieved_at=self.retrieved_at,
            metadata=json.loads(self.metadata_json) if self.metadata_json else {},
            raw=json.loads(self.raw_json) if self.raw_json else None,
        )

    def citation_label(self) -> str:
        parts = [self.court, self.chamber, self.decision_date, self.esas_no, self.karar_no]
        return " | ".join([p for p in parts if p]) or f"{self.source}:{self.document_id}"


class SourceCapability(BaseModel):
    """Rich capability descriptor for a legal data source.

    Canonical fields use snake_case.  Legacy camelCase aliases are provided
    via ``model_config`` so that older consumers (CLI ``--json``, MCP tools)
    continue to receive the shape they expect.
    """

    # ── Canonical fields ────────────────────────────────────────────────
    source_id: str
    display_name: str
    status: SourceStatus = SourceStatus.STABLE
    public: bool = True
    supports_search: bool = True
    supports_get_document: bool = True
    supports_full_text: bool = True
    supports_pdf_link: bool = False
    supports_metadata_only: bool = True
    supports_article_search: bool = False
    supports_type_filter: bool = False
    supports_workflow: bool = True
    live_smoke_recommended: bool = True
    notes: str = ""
    known_limitations: list[str] = Field(default_factory=list)

    # ── Compatibility alias (kept for backward compat, not canonical-only) ──
    supports_document: bool = Field(default=True, repr=False)

    # ── Legacy camelCase aliases kept for backward compatibility ────────
    citation_safe_rule: str = Field(
        default="Only documents with content_status full_text/html_markdown and non-empty text are quote/draft usable.",
        alias="citationSafeRule",
        repr=False,
    )
    no_fabrication: bool = Field(default=True, alias="noFabrication", repr=False)

    model_config = {"populate_by_name": True}

    def to_legacy_dict(self) -> dict[str, Any]:
        """Return a dict with both snake_case and legacy v0.1 camelCase keys."""
        d = self.model_dump(mode="json")
        # Legacy v0.1 keys
        d["source"] = self.source_id
        d["name"] = self.display_name
        d["public"] = self.public
        d["supports_document"] = self.supports_get_document
        d["tools"] = []
        if self.supports_search:
            d["tools"].append("search")
        if self.supports_get_document:
            d["tools"].append("get_document")
        d["citationSafeRule"] = self.citation_safe_rule
        d["noFabrication"] = self.no_fabrication
        return d


class SourceSmokeResult(BaseModel):
    """Per-source smoke test result. Offline-safe by default."""

    source_id: str
    offline_ok: bool = True
    online_ok: bool | None = None  # None = not tested
    search_callable: bool = True
    get_document_callable: bool = True
    min_content_length_ok: bool = True
    content_length_chars: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    tested_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_health: dict | None = None


class SourceProvenance(BaseModel):
    source: str
    document_id: str
    source_url: str | None = None
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    content_hash: str | None = None


class SearchResult(BaseModel):
    source: str
    document_id: str
    title: str
    summary: str | None = None
    court: str | None = None
    chamber: str | None = None
    decision_date: str | None = None
    esas_no: str | None = None
    karar_no: str | None = None
    source_url: str | None = None
    content_status: ContentStatus = ContentStatus.METADATA_ONLY
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ── Snippet (Yargı-MCP parity Görev 4) ───────────────────────────────
    # When include_snippets=true (or the document is in the local corpus),
    # this holds the first ~300–400 char passage containing the query terms,
    # extracted from the full text.  Lets the LLM triage relevance without
    # fetching every result individually.
    snippet: str | None = None

    # ── Enrichment fields (v0.2) ────────────────────────────────────────
    content_status_label: str | None = None
    content_available: bool = False
    full_text_available: bool = False
    pdf_url: str | None = None
    metadata_confidence: Literal["high", "medium", "low"] | None = None
    metadata_confidence_reason: str | None = None
    recommended_next_step: str | None = None

    def model_post_init(self, __context: Any) -> None:
        fields = build_content_status_fields(self)
        for key, value in fields.items():
            if getattr(self, key) in (None, False):
                setattr(self, key, value)


class Document(SearchResult):
    full_text: str | None = None
    markdown: str | None = None
    mime_type: str | None = None
    content_hash: str | None = None
    raw: Any = None
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    safety_state: SafetyState = SafetyState.UNKNOWN

    @property
    def quote_usable(self) -> bool:
        return self.content_status in {ContentStatus.FULL_TEXT, ContentStatus.HTML_MARKDOWN} and bool(self.text)

    @property
    def draft_usable(self) -> bool:
        return self.quote_usable

    @property
    def text(self) -> str:
        return self.full_text or self.markdown or ""

    def citation_label(self) -> str:
        parts = [self.court, self.chamber, self.decision_date, self.esas_no, self.karar_no]
        return " | ".join([p for p in parts if p]) or f"{self.source}:{self.document_id}"

    def provenance(self) -> SourceProvenance:
        return SourceProvenance(
            source=self.source,
            document_id=self.document_id,
            source_url=self.source_url,
            retrieved_at=self.retrieved_at,
            content_hash=self.content_hash,
        )


def build_content_status_fields(item: Any) -> dict[str, Any]:
    """Build local-yargi style content status helper fields.

    This is intentionally deterministic and citation-safe: it never upgrades a
    document to quote/draft usable; it only labels the existing content status
    and exposes next-step hints for agents.
    """
    status = item.content_status
    pdf_url = getattr(item, "pdf_url", None) or item.metadata.get("pdfUrl") or item.metadata.get("pdf_url")
    text = getattr(item, "text", "") or getattr(item, "full_text", None) or getattr(item, "markdown", None) or ""
    full_text_available = status in {ContentStatus.FULL_TEXT, ContentStatus.HTML_MARKDOWN} and bool(str(text).strip())
    content_available = full_text_available or status == ContentStatus.PDF_LINK_ONLY or bool(pdf_url)
    label = {
        ContentStatus.FULL_TEXT: "Tam metin",
        ContentStatus.HTML_MARKDOWN: "HTML'den Markdown",
        ContentStatus.PDF_LINK_ONLY: "PDF linki",
        ContentStatus.METADATA_ONLY: "Metadata",
        ContentStatus.UNAVAILABLE: "Yok",
    }[status]
    if getattr(item, "title", None) and getattr(item, "source", None) and (
        getattr(item, "decision_date", None) or getattr(item, "esas_no", None) or getattr(item, "karar_no", None)
    ):
        confidence, reason = "high", "Başlık, kaynak ve güçlü karar metadata alanları var."
    elif getattr(item, "title", None) and getattr(item, "source", None):
        confidence, reason = "medium", "Başlık ve kaynak var; bazı tarih/numara/daire alanları eksik."
    else:
        confidence, reason = "low", "Metadata alanları zayıf veya eksik."
    next_step = None
    if status == ContentStatus.PDF_LINK_ONLY or (pdf_url and not full_text_available):
        next_step = "Bu kayıt PDF bağlantısı içerir; alıntı için PDF metni ayrıca doğrulanmalıdır."
    elif status == ContentStatus.METADATA_ONLY:
        next_step = "Bu kayıtta tam metin yok; dilekçede kullanmadan önce resmi kaynaktan doğrulayın."
    elif status == ContentStatus.UNAVAILABLE:
        next_step = "Bu kaynak için okunabilir içerik alınamadı."
    return {
        "content_status_label": label,
        "content_available": content_available,
        "full_text_available": full_text_available,
        "metadata_confidence": confidence,
        "metadata_confidence_reason": reason,
        "recommended_next_step": next_step,
    }


class CitationCheck(BaseModel):
    ok: bool
    quoteUsable: bool
    draftUsable: bool
    reasons: list[str] = Field(default_factory=list)
    safety_state: SafetyState = SafetyState.UNKNOWN


class InputPack(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    matter: str
    issue: str
    documents: list[Document]
    safe_citations: list[str]
    excluded: list[dict[str, str]]
    warnings: list[str]
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pack_hash: str | None = None

    def compute_hash(self) -> str:
        content = f"{self.matter}:{self.issue}:{':'.join(d.document_id for d in self.documents)}"
        return hashlib.sha256(content.encode()).hexdigest()

    def model_post_init(self, __context: Any) -> None:
        if self.pack_hash is None:
            self.pack_hash = self.compute_hash()


class Draft(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: str
    body_markdown: str
    citations: list[str]
    warnings: list[str] = Field(default_factory=list)
    status: Literal["draft"] = "draft"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pack_id: str | None = None

    def has_citation_patterns(self) -> list[str]:
        import re
        patterns = [
            r'\d{4}/\d+',
            r'Esas\s*No',
            r'Karar\s*No',
            r'Yargıtay|Danıştay|Anayasa',
        ]
        found = []
        for p in patterns:
            if re.search(p, self.body_markdown):
                found.append(p)
        return found


MIN_CONTENT_LENGTH = 50  # minimum chars for full_text/html_markdown to be considered real content

# ── M-66 date plausibility ───────────────────────────────────────────────────

import datetime as _dt

_YEAR_MIN = 1920  # earliest plausible decision year


def _year_ceiling() -> int:
    """Return current year + 1 as the upper bound for plausible dates."""
    return _dt.date.today().year + 1


def _check_date_plausibility(doc: Document, w: list[str]) -> None:
    """Flag implausible decision_date values with a warning.

    Never modifies the date field — only appends a warning and lowers
    metadata_confidence when the year is outside [1920, current_year+1].
    """
    date_str = getattr(doc, "decision_date", None) or ""
    date_str = date_str.strip()
    if not date_str:
        return

    # Try to extract a 4-digit year from ISO (YYYY-MM-DD) or TR (DD.MM.YYYY).
    year: int | None = None
    import re
    m = re.match(r"^(\d{4})-\d{2}-\d{2}$", date_str)  # ISO
    if m:
        year = int(m.group(1))
    else:
        m = re.match(r"^\d{2}\.\d{2}\.(\d{4})$", date_str)  # DD.MM.YYYY
        if m:
            year = int(m.group(1))
        else:
            m = re.match(r"^(\d{4})$", date_str)  # bare year
            if m:
                year = int(m.group(1))

    if year is None:
        return  # unparseable format — don't flag

    ceiling = _year_ceiling()
    if year < _YEAR_MIN or year > ceiling:
        w.append(
            f"Implausible decision_date '{date_str}': year {year} outside "
            f"[{_YEAR_MIN}, {ceiling}]. Date preserved as-is; metadata_confidence lowered."
        )
        if isinstance(doc.metadata, dict):
            doc.metadata["metadata_confidence"] = "low"


def finalize_document(doc: Document, warnings: list[str] | None = None) -> Document:
    """Finalize a Document after source-specific parsing.

    - Applies min content length sanity: if content is too short for a
      full_text/html_markdown doc, downgrades to metadata_only with a warning.
    - Enriches content_status fields via build_content_status_fields.
    - Never fabricates metadata; warnings list is appended to, not replaced.
    - Returns the document (mutated in-place and returned for convenience).
    """
    import hashlib

    w = list(warnings or [])

    text = doc.text or ""

    # Min content length sanity
    if doc.content_status in {ContentStatus.FULL_TEXT, ContentStatus.HTML_MARKDOWN}:
        if len(text.strip()) < MIN_CONTENT_LENGTH:
            w.append(
                f"Content length {len(text.strip())} chars < {MIN_CONTENT_LENGTH} "
                f"minimum; downgrading to metadata_only."
            )
            doc.content_status = ContentStatus.METADATA_ONLY
            doc.full_text = None
            doc.markdown = None
            doc.content_hash = None

    # Compute content_hash if missing
    if doc.content_hash is None and text.strip() and doc.content_status in {
        ContentStatus.FULL_TEXT,
        ContentStatus.HTML_MARKDOWN,
    }:
        doc.content_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    # M-66: date plausibility — flag impossible years, never modify the date
    _check_date_plausibility(doc, w)

    # Attach warnings via metadata if not already present
    if w:
        existing = doc.metadata.get("_emsal_warnings", []) if isinstance(doc.metadata, dict) else []
        doc.metadata["_emsal_warnings"] = existing + w

    return doc


# Provenance fields that may be carried over from a SearchResult to a fetched
# Document. These come from the structured search API — never fabricated.
_PROVENANCE_FIELDS = (
    "decision_date", "esas_no", "karar_no", "court", "chamber",
    "source_url", "summary", "title",
)


def merge_search_metadata(doc: Document, source_result: SearchResult) -> Document:
    """Fill empty provenance fields on a fetched Document from its SearchResult.

    The ``getDocumentContent`` endpoints of some sources (e.g. Bedesten) return
    only the content blob with no structured metadata, leaving ``esas_no`` /
    ``karar_no`` / ``decision_date`` empty. That causes ``citation_check`` to
    fail even when full text is present. This helper carries the metadata the
    search API already returned into the document.

    - Fill-empty-only: never overwrites a value the document already has.
    - Only the structured fields the search API provided are copied; nothing
      is inferred, parsed from text, or fabricated.
    - Identity fields (source, document_id) and content fields are untouched.

    Returns the document (mutated in-place and returned for convenience).
    """
    if source_result is None:
        return doc
    for field in _PROVENANCE_FIELDS:
        current = getattr(doc, field, None)
        incoming = getattr(source_result, field, None)
        if (current is None or current == "" or current == doc.document_id) and incoming:
            setattr(doc, field, incoming)
    return doc


def build_error(
    error_code: str,
    message: str,
    *,
    ok: bool = False,
    source: str | None = None,
    retryable: bool = False,
    warnings: list[str] | None = None,
    recommended_next_steps: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a canonical error dict for consistent error shapes.

    All modules should use this helper for structured error responses
    instead of ad-hoc dicts.  This ensures every error response has
    `ok`, `errorCode`, `message`, and optional context fields.

    Args:
        error_code: Machine-readable error code (e.g. "TOOLKIT_UNAVAILABLE").
        message: Human-readable error description.
        ok: Always False for errors (kept as kwarg for clarity).
        source: Optional source identifier that produced the error.
        retryable: Whether the operation can be retried.
        warnings: Optional list of non-fatal warning strings.
        recommended_next_steps: Optional actionable next steps.
        **extra: Additional fields attached to the error dict.

    Returns:
        Dict with canonical keys: ok, errorCode, message, and any extra fields.
    """
    result: dict[str, Any] = {
        "ok": ok,
        "errorCode": error_code,
        "message": message,
    }
    if source is not None:
        result["source"] = source
    if retryable:
        result["retryable"] = True
    if warnings:
        result["warnings"] = list(warnings)
    if recommended_next_steps:
        result["recommended_next_steps"] = list(recommended_next_steps)
    result.update(extra)
    return result
