from __future__ import annotations

import hashlib
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
