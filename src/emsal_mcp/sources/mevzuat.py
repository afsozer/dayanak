from __future__ import annotations

from typing import Any

from emsal_mcp.models import Document, SearchPage, SearchResult

from .bedesten import BedestenClient


class MevzuatClient(BedestenClient):
    source_id = "mevzuat"
    name = "Mevzuat/Bedesten"
    base = "https://bedesten.adalet.gov.tr"

    # Response schema — declared for M-60 schema-drift detection.
    _search_response_keys = ["mevzuatList", "items", "data"]
    _get_document_response_keys = ["content"]

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        results, _ = await self._search_raw(query, limit, **filters)
        return results

    async def search_page(
        self, query: str = "", limit: int = 10, page: int = 1, **filters
    ) -> SearchPage:
        """Search with the upstream total, which ``search()`` throws away.

        Bedesten answers ``{"data": {"mevzuatList": [...], "total": 1860,
        "start": 0}}`` (measured 05.09.2026, mevzuatAdi="Kanun"), but the
        list-returning ``search()`` contract has no room for ``total`` — so a
        caller asking for 10 of 1 860 matches could not tell that from 10 of
        10. Kept alongside ``search()`` rather than replacing it.
        """
        filters.setdefault("page", page)
        results, total = await self._search_raw(query, limit, **filters)
        page_size = max(1, int(limit))
        total_pages = None
        if isinstance(total, int):
            total_pages = max(1, (total + page_size - 1) // page_size) if total else 0
        return SearchPage(
            results=results, total=total if isinstance(total, int) else None,
            page=page, page_size=page_size, total_pages=total_pages,
        )

    async def _search_raw(
        self, query: str, limit: int = 10, **filters
    ) -> tuple[list[SearchResult], int | None]:
        from .base import (
            BedestenUpstreamError,
            check_bedesten_response_error,
            check_http_response,
            client,
        )
        from emsal_mcp.models import ContentStatus, SearchResult
        # ── sort_by: relevance vs date ──────────────────────────────────
        # Mirror Bedesten: default to relevance when a phrase is present, date
        # when only filters are used.  Bedesten's Solr default ordering is by
        # score (relevance) when sortFields is omitted; sending RESMI_GAZETE_TARIHI
        # forces newest-first which buries the actual matching law beneath
        # recent unrelated regulation amendments.
        sort_by = filters.get("sort_by")
        if sort_by is None:
            sort_by = "relevance" if query and query.strip() else "date"
        sort_by = str(sort_by).lower()
        if sort_by not in ("relevance", "date", "kayit_tarihi", "resmi_gazete_tarihi"):
            sort_by = "relevance" if query and query.strip() else "date"

        data_payload: dict[str, Any] = {
            "pageSize": min(int(limit), 100),
            "pageNumber": filters.get("page", 1),
            "phrase": query,
        }
        if sort_by == "date" or sort_by == "resmi_gazete_tarihi":
            data_payload["sortFields"] = ["RESMI_GAZETE_TARIHI"]
            data_payload["sortDirection"] = filters.get("sort_direction") or "desc"
        elif sort_by == "kayit_tarihi":
            data_payload["sortFields"] = ["KAYIT_TARIHI"]
            data_payload["sortDirection"] = filters.get("sort_direction") or "desc"
        # relevance → omit sortFields/sortDirection (Solr score default).
        body: dict[str, Any] = {
            "data": data_payload,
            "applicationName": "UyapMevzuat",
            "paging": True,
        }
        # ── Title / number / type filters (mevzuat.gov.tr-style) ──────────
        # mevzuat_adi → search ONLY in the title (mevzuatAdi).  When a title is
        # given, we replace the body-text `phrase` with the title search so the
        # actual law (e.g. KVKK) surfaces instead of recent unrelated amendments.
        mevzuat_adi = filters.get("mevzuat_adi") or filters.get("mevzuatAdi")
        if mevzuat_adi:
            data_payload["mevzuatAdi"] = mevzuat_adi
            # Drop the body phrase — we want a title-scoped search, not a
            # full-text search that buries the law under amendments.
            data_payload.pop("phrase", None)
        mevzuat_no = filters.get("mevzuat_no") or filters.get("mevzuatNo")
        if mevzuat_no is not None and str(mevzuat_no).strip():
            data_payload["mevzuatNo"] = str(mevzuat_no).strip()
            # A direct number lookup should NOT be constrained by an empty
            # body phrase — Bedesten applies an empty phrase as a filter that
            # suppresses matches. Drop it so the number resolves cleanly.
            if not (query and query.strip()):
                data_payload.pop("phrase", None)
        # mevzuat_tur_list → multi-type filter (KANUN, KHK, YONETMELIK, ...).
        tur_list = (
            filters.get("mevzuat_tur_list")
            or filters.get("mevzuatTurList")
        )
        if tur_list and isinstance(tur_list, list) and len(tur_list) > 0:
            data_payload["mevzuatTurList"] = tur_list
        elif filters.get("type"):
            data_payload["mevzuatTurList"] = [filters["type"]]
        async with client() as c:
            r = await c.post(f"{self.base}/mevzuat/searchDocuments", json=body, headers=self.headers)
            check_http_response(r, self.source_id)
            raw_data = r.json()
        # Surface upstream Solr/service faults explicitly (one short retry).
        try:
            check_bedesten_response_error(raw_data, source=self.source_id)
        except BedestenUpstreamError as exc:
            if not exc.retryable:
                raise
            import asyncio as _aio
            await _aio.sleep(self._upstream_retry_delay)
            async with client() as c:
                r2 = await c.post(f"{self.base}/mevzuat/searchDocuments", json=body, headers=self.headers)
                check_http_response(r2, self.source_id)
                raw_data = r2.json()
            check_bedesten_response_error(raw_data, source=self.source_id)
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
            url = i.get("url")
            if not url and i.get("mevzuatNo") and i.get("mevzuatTur"):
                tur_id = i["mevzuatTur"].get("id") if isinstance(i["mevzuatTur"], dict) else i["mevzuatTur"]
                tertip = i.get("mevzuatTertip") or 5
                url = f"https://www.mevzuat.gov.tr/mevzuat?MevzuatNo={i['mevzuatNo']}&MevzuatTur={tur_id}&MevzuatTertip={tertip}"

            out.append(SearchResult(
                source=self.source_id, document_id=doc_id, title=title,
                summary=i.get("summary") or i.get("ozet"),
                court="Mevzuat",
                decision_date=i.get("resmiGazeteTarihi") or i.get("date"),
                karar_no=(str(i["mevzuatNo"]) if i.get("mevzuatNo") is not None else None),
                source_url=url,
                content_status=ContentStatus.METADATA_ONLY, metadata=i,
            ))
        total = data.get("total")
        return out, (total if isinstance(total, int) else None)

    async def get_document(self, document_id: str, **kwargs) -> Document:
        from .base import (
            BedestenUpstreamError,
            check_bedesten_response_error,
            check_http_response,
            client,
            decode_b64,
            html_to_text,
            sha,
        )
        from emsal_mcp.models import ContentStatus, Document, finalize_document
        payload = {"data": {"id": document_id, "documentType": "MEVZUAT"}, "applicationName": "UyapMevzuat"}
        async with client() as c:
            r = await c.post(f"{self.base}/mevzuat/getDocumentContent", json=payload, headers=self.headers)
            check_http_response(r, self.source_id)
            raw = r.json()
        # Surface upstream faults explicitly (one short retry).
        try:
            check_bedesten_response_error(raw, source=self.source_id)
        except BedestenUpstreamError as exc:
            if not exc.retryable:
                raise
            import asyncio as _aio
            await _aio.sleep(self._upstream_retry_delay)
            async with client() as c:
                r2 = await c.post(f"{self.base}/mevzuat/getDocumentContent", json=payload, headers=self.headers)
                check_http_response(r2, self.source_id)
                raw = r2.json()
            check_bedesten_response_error(raw, source=self.source_id)
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
        # Fix title: prefer mevzuatAdi. getDocumentContent often answers with
        # {content, mimeType, version} only — no metadata at all — so fall back
        # to the heading in the document text before giving up on the raw id.
        from .mevzuatgov import _leading_title
        title = data.get("mevzuatAdi") or data.get("title") or ""
        if not title:
            title = _leading_title(text, document_id) if text else document_id
        url = data.get("url")
        if not url and data.get("mevzuatNo") and data.get("mevzuatTur"):
            tur_id = data["mevzuatTur"].get("id") if isinstance(data["mevzuatTur"], dict) else data["mevzuatTur"]
            tertip = data.get("mevzuatTertip") or 5
            url = f"https://www.mevzuat.gov.tr/mevzuat?MevzuatNo={data['mevzuatNo']}&MevzuatTur={tur_id}&MevzuatTertip={tertip}"

        doc = Document(
            source=self.source_id, document_id=document_id,
            title=title,
            markdown=text, full_text=text,
            content_status=status,
            content_hash=sha(text) if text else None,
            source_url=url,
            raw=raw, metadata=data,
        )
        return finalize_document(doc, warnings)
