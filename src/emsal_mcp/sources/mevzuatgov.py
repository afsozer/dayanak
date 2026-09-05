"""mevzuat.gov.tr — the official consolidated legislation register.

Why this exists alongside the ``mevzuat`` source: that one queries UYAP's
Bedesten index, which lags the official register badly. Law 7589 was published
on 31.07.2026 and Bedesten still returned nothing for it a day later — by
number, by title, with and without a type filter. mevzuat.gov.tr's own listing
had it within hours.

The register also numbers legislation PER TYPE, so 7589 is simultaneously a
2026 Kanun and a 1998 Üniversite Yönetmeliği. Callers must pass a type (the
default here is KANUN) or check the title they get back.

⚠️ Consolidated text lags separately from the register. A law appears in this
listing on publication day, but the amendments it makes to OTHER laws are not
folded into those laws' consolidated text for some time. On 01.08.2026, HMK
m.107 still rendered as in force even though 7589 m.19 had repealed it the day
before. To answer "is this still in force", read the amending law, not only
the amended one.

⚠️ And the amending law itself is served STUBBED here. The register's copy of
an amending act replaces each operative article with a placeholder —
``MADDE 19- (… ile ilgili olup, yerine işlenmiştir.)`` — because the substance
is meant to be read in the amended law. So the sentence that actually repeals
HMK 107 is NOT in this source; it is in the Resmî Gazete original. Transitional
articles do survive intact, which is often enough to establish what happened
(7589's GEÇİCİ MADDE 1/(10) refers to "yürürlükten kaldırılan 107 nci
maddesi"). For the operative wording, use the ``resmigazete`` source.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from .base import (
    SourceClient,
    check_http_response,
    client,
    decode_turkish_html,
    html_to_text,
    sha,
)
from emsal_mcp.models import (
    ContentStatus,
    Document,
    SearchPage,
    SearchResult,
    finalize_document,
)

# MevzuatTur codes, probed live against the register (record counts are the
# site's own totals, kept as a sanity anchor if the vocabulary ever shifts).
TYPE_CODES: dict[str, int] = {
    "KANUN": 1,          # 915
    "TUZUK": 2,          # 107
    "YONETMELIK": 3,     # 8 865
    "KHK": 4,            # 63
    "MULGA": 5,          # 185 — repealed laws, kept searchable
    "KKY": 7,            # 3 653 — kurum ve kuruluş yönetmelikleri
    "UY": 8,             # 5 063 — üniversite yönetmelikleri
    "TEBLIGLER": 9,      # 4 459
    "CB_YONETMELIK": 10,  # 149
    # Probed 05.09.2026: the register's own totals for these two were missing
    # from the table, so a Cumhurbaşkanlığı Kararnamesi could not be listed at
    # all. Codes 6 and 11–18 are NOT free slots — the site silently drops an
    # unknown filter and answers with the whole corpus (19 069 rows), which
    # reads as "this type has 19 069 items".
    "CBK": 19,           # 33 — Cumhurbaşkanlığı Kararnameleri
    "CB_KARAR": 20,      # 4 294 — Cumhurbaşkanı Kararları
}
_CODE_TO_NAME = {v: k for k, v in TYPE_CODES.items()}

# AranacakYer: where the phrase is matched.
_SCOPE_BODY = "1"
_SCOPE_TITLE = "2"

_SEARCH_PATH = "/anasayfa/MevzuatDatatable"

# A non-existent tür.tertip.no triple does NOT get a 404 here: the register
# accepts the connection and then never answers, so the default 30 s client
# timeout turned every typo into a 30 s hang (measured 05.09.2026). 8 s plus a
# single retry covers the real documents while failing fast on the rest.
_DOC_TIMEOUT = 8.0
_DOC_RETRIES = 1
# Per-read timeouts alone do not bound the wall clock: the register trickles
# its not-found page out in small chunks, so 19.5.888 still took 17.8 s under
# an 8 s read timeout. _DOC_BUDGET caps the whole attempt.
_DOC_BUDGET = 8.0

# The register answers an unknown tür.tertip.no with HTTP 200 and its own
# "404 - Sayfa Bulunamadı" landing page (1 783 chars of site chrome, measured
# 05.09.2026 on 1.5.999999). Without this check the caller receives a
# successfully-fetched "document" whose text is the navigation menu.
_SOFT_404_RE = re.compile(r"404\s*[-–—]?\s*Sayfa\s+Bulunamad", re.IGNORECASE)
# Full text lives at MevzuatMetin/{tur}.{tertip}.{no}.htm
_DOC_ID_RE = re.compile(r"^(?P<tur>\d+)\.(?P<tertip>\d+)\.(?P<no>\d+)$")


def _doc_id(tur: Any, tertip: Any, no: Any) -> str:
    return f"{tur}.{tertip}.{no}"


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_title(raw: Any) -> str:
    """Strip the register's search-hit highlighting out of a title.

    A title-scoped search returns ``mevAdi`` wrapped in
    ``<span style='background-color:yellow'>…</span>``, which would otherwise
    end up verbatim in citations.
    """
    if not raw:
        return ""
    return re.sub(r"\s+", " ", _TAG_RE.sub("", str(raw))).strip()


_FOOTNOTE_MARKER_RE = re.compile(r"\[\d+\]")
# A heading that ends in one of these is already a whole legislation title.
_TITLE_TAIL_RE = re.compile(
    r"(KANUNU|KANUN|KANUNNAMESİ|KANUN\s+HÜKMÜNDE\s+KARARNAME(?:Sİ)?|YÖNETMELİĞİ"
    r"|YÖNETMELİK|TÜZÜĞÜ|TÜZÜK|KARARNAMESİ|TEBLİĞİ|YÖNERGESİ|GENELGESİ)\s*$",
    re.IGNORECASE,
)


def _leading_title(text: str, fallback: str) -> str:
    """First meaningful heading of a fetched document.

    Titles are split across several short lines in the source markup
    ("YARGININ" / "ETKİN VE VERİMLİ …"), so take lines until they add up to
    something title-sized rather than grabbing the first long one.
    """
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or _FOOTNOTE_MARKER_RE.fullmatch(line):
            # "[1]", "[2]" — footnote anchors interleaved with the heading.
            continue
        parts.append(line)
        joined = " ".join(parts)
        if _TITLE_TAIL_RE.search(joined):
            # Already a complete title ("İCRA VE İFLAS KANUNU"); stop before
            # swallowing the "Kanun Numarası : 2004" header that follows.
            return joined[:200]
        if len(joined) >= 25:
            return joined[:200]
        if len(parts) >= 4:
            break
    return " ".join(parts)[:200] or fallback


class MevzuatGovClient(SourceClient):
    source_id = "mevzuatgov"
    name = "Mevzuat.gov.tr"
    base = "https://www.mevzuat.gov.tr"

    _supports_pdf_link = True
    _supports_type_filter = True
    _search_response_keys = ["data", "recordsTotal"]

    # mevzuat.gov.tr'nin guvenlik duvari tarayici disi User-Agent'li istekleri
    # SESSIZCE dusuruyor (TCP zaman asimi, 4xx yok): 5 Eyl 2026'da olculdu —
    # ayni IP'den curl/httpx varsayilan UA ile 000, Mozilla UA ile 200 (0,3 s).
    # base.client() varsayilani "EmsalMcp/…"; bu kaynak icin tarayici UA sart.
    _BROWSER_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    headers = {
        "User-Agent": _BROWSER_UA,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://www.mevzuat.gov.tr",
        "Referer": "https://www.mevzuat.gov.tr/",
    }
    _doc_headers = {"User-Agent": _BROWSER_UA, "Referer": "https://www.mevzuat.gov.tr/"}

    # ── Filters → upstream parameters ───────────────────────────────────
    def _resolve_type(self, filters: dict[str, Any]) -> tuple[int, list[str]]:
        """Pick the MevzuatTur code, defaulting to KANUN.

        Returns ``(code, warnings)``. Unknown names are reported rather than
        silently ignored — the register answers an unusable type with an empty
        result set, which reads as "no such legislation".
        """
        warnings: list[str] = []
        raw = filters.get("mevzuat_tur") or filters.get("type")
        tur_list = filters.get("mevzuat_tur_list")
        if not raw and tur_list:
            if len(tur_list) > 1:
                warnings.append(
                    "mevzuat.gov.tr tek seferde tek tür arar; "
                    f"ilk tür kullanıldı ({tur_list[0]}), diğerleri yok sayıldı: "
                    f"{', '.join(str(t) for t in tur_list[1:])}."
                )
            raw = tur_list[0]
        if raw is None:
            return TYPE_CODES["KANUN"], warnings
        if isinstance(raw, int) or str(raw).isdigit():
            return int(raw), warnings
        key = str(raw).strip().upper()
        if key in TYPE_CODES:
            return TYPE_CODES[key], warnings
        warnings.append(
            f"Bilinmeyen mevzuat türü {raw!r}; KANUN varsayıldı. "
            f"Geçerli değerler: {', '.join(sorted(TYPE_CODES))}."
        )
        return TYPE_CODES["KANUN"], warnings

    async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]:
        sp = await self.search_page(query, limit=limit, **filters)
        return sp.results

    async def search_page(
        self, query: str = "", limit: int = 10, page: int = 1, **filters: Any
    ) -> SearchPage:
        tur, warnings = self._resolve_type(filters)

        params: dict[str, Any] = {"MevzuatTur": tur, "AranacakIfade": ""}

        mevzuat_no = filters.get("mevzuat_no")
        if mevzuat_no is not None and str(mevzuat_no).strip():
            params["MevzuatNo"] = str(mevzuat_no).strip()

        # A title search beats a body search for "find me this law": the body
        # index matches every later act that merely mentions the name.
        mevzuat_adi = filters.get("mevzuat_adi")
        if mevzuat_adi and str(mevzuat_adi).strip():
            params["AranacakIfade"] = str(mevzuat_adi).strip()
            params["AranacakYer"] = _SCOPE_TITLE
        elif query and query.strip():
            params["AranacakIfade"] = query.strip()
            params["AranacakYer"] = _SCOPE_BODY

        for key, param in (
            ("resmi_gazete_tarihi_start", "BaslangicTarihi"),
            ("resmi_gazete_tarihi_end", "BitisTarihi"),
        ):
            val = filters.get(key)
            if val:
                params[param] = str(val)

        page_size = max(1, min(int(limit), 100))
        payload = {
            "draw": 1,
            "columns": [],
            "order": [],
            "start": max(0, (int(page) - 1) * page_size),
            "length": page_size,
            "search": {"value": "", "regex": False},
            "parameters": params,
        }

        async with client() as c:
            resp = await c.post(f"{self.base}{_SEARCH_PATH}", json=payload, headers=self.headers)
            check_http_response(resp, self.source_id)
            raw = resp.json()

        _, schema_warnings = self._check_response_schema(raw, self._search_response_keys, "search")
        warnings.extend(schema_warnings)

        total = raw.get("recordsTotal")
        rows = raw.get("data") or []
        results: list[SearchResult] = []
        for row in rows[:page_size]:
            no = row.get("mevzuatNo")
            tertip = row.get("mevzuatTertip")
            row_tur = row.get("mevzuatTur", tur)
            if no is None or tertip is None:
                continue
            did = _doc_id(row_tur, tertip, no)
            rel_url = row.get("url")
            results.append(SearchResult(
                source=self.source_id,
                document_id=did,
                title=_clean_title(row.get("mevAdi")) or did,
                court=row.get("mevzuatTurEnumString") or _CODE_TO_NAME.get(int(row_tur), None),
                decision_date=row.get("resmiGazeteTarihi"),
                karar_no=str(no),
                source_url=(f"{self.base}/{rel_url}" if rel_url else None),
                content_status=ContentStatus.METADATA_ONLY,
                metadata={
                    "mevzuat_no": str(no),
                    "mevzuat_tur": row_tur,
                    "mevzuat_tur_adi": row.get("mevzuatTurEnumString"),
                    "mevzuat_tertip": tertip,
                    "kabul_tarihi": row.get("kabulTarih"),
                    "resmi_gazete_tarihi": row.get("resmiGazeteTarihi"),
                    "resmi_gazete_sayisi": row.get("resmiGazeteSayisi"),
                    "mukerrer": row.get("mukerrer"),
                },
            ))

        total_pages = None
        if isinstance(total, int):
            total_pages = max(1, (total + page_size - 1) // page_size) if total else 0
        return SearchPage(
            results=results, total=total, page=page, page_size=page_size,
            total_pages=total_pages, warnings=warnings,
        )

    # ── Document fetch ──────────────────────────────────────────────────
    async def _fetch_text(self, url: str, doc_id: str) -> tuple[str, Any]:
        """Fetch the .htm body, falling back to the .pdf link on 404.

        Returns ``("html", text)`` or ``("document", Document)`` — the latter
        for the terminal 404 outcomes, which already know their answer.
        Raises ``httpx.TimeoutException`` when every attempt times out.
        """
        last: httpx.TimeoutException | None = None
        for attempt in range(_DOC_RETRIES + 1):
            try:
                async with asyncio.timeout(_DOC_BUDGET), client(timeout=_DOC_TIMEOUT) as c:
                    resp = await c.get(url, headers=self._doc_headers)
                    if resp.status_code == 404:
                        pdf_url = f"{self.base}/MevzuatMetin/{doc_id}.pdf"
                        head = await c.get(pdf_url, headers=self._doc_headers)
                        if head.status_code < 400:
                            doc = Document(
                                source=self.source_id, document_id=doc_id,
                                title=doc_id, source_url=pdf_url, pdf_url=pdf_url,
                                content_status=ContentStatus.PDF_LINK_ONLY,
                            )
                            return "document", finalize_document(doc, [
                                "Bu mevzuat yalnızca PDF olarak yayımlanmış; tam metin "
                                "için PDF çıkarımı gerekir."
                            ])
                        doc = Document(
                            source=self.source_id, document_id=doc_id,
                            title=doc_id, content_status=ContentStatus.UNAVAILABLE,
                        )
                        return "document", finalize_document(doc, [
                            f"{doc_id}: kaynakta bulunamadı (HTTP 404). Tür/tertip/no "
                            "üçlüsünü search() sonucundan doğrulayın."
                        ])
                    check_http_response(resp, self.source_id)
                    return "html", decode_turkish_html(resp)
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                last = (
                    exc if isinstance(exc, httpx.TimeoutException)
                    else httpx.ReadTimeout(f"{_DOC_BUDGET:.0f} sn bütçe aşıldı")
                )
                if attempt < _DOC_RETRIES:
                    await asyncio.sleep(0.5)
        raise last  # type: ignore[misc]

    async def get_document(self, document_id: str, **kwargs: Any) -> Document:
        m = _DOC_ID_RE.match(str(document_id).strip())
        if not m:
            doc = Document(
                source=self.source_id, document_id=str(document_id),
                title=str(document_id), content_status=ContentStatus.UNAVAILABLE,
            )
            return finalize_document(doc, [
                f"Geçersiz belge kimliği {document_id!r}. Beklenen biçim "
                "'<tür>.<tertip>.<no>', örn. '1.5.7589' (7589 sayılı Kanun). "
                "Kimlikleri search() sonucundan alın."
            ])

        url = f"{self.base}/MevzuatMetin/{m.group(0)}.htm"
        warnings: list[str] = []
        try:
            outcome, payload = await self._fetch_text(url, m.group(0))
        except httpx.TimeoutException as exc:
            doc = Document(
                source=self.source_id, document_id=m.group(0),
                title=m.group(0), content_status=ContentStatus.UNAVAILABLE,
            )
            return finalize_document(doc, [
                f"{m.group(0)}: kaynak {_DOC_TIMEOUT:.0f} sn içinde yanıt vermedi "
                f"({_DOC_RETRIES + 1} deneme, {type(exc).__name__}). Var olmayan bir "
                "tür/tertip/no üçlüsü bu kaynakta 404 yerine sessizce zaman aşımına "
                "düşer; üçlüyü search() sonucundan doğrulayın."
            ])
        if outcome == "document":
            return payload  # type: ignore[return-value]
        html = str(payload)

        text = html_to_text(html)
        if _SOFT_404_RE.search(text):
            doc = Document(
                source=self.source_id, document_id=m.group(0),
                title=m.group(0), content_status=ContentStatus.UNAVAILABLE,
            )
            return finalize_document(doc, [
                f"{m.group(0)}: kaynakta bulunamadı (HTTP 200 döndü ama gövde "
                "kaynağın kendi '404 - Sayfa Bulunamadı' sayfası). Tür/tertip/no "
                "üçlüsünü search() sonucundan doğrulayın."
            ])
        status = ContentStatus.HTML_MARKDOWN if text else ContentStatus.UNAVAILABLE
        if not text:
            warnings.append(f"{m.group(0)}: sayfa boş döndü, metin çıkarılamadı.")

        title = _leading_title(text, m.group(0))

        doc = Document(
            source=self.source_id, document_id=m.group(0), title=title,
            markdown=text, full_text=text,
            content_status=status,
            content_hash=sha(text) if text else None,
            source_url=(
                f"{self.base}/mevzuat?MevzuatNo={m.group('no')}"
                f"&MevzuatTur={m.group('tur')}&MevzuatTertip={m.group('tertip')}"
            ),
            metadata={
                "mevzuat_no": m.group("no"),
                "mevzuat_tur": int(m.group("tur")),
                "mevzuat_tur_adi": _CODE_TO_NAME.get(int(m.group("tur"))),
                "mevzuat_tertip": m.group("tertip"),
            },
        )
        return finalize_document(doc, warnings)
