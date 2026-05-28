from __future__ import annotations

import base64
import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx
from bs4 import BeautifulSoup

from emsal_mcp.models import ContentStatus, Document, SearchResult, SourceCapability, SourceStatus


class SourceClient(ABC):
    source_id: str
    name: str
    public: bool = True

    # Capability metadata — subclasses may override to add known_limitations / notes.
    _capability_status: SourceStatus = SourceStatus.STABLE
    _supports_search: bool = True
    _supports_get_document: bool = True
    _supports_full_text: bool = True
    _supports_pdf_link: bool = False
    _supports_metadata_only: bool = True
    _supports_article_search: bool = False
    _supports_type_filter: bool = False
    _supports_workflow: bool = True
    _live_smoke_recommended: bool = True
    _known_limitations: list[str] = []
    _notes: str = ""

    @abstractmethod
    async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]: ...

    @abstractmethod
    async def get_document(self, document_id: str, **kwargs: Any) -> Document: ...

    def capability_model(self) -> SourceCapability:
        """Return a typed SourceCapability model for this client."""
        return SourceCapability(
            source_id=self.source_id,
            display_name=self.name,
            status=self._capability_status,
            public=self.public,
            supports_search=self._supports_search,
            supports_get_document=self._supports_get_document,
            supports_full_text=self._supports_full_text,
            supports_pdf_link=self._supports_pdf_link,
            supports_metadata_only=self._supports_metadata_only,
            supports_article_search=self._supports_article_search,
            supports_type_filter=self._supports_type_filter,
            supports_workflow=self._supports_workflow,
            live_smoke_recommended=self._live_smoke_recommended,
            known_limitations=list(self._known_limitations),
            notes=self._notes,
        )

    def capabilities(self) -> dict[str, Any]:
        """Legacy dict form — kept for backward compat with callers."""
        return self.capability_model().to_legacy_dict()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def decode_b64(data: str) -> bytes:
    return base64.b64decode(data + "=" * (-len(data) % 4))


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "EmsalMcp/0.1 FatihSozer"})


def metadata_doc(source: str, document_id: str, title: str, **kw: Any) -> Document:
    return Document(source=source, document_id=document_id, title=title, content_status=ContentStatus.METADATA_ONLY, **kw)
