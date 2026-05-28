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
