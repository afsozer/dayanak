"""Resmî Gazete (Turkish Official Gazette) source adapter.

The gazette has no API, but it does not need one: every issue is a static
index page at ``/eskiler/YYYY/MM/YYYYMMDD.htm`` listing that day's items, and
each item is a static ``YYYYMMDD-N.htm`` (or ``.pdf``) next to it.  Plain GETs,
no session, no cookies.

Two encoding traps, both hit while writing this:

* The pages declare ``windows-1254`` in a ``<meta>`` tag but the server sends
  no ``charset`` in the Content-Type header, so httpx guesses UTF-8 and every
  Turkish character comes back mangled.  We decode from the declared charset.
* Item ids look like ``20260731-1``; "mükerrer" (repeat) issues insert an ``m``
  and a sequence: ``20260731m1-1``.
"""
from __future__ import annotations

import re
from datetime import date as _date
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
from dayanak.models import (
    ContentStatus,
    Document,
    SearchPage,
    SearchResult,
    finalize_document,
)

# Item ids: 20260731-1, and mükerrer issues 20260731m1-1.
_ITEM_ID_RE = re.compile(r"^(?P<day>\d{8})(?P<muk>m\d+)?-(?P<seq>\d+)$", re.I)
_ITEM_HREF_RE = re.compile(r"^(?P<id>\d{8}(?:m\d+)?-\d+)\.(?P<ext>html?|pdf)$", re.I)
_META_CHARSET_RE = re.compile(rb"charset=[\"']?([\w-]+)", re.I)

# The gazette's own section names; anything else in caps is a category
# ("KANUNLAR", "YÖNETMELİKLER", "TEBLİĞLER", ...).
_SECTION_MARKER = "BÖLÜMÜ"

_TR_FOLD = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosucgiosuaiu")


def _fold(text: str) -> str:
    """Lower-case and strip Turkish diacritics for accent-insensitive matching."""
    return text.translate(_TR_FOLD).lower()


def _decode(resp: httpx.Response) -> str:
    """Decode a gazette page using its declared charset.

    Thin alias over the shared helper — mevzuat.gov.tr has the same
    windows-1254-without-a-header quirk, so the logic lives in ``base``.
    """
    return decode_turkish_html(resp)


def _parse_item_id(document_id: str) -> tuple[str, str] | None:
    """Split an item id into ``(YYYYMMDD, full_id)``; None when malformed."""
    m = _ITEM_ID_RE.match(document_id.strip())
    if not m:
        return None
    # Sunucu buyuk/kucuk harfe duyarsiz (20230309M1-1 == 20230309m1-1); sayfalar
    # 'M' ile yaziyor, kimligi kucuk 'm' ile tekillestiriyoruz.
    return m.group("day"), m.group(0).lower()


_HEADER_RE = re.compile(
    r"\d{1,2}\s+\w+(?:\s+\d{4})?\s+Tarihli\s+ve\s+(\d+)\s+Say\w+\s+Resm\w+\s+Gazete"
    r"(?P<muk>\s*-\s*M\w*kerrer)?", re.I)
# Fihrist basligi ilk oge baglantisindan ONCE gelir; eski tek sayfalik fihristte
# govde de ayni dosyada ("21/1/1988 tarihli ve 19701 sayili Resmi Gazete'de
# yayimlanan ..." atiflari) oldugundan arama bu bolgeyle sinirlanir.
_FIRST_ITEM_RE = re.compile(r"""href=["']?(?:#\d+|\d{8}(?:m\d+)?-\d+\.)""", re.I)


def header_text(html: str) -> str:
    """Fihrist baslik bolgesinin duz metni (ilk oge baglantisina kadar, en cok 12k)."""
    m = _FIRST_ITEM_RE.search(html)
    head = html[: min(m.start() if m else 12000, 12000)]
    flat = re.sub(r"<[^>]+>", "", head)
    return re.sub(r"\s+", " ", flat.replace("&nbsp;", " "))


def parse_issue_header(html: str) -> tuple[str | None, bool]:
    """Fihrist basligindan ``(sayi_no, mukerrer_mi)``: '9 Mart 2023 Tarihli ve
    32127 Sayılı Resmî Gazete - Mükerrer'.  Bulunamazsa ``(None, False)``;
    yanlis numara numarasizdan kotu, govde atiflari yakalanmaz."""
    m = _HEADER_RE.search(header_text(html))
    if not m:
        return None, False
    return m.group(1), bool(m.group("muk"))


def _iso_from_day(day: str) -> str:
    return f"{day[0:4]}-{day[4:6]}-{day[6:8]}"


