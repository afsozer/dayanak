from __future__ import annotations

import base64
import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx
from bs4 import BeautifulSoup

from emsal_mcp.models import ContentStatus, Document, SearchResult


class SourceClient(ABC):
    source_id: str
    name: str
    public: bool = True

    @abstractmethod
    async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]: ...

    @abstractmethod
    async def get_document(self, document_id: str, **kwargs: Any) -> Document: ...

    def capabilities(self) -> dict[str, Any]:
        return {"source": self.source_id, "name": self.name, "public": self.public, "tools": ["search", "get_document"]}


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
