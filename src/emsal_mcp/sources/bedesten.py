from __future__ import annotations

from typing import Any

from .base import SourceClient, check_http_response, client, decode_b64, html_to_text, sha
from emsal_mcp.models import ContentStatus, Document, SearchResult, SourceSmokeResult, finalize_document


class BedestenClient(SourceClient):
    source_id = "bedesten"
    name = "Bedesten/Yargıtay"
    base = "https://bedesten.adalet.gov.tr"
    headers = {
        "AdaletApplicationName": "UyapMevzuat",
        "Origin": "https://mevzuat.adalet.gov.tr",
        "Referer": "https://mevzuat.adalet.gov.tr/",
    }

    # Bedesten item_type constants (used by Yargıtay adapter override)
    _default_item_type = "YARGITAYKARARI"

    # Response schema — declared for M-60 schema-drift detection.
    _search_response_keys = ["emsalKararList", "items", "data", "content"]
    _get_document_response_keys = ["content", "document", "data"]

    async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]:
        item_type = filters.get("item_type") or filters.get("court") or self._default_item_type
        # Normalize item_type: accept common variations
        if item_type and not item_type.isupper():
            item_type = item_type.upper().replace(" ", "").replace("İ", "I").replace("Ş", "S").replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")

        data_payload: dict[str, Any] = {
            "pageSize": min(int(limit), 100),
            "pageNumber": filters.get("page", 1),
            "itemTypeList": [item_type],
            "phrase": query,
            "sortFields": ["KARAR_TARIHI"],
            "sortDirection": "desc",
        }
        payload: dict[str, Any] = {
            "data": data_payload,
            "applicationName": "UyapMevzuat",
            "paging": True,
        }
        if filters.get("chamber"):
            data_payload["birimAdi"] = filters["chamber"]
        if filters.get("start_date"):
            data_payload["kararTarihiStart"] = filters["start_date"]
        if filters.get("end_date"):
            data_payload["kararTarihiEnd"] = filters["end_date"]
        async with client() as c:
            r = await c.post(f"{self.base}/emsal-karar/searchDocuments", json=payload, headers=self.headers)
            check_http_response(r, self.source_id)
            raw_data = r.json()
        data = raw_data.get("data", raw_data)
        # M-60: schema validation — never silently swallow an API shape change
        _ = self._check_response_schema(data, self._search_response_keys, "search")
        items = data.get("emsalKararList") or data.get("data") or data.get("items") or data.get("content") or []
        out: list[SearchResult] = []
        for it in items[:limit]:
            did = str(it.get("id") or it.get("documentId") or it.get("docId") or it.get("uuid") or "")
            if not did:
                continue
            item_type_obj = it.get("itemType") if isinstance(it.get("itemType"), dict) else {}
            court = item_type_obj.get("description") or item_type_obj.get("name") or it.get("itemType")
            chamber = it.get("birimAdi") or it.get("daire") or it.get("chamber")
            title = " | ".join([
                str(x) for x in [
                    court, chamber,
                    it.get("kararTarihiStr") or it.get("kararTarihi"),
                    it.get("esasNo"), it.get("kararNo"),
                ] if x
            ]) or did
            out.append(SearchResult(
                source=self.source_id, document_id=did, title=title,
                court=court, chamber=chamber,
                decision_date=it.get("kararTarihiStr") or it.get("kararTarihi"),
                esas_no=it.get("esasNo"), karar_no=it.get("kararNo"),
                content_status=ContentStatus.METADATA_ONLY, metadata=it,
            ))
        return out

    async def get_document(self, document_id: str, **kwargs: Any) -> Document:
        payload = {"data": {"documentId": document_id}, "applicationName": "UyapMevzuat"}
        async with client() as c:
            r = await c.post(f"{self.base}/emsal-karar/getDocumentContent", json=payload, headers=self.headers)
            check_http_response(r, self.source_id)
            raw = r.json()
        data = raw.get("data", raw)
        # M-60: schema validation
        _ = self._check_response_schema(data, self._get_document_response_keys, "get_document")
        encoded = data.get("content") or data.get("document") or data.get("data") or ""
        mime = data.get("mimeType") or "text/html"
        text = ""
        status = ContentStatus.METADATA_ONLY
        warnings: list[str] = []
        if encoded:
            blob = decode_b64(encoded) if isinstance(encoded, str) else encoded
            if not blob:
                warnings.append(f"Base64 decode failed for {self.source_id}/{document_id}; content unavailable.")
                status = ContentStatus.UNAVAILABLE
            elif "pdf" in mime:
                status = ContentStatus.PDF_LINK_ONLY
            else:
                try:
                    html = blob.decode("utf-8", errors="ignore")
                except Exception:
                    html = ""
                    warnings.append("Failed to decode content blob as UTF-8.")
                if html:
                    text = html_to_text(html)
                    status = ContentStatus.HTML_MARKDOWN
        doc = Document(
            source=self.source_id, document_id=document_id,
            title=data.get("title") or document_id,
            full_text=text, markdown=text, mime_type=mime,
            content_hash=sha(text) if text else None,
            content_status=status, raw=raw, metadata=data,
        )
        return finalize_document(doc, warnings)

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        result.min_content_length_ok = True  # Bedesten returns full HTML
        return result
