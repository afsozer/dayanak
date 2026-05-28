from __future__ import annotations

from typing import Any

from .base import SourceClient, client, decode_b64, html_to_text, sha
from emsal_mcp.models import ContentStatus, Document, SearchResult


class BedestenClient(SourceClient):
    source_id = "bedesten"
    name = "Bedesten/Yargıtay"
    base = "https://bedesten.adalet.gov.tr"
    headers = {"AdaletApplicationName": "UyapMevzuat", "Origin": "https://mevzuat.adalet.gov.tr", "Referer": "https://mevzuat.adalet.gov.tr/"}

    async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]:
        item_type = filters.get("item_type") or filters.get("court") or "YARGITAYKARARI"
        payload = {"data": {"pageSize": min(int(limit), 100), "pageNumber": filters.get("page", 1), "itemTypeList": [item_type], "phrase": query, "sortFields": ["KARAR_TARIHI"], "sortDirection": "desc"}, "applicationName": "UyapMevzuat", "paging": True}
        if filters.get("chamber"):
            payload["data"]["birimAdi"] = filters["chamber"]
        if filters.get("start_date"):
            payload["data"]["kararTarihiStart"] = filters["start_date"]
        if filters.get("end_date"):
            payload["data"]["kararTarihiEnd"] = filters["end_date"]
        async with client() as c:
            r = await c.post(f"{self.base}/emsal-karar/searchDocuments", json=payload, headers=self.headers)
            r.raise_for_status()
            data = r.json().get("data", {})
        items = data.get("emsalKararList") or data.get("data") or data.get("items") or data.get("content") or []
        out: list[SearchResult] = []
        for it in items[:limit]:
            did = str(it.get("id") or it.get("documentId") or it.get("docId") or it.get("uuid") or "")
            if not did:
                continue
            item_type_obj = it.get("itemType") if isinstance(it.get("itemType"), dict) else {}
            court = item_type_obj.get("description") or item_type_obj.get("name") or it.get("itemType")
            chamber = it.get("birimAdi") or it.get("daire") or it.get("chamber")
            title = " | ".join([str(x) for x in [court, chamber, it.get("kararTarihiStr") or it.get("kararTarihi"), it.get("esasNo"), it.get("kararNo")] if x]) or did
            out.append(SearchResult(source=self.source_id, document_id=did, title=title, court=court, chamber=chamber, decision_date=it.get("kararTarihiStr") or it.get("kararTarihi"), esas_no=it.get("esasNo"), karar_no=it.get("kararNo"), content_status=ContentStatus.METADATA_ONLY, metadata=it))
        return out

    async def get_document(self, document_id: str, **kwargs: Any) -> Document:
        payload = {"data": {"documentId": document_id}, "applicationName": "UyapMevzuat"}
        async with client() as c:
            r = await c.post(f"{self.base}/emsal-karar/getDocumentContent", json=payload, headers=self.headers)
            r.raise_for_status()
            raw = r.json()
        data = raw.get("data", raw)
        encoded = data.get("content") or data.get("document") or data.get("data") or ""
        mime = data.get("mimeType") or "text/html"
        text = ""
        status = ContentStatus.METADATA_ONLY
        if encoded:
            blob = decode_b64(encoded) if isinstance(encoded, str) else encoded
            if "pdf" in mime:
                status = ContentStatus.PDF_LINK_ONLY
            else:
                html = blob.decode("utf-8", errors="ignore")
                text = html_to_text(html)
                status = ContentStatus.HTML_MARKDOWN
        return Document(source=self.source_id, document_id=document_id, title=data.get("title") or document_id, full_text=text, markdown=text, mime_type=mime, content_hash=sha(text) if text else None, content_status=status, raw=raw, metadata=data)
