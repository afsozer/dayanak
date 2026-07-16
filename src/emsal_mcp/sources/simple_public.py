from __future__ import annotations

import base64
import re
from urllib.parse import quote

from .base import SourceClient, check_http_response, client, html_to_text, metadata_doc, sha
from emsal_mcp.models import ContentStatus, Document, SearchPage, SearchResult, SourceSmokeResult, finalize_document


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _url_id(url: str) -> str:
    return "url:" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def _decode_url_id(document_id: str) -> str:
    if not document_id.startswith("url:"):
        return document_id
    raw = document_id[4:]
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()


class AymClient(SourceClient):
    """Anayasa Mahkemesi (AYM) source adapter — KBB (Karar Bilgi Bankası) API.

    AYM migrated its decision banks to a React SPA (KBB) in 2025.  The SPA's
    backend is a public JSON API discovered 2026-07-15 (see
    PARITY_V2_RAPOR.md, Görev 7b):

    - Search: ``POST /api/core/public/search`` with JSON body
      ``{page (0-based), size, query, kararTipi?, sort?, order?}``.
      A single host serves ALL decision types via ``kararTipi``:
      ``BireyselBasvuru`` / ``NormDenetimi`` / ``SiyasiParti`` / ``YuceDivan``.
    - Files: ``GET /api/core/public/kararlar/{uuid}/dosyalar?kararTipi=X``
      lists decision files (UDF), then
      ``GET /api/core/public/files/download-attachment/{folder}/{filename}``
      returns the UDF bytes.  Full text is extracted with ``emsal_mcp.udf``.

    ⚠️ The site sits behind an F5 WAF: requests need a browser-like
    User-Agent, a cookie warm-up GET on ``/kbb/`` in the same session, and a
    strictly UTF-8 JSON body (invalid byte sequences are rejected with an
    HTML "Request Rejected" page).

    Filters: ``decision_type`` (``bireysel_basvuru``/``norm_denetimi``/
    ``siyasi_parti``/``yuce_divan``), ``sort_by`` (``relevance`` default /
    ``date``).  Legacy IDs (``BB/2021/30620``, ``ND/2023/123``) are resolved
    to KBB UUIDs via a docket-number search.
    """

    source_id = "aym"
    name = "Anayasa Mahkemesi"
    base = "https://kararlarbilgibankasi.anayasa.gov.tr"

    _DECISION_TYPES = {
        "bireysel_basvuru": "BireyselBasvuru",
        "norm_denetimi": "NormDenetimi",
        "siyasi_parti": "SiyasiParti",
        "yuce_divan": "YuceDivan",
    }

    @property
    def _headers(self) -> dict:
        # F5 WAF rejects non-browser user agents on the JSON API.
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Origin": self.base,
            "Referer": f"{self.base}/kbb/pages/search/Tumu",
        }

    async def _api_search(self, body: dict) -> dict:
        """POST the KBB search API inside a warmed-up (cookied) session."""
        async with client() as c:
            # WAF cookie warm-up — same session carries the F5 cookies.
            await c.get(f"{self.base}/kbb/", headers=self._headers)
            r = await c.post(
                f"{self.base}/api/core/public/search",
                json=body, headers=self._headers,
            )
            check_http_response(r, self.source_id)
            data = r.json()
        if not isinstance(data, dict) or "data" not in data:
            raise ValueError(f"AYM KBB search: beklenmeyen yanıt şeması: {str(data)[:200]}")
        return data

    def _to_result(self, it: dict) -> SearchResult:
        karar_tipi = it.get("kararTipi") or ""
        appno = it.get("basvuruNo")
        esas = it.get("esasNo") or appno
        karar_no = it.get("kararNo")
        name = _clean(it.get("basvuruAdi") or it.get("davaAdi"))
        parts = ["AYM", karar_tipi, name, esas, karar_no, it.get("kararTarihi")]
        title = " | ".join(str(p) for p in parts if p)
        summary = html_to_text(it.get("kararKonusu") or "")[:1000]
        meta = {
            k: it.get(k)
            for k in ("kararTipi", "basvuruNo", "eskiDBID", "yayinTarihi",
                      "resmiGazeteTarihi", "kararTuruDosyaSonucuLabel", "highlightCount")
            if it.get(k) is not None
        }
        return SearchResult(
            source=self.source_id, document_id=str(it.get("id")),
            title=title, summary=summary or None,
            court="Anayasa Mahkemesi",
            decision_date=it.get("kararTarihi"),
            esas_no=esas, karar_no=karar_no,
            source_url=f"{self.base}/kbb/?id={it.get('id')}",
            content_status=ContentStatus.METADATA_ONLY,
            metadata=meta,
        )

    def _build_body(self, query: str, limit: int, page: int, filters: dict) -> dict:
        body: dict = {"page": max(int(page), 1) - 1, "size": min(int(limit), 50)}
        if query and query.strip():
            body["query"] = query.strip()
        dt = str(filters.get("decision_type", "")).lower()
        if dt in self._DECISION_TYPES:
            body["kararTipi"] = self._DECISION_TYPES[dt]
        if str(filters.get("sort_by", "")).lower() == "date":
            body["sort"] = "kararTarihi"
            body["order"] = str(filters.get("sort_direction") or "desc")
        return body

    async def search_page(self, query: str, limit: int = 10, page: int = 1, **filters):
        from emsal_mcp.models import SearchPage
        body = self._build_body(query, limit, page, filters)
        data = await self._api_search(body)
        results = [self._to_result(it) for it in (data.get("data") or []) if it.get("id")]
        total = data.get("total") if isinstance(data.get("total"), int) else None
        return SearchPage(results=results, total=total, page=page, page_size=limit)

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        page = int(filters.pop("page", 1) or 1)
        sp = await self.search_page(query, limit=limit, page=page, **filters)
        return sp.results

    async def _resolve_legacy_id(self, prefix: str, appno: str) -> tuple[str | None, str | None]:
        """Resolve a legacy ``BB/YYYY/N`` / ``ND/YYYY/N`` id to (uuid, kararTipi)."""
        karar_tipi = "BireyselBasvuru" if prefix == "BB" else "NormDenetimi"
        data = await self._api_search({"page": 0, "size": 10, "query": appno, "kararTipi": karar_tipi})
        for it in data.get("data") or []:
            if appno in (it.get("basvuruNo"), it.get("esasNo"), it.get("kararNo")):
                return str(it.get("id")), karar_tipi
        return None, karar_tipi

    async def _fetch_udf_text(self, c, uuid: str, karar_tipi: str) -> tuple[str | None, str | None]:
        """Return (markdown_text, file_url) for a decision's UDF file, or (None, None)."""
        import asyncio as _aio
        files_url = f"{self.base}/api/core/public/kararlar/{uuid}/dosyalar"
        payload = None
        for attempt in range(2):  # endpoint is intermittently flaky (HTTP 500)
            r = await c.get(files_url, params={"kararTipi": karar_tipi}, headers=self._headers)
            if r.status_code == 200:
                payload = r.json()
                break
            await _aio.sleep(1.5)
        if not payload or not payload.get("data"):
            return None, None
        file_url = None
        for f in payload["data"]:
            if str(f.get("url", "")).endswith(".udf"):
                file_url = f["url"]
                break
        if not file_url:
            return None, None
        # "/files/{folder}/{filename}" → download-attachment/{folder}/{filename}
        segs = [s for s in file_url.split("/") if s]
        if segs and segs[0] == "files":
            segs = segs[1:]
        if len(segs) < 2:
            return None, None
        folder, filename = segs[-2], segs[-1]
        r = await c.get(
            f"{self.base}/api/core/public/files/download-attachment/{quote(folder)}/{quote(filename)}",
            headers=self._headers,
        )
        if r.status_code != 200 or not r.content.startswith(b"PK"):
            return None, file_url
        import tempfile
        from pathlib import Path
        from emsal_mcp.udf import udf_to_markdown
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".udf", delete=False) as fh:
                fh.write(r.content)
                tmp = Path(fh.name)
            return udf_to_markdown(tmp), file_url
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    async def get_document(self, document_id: str, **kwargs) -> Document:
        """Fetch AYM decision full text (UDF → markdown) by KBB UUID.

        Legacy IDs (``BB/2021/30620``, ``ND/2023/123``) are resolved to UUIDs
        via a docket-number search first.  ``kararTipi`` can be passed as a
        kwarg to skip type probing; otherwise both main types are tried.
        """
        warnings: list[str] = []
        did = document_id
        karar_tipi = kwargs.get("kararTipi") or kwargs.get("karar_tipi")
        try:
            m = re.match(r"^(BB|ND)[/:](\d+/\d+)$", did)
            if m:
                uuid, karar_tipi = await self._resolve_legacy_id(m.group(1), m.group(2))
                if not uuid:
                    return finalize_document(Document(
                        source=self.source_id, document_id=document_id,
                        title=f"AYM {did}", court="Anayasa Mahkemesi",
                        content_status=ContentStatus.UNAVAILABLE,
                    ), [f"AYM: {did} numarası KBB'de bulunamadı."])
                did = uuid

            tipler = [karar_tipi] if karar_tipi else ["BireyselBasvuru", "NormDenetimi"]
            text = None
            file_url = None
            async with client() as c:
                await c.get(f"{self.base}/kbb/", headers=self._headers)  # WAF warm-up
                for tip in tipler:
                    text, file_url = await self._fetch_udf_text(c, did, tip)
                    if text:
                        karar_tipi = tip
                        break

            if not text:
                warnings.append(
                    "AYM KBB: karar UDF dosyası alınamadı (dosya listesi boş veya indirme başarısız). "
                    f"SPA görünümü: {self.base}/kbb/?id={did}"
                )
                return finalize_document(Document(
                    source=self.source_id, document_id=document_id,
                    title=f"AYM {did}", court="Anayasa Mahkemesi",
                    source_url=f"{self.base}/kbb/?id={did}",
                    content_status=ContentStatus.METADATA_ONLY,
                    metadata={"kararTipi": karar_tipi, "file_url": file_url},
                ), warnings)

            doc = Document(
                source=self.source_id, document_id=document_id,
                title=f"AYM {did}", court="Anayasa Mahkemesi",
                markdown=text, full_text=text,
                source_url=f"{self.base}/kbb/?id={did}",
                content_status=ContentStatus.FULL_TEXT,
                content_hash=sha(text),
                metadata={"kararTipi": karar_tipi, "file_url": file_url},
            )
            return finalize_document(doc, warnings)
        except Exception as exc:
            return Document(
                source=self.source_id, document_id=document_id,
                title=f"AYM {did} (erişilemedi)", court="Anayasa Mahkemesi",
                content_status=ContentStatus.UNAVAILABLE,
                metadata={"error": f"{type(exc).__name__}: {exc}"},
            )

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        if online:
            try:
                sp = await self.search_page("mülkiyet", limit=1)
                result.online_ok = bool(sp.results)
            except Exception as exc:
                result.online_ok = False
                result.errors.append(f"AYM KBB search smoke failed: {type(exc).__name__}")
        return result


