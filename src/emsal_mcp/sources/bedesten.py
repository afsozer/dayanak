from __future__ import annotations

import re
from typing import Any

from .base import (
    BedestenUpstreamError,
    SourceClient,
    check_bedesten_response_error,
    check_http_response,
    client,
    decode_b64,
    html_to_text,
    sha,
)
from emsal_mcp.models import ContentStatus, Document, SearchPage, SearchResult, SourceSmokeResult, build_error, finalize_document


# ── Bedesten Solr query preprocessing ────────────────────────────────────────
# Bedesten runs Apache Solr with StandardQueryParser and the *default operator
# is OR*.  That means bare terms separated by whitespace match the UNION of the
# terms, not the intersection — `tahliye taahhüdü geçerlilik` returns any
# decision containing *any* of the three words, which is rarely what the caller
# wants.  Hosted yargı-mcp documents this explicitly; we go one step further and
# transparently rewrite queries that contain no Solr operators so that every
# bare term becomes required (`+term`).  Operator-bearing queries are passed
# through untouched.  The rewrite is reported back via `query_rewritten` so the
# behaviour stays auditable.

_SOLR_OPERATOR_RE = re.compile(r'[+\-"()]|\b(?:AND|OR|NOT)\b', re.UNICODE)


def rewrite_solr_query(query: str) -> tuple[str, bool]:
    """Rewrite a bare-term Solr query so every term is required.

    Bedesten's default Solr operator is OR — whitespace between bare terms
    means UNION.  When the caller writes a plain multi-word phrase without any
    Solr operator (``+``, ``-``, ``"``, ``AND``, ``OR``, ``NOT``, parens), we
    prefix each whitespace-separated token with ``+`` so all terms become
    required (intersection).  Queries that already use operators are returned
    unchanged — the caller clearly knows the dialect.

    Returns ``(rewritten_query, was_rewritten)``.
    """
    if not query or not query.strip():
        return query, False
    # If the query already uses any Solr operator, leave it alone.
    if _SOLR_OPERATOR_RE.search(query):
        return query, False
    tokens = query.split()
    # Single token — no rewrite needed.
    if len(tokens) <= 1:
        return query, False
    rewritten = " ".join(f"+{t}" for t in tokens)
    return rewritten, True


