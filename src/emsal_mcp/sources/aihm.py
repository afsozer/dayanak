"""AİHM (European Court of Human Rights) source adapter via HUDOC.

HUDOC search API: ``GET /app/query/results`` with a Lucene-style ``query``
parameter.  The 404 observed on 2026-07-15 (PARITY_V2_RAPOR.md Görev 5) was
caused by a malformed query, not a retired endpoint: the query MUST start
with ``contentsitename:ECHR`` and use field expressions such as
``(respondent:"TUR")``, ``docname:"Kavala"``, ``(article:"10")``.  With a
well-formed query the endpoint returns ``{"resultcount": N, "results":
[{"columns": {...}}]}`` (verified live, Görev 5b).

The document content API (``/app/conversion/docx/html/body``) is used for
``get_document()``.
"""
from __future__ import annotations

import asyncio
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
    SearchPage,
    SearchResult,
    SourceSmokeResult,
    finalize_document,
)


class AihmClient(SourceClient):
    source_id = "aihm"
    name = "AİHM (HUDOC)"
    base = "https://hudoc.echr.coe.int"

    _capability_status = "EXPERIMENTAL"  # type: ignore[assignment]  # set as class attribute
    _supports_full_text = True
    _supports_pdf_link = False
    _known_limitations: list[str] = [
        "Varsayilan arama Turkce cevirileri (dil=TUR) dondurur; sonuc yoksa "
        "ENG/FRE'ye dusulur ve warnings'e yazilir. dil='HEPSI' tum diller.",
    ]

    # Varsayilan dil ve dususte kullanilacak diller (HUDOC languageisocode).
    DEFAULT_LANG = "TUR"
    FALLBACK_LANG = "ENG,FRE"
    _ALL_LANG = {"HEPSI", "ALL", "TUMU", "*"}

    _SELECT_FIELDS = (
        "itemid,docname,appno,conclusion,importance,kpdate,languageisocode,doctype"
    )

    def _build_query(self, query: str, filters: dict) -> str:
        """Build the HUDOC Lucene query. Must start with contentsitename:ECHR."""
        parts = ["contentsitename:ECHR"]
        ulke = str(filters.get("ulke") or "TUR").upper()
        if ulke != "HEPSI":
            parts.append(f'(respondent:"{ulke}")')
        field_map = {
            "madde": "article",
            "ihlal": "violation",
            "ihlal_yok": "nonviolation",
            "basvuru_no": "appno",
            "dava_adi": "docname",
            "dil": "languageisocode",
        }
        for key, field in field_map.items():
            val = filters.get(key)
            if not val:
                continue
            if key == "dil":
                langs = [
                    x.strip().upper().replace('"', "")
                    for x in str(val).split(",") if x.strip()
                ]
                if not langs or any(x in self._ALL_LANG for x in langs):
                    continue  # tum diller: filtre yok
                if len(langs) == 1:
                    parts.append(f'({field}:"{langs[0]}")')
                else:
                    parts.append(
                        "(" + " OR ".join(f'{field}:"{x}"' for x in langs) + ")"
                    )
                continue
            escaped = str(val).replace('"', "")
            parts.append(f'({field}:"{escaped}")')
        # server.py karar_tarihi_start/_end adlarini kullanir; ikisi de kabul.
        start = filters.get("start_date") or filters.get("karar_tarihi_start")
        end = filters.get("end_date") or filters.get("karar_tarihi_end")
        if start:
            parts.append(f'(kpdate>="{str(start)[:10]}T00:00:00.0Z")')
        if end:
            parts.append(f'(kpdate<="{str(end)[:10]}T23:59:59.0Z")')
        if query and query.strip():
            parts.append(f"({query.strip()})")
        return " AND ".join(parts)

    async def search_page(
        self, query: str, limit: int = 10, page: int = 1, **filters: Any
    ) -> SearchPage:
        """Dil verilmemisse once Turkce cevirileri (TUR) ara; 0 sonucta ENG/FRE'ye
        dus ve warnings'e yaz. Acik dil verilirse ona uyulur."""
        if filters.get("dil"):
            return await self._search_page_once(query, limit, page, **filters)
        f_tur = {**filters, "dil": self.DEFAULT_LANG}
        f_alt = {**filters, "dil": self.FALLBACK_LANG}
        # Ucuz sayim sorgulari (length=1, kpdate azalan): orijinal dildeki en yeni
        # karar ile TUR'daki en yeni karar. Hata asil sonucu bozmaz.
        probe = {"sort_by": "date", "sort_direction": "desc"}
        sp, alt_probe, tur_probe = await asyncio.gather(
            self._search_page_once(query, limit, page, **f_tur),
            self._search_page_once(query, 1, 1, **{**f_alt, **probe}),
            self._search_page_once(query, 1, 1, **{**f_tur, **probe}),
            return_exceptions=True,
        )
        if isinstance(sp, BaseException):
            raise sp
        if sp.total == 0 or (sp.total is None and not sp.results and page == 1):
            sp = await self._search_page_once(query, limit, page, **f_alt)
            if sp.total == 0:
                sp.warnings.append(
                    "AIHM: dil=TUR ve ENG/FRE'de sonuc yok; sorguyu sadelestirin "
                    "(HUDOC ceviri disi serbest metin Ingilizce/Fransizca indekslidir) "
                    "ya da dil='HEPSI' deneyin."
                )
            else:
                sp.warnings.append(
                    "AIHM: Turkce ceviri (dil=TUR) bulunamadi; sonuclar ENG/FRE "
                    "orijinal dilinde. Tum diller icin dil='HEPSI', tek dil icin "
                    "dil='ENG' verin."
                )
            return sp
        try:
            if isinstance(alt_probe, BaseException) or not alt_probe.total:
                return sp
            note = (
                f"AIHM: Turkce ceviriler gosteriliyor ({sp.total}); orijinal dilde "
                f"(ENG/FRE) {alt_probe.total} belge daha var - en yeni kararlar "
                "genelde yalniz ENG/FRE'dir; dil='ENG,FRE' ya da 'HEPSI' ile bakin."
            )
            if alt_probe.results:
                top = alt_probe.results[0]
                tur_newest = ""
                if not isinstance(tur_probe, BaseException) and tur_probe.results:
                    tur_newest = tur_probe.results[0].decision_date or ""
                elif sp.results:
                    tur_newest = max((r.decision_date or "" for r in sp.results), default="")
                if (top.decision_date or "") > tur_newest:
                    docname = top.title.split(" | ")[0]
                    note += (
                        f" Orijinal dilde daha yeni karar var: {top.decision_date} "
                        f"{docname}."
                    )
            sp.warnings.append(note)
        except Exception:
            pass
        return sp

    async def _search_page_once(
        self, query: str, limit: int = 10, page: int = 1, **filters: Any
    ) -> SearchPage:
        sort = ""
        if str(filters.get("sort_by", "")).lower() == "date":
            direction = "Ascending" if str(filters.get("sort_direction", "")).lower() == "asc" else "Descending"
            sort = f"kpdate {direction}"
        params = {
            "query": self._build_query(query, filters),
            "select": self._SELECT_FIELDS,
            "sort": sort,
            "start": (max(int(page), 1) - 1) * int(limit),
            "length": min(int(limit), 50),
        }
        async with client() as c:
            r = await c.get(f"{self.base}/app/query/results", params=params, timeout=30)  # type: ignore[arg-type]
            check_http_response(r, self.source_id)
            data = r.json()
        if not isinstance(data, dict) or "results" not in data:
            raise ValueError(f"HUDOC search: beklenmeyen yanıt şeması: {str(data)[:200]}")
        results: list[SearchResult] = []
        for row in data.get("results") or []:
            col = row.get("columns") or {}
            itemid = col.get("itemid")
            if not itemid:
                continue
            title_parts = [col.get("docname"), col.get("appno"), col.get("kpdate", "")[:10]]
            results.append(SearchResult(
                source=self.source_id, document_id=str(itemid),
                title=" | ".join(str(p) for p in title_parts if p) or str(itemid),
                summary=(col.get("conclusion") or None),
                court="AİHM",
                decision_date=(col.get("kpdate") or "")[:10] or None,
                esas_no=col.get("appno"),
                source_url=f"{self.base}/eng?i={itemid}",
                content_status=ContentStatus.METADATA_ONLY,
                metadata={
                    k: col.get(k)
                    for k in ("doctype", "languageisocode", "importance")
                    if col.get(k)
                },
            ))
        total = data.get("resultcount") if isinstance(data.get("resultcount"), int) else None
        return SearchPage(results=results, total=total, page=page, page_size=limit)

    async def search(
        self, query: str, limit: int = 10, **filters: Any
    ) -> list[SearchResult]:
        """Search HUDOC. Filters: ulke (default TUR, HEPSI=all), madde, ihlal,
        ihlal_yok, basvuru_no, dava_adi, dil (TUR varsayilan, ENG/FRE, virgulle coklu, HEPSI=tumu),
        start_date/end_date (ya da karar_tarihi_start/_end), sort_by (relevance default / date)."""
        page = int(filters.pop("page", 1) or 1)
        sp = await self.search_page(query, limit=limit, page=page, **filters)
        return sp.results  # type: ignore[no-any-return]

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