class DanistayClient(SourceClient):
    source_id = "danistay"
    name = "Danıştay"
    base = "https://karararama.danistay.gov.tr"
    _headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }

    # Response schema (M-60)
    _search_response_keys = ["data"]

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        payload = {
            "data": {
                "andKelimeler": [f'"{query.strip().strip(chr(34))}"'] if query.strip() else [],
                "orKelimeler": [],
                "notAndKelimeler": [],
                "notOrKelimeler": [],
                "pageSize": limit,
                "pageNumber": filters.get("page", 1),
            }
        }
        async with client() as c:
            r = await c.post(f"{self.base}/aramalist", json=payload, headers=self._headers)
            check_http_response(r, self.source_id)
            data = r.json()
        # M-60: schema validation
        _ = self._check_response_schema(data, self._search_response_keys, "search")
        items = data.get("data", {}).get("data") or data.get("data") or []
        return [
            SearchResult(
                source=self.source_id,
                document_id=str(i.get("id") or i.get("documentId")),
                title=i.get("daire") or i.get("title") or "Danıştay kararı",
                decision_date=i.get("kararTarihi"),
                esas_no=i.get("esasNo"), karar_no=i.get("kararNo"),
                content_status=ContentStatus.METADATA_ONLY, metadata=i,
            )
            for i in items[:limit]
        ]

    async def get_document(self, document_id: str, **kwargs) -> Document:
        url = f"{self.base}/getDokuman?id={quote(document_id)}&arananKelime="
        async with client() as c:
            r = await c.get(url, headers={"Accept": "text/html"})
            check_http_response(r, self.source_id)
            html = r.text
        text = html_to_text(html)
        warnings: list[str] = []
        status = ContentStatus.HTML_MARKDOWN
        if len(text.strip()) < 50:
            warnings.append("Danıştay parsed content too short; falling back to metadata_only.")
            status = ContentStatus.METADATA_ONLY
        doc = Document(
            source=self.source_id, document_id=document_id,
            title=f"Danıştay {document_id}", markdown=text,
            full_text=text if status == ContentStatus.HTML_MARKDOWN else None,
            source_url=url, content_status=status,
            content_hash=sha(text) if text and status == ContentStatus.HTML_MARKDOWN else None,
        )
        return finalize_document(doc, warnings)

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        result.min_content_length_ok = True
        return result


