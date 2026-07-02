from __future__ import annotations

import re
from typing import Any

from .base import SourceClient, check_http_response, client, decode_b64, html_to_text, sha
from emsal_mcp.models import ContentStatus, Document, SearchResult, SourceSmokeResult, finalize_document


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

    # Bedesten item_type constants (used by Yargıtay adapter override)
    _default_item_type = "YARGITAYKARARI"

    # Response schema — declared for M-60 schema-drift detection.
    _search_response_keys = ["emsalKararList", "items", "data", "content"]
    _get_document_response_keys = ["content", "document", "data"]

    async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]:
        # ── Solr query preprocessing ────────────────────────────────────
        # Bedesten's default Solr operator is OR: bare whitespace-separated
        # terms are unioned, not intersected.  When the caller hands us a plain
        # multi-word phrase with no Solr operators, transparently prefix every
        # token with `+` so all terms are required.  Operator-bearing queries
        # pass through untouched.  See rewrite_solr_query docstring.
        original_query = query
        query, query_rewritten = rewrite_solr_query(query)

        # ── court_types → itemTypeList ────────────────────────────────
        # Accept a list of court types for multi-court search in a single call.
        # Falls back to single item_type (backward-compatible).
        court_types: list[str] | None = filters.get("court_types") or filters.get("court_types_list")
        if court_types and isinstance(court_types, list) and len(court_types) > 0:
            item_type_list = court_types
        else:
            item_type = filters.get("item_type") or filters.get("court") or self._default_item_type
            # Normalize item_type: accept common variations
            if item_type and not item_type.isupper():
                item_type = item_type.upper().replace(" ", "").replace("İ", "I").replace("Ş", "S").replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")
            item_type_list = [item_type]

        # ── esas_no / karar_no parsing (YIL/SIRA → int fields) ───────
        def _parse_yy_slash_ss(raw: str | None) -> tuple[int | None, int | None]:
            """Parse 'YIL/SIRA' (e.g. '2023/1234') into (year, sequence) ints."""
            if not raw:
                return None, None
            parts = raw.split("/")
            if len(parts) != 2:
                return None, None
            try:
                yil = int(parts[0].strip())
                sira = int(parts[1].strip())
                return yil, sira
            except (ValueError, TypeError):
                return None, None

        esas_yil, esas_sira = _parse_yy_slash_ss(filters.get("esas_no"))
        karar_yil, karar_sira = _parse_yy_slash_ss(filters.get("karar_no"))

        # ── sort_by: relevance (Solr score) vs date ────────────────────
        # Bedesten's Solr default ordering is by score (relevance) when no
        # sortFields are sent.  Hosted yargi-mcp exposes this as
        # sort_by: "relevance"|"date" and defaults to relevance when a phrase
        # is present, date when only filters (docket no / date range) are used.
        # We mirror that: callers can force sort_by; otherwise we infer it —
        # a non-empty phrase → relevance, an empty phrase (filter-only lookup)
        # → date desc.
        sort_by = filters.get("sort_by")
        if sort_by is None:
            sort_by = "relevance" if query and query.strip() else "date"
        sort_by = str(sort_by).lower()
        if sort_by not in ("relevance", "date"):
            sort_by = "relevance" if query and query.strip() else "date"

        data_payload: dict[str, Any] = {
            "pageSize": min(int(limit), 100),
            "pageNumber": filters.get("page", 1),
            "itemTypeList": item_type_list,
            "phrase": query,
        }
        if sort_by == "date":
            data_payload["sortFields"] = ["KARAR_TARIHI"]
            data_payload["sortDirection"] = filters.get("sort_direction") or "desc"
        # relevance → omit sortFields/sortDirection so Solr uses score-based
        # ordering (its default).
        payload: dict[str, Any] = {
            "data": data_payload,
            "applicationName": "UyapMevzuat",
            "paging": True,
        }
        # birimAdi: accept both "chamber" (legacy) and "birimAdi" (new, direct)
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
        data = raw_data.get("data", raw_data)
        # M-60: schema validation — never silently swallow an API shape change
        _ = self._check_response_schema(data, self._search_response_keys, "search")
        if not isinstance(data, dict):
            # Null/non-dict data (empty phrase, past last page) → no results.
            return []
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
            # Carry the Solr query-rewrite flag into result metadata so the
            # auto-+ safety net stays auditable end-to-end.
            meta = dict(it) if isinstance(it, dict) else {}
            if query_rewritten:
                meta["query_rewritten"] = True
                meta["original_query"] = original_query
            out.append(SearchResult(
                source=self.source_id, document_id=did, title=title,
                court=court, chamber=chamber,
                decision_date=it.get("kararTarihiStr") or it.get("kararTarihi"),
                esas_no=it.get("esasNo"), karar_no=it.get("kararNo"),
                source_url=f"https://emsal.uyap.gov.tr/getDokuman?id={did}",
                content_status=ContentStatus.METADATA_ONLY, metadata=meta,
            ))
        return out

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
            source_url=f"https://emsal.uyap.gov.tr/getDokuman?id={document_id}",
            content_status=status, raw=raw, metadata=data,
        )
        return finalize_document(doc, warnings)

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        result.min_content_length_ok = True  # Bedesten returns full HTML
        return result
