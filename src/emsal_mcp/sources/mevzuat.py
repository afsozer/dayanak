from __future__ import annotations

from typing import Any

from emsal_mcp.models import Document, SearchResult

from .bedesten import BedestenClient


class MevzuatClient(BedestenClient):
    source_id = "mevzuat"
    name = "Mevzuat/Bedesten"
    base = "https://bedesten.adalet.gov.tr"

    # Response schema — declared for M-60 schema-drift detection.
    _search_response_keys = ["mevzuatList", "items", "data"]
    _get_document_response_keys = ["content"]

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        from .base import check_http_response, client
        from emsal_mcp.models import ContentStatus, SearchResult
        data_payload: dict[str, Any] = {
            "pageSize": min(int(limit), 100),
            "pageNumber": filters.get("page", 1),
            "phrase": query,
            "sortFields": ["RESMI_GAZETE_TARIHI"],
            "sortDirection": "desc",
        }
        body: dict[str, Any] = {
            "data": data_payload,
            "applicationName": "UyapMevzuat",
            "paging": True,
        }
        if filters.get("type"):
            data_payload["mevzuatTurList"] = [filters["type"]]
        async with client() as c:
            r = await c.post(f"{self.base}/mevzuat/searchDocuments", json=body, headers=self.headers)
            check_http_response(r, self.source_id)
            raw_data = r.json()
        data = raw_data.get("data", raw_data)
        # M-60: schema validation
        _ = self._check_response_schema(data, self._search_response_keys, "search")
        items = data.get("mevzuatList") or data.get("items") or data.get("data") or []
        out: list[SearchResult] = []
        for i in items[:limit]:
            doc_id = str(i.get("documentId") or i.get("mevzuatId") or i.get("id") or "")
            if not doc_id:
                continue
            # Fix title: prefer mevzuatAdi, fallback to title, then construct from fields
            title = (
                i.get("mevzuatAdi")
                or i.get("title")
                or " | ".join(filter(None, [
                    str(x) for x in [
                        i.get("mevzuatNo"),
                        i.get("resmiGazeteTarihi") or i.get("date"),
                        i.get("summary"),
                    ] if x
                ]))
                or f"Mevzuat {doc_id}"
            )
            out.append(SearchResult(
                source=self.source_id, document_id=doc_id, title=title,
                summary=i.get("summary") or i.get("ozet"),
                court="Mevzuat",
                decision_date=i.get("resmiGazeteTarihi") or i.get("date"),
                karar_no=(str(i["mevzuatNo"]) if i.get("mevzuatNo") is not None else None),
                content_status=ContentStatus.METADATA_ONLY, metadata=i,
            ))
        return out

    async def get_document(self, document_id: str, **kwargs) -> Document:
        from .base import check_http_response, client, decode_b64, html_to_text, sha
        from emsal_mcp.models import ContentStatus, Document, finalize_document
        payload = {"data": {"documentId": document_id}, "applicationName": "UyapMevzuat"}
        async with client() as c:
            r = await c.post(f"{self.base}/mevzuat/getDocumentContent", json=payload, headers=self.headers)
            check_http_response(r, self.source_id)
            raw = r.json()
        data = raw.get("data", raw)
        # M-60: schema validation
        _ = self._check_response_schema(data, self._get_document_response_keys, "get_document")
        encoded = data.get("content") or ""
        text = ""
        warnings: list[str] = []
        status = ContentStatus.METADATA_ONLY
        if encoded:
            blob = decode_b64(encoded)
            if not blob:
                warnings.append(f"Base64 decode failed for mevzuat/{document_id}; content unavailable.")
                status = ContentStatus.UNAVAILABLE
            else:
                try:
                    html = blob.decode("utf-8", errors="ignore")
                except Exception:
                    html = ""
                    warnings.append("Failed to decode content blob as UTF-8.")
                if html:
                    text = html_to_text(html)
                    status = ContentStatus.HTML_MARKDOWN
        # Fix title: prefer mevzuatAdi
        title = data.get("mevzuatAdi") or data.get("title") or document_id
        doc = Document(
            source=self.source_id, document_id=document_id,
            title=title,
            markdown=text, full_text=text,
            content_status=status,
            content_hash=sha(text) if text else None,
            raw=raw, metadata=data,
        )
        return finalize_document(doc, warnings)
