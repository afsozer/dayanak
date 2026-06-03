"""KVKK (Kişisel Verileri Koruma Kurulu) source adapter — M-74.

Turkish Personal Data Protection Board decisions — HTML-based, EXPERIMENTAL.
"""
from __future__ import annotations

from .base import SourceClient
from emsal_mcp.models import Document, ContentStatus


class KvkkClient(SourceClient):
    source_id = "kvkk"
    name = "KVKK Kurul Kararları"
    base = "https://www.kvkk.gov.tr"

    async def search(self, query: str, limit: int = 10, **filters):
        return []

    async def get_document(self, document_id: str, **kwargs):
        return Document(
            source=self.source_id, document_id=document_id,
            title="KVKK Kararı", content_status=ContentStatus.UNAVAILABLE,
        )
