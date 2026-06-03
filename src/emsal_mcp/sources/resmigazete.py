"""Resmi Gazete (Official Gazette) source adapter — M-74.

Turkish Official Gazette — HTML-based, EXPERIMENTAL status.
"""
from __future__ import annotations

from .base import SourceClient
from emsal_mcp.models import Document, ContentStatus


class ResmiGazeteClient(SourceClient):
    source_id = "resmigazete"
    name = "Resmî Gazete"
    base = "https://www.resmigazete.gov.tr"

    async def search(self, query: str, limit: int = 10, **filters):
        return []  # HTML scraping not implemented — experimental

    async def get_document(self, document_id: str, **kwargs):
        return Document(
            source=self.source_id, document_id=document_id,
            title="Resmî Gazete", content_status=ContentStatus.UNAVAILABLE,
        )
