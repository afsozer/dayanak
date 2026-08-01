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

import re
from typing import Any

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
}
_CODE_TO_NAME = {v: k for k, v in TYPE_CODES.items()}

# AranacakYer: where the phrase is matched.
_SCOPE_BODY = "1"
_SCOPE_TITLE = "2"

_SEARCH_PATH = "/anasayfa/MevzuatDatatable"
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


def _leading_title(text: str, fallback: str) -> str:
    """First meaningful heading of a fetched document.

    Titles are split across several short lines in the source markup
    ("YARGININ" / "ETKİN VE VERİMLİ …"), so take lines until they add up to
    something title-sized rather than grabbing the first long one.
    """
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts.append(line)
        joined = " ".join(parts)
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

    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://www.mevzuat.gov.tr",
        "Referer": "https://www.mevzuat.gov.tr/",
    }

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
        async with client() as c:
            resp = await c.get(url, headers={"Referer": f"{self.base}/"})
            if resp.status_code == 404:
                pdf_url = f"{self.base}/MevzuatMetin/{m.group(0)}.pdf"
                head = await c.get(pdf_url, headers={"Referer": f"{self.base}/"})
                if head.status_code < 400:
                    doc = Document(
                        source=self.source_id, document_id=m.group(0),
                        title=m.group(0), source_url=pdf_url, pdf_url=pdf_url,
                        content_status=ContentStatus.PDF_LINK_ONLY,
                    )
                    return finalize_document(doc, [
                        "Bu mevzuat yalnızca PDF olarak yayımlanmış; tam metin için "
                        "PDF çıkarımı gerekir."
                    ])
                doc = Document(
                    source=self.source_id, document_id=m.group(0),
                    title=m.group(0), content_status=ContentStatus.UNAVAILABLE,
                )
                return finalize_document(doc, [
                    f"{m.group(0)}: kaynakta bulunamadı (HTTP 404). Tür/tertip/no "
                    "üçlüsünü search() sonucundan doğrulayın."
                ])
            check_http_response(resp, self.source_id)
            html = decode_turkish_html(resp)

        text = html_to_text(html)
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
