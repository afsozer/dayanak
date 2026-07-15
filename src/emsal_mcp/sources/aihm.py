"""AİHM (European Court of Human Rights) source adapter via HUDOC.

HUDOC search API endpoint (``/app/query/results``) returns HTTP 404 as of
2026-07 — the endpoint has been retired or moved.  Direct HTTP calls fail
even with session cookies.  The document content API
(``/app/conversion/docx/html/body``) still works and is used for
``get_document()``.

Search is unsupported until the upstream API is re-discovered or a new
endpoint is documented by the HUDOC team.  See PARITY_V2_RAPOR.md for the
exact observed response.
"""
from __future__ import annotations

from typing import Any

import httpx

from .base import (
    SourceClient,
    check_http_response,
    client,
    html_to_text,
    sha,
)
from emsal_mcp.models import (
    ContentStatus,
    Document,
    SearchResult,
    SourceSmokeResult,
    finalize_document,
)


class AihmClient(SourceClient):
    source_id = "aihm"
    name = "AİHM (HUDOC)"
    base = "https://hudoc.echr.coe.int"

    _capability_status = "EXPERIMENTAL"  # set as class attribute
    _supports_full_text = True
    _supports_pdf_link = False
    _known_limitations: list[str] = [
        "HUDOC search (query/results) API endpoint returns 404 (retired/moved). "
        "Only get_document works via the HTML content API.",
    ]

    async def search(
        self, query: str, limit: int = 10, **filters: Any
    ) -> list[SearchResult]:
        """HUDOC search is unavailable — the query/results endpoint 404s.

        Returns an empty list rather than raising an error so callers that
        iterate over search results for multi-source sweeps don't crash.
        The capability matrix marks this source as EXPERIMENTAL with a clear
        limitation note.
        """
        return []

    async def get_document(self, document_id: str, **kwargs: Any) -> Document:
        """Fetch a HUDOC document by itemid and return its Markdown text.

        Uses the working HTML content conversion endpoint:
        ``/app/conversion/docx/html/body?library=ECHR&id=<itemid>``.

        Args:
            document_id: HUDOC itemid, e.g. ``"001-218575"``.
        """
        url = f"{self.base}/app/conversion/docx/html/body"
        params = {"library": "ECHR", "id": document_id}
        warnings: list[str] = []

        try:
            async with client() as c:
                r = await c.get(url, params=params, timeout=30)
                check_http_response(r, self.source_id)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 404:
                doc = Document(
                    source=self.source_id,
                    document_id=document_id,
                    title=document_id,
                    content_status=ContentStatus.UNAVAILABLE,
                )
                return finalize_document(doc, [
                    f"{self.source_id}/{document_id}: belge bulunamadı (HTTP 404)."
                ])
            raise

        html = r.text
        if not html or len(html.strip()) < 100:
            warnings.append(
                f"Empty or too-short HTML response for {self.source_id}/{document_id}"
            )
            return finalize_document(
                Document(
                    source=self.source_id,
                    document_id=document_id,
                    title=document_id,
                    content_status=ContentStatus.UNAVAILABLE,
                ),
                warnings,
            )

        text = html_to_text(html)
        doc = Document(
            source=self.source_id,
            document_id=document_id,
            title=document_id,
            full_text=text,
            markdown=text,
            content_hash=sha(text) if text else None,
            source_url=f"https://hudoc.echr.coe.int/eng?i={document_id}",
            content_status=ContentStatus.HTML_MARKDOWN if text else ContentStatus.METADATA_ONLY,
        )
        return finalize_document(doc, warnings)

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        if online:
            # Quick smoke: try fetching a known document
            try:
                doc = await self.get_document("001-218575")
                result.content_length_chars = len(doc.text or "")
                result.min_content_length_ok = result.content_length_chars >= 100
            except Exception:
                result.online_ok = False
                result.errors.append("HUDOC content API smoke failed.")
        return result
