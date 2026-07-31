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

from .base import SourceClient, check_http_response, client, html_to_text, sha
from emsal_mcp.models import (
    ContentStatus,
    Document,
    SearchPage,
    SearchResult,
    finalize_document,
)

# Item ids: 20260731-1, and mükerrer issues 20260731m1-1.
_ITEM_ID_RE = re.compile(r"^(?P<day>\d{8})(?P<muk>m\d+)?-(?P<seq>\d+)$")
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

    The server omits ``charset`` from Content-Type, so ``resp.text`` would
    apply httpx's UTF-8 guess and mangle every Turkish character.  Read the
    ``<meta>`` declaration from the raw bytes instead; windows-1254 is the
    site's long-standing default when nothing is declared.
    """
    m = _META_CHARSET_RE.search(resp.content[:4096])
    charset = m.group(1).decode("ascii", "ignore") if m else "windows-1254"
    try:
        return resp.content.decode(charset, errors="replace")
    except LookupError:
        return resp.content.decode("windows-1254", errors="replace")


def _parse_item_id(document_id: str) -> tuple[str, str] | None:
    """Split an item id into ``(YYYYMMDD, full_id)``; None when malformed."""
    m = _ITEM_ID_RE.match(document_id.strip())
    if not m:
        return None
    return m.group("day"), m.group(0)


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
                       if _ITEM_HREF_RE.match(a["href"].strip())]
            if not anchors:
                text = para.get_text(" ", strip=True)
                # Headings are set entirely in capitals; item titles are not.
                if text and len(text) > 3 and not any(c.islower() for c in text):
                    if _SECTION_MARKER in text:
                        section, category = text, None
                    else:
                        category = text
                continue

            for anchor in anchors:
                href_match = _ITEM_HREF_RE.match(anchor["href"].strip())
                if href_match is None:  # pragma: no cover - guarded above
                    continue
                item_id = href_match.group("id")
                ext = href_match.group("ext").lower()
                raw = anchor.get_text(" ", strip=True)
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
                        f"{_iso_from_day(day)} tarihli Resmî Gazete sayısı bulunamadı "
                        "(tatil günü ya da henüz yayımlanmamış olabilir)."
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