class ResmiGazeteClient(SourceClient):
    source_id = "resmigazete"
    name = "Resmî Gazete"
    base = "https://www.resmigazete.gov.tr"

    _supports_pdf_link = True
    # There is no server-side search; we fetch one day's index and filter it
    # locally, so callers must think in terms of an issue date.
    _supports_type_filter = True

    # ── URL construction ────────────────────────────────────────────────
    def _index_url(self, day: str) -> str:
        return f"{self.base}/eskiler/{day[0:4]}/{day[4:6]}/{day}.htm"

    def _item_url(self, day: str, item_id: str, ext: str = "htm") -> str:
        return f"{self.base}/eskiler/{day[0:4]}/{day[4:6]}/{item_id}.{ext}"

    # ── Index parsing ───────────────────────────────────────────────────
    def _parse_index(self, html: str, day: str) -> list[dict[str, Any]]:
        """Extract the day's items, carrying section/category headings down.

        The index is a flat sequence of ``<p>`` elements: all-caps ones are
        headings, the rest hold a single ``<a>`` per item.  Walking in document
        order lets each item inherit the most recent heading.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        section: str | None = None
        category: str | None = None
        items: list[dict[str, Any]] = []

        for para in soup.find_all("p"):
            anchors = [a for a in para.find_all("a", href=True)
                       if _ITEM_HREF_RE.match(a["href"].strip())]  # type: ignore[union-attr]
            if not anchors:
                # Baslik, tek sozcugun ortasinda bile <span> ile bolunebiliyor
                # ("MİLL" + "ETLERARASI ANDLAŞMALAR"); ayirici koymadan birlestir.
                text = re.sub(r"\s+", " ", para.get_text("").replace("\xa0", " ")).strip()
                # Headings are set entirely in capitals; item titles are not.
                if text and len(text) > 3 and not any(c.islower() for c in text):
                    if _SECTION_MARKER in text:
                        section, category = text, None
                    else:
                        category = text
                elif text and len(text) <= 100 and para.find("u") is not None:
                    # Eski sayfalar (2003-2009 civari) kategori basliklarini
                    # buyuk harfle degil, alti cizili karma harfle yaziyor.
                    category = text
                continue

            for anchor in anchors:
                href_match = _ITEM_HREF_RE.match(anchor["href"].strip())  # type: ignore[union-attr]
                if href_match is None:  # pragma: no cover - guarded above
                    continue
                item_id = href_match.group("id").lower()
                ext = href_match.group("ext").lower()
                raw = anchor.get_text("")
                raw = re.sub(r"\s+", " ", raw).strip()
                raw = raw.replace("\xa0", " ")
                # Laws and numbered decisions prefix the title with their
                # number; everything else uses an em dash placeholder.
                number: str | None = None
                parts = raw.split(None, 1)
                if parts and parts[0].isdigit():
                    number, raw = parts[0], (parts[1] if len(parts) > 1 else "")
                title = re.sub(r"^[\s–—–—-]+", "", raw).strip()
                title = re.sub(r"\s+", " ", title)
                if not title:
                    continue
                items.append({
                    "id": item_id,
                    "ext": ext,
                    "number": number,
                    "title": title,
                    "section": section,
                    "category": category,
                })
        return items

    # ── Yerel baslik dizini (tarihler arasi arama) ────────────────────────
    @staticmethod
    def _iso_or_none(value: Any) -> str | None:
        day = re.sub(r"\D", "", str(value or ""))
        return _iso_from_day(day) if len(day) == 8 else None

    def _search_local_index(
        self, query: str, limit: int, page: int, filters: dict[str, Any],
        warnings: list[str],
    ) -> SearchPage | None:
        """Tarih araligi / tarihsiz anahtar kelime aramasini yerel dizinden (rg_index)
        cevapla.  Tek gun istendiyse (``date``, ya da baslangic==bitis) ya da dizin
        yok/bossa None doner ve cagiran eski tek-gun yoluna duser.

        Kurallar: ``date``/``resmi_gazete_tarihi`` her zaman tek gun.  ``query`` +
        yalniz ``karar_tarihi_start`` -> baslangictan bugune aralik.  ``query`` yok
        ama ``karar_tarihi_start`` ve ``_end`` farkli -> aralikta liste.
        """
        if filters.get("date") or filters.get("resmi_gazete_tarihi"):
            return None
        start = self._iso_or_none(filters.get("karar_tarihi_start"))
        end = self._iso_or_none(filters.get("karar_tarihi_end"))
        has_query = bool(query and query.strip())
        if start and end and start == end:
            return None
        if not has_query and not (start and end):
            return None            # sorgusuz + tek tarih = eski gun listeleme
        from dayanak import rg_index

        db = rg_index.open_readonly()
        try:
            if db is None or rg_index.index_status(db)["oge_sayisi"] == 0:
                warnings.append(
                    "Resmî Gazete başlık dizini kurulu değil/boş; yalnızca tek gün "
                    "(karar_tarihi_start, vars. bugün) aranabildi. Tarih aralığı araması için "
                    "dizin gerekir: `dayanak rg backfill --from YYYY-MM-DD --to YYYY-MM-DD`."
                )
                return None
            if start and not end and has_query:
                warnings.append(
                    f"Yalnızca karar_tarihi_start verildi: {start} ile bugün arası arandı. "
                    "Tek gün için karar_tarihi_end'e aynı günü verin."
                )
            total, rows = rg_index.search_index(
                db, query or "", date_from=start, date_to=end,
                sort_by=filters.get("sort_by"), limit=limit, page=page,
            )
            status = rg_index.index_status(db)
        finally:
            if db is not None:
                db.close()
        if status.get("en_yeni_oge_tarihi") and end and end > status["en_yeni_oge_tarihi"]:
            warnings.append(
                f"Dizin {status['en_yeni_oge_tarihi']} tarihine kadar güncel; "
                "sonrası dizinde yok (tek gün için karar_tarihi_start=karar_tarihi_end kullanın)."
            )
        if status.get("en_eski_oge_tarihi") and start and start < status["en_eski_oge_tarihi"]:
            warnings.append(
                f"Dizin {status['en_eski_oge_tarihi']} tarihinden başlıyor; daha eski günler "
                "henüz doldurulmamış olabilir."
            )
        results = [self._row_to_result(r) for r in rows]
        limit = max(1, int(limit))
        return SearchPage(
            results=results, total=total, page=max(1, int(page)), page_size=limit,
            total_pages=-(-total // limit) if total else 0, warnings=warnings,
        )

    def _row_to_result(self, r: Any) -> SearchResult:
        is_pdf = r["ext"] == "pdf"
        return SearchResult(
            source=self.source_id,
            document_id=r["item_id"],
            title=r["baslik"],
            court=r["kategori"] or r["bolum"],
            chamber=r["bolum"],
            decision_date=r["tarih"],
            karar_no=r["numara"],
            source_url=r["url"],
            content_status=ContentStatus.PDF_LINK_ONLY if is_pdf else ContentStatus.METADATA_ONLY,
            metadata={
                "resmi_gazete_tarihi": r["tarih"],
                "sayi_no": r["sayi_no"],
                "bolum": r["bolum"],
                "kategori": r["kategori"],
                "mevzuat_no": r["numara"],
                "format": r["ext"],
                "mukerrer": bool(r["mukerrer"]),
                "kaynak": "yerel_baslik_dizini",
            },
        )

    # ── Search ──────────────────────────────────────────────────────────
    async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]:
        sp = await self.search_page(query, limit=limit, **filters)
        return sp.results

    async def search_page(
        self, query: str = "", limit: int = 10, page: int = 1, **filters: Any
    ) -> SearchPage:
        """List one issue's contents, optionally filtered by keywords.

        There is no server-side search: an issue is a single page, so we fetch
        that page and filter locally.  ``date`` (ISO ``YYYY-MM-DD``) selects the
        issue; it defaults to today, which is what "bugünkü Resmî Gazete" means.
        """
        warnings: list[str] = []
        local = self._search_local_index(query, limit, page, filters, warnings)
        if local is not None:
            return local
        raw_date = (
            filters.get("date")
            or filters.get("karar_tarihi_start")
            or filters.get("resmi_gazete_tarihi")
        )
        if raw_date:
            day = re.sub(r"\D", "", str(raw_date))
            if len(day) != 8:
                warnings.append(
                    f"Tarih anlaşılamadı ({raw_date!r}); ISO 'YYYY-MM-DD' bekleniyor. "
                    "Bugünün sayısı kullanıldı."
                )
                day = _date.today().strftime("%Y%m%d")
        else:
            day = _date.today().strftime("%Y%m%d")

        url = self._index_url(day)
        async with client() as c:
            resp = await c.get(url)
            if resp.status_code == 404:
                # No issue that day (weekend/holiday), or a future date.
                return SearchPage(
                    results=[], total=0, page=1, page_size=limit, total_pages=0,
                    warnings=[
                        *warnings,
                        f"{_iso_from_day(day)} tarihli Resmî Gazete sayısı bulunamadı "
                        "(tatil günü ya da henüz yayımlanmamış olabilir).",
                    ],
                )
            check_http_response(resp, self.source_id)
            html = _decode(resp)

        items = self._parse_index(html, day)
        if not items:
            warnings.append(
                f"{_iso_from_day(day)} fihristi ayrıştırılamadı; sayfa yapısı değişmiş olabilir."
            )

        terms = [_fold(t) for t in query.split()] if query and query.strip() else []
        if terms:
            items = [
                it for it in items
                if all(
                    t in _fold(f"{it['title']} {it.get('number') or ''} "
                               f"{it.get('category') or ''} {it.get('section') or ''}")
                    for t in terms
                )
            ]

        total = len(items)
        results: list[SearchResult] = []
        for it in items[:limit]:
            is_pdf = it["ext"] == "pdf"
            results.append(SearchResult(
                source=self.source_id,
                document_id=it["id"],
                title=it["title"],
                court=it.get("category") or it.get("section"),
                chamber=it.get("section"),
                decision_date=_iso_from_day(day),
                karar_no=it.get("number"),
                source_url=self._item_url(day, it["id"], it["ext"]),
                content_status=(
                    ContentStatus.PDF_LINK_ONLY if is_pdf else ContentStatus.METADATA_ONLY
                ),
                metadata={
                    "resmi_gazete_tarihi": _iso_from_day(day),
                    "bolum": it.get("section"),
                    "kategori": it.get("category"),
                    "mevzuat_no": it.get("number"),
                    "format": it["ext"],
                    "mukerrer": "m" in it["id"].split("-")[0],
                },
            ))
        return SearchPage(
            results=results, total=total, page=1, page_size=limit,
            total_pages=1 if total else 0, warnings=warnings,
        )

    # ── Document fetch ──────────────────────────────────────────────────
    async def get_document(self, document_id: str, **kwargs: Any) -> Document:
        parsed = _parse_item_id(document_id)
        if parsed is None:
            doc = Document(
                source=self.source_id, document_id=document_id,
                title=document_id, content_status=ContentStatus.UNAVAILABLE,
            )
            return finalize_document(doc, [
                f"Geçersiz belge kimliği {document_id!r}. Beklenen biçim "
                "'YYYYMMDD-N' (mükerrer sayılarda 'YYYYMMDDmK-N'), "
                "örn. '20260731-1'. Kimlikleri search() ile alın."
            ])
        day, item_id = parsed

        warnings: list[str] = []
        async with client() as c:
            resp = await c.get(self._item_url(day, item_id, "htm"))
            if resp.status_code == 404:
                # Scanned items are published as PDF instead; no HTML twin.
                pdf_url = self._item_url(day, item_id, "pdf")
                head = await c.get(pdf_url)
                if head.status_code < 400:
                    doc = Document(
                        source=self.source_id, document_id=item_id,
                        title=item_id, decision_date=_iso_from_day(day),
                        source_url=pdf_url, pdf_url=pdf_url,
                        content_status=ContentStatus.PDF_LINK_ONLY,
                    )
                    return finalize_document(doc, [
                        "Bu kalem yalnızca PDF olarak yayımlanmış; tam metin için "
                        "PDF çıkarımı gerekir."
                    ])
                doc = Document(
                    source=self.source_id, document_id=item_id,
                    title=item_id, content_status=ContentStatus.UNAVAILABLE,
                )
                return finalize_document(doc, [
                    f"{item_id}: kaynakta bulunamadı (HTTP 404). Kimliği ve "
                    "tarihi search() sonucundan doğrulayın."
                ])
            check_http_response(resp, self.source_id)
            html = _decode(resp)

        text = html_to_text(html)
        status = ContentStatus.HTML_MARKDOWN if text else ContentStatus.UNAVAILABLE
        if not text:
            warnings.append(f"{item_id}: sayfa boş döndü, metin çıkarılamadı.")

        # First non-boilerplate line is the item's own heading.
        title = item_id
        for line in text.splitlines():
            line = line.strip()
            if len(line) > 12 and not re.match(r"^\d{1,2} \w+ \d{4}", line):
                title = re.sub(r"\s+", " ", line)[:200]
                break

        doc = Document(
            source=self.source_id, document_id=item_id, title=title,
            decision_date=_iso_from_day(day),
            markdown=text, full_text=text,
            content_status=status,
            content_hash=sha(text) if text else None,
            source_url=self._item_url(day, item_id, "htm"),
            metadata={"resmi_gazete_tarihi": _iso_from_day(day)},
        )
        return finalize_document(doc, warnings)