class GibClient(SourceClient):
    source_id = "gib"
    name = "Gelir İdaresi Başkanlığı"
    base = "https://gib.gov.tr/api"

    # Response schema (M-60)
    _search_response_keys = ["resultContainer", "content", "data"]

    # GİB query normalization map
    _query_norm: dict[str, str] = {
        "katma değer vergisi": "KDV",
        "katma deger vergisi": "KDV",
        "kdv": "KDV",
    }

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        sp = await self.search_page(query=query, limit=limit, page=filters.get("page", 1), **filters)
        return sp.results

    async def search_page(self, query: str, limit: int = 10, page: int = 1, **filters) -> SearchPage:
        q = self._query_norm.get(query.lower().strip(), query)
        payload = {"status": 2, "deleted": False, "ktype": 99, "title": q, "kanunNo": q, "description": q}
        if filters.get("start_date"):
            payload["ozelgeStartDate"] = filters["start_date"] + (
                "T00:00:00.000Z" if "T" not in filters["start_date"] else ""
            )
        if filters.get("end_date"):
            payload["ozelgeEndDate"] = filters["end_date"] + (
                "T23:59:59.999Z" if "T" not in filters["end_date"] else ""
            )
        upstream_page = max(0, int(page) - 1)  # 1-based → 0-based
        async with client() as c:
            r = await c.post(
                f"{self.base}/gibportal/mevzuat/ozelge/list"
                f"?page={upstream_page}&size={limit}"
                f"&sortFieldName=ozelgeTarih&sortType=DESC",
                json=payload,
            )
            check_http_response(r, self.source_id)
            data = r.json()
        _ = self._check_response_schema(data, self._search_response_keys, "search")
        result_container = data.get("resultContainer", {})
        total: int | None = result_container.get("totalElements")
        total_pages: int | None = result_container.get("totalPages")
        items = result_container.get("content") or data.get("content") or data.get("data", {}).get("content") or []
        out: list[SearchResult] = []
        for i in items[:limit]:
            if not i.get("id"):
                continue
            title = i.get("title") or i.get("baslik") or "GİB özelge"
            title = html_to_text(title) if "<" in title else title
            out.append(SearchResult(
                source=self.source_id,
                document_id=str(i.get("id")),
                title=title,
                summary=html_to_text(i.get("description") or "")[:1000],
                court="Gelir İdaresi Başkanlığı",
                chamber=i.get("kanunTitle"),
                decision_date=i.get("ozelgeTarih") or i.get("tarih"),
                esas_no=i.get("kanunNo"),
                karar_no=i.get("ozelgeNo"),
                source_url=i.get("siteLink"),
                content_status=ContentStatus.METADATA_ONLY, metadata=i,
            ))
        return SearchPage(results=out, total=total, page=page, page_size=limit, total_pages=total_pages)

    async def get_document(self, document_id: str, **kwargs) -> Document:
        payload = {"status": 2, "deleted": False, "ktype": 99, "id": int(document_id)}
        async with client() as c:
            r = await c.post(
                f"{self.base}/gibportal/mevzuat/ozelge/list?page=0&size=1", json=payload
            )
            check_http_response(r, self.source_id)
            data = r.json()
        item = (data.get("resultContainer", {}).get("content") or data.get("content") or [None])[0]
        if not item:
            return metadata_doc(self.source_id, document_id, "GİB belge detayı", metadata={"not_found": True})
        # Build text from structured fields (not from HTML scraping)
        parts = [
            str(item.get("title") or ""),
            str(item.get("ozelgeNo") or ""),
            str(item.get("ozelgeTarih") or ""),
            str(item.get("description") or ""),
        ]
        text = html_to_text("\n".join(parts))
        warnings: list[str] = []
        status = ContentStatus.HTML_MARKDOWN
        if len(text.strip()) < 50:
            warnings.append("GİB parsed content too short; falling back to metadata_only.")
            status = ContentStatus.METADATA_ONLY
        title = item.get("title") or f"GİB {document_id}"
        title = html_to_text(title) if "<" in title else title
        doc = Document(
            source=self.source_id, document_id=document_id,
            title=title, summary=text[:1000],
            court="Gelir İdaresi Başkanlığı",
            chamber=item.get("kanunTitle"),
            decision_date=item.get("ozelgeTarih"),
            esas_no=item.get("kanunNo"), karar_no=item.get("ozelgeNo"),
            source_url=item.get("siteLink"),
            markdown=text if status == ContentStatus.HTML_MARKDOWN else None,
            full_text=text if status == ContentStatus.HTML_MARKDOWN else None,
            content_status=status,
            content_hash=sha(text) if text and status == ContentStatus.HTML_MARKDOWN else None,
            raw=data, metadata=item,
        )
        return finalize_document(doc, warnings)

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        result.min_content_length_ok = True
        return result