class BedestenClient(SourceClient):
    source_id = "bedesten"
    name = "Bedesten/Yargıtay"
    base = "https://bedesten.adalet.gov.tr"
    headers = {
        "AdaletApplicationName": "UyapMevzuat",
        "Origin": "https://mevzuat.adalet.gov.tr",
        "Referer": "https://mevzuat.adalet.gov.tr/",
    }

    # Delay (seconds) before the single upstream-error retry.  Overridable in
    # tests so the suite isn't slowed by a real sleep at the tail position.
    _upstream_retry_delay: float = 1.0

    # Bedesten item_type constants (used by Yargıtay adapter override)
    _default_item_type = "YARGITAYKARARI"

    # Response schema — declared for M-60 schema-drift detection.
    _search_response_keys = ["emsalKararList", "items", "data", "content"]
    _get_document_response_keys = ["content", "document", "data"]

    async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]:
        """Search and return only the results list.

        Delegates to ``search_page()`` and unwraps the ``SearchPage``
        container.  Keeps the ``list[SearchResult]`` contract intact.
        """
        page_num = filters.pop("page", 1)
        sp = await self.search_page(query=query, limit=limit, page=page_num, **filters)
        return sp.results

    async def search_page(self, query: str, limit: int = 10, page: int = 1, **filters: Any) -> SearchPage:
        """Search with pagination metadata from the upstream Bedesten response.

        The upstream returns ``data.total`` (total matching records) and
        ``data.start`` (0-based offset), letting us compute ``total_pages``.
        """
        # ── Solr query preprocessing ────────────────────────────────────
        original_query = query
        query, query_rewritten = rewrite_solr_query(query)

        # ── court_types → itemTypeList ────────────────────────────────
        court_types: list[str] | None = filters.get("court_types") or filters.get("court_types_list")
        if court_types and isinstance(court_types, list) and len(court_types) > 0:
            item_type_list = court_types
        else:
            item_type = filters.get("item_type") or filters.get("court") or self._default_item_type
            if item_type and not item_type.isupper():
                item_type = item_type.upper().replace(" ", "").replace("İ", "I").replace("Ş", "S").replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")
            item_type_list = [item_type]

        # ── esas_no / karar_no parsing ─────────────────────────────────
        def _parse_yy_slash_ss(raw: str | None) -> tuple[int | None, int | None]:
            if not raw:
                return None, None
            parts = raw.split("/")
            if len(parts) != 2:
                return None, None
            try:
                return int(parts[0].strip()), int(parts[1].strip())
            except (ValueError, TypeError):
                return None, None

        esas_yil, esas_sira = _parse_yy_slash_ss(filters.get("esas_no"))
        karar_yil, karar_sira = _parse_yy_slash_ss(filters.get("karar_no"))

        # ── sort_by ────────────────────────────────────────────────────
        sort_by = filters.get("sort_by")
        if sort_by is None:
            sort_by = "relevance" if query and query.strip() else "date"
        sort_by = str(sort_by).lower()
        if sort_by not in ("relevance", "date"):
            sort_by = "relevance" if query and query.strip() else "date"

        data_payload: dict[str, Any] = {
            "pageSize": min(int(limit), 100),
            "pageNumber": page,
            "itemTypeList": item_type_list,
            "phrase": query,
        }
        if sort_by == "date":
            data_payload["sortFields"] = ["KARAR_TARIHI"]
            data_payload["sortDirection"] = filters.get("sort_direction") or "desc"
        payload: dict[str, Any] = {
            "data": data_payload,
            "applicationName": "UyapMevzuat",
            "paging": True,
        }
        birim = filters.get("birimAdi") or filters.get("chamber")
        if birim:
            data_payload["birimAdi"] = birim
        if filters.get("start_date") or filters.get("karar_tarihi_start"):
            data_payload["kararTarihiStart"] = filters.get("start_date") or filters.get("karar_tarihi_start")
        if filters.get("end_date") or filters.get("karar_tarihi_end"):
            data_payload["kararTarihiEnd"] = filters.get("end_date") or filters.get("karar_tarihi_end")
        if esas_yil is not None:
            data_payload["esasNoYil"] = esas_yil
        if esas_sira is not None:
            data_payload["esasNoSira"] = esas_sira
        if karar_yil is not None:
            data_payload["kararNoYil"] = karar_yil
        if karar_sira is not None:
            data_payload["kararNoSira"] = karar_sira
        async with client() as c:
            r = await c.post(f"{self.base}/emsal-karar/searchDocuments", json=payload, headers=self.headers)
            check_http_response(r, self.source_id)
            raw_data = r.json()
        try:
            check_bedesten_response_error(raw_data, source=self.source_id)
        except BedestenUpstreamError:
            import asyncio as _aio
            await _aio.sleep(self._upstream_retry_delay)
            async with client() as c:
                r2 = await c.post(f"{self.base}/emsal-karar/searchDocuments", json=payload, headers=self.headers)
                check_http_response(r2, self.source_id)
                raw_data = r2.json()
            check_bedesten_response_error(raw_data, source=self.source_id)
        data = raw_data.get("data", raw_data)
        _ = self._check_response_schema(data, self._search_response_keys, "search")

        # ── Extract total before processing items ──────────────────────
        total: int | None = data.get("total") if isinstance(data, dict) else None
        page_size = min(int(limit), 100)
        total_pages: int | None = None
        if total is not None and isinstance(total, int):
            total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 0

        if not isinstance(data, dict):
            return SearchPage(results=[], total=total, page=page, page_size=page_size, total_pages=total_pages)

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
            meta = dict(it) if isinstance(it, dict) else {}
            if query_rewritten:
                meta["query_rewritten"] = True
                meta["original_query"] = original_query
            # Legacy link kept as alternate_url for callers depending on it.
            meta["alternate_url"] = f"https://emsal.uyap.gov.tr/getDokuman?id={did}"
            out.append(SearchResult(
                source=self.source_id, document_id=did, title=title,
                court=court, chamber=chamber,
                decision_date=it.get("kararTarihiStr") or it.get("kararTarihi"),
                esas_no=it.get("esasNo"), karar_no=it.get("kararNo"),
                source_url=f"https://mevzuat.adalet.gov.tr/ictihat/{did}",
                content_status=ContentStatus.METADATA_ONLY, metadata=meta,
            ))
        return SearchPage(results=out, total=total, page=page, page_size=page_size, total_pages=total_pages)

    async def get_document(self, document_id: str, **kwargs: Any) -> Document:
        import httpx

        payload = {"data": {"documentId": document_id}, "applicationName": "UyapMevzuat"}
        try:
            async with client() as c:
                r = await c.post(f"{self.base}/emsal-karar/getDocumentContent", json=payload, headers=self.headers)
                check_http_response(r, self.source_id)
                raw = r.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            # 404 = full text not (yet) published by the source. Very recent
            # decisions often have searchable metadata but no uploaded content.
            # Degrade gracefully (invariant #3: structured result, not exception)
            # so callers get a fast UNAVAILABLE instead of a crash. Date-agnostic:
            # once the source backfills the text, the same code returns it.
            if status_code == 404:
                doc = Document(
                    source=self.source_id, document_id=document_id,
                    title=document_id, content_status=ContentStatus.UNAVAILABLE,
                )
                return finalize_document(doc, [
                    f"{self.source_id}/{document_id}: tam metin kaynakta yok (HTTP 404); "
                    "büyük olasılıkla çok yeni bir karar, içerik henüz yayımlanmamış."
                ])
            raise
        # Surface upstream faults explicitly (do not silently return UNAVAILABLE).
        try:
            check_bedesten_response_error(raw, source=self.source_id)
        except BedestenUpstreamError:
            import asyncio as _aio
            await _aio.sleep(self._upstream_retry_delay)
            async with client() as c:
                r2 = await c.post(f"{self.base}/emsal-karar/getDocumentContent", json=payload, headers=self.headers)
                check_http_response(r2, self.source_id)
                raw = r2.json()
            check_bedesten_response_error(raw, source=self.source_id)
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
            source_url=f"https://mevzuat.adalet.gov.tr/ictihat/{document_id}",
            content_status=status, raw=raw,
            metadata={**data, "alternate_url": f"https://emsal.uyap.gov.tr/getDokuman?id={document_id}"} if isinstance(data, dict) else data,
        )
        return finalize_document(doc, warnings)

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        result.min_content_length_ok = True  # Bedesten returns full HTML
        return result
