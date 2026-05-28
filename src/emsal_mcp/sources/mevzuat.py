from __future__ import annotations

from .bedesten import BedestenClient


class MevzuatClient(BedestenClient):
    source_id = "mevzuat"
    name = "Mevzuat/Bedesten"
    base = "https://bedesten.adalet.gov.tr"

    async def search(self, query: str, limit: int = 10, **filters):
        from .base import client
        from emsal_mcp.models import ContentStatus, SearchResult
        body = {"data": {"pageSize": min(int(limit), 100), "pageNumber": filters.get("page", 1), "phrase": query, "sortFields": ["RESMI_GAZETE_TARIHI"], "sortDirection": "desc"}, "applicationName": "UyapMevzuat", "paging": True}
        if filters.get("type"):
            body["data"]["mevzuatTurList"] = [filters["type"]]
        async with client() as c:
            r = await c.post(f"{self.base}/mevzuat/searchDocuments", json=body, headers=self.headers)
            r.raise_for_status()
            data = r.json().get("data", {})
        items = data.get("mevzuatList") or data.get("items") or data.get("data") or []
        return [SearchResult(source=self.source_id, document_id=str(i.get("documentId") or i.get("id") or ""), title=i.get("title") or i.get("mevzuatAdi") or str(i.get("documentId") or i.get("id")), summary=i.get("summary") or i.get("ozet"), court="Mevzuat", decision_date=i.get("resmiGazeteTarihi") or i.get("date"), karar_no=i.get("mevzuatNo"), content_status=ContentStatus.METADATA_ONLY, metadata=i) for i in items[:limit] if (i.get("documentId") or i.get("id"))]

    async def get_document(self, document_id: str, **kwargs):
        from .base import client, decode_b64, html_to_text, sha
        from emsal_mcp.models import ContentStatus, Document
        payload = {"data": {"documentId": document_id}, "applicationName": "UyapMevzuat"}
        async with client() as c:
            r = await c.post(f"{self.base}/mevzuat/getDocumentContent", json=payload, headers=self.headers)
            r.raise_for_status()
            raw = r.json()
        data = raw.get("data", raw)
        encoded = data.get("content") or ""
        text = html_to_text(decode_b64(encoded).decode("utf-8", errors="ignore")) if encoded else ""
        return Document(source=self.source_id, document_id=document_id, title=data.get("title") or data.get("mevzuatAdi") or document_id, markdown=text, full_text=text, content_status=ContentStatus.HTML_MARKDOWN if text else ContentStatus.METADATA_ONLY, content_hash=sha(text) if text else None, raw=raw, metadata=data)