class BtkClient(SourceClient):
    """BTK (Bilgi Teknolojileri ve İletişim Kurumu) Kurul Kararları.

    Server-rendered HTML page at https://www.btk.gov.tr/kurul-kararlari.
    Each page has ~11 decision cards with Karar No, Konu, Tarih, PDF link.
    No server-side keyword search — local filter when query is provided.
    """

    source_id = "btk"
    name = "BTK Kurul Kararları"
    base = "https://www.btk.gov.tr"

    _total_count: int | None = None

    async def _fetch_page(self, query: str | None = None, page: int = 1) -> tuple[list[SearchResult], int | None]:
        url = f"{self.base}/kurul-kararlari?page={page}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        async with client() as c:
            r = await c.get(url, headers=headers)
            check_http_response(r, self.source_id)
            html = r.text

        # BTK page has no total count — only pagination controls
        total: int | None = None

        # Parse decision cards
        out: list[SearchResult] = []
        for card_m in re.finditer(
            r'<h3[^>]*class="[^"]*"[^>]*>([\s\S]*?)</h3>([\s\S]*?)</div></div></div>',
            html, re.I
        ):
            title_html = card_m.group(1)
            body = card_m.group(2)
            title = html_to_text(re.sub(r'<[^>]+>', '', title_html)).strip()
            if not title or title in ("Mevzuat", "Bilgi Teknolojileri ve İletişim Kurumu"):
                continue

            # Extract Karar tarihi ve no
            kn_m = re.search(r'Karar tarihi ve no</span><span[^>]*>(.+?)</span>', body)
            if not kn_m:
                continue
            kn_raw = html_to_text(kn_m.group(1)).strip()
            date_part = kn_raw.split(" - ")[0].strip() if " - " in kn_raw else ""
            karar_no = kn_raw.split(" - ")[1].strip() if " - " in kn_raw else kn_raw

            # Yayım Tarihi
            yt_m = re.search(r'Yayım Tarihi</span><span[^>]*>(.+?)</span>', body)
            yayim_tarihi = html_to_text(yt_m.group(1)).strip() if yt_m else ""

            # PDF link
            pdf_m = re.search(r'href="([^"]+\.pdf)"', body)
            pdf_url = pdf_m.group(1) if pdf_m else ""

            doc_id = _url_id(pdf_url) if pdf_url else f"btk:{karar_no}"
            decision_date = date_part.replace(".", "-").strip()

            # Decoded card text for local query filter
            card_text = f"{title} {karar_no} {date_part}"
            if query:
                decoded_card = html_to_text(card_text).lower()
                if query.lower() not in decoded_card:
                    continue

            meta = {"kararNo": karar_no, "kararTarihi": date_part, "yayimTarihi": yayim_tarihi}
            if pdf_url:
                meta["pdfUrl"] = pdf_url
            out.append(SearchResult(
                source=self.source_id, document_id=doc_id,
                title=title or f"BTK Kararı {karar_no}",
                summary=f"Karar No: {karar_no}, Tarih: {date_part}",
                court="Bilgi Teknolojileri ve İletişim Kurumu",
                decision_date=decision_date,
                karar_no=karar_no,
                source_url=pdf_url or url,
                content_status=ContentStatus.PDF_LINK_ONLY if pdf_url else ContentStatus.METADATA_ONLY,
                metadata=meta,
            ))
        return out, total

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        sp = await self.search_page(query=query, limit=limit, page=filters.get("page", 1), **filters)
        return sp.results

    async def search_page(self, query: str, limit: int = 10, page: int = 1, **filters) -> SearchPage:
        results, total = await self._fetch_page(query=query, page=page)
        page_size = limit
        total_pages: int | None = None
        if total is not None and total > 0:
            total_pages = max(1, (total + page_size - 1) // page_size)
        return SearchPage(results=results[:limit], total=total, page=page, page_size=page_size, total_pages=total_pages)

    async def get_document(self, document_id: str, **kwargs) -> Document:
        """BTK karar metni — PDF indir -> metin çıkar."""
        url = _decode_url_id(document_id) if document_id.startswith("url:") else document_id
        if not url.startswith("http"):
            url = f"{self.base}{url}" if url.startswith("/") else f"{self.base}/{url}"

        try:
            from .pdf_extractor import extract_pdf_text_from_bytes
            async with client() as c:
                r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
                check_http_response(r, self.source_id)
                pdf_bytes = r.content

            result = extract_pdf_text_from_bytes(pdf_bytes) if pdf_bytes else {}
            text = (result.get("text") or "") if isinstance(result, dict) else ""

            if text.strip():
                doc = Document(
                    source=self.source_id, document_id=document_id,
                    title=f"BTK Kararı", markdown=text, full_text=text,
                    source_url=url, content_status=ContentStatus.HTML_MARKDOWN,
                    content_hash=sha(text),
                )
                return finalize_document(doc)
            else:
                return Document(
                    source=self.source_id, document_id=document_id,
                    title="BTK Kararı (PDF)", source_url=url,
                    content_status=ContentStatus.PDF_LINK_ONLY,
                    metadata={"pdfUrl": url},
                )
        except Exception:
            return Document(
                source=self.source_id, document_id=document_id,
                title="BTK Kararı (erişilemedi)",
                content_status=ContentStatus.UNAVAILABLE,
                metadata={"error": "fetch_or_parse_failure"},
            )

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        result.warnings.append("BTK HTML card scraping; may break on site redesign.")
        return result


class UrlSearchClient(SourceClient):
    def __init__(self, source_id: str, name: str, search_url: str):
        self.source_id = source_id
        self.name = name
        self.search_url = search_url

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        url = self.search_url.format(q=quote(query))
        async with client() as c:
            r = await c.get(url)
            check_http_response(r, self.source_id)
            html = r.text
        return [SearchResult(
            source=self.source_id, document_id=url,
            title=f"{self.name} arama: {query}",
            summary=html_to_text(html)[:1000],
            source_url=url, content_status=ContentStatus.HTML_MARKDOWN,
        )]

    async def get_document(self, document_id: str, **kwargs) -> Document:
        async with client() as c:
            r = await c.get(document_id)
            check_http_response(r, self.source_id)
            html = r.text
        text = html_to_text(html)
        return Document(
            source=self.source_id, document_id=document_id,
            title=f"{self.name} belge", markdown=text, full_text=text,
            source_url=document_id, content_status=ContentStatus.HTML_MARKDOWN,
            content_hash=sha(text),
        )


class UyusmazlikClient(SourceClient):
    source_id = "uyusmazlik"
    name = "Uyuşmazlık Mahkemesi"
    base = "https://kararlar.uyusmazlik.gov.tr"

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        try:
            async with client() as c:
                r = await c.get(f"{self.base}/")
                check_http_response(r, self.source_id)
                initial = r.text
                form = {"txtSearch": query, "btnSearch": "Ara", "rblSearchScope": "All"}
                for key in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]:
                    m = re.search(rf'name=["\']{key}["\'][^>]*value=["\']([^"\']*)', initial, re.I)
                    if m:
                        form[key] = m.group(1)
                r = await c.post(
                    f"{self.base}/", data=form,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                check_http_response(r, self.source_id)
                html = r.text
        except Exception:
            return [SearchResult(
                source=self.source_id, document_id="unavailable:uyusmazlik",
                title="Uyuşmazlık Mahkemesi araması kullanılamıyor",
                summary="ASp.NET form-based scraping başarısız oldu.",
                court="Uyuşmazlık Mahkemesi",
                content_status=ContentStatus.UNAVAILABLE,
                metadata={"error": "parser_failure"},
            )][:1]
        out: list[SearchResult] = []
        for row in re.findall(r"<tr[\s\S]*?</tr>", html, re.I):
            href = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', row, re.I)
            cols = [html_to_text(x) for x in re.findall(r"<td[^>]*>([\s\S]*?)</td>", row, re.I)]
            if not href or len(cols) < 2:
                continue
            url = href.group(1) if href.group(1).startswith("http") else f"{self.base}/{href.group(1).lstrip('/')}"
            out.append(SearchResult(
                source=self.source_id, document_id=_url_id(url),
                title="Uyuşmazlık Mahkemesi | " + " | ".join(cols[:2]),
                summary=" | ".join(cols[2:5])[:1000],
                court="Uyuşmazlık Mahkemesi",
                decision_date=_first_date(" ".join(cols)),
                source_url=url,
                content_status=(
                    ContentStatus.PDF_LINK_ONLY if url.lower().endswith(".pdf")
                    else ContentStatus.METADATA_ONLY
                ),
                metadata={"columns": cols},
            ))
            if len(out) >= limit:
                break
        return out

    async def get_document(self, document_id: str, **kwargs) -> Document:
        url = _decode_url_id(document_id)
        if url.lower().endswith(".pdf"):
            return Document(
                source=self.source_id, document_id=document_id,
                title="Uyuşmazlık Mahkemesi PDF", source_url=url,
                markdown=f"PDF karar bağlantısı: {url}",
                content_status=ContentStatus.PDF_LINK_ONLY,
                metadata={"pdfUrl": url},
            )
        try:
            async with client() as c:
                r = await c.get(url)
                check_http_response(r, self.source_id)
                html = r.text
            text = html_to_text(html)
            status = ContentStatus.HTML_MARKDOWN
            warnings: list[str] = []
            if len(text.strip()) < 50:
                warnings.append("Uyuşmazlık parsed content too short; falling back to metadata_only.")
                status = ContentStatus.METADATA_ONLY
            doc = Document(
                source=self.source_id, document_id=document_id,
                title="Uyuşmazlık Mahkemesi Kararı",
                court="Uyuşmazlık Mahkemesi",
                decision_date=_first_date(text),
                source_url=url,
                markdown=text if status == ContentStatus.HTML_MARKDOWN else None,
                full_text=text if status == ContentStatus.HTML_MARKDOWN else None,
                content_status=status,
                content_hash=sha(text) if text and status == ContentStatus.HTML_MARKDOWN else None,
                raw=html,
            )
            return finalize_document(doc, warnings)
        except Exception:
            return Document(
                source=self.source_id, document_id=document_id,
                title="Uyuşmazlık Mahkemesi (erişilemedi)",
                court="Uyuşmazlık Mahkemesi",
                content_status=ContentStatus.UNAVAILABLE,
                metadata={"error": "fetch_or_parse_failure"},
            )

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        result.warnings.append("ASP.NET form-based; parser may fail on server changes.")
        return result


class RekabetClient(SourceClient):
    source_id = "rekabet"
    name = "Rekabet Kurumu"
    base = "https://www.rekabet.gov.tr"

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        sp = await self.search_page(query=query, limit=limit, page=filters.get("page", 1), **filters)
        return sp.results

    async def search_page(self, query: str, limit: int = 10, page: int = 1, **filters) -> SearchPage:
        try:
            async with client() as c:
                r = await c.get(f"{self.base}/tr/Kararlar?PdfText={quote(query)}")
                check_http_response(r, self.source_id)
                html = r.text
        except Exception:
            return SearchPage(results=[
                SearchResult(
                    source=self.source_id, document_id="unavailable:rekabet",
                    title="Rekabet Kurumu araması kullanılamıyor",
                    summary="HTML scraping başarısız oldu.",
                    court="Rekabet Kurumu",
                    content_status=ContentStatus.UNAVAILABLE,
                    metadata={"error": "parser_failure"},
                )
            ], total=None, page=page, page_size=limit)

        # Extract total from HTML
        total: int | None = None
        tm = re.search(r'Toplam\s*:\s*(\d+)', html, re.I)
        if tm:
            total = int(tm.group(1))
        total_pages: int | None = None
        if total is not None and total > 0:
            total_pages = max(1, (total + limit - 1) // limit)

        out: list[SearchResult] = []
        for table in re.findall(r"<table[^>]*equalDivide[\s\S]*?</table>", html, re.I):
            kid = (re.search(r"kararId=([^\"'\s&]+)", table, re.I) or [None, None])[1]
            if not kid:
                continue
            title_match = re.search(
                r"<a[^>]+href=[\"'][^\"']*Karar\?kararId=[^\"']+[\"'][^>]*>([\s\S]*?)</a>",
                table, re.I,
            )
            title = html_to_text(title_match.group(1) if title_match else "")
            txt = html_to_text(table)
            out.append(SearchResult(
                source=self.source_id, document_id=kid,
                title=title or f"Rekabet Kurumu Kararı {kid}",
                summary=txt[:1000], court="Rekabet Kurumu",
                decision_date=_first_date(txt),
                source_url=f"{self.base}/Karar?kararId={quote(kid)}",
                content_status=ContentStatus.METADATA_ONLY,
                metadata={"htmlText": txt},
            ))
            if len(out) >= limit:
                break
        return SearchPage(results=out, total=total, page=page, page_size=limit, total_pages=total_pages)

    async def get_document(self, document_id: str, **kwargs) -> Document:
        url = f"{self.base}/Karar?kararId={quote(document_id)}"
        try:
            async with client() as c:
                r = await c.get(url)
                check_http_response(r, self.source_id)
                html = r.text
            text = html_to_text(html)
            pdf = (re.search(r'href=["\']([^"\']+\.pdf[^"\']*)', html, re.I) or [None, None])[1]
            warnings: list[str] = []

            # If PDF link exists, attempt PDF text extraction
            if pdf and len(text.strip()) < 200:
                pdf_url = pdf if pdf.startswith("http") else f"{self.base}/{pdf.lstrip('/')}"
                try:
                    async with client() as c:
                        r2 = await c.get(pdf_url)
                        r2_bytes = r2.content
                    from .pdf_extractor import extract_pdf_text_from_bytes
                    pdf_result = extract_pdf_text_from_bytes(r2_bytes) if r2_bytes else {}
                    pdf_text = (pdf_result.get("text") or "") if isinstance(pdf_result, dict) else ""
                    if pdf_text.strip():
                        text = pdf_text
                        warnings.append("PDF metni başarıyla çıkarıldı.")
                except Exception:
                    warnings.append("PDF çıkarımı başarısız; HTML metin kullanıldı.")

            status = ContentStatus.HTML_MARKDOWN
            if len(text.strip()) < 50:
                warnings.append("Rekabet parsed content too short; falling back to metadata_only.")
                status = ContentStatus.METADATA_ONLY
            doc = Document(
                source=self.source_id, document_id=document_id,
                title=f"Rekabet Kurumu Kararı {document_id}",
                court="Rekabet Kurumu", decision_date=_first_date(text),
                source_url=url,
                markdown=text if status == ContentStatus.HTML_MARKDOWN else None,
                full_text=text if status == ContentStatus.HTML_MARKDOWN else None,
                content_status=status if text else ContentStatus.PDF_LINK_ONLY,
                content_hash=sha(text) if text and status == ContentStatus.HTML_MARKDOWN else None,
                raw=html, metadata={"pdfUrl": pdf} if pdf else {},
            )
            return finalize_document(doc, warnings)
        except Exception:
            return Document(
                source=self.source_id, document_id=document_id,
                title="Rekabet Kurumu (erişilemedi)",
                court="Rekabet Kurumu",
                content_status=ContentStatus.UNAVAILABLE,
                metadata={"error": "fetch_or_parse_failure"},
            )

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        result.warnings.append("HTML table-based scraping; may break on site redesign.")
        return result


class SayistayClient(SourceClient):
    source_id = "sayistay"
    name = "Sayıştay"
    base = "https://www.sayistay.gov.tr"
    # Response schema (M-60)
    _search_response_keys = ["data"]
    endpoints = {
        "daire": ("/KararlarDaire", "/KararlarDaire/DataTablesList", "/KararlarDaire/Detay"),
        "temyiz_kurulu": ("/KararlarTemyiz", "/KararlarTemyiz/DataTablesList", "/KararlarTemyiz/Detay"),
        "genel_kurul": ("/KararlarGenelKurul", "/KararlarGenelKurul/DataTablesList", "/KararlarGenelKurul/Detay"),
    }

    async def search(self, query: str, limit: int = 10, **filters) -> list[SearchResult]:
        kind = filters.get("kind") or filters.get("chamber") or "daire"
        if kind not in self.endpoints:
            kind = "daire"
        page, list_ep, detail = self.endpoints[kind]
        form = {
            "draw": "1", "start": "0", "length": str(limit),
            "search[value]": "", "search[regex]": "false",
            "order[0][column]": "2", "order[0][dir]": "desc",
        }
        for idx, name in enumerate(
            ["YARGILAMADAIRESI", "KARARTRH", "KARARNO", "YARGILAMADAIRESI", "WEBKARARMETNI", ""]
        ):
            form[f"columns[{idx}][data]"] = name
            form[f"columns[{idx}][name]"] = ""
            form[f"columns[{idx}][searchable]"] = "true"
            form[f"columns[{idx}][orderable]"] = "false" if idx == 5 else "true"
            form[f"columns[{idx}][search][value]"] = ""
            form[f"columns[{idx}][search][regex]"] = "false"
        if kind == "daire":
            form["KararlarDaireAra.WEBKARARMETNI"] = query
            form["KararlarDaireAra.YARGILAMADAIRESI"] = "Tüm Daireler"
        elif kind == "temyiz_kurulu":
            form["KararlarTemyizAra.TEMYIZKARAR"] = query
        else:
            form["KararlarGenelKurulAra.KARARTAMAMI"] = query
        try:
            async with client() as c:
                r = await c.get(self.base + page)
                check_http_response(r, self.source_id)
                first = r.text
                tok = (
                    re.search(
                        r'name=["\']__RequestVerificationToken["\'][^>]*value=["\']([^"\']+)',
                        first, re.I,
                    )
                    or [None, None]
                )[1]
                if tok:
                    form["__RequestVerificationToken"] = tok
                r = await c.post(
                    self.base + list_ep, data=form,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                check_http_response(r, self.source_id)
                data = r.json()
        except Exception:
            return [SearchResult(
                source=self.source_id, document_id=f"unavailable:sayistay:{kind}",
                title=f"Sayıştay {kind} araması kullanılamıyor",
                summary="DataTables scraping başarısız oldu.",
                court="Sayıştay",
                content_status=ContentStatus.UNAVAILABLE,
                metadata={"error": "parser_failure", "kind": kind},
            )][:1]
        # M-60: schema validation
        _ = self._check_response_schema(data, self._search_response_keys, "search")
        out = []
        for row in (data.get("data") or [])[:limit]:
            rid = str(row.get("Id") or row.get("id") or "")
            if not rid:
                continue
            text = _clean(row.get("WEBKARARMETNI") or row.get("KARAROZETI") or row.get("TEMYIZKARAR"))
            out.append(SearchResult(
                source=self.source_id, document_id=f"{kind}:{rid}",
                title=f"Sayıştay {kind} {row.get('KARARNO') or rid}",
                summary=text[:1000], court="Sayıştay",
                chamber=row.get("YARGILAMADAIRESI") or row.get("ILAMDAIRESI"),
                decision_date=row.get("KARARTRH") or row.get("KARARTARIH") or row.get("TEMYIZTUTANAKTARIHI"),
                esas_no=row.get("ILAMNO") or row.get("DOSYANO"),
                karar_no=row.get("KARARNO") or row.get("TEMYIZTUTANAKNO"),
                source_url=self.base + detail + "/" + rid + "/",
                content_status=ContentStatus.METADATA_ONLY, metadata=row,
            ))
        return out

    async def get_document(self, document_id: str, **kwargs) -> Document:
        kind, rid = (document_id.split(":", 1) + [""])[:2] if ":" in document_id else ("daire", document_id)
        if kind not in self.endpoints:
            kind = "daire"
        url = self.base + self.endpoints[kind][2] + f"/{quote(rid)}/"
        try:
            async with client() as c:
                r = await c.get(url)
                check_http_response(r, self.source_id)
                html = r.text
            text = html_to_text(html)
            warnings: list[str] = []
            status = ContentStatus.HTML_MARKDOWN
            if len(text.strip()) < 50:
                warnings.append("Sayıştay parsed content too short; falling back to metadata_only.")
                status = ContentStatus.METADATA_ONLY
            doc = Document(
                source=self.source_id, document_id=document_id,
                title=f"Sayıştay {kind} {rid}",
                court="Sayıştay", decision_date=_first_date(text),
                source_url=url,
                markdown=text if status == ContentStatus.HTML_MARKDOWN else None,
                full_text=text if status == ContentStatus.HTML_MARKDOWN else None,
                content_status=status,
                content_hash=sha(text) if text and status == ContentStatus.HTML_MARKDOWN else None,
                raw=html,
            )
            return finalize_document(doc, warnings)
        except Exception:
            return Document(
                source=self.source_id, document_id=document_id,
                title=f"Sayıştay {kind} (erişilemedi)",
                court="Sayıştay",
                content_status=ContentStatus.UNAVAILABLE,
                metadata={"error": "fetch_or_parse_failure"},
            )

    async def smoke(self, online: bool = False) -> SourceSmokeResult:
        result = await super().smoke(online=online)
        result.warnings.append("DataTables-based scraping; may require CSRF tokens.")
        return result


def _first_date(text: str):
    m = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{4}", text or "")
    return m.group(0) if m else None


def _ymd_to_dmy(value: str) -> str:
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", value or "")
    return f"{m.group(3).zfill(2)}/{m.group(2).zfill(2)}/{m.group(1)}" if m else value
