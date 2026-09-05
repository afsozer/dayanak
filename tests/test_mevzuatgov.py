"""Tests for the mevzuat.gov.tr adapter.

This source exists because the Bedesten-backed ``mevzuat`` source missed law
7589 entirely — by number, by title, with and without a type filter — a full
day after it was published. The register itself had it within hours.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.sources.mevzuatgov import (
    TYPE_CODES,
    MevzuatGovClient,
    _clean_title,
    _leading_title,
    _looks_like_text,
)

_ROW = {
    "mevzuatNo": "7589",
    "mevAdi": "YARGININ ETKİN VE VERİMLİ İŞLEMESİNE YÖNELİK BAZI KANUNLARDA DEĞİŞİKLİK YAPILMASINA DAİR KANUN",
    "kabulTarih": "16.07.2026",
    "resmiGazeteTarihi": "31.07.2026",
    "resmiGazeteSayisi": "33326",
    "mevzuatTertip": "5",
    "mevzuatTur": 1,
    "mevzuatTurEnumString": "Kanunlar",
    "url": "mevzuat?MevzuatNo=7589&MevzuatTur=1&MevzuatTertip=5",
    "mukerrer": "HAYIR",
}


def _resp(json_data=None, status=200, body: bytes | None = None, headers=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data or {}
    r.content = body if body is not None else b""
    r.headers = headers if headers is not None else {}
    r.url = "http://mock"
    r.request = MagicMock()
    return r


# The register's own "404 - Sayfa Bulunamadı" landing page, which it serves
# with HTTP 200 (or via a 302 that ``client()`` follows) instead of a 404.
_SOFT_404_BODY = (
    "<html><head><meta charset='utf-8'></head><body>"
    "<h1>404 - Sayfa Bulunamadı</h1></body></html>"
).encode("utf-8")


def _patched(post=None, get=None):
    mc = patch("emsal_mcp.sources.mevzuatgov.client")
    started = mc.start()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=MagicMock(
        post=AsyncMock(side_effect=post) if post else AsyncMock(),
        get=AsyncMock(side_effect=get) if get else AsyncMock(),
    ))
    cm.__aexit__ = AsyncMock(return_value=False)
    started.return_value = cm
    return mc


class TestTitleHelpers:
    def test_highlight_markup_stripped(self):
        """A title-scoped search wraps the match in a yellow <span>; that must
        never reach a citation."""
        raw = "<span style='background-color:yellow'>YARGININ ETKİN</span> VE VERİMLİ"
        assert _clean_title(raw) == "YARGININ ETKİN VE VERİMLİ"

    def test_clean_title_handles_empty(self):
        assert _clean_title(None) == ""
        assert _clean_title("") == ""

    def test_leading_title_joins_split_lines(self):
        """The source splits headings across short lines; taking the first long
        one alone dropped the opening word."""
        text = "YARGININ\nETKİN VE VERİMLİ İŞLEMESİNE YÖNELİK KANUN\nKanun Numarası : 7589"
        assert _leading_title(text, "x").startswith("YARGININ ETKİN")

    def test_leading_title_falls_back(self):
        assert _leading_title("", "1.5.7589") == "1.5.7589"


class TestTypeResolution:
    def test_defaults_to_kanun(self):
        ci = MevzuatGovClient()
        code, warns = ci._resolve_type({})
        assert code == TYPE_CODES["KANUN"] == 1
        assert warns == []

    def test_named_type(self):
        ci = MevzuatGovClient()
        assert ci._resolve_type({"mevzuat_tur_list": ["UY"]})[0] == 8

    def test_numeric_type_passes_through(self):
        ci = MevzuatGovClient()
        assert ci._resolve_type({"mevzuat_tur": 9})[0] == 9

    def test_unknown_type_warns_and_defaults(self):
        ci = MevzuatGovClient()
        code, warns = ci._resolve_type({"mevzuat_tur": "ANAYASA"})
        assert code == 1
        assert any("ANAYASA" in w for w in warns)

    def test_multiple_types_reported_not_silently_dropped(self):
        ci = MevzuatGovClient()
        code, warns = ci._resolve_type({"mevzuat_tur_list": ["KANUN", "TEBLIGLER"]})
        assert code == 1
        assert any("TEBLIGLER" in w for w in warns)


class TestSearch:
    def test_number_lookup_builds_expected_payload(self):
        captured = []

        async def _post(*a, **k):
            captured.append(k.get("json"))
            return _resp({"recordsTotal": 1, "data": [_ROW]})

        mc = _patched(post=_post)
        try:
            sp = asyncio.run(MevzuatGovClient().search_page("", limit=5, mevzuat_no="7589"))
        finally:
            mc.stop()
        params = captured[0]["parameters"]
        assert params["MevzuatTur"] == 1
        assert params["MevzuatNo"] == "7589"
        assert sp.total == 1
        hit = sp.results[0]
        assert hit.document_id == "1.5.7589"
        assert hit.karar_no == "7589"
        assert hit.metadata["resmi_gazete_sayisi"] == "33326"

    def test_title_search_uses_title_scope(self):
        captured = []

        async def _post(*a, **k):
            captured.append(k.get("json"))
            return _resp({"recordsTotal": 1, "data": [_ROW]})

        mc = _patched(post=_post)
        try:
            asyncio.run(MevzuatGovClient().search_page(
                "", limit=5, mevzuat_adi="Yargının Etkin"))
        finally:
            mc.stop()
        params = captured[0]["parameters"]
        assert params["AranacakYer"] == "2", "title scope"
        assert params["AranacakIfade"] == "Yargının Etkin"

    def test_free_query_uses_body_scope(self):
        captured = []

        async def _post(*a, **k):
            captured.append(k.get("json"))
            return _resp({"recordsTotal": 0, "data": []})

        mc = _patched(post=_post)
        try:
            asyncio.run(MevzuatGovClient().search_page("belirsiz alacak", limit=5))
        finally:
            mc.stop()
        assert captured[0]["parameters"]["AranacakYer"] == "1"

    def test_pagination_offset(self):
        captured = []

        async def _post(*a, **k):
            captured.append(k.get("json"))
            return _resp({"recordsTotal": 100, "data": []})

        mc = _patched(post=_post)
        try:
            sp = asyncio.run(MevzuatGovClient().search_page("x", limit=10, page=3))
        finally:
            mc.stop()
        assert captured[0]["start"] == 20
        assert sp.total_pages == 10


class TestGetDocument:
    def test_bad_id_explains_the_format(self):
        doc = asyncio.run(MevzuatGovClient().get_document("7589"))
        assert doc.content_status.value == "unavailable"
        warns = (doc.metadata or {}).get("_emsal_warnings", [])
        assert any("1.5.7589" in w for w in warns), warns

    def test_windows_1254_decoded(self):
        """mevzuat.gov.tr declares windows-1254 but sends no charset header."""
        html = (
            "<html><head><meta charset='Windows-1254'></head><body>"
            "<p>YARGININ ETKİN VE VERİMLİ İŞLEMESİNE YÖNELİK KANUN</p>"
            "<p>yürürlükten kaldırılan 107 nci maddesi</p></body></html>"
        )

        async def _get(*a, **k):
            return _resp(
                body=html.encode("windows-1254"),
                headers={"content-type": "text/html"},
            )

        mc = _patched(get=_get)
        try:
            doc = asyncio.run(MevzuatGovClient().get_document("1.5.7589"))
        finally:
            mc.stop()
        assert "yürürlükten" in (doc.full_text or ""), "mojibake"
        assert "�" not in (doc.full_text or "")
        assert doc.metadata["mevzuat_tur_adi"] == "KANUN"

    def test_iframe_serves_the_types_that_have_no_htm(self):
        """Yönetmelik, tebliğ, KKY and üniversite yönetmeliği have no .htm.

        Measured 05.09.2026 over 30 records: ``/MevzuatMetin/{id}.htm``
        answers 302 → ``/Anasayfa/ErrorPage?code=404`` for MevzuatTur 3, 7, 8,
        9 and 20, and since ``client()`` follows redirects the adapter used to
        read that error page, hit the soft-404 check and report
        ``unavailable`` — for most of the register. The detail page's iframe
        serves all of them.
        """
        calls = []
        html = (
            "<html><body><p>TÜRKİYE EMİSYON TİCARET SİSTEMİ YÖNETMELİĞİ</p>"
            "<p>MADDE 1- (1) Bu Yönetmeliğin amacı…</p></body></html>"
        )

        async def _get(url, *a, **k):
            calls.append(url)
            if ".htm" in url:
                return _resp(body=_SOFT_404_BODY, headers={"content-type": "text/html"})
            return _resp(
                body=html.encode("utf-8"),
                headers={"content-type": "text/html; charset=utf-8"},
            )

        mc = _patched(get=_get)
        try:
            doc = asyncio.run(MevzuatGovClient().get_document("7.5.46261"))
        finally:
            mc.stop()
        assert doc.content_status.value == "html_markdown"
        assert "EMİSYON" in (doc.full_text or "")
        assert any("MevzuatFihristDetayIframe" in c for c in calls), calls
        warns = (doc.metadata or {}).get("_emsal_warnings", [])
        assert any("iframe" in w for w in warns), warns

    def test_iframe_charset_comes_from_the_header(self):
        """The iframe is UTF-8 while the embedded Word export says 1254.

        ``decode_turkish_html`` trusts the ``<meta charset>``, which here
        belongs to the document the iframe wraps, not to the response — so
        this route produced mojibake ("TÃœRKÄ°YE") for every Turkish letter.
        """
        html = (
            "<html><head><meta http-equiv=Content-Type "
            "content='text/html; charset=Windows-1254'></head><body>"
            "<p>TÜRKİYE EMİSYON TİCARET SİSTEMİ YÖNETMELİĞİ</p>"
            "<p>MADDE 1- (1) Bu Yönetmeliğin amacı, sera gazı emisyonlarının "
            "izlenmesine ilişkin usul ve esasları düzenlemektir.</p></body></html>"
        )

        async def _get(url, *a, **k):
            if ".htm" in url:
                return _resp(body=_SOFT_404_BODY, headers={"content-type": "text/html"})
            return _resp(
                body=html.encode("utf-8"),
                headers={"content-type": "text/html; charset=utf-8"},
            )

        mc = _patched(get=_get)
        try:
            doc = asyncio.run(MevzuatGovClient().get_document("7.5.46261"))
        finally:
            mc.stop()
        text = doc.full_text or ""
        assert "TÜRKİYE" in text, text[:120]
        assert "Ã" not in text and "Ä°" not in text

    def test_scanned_pdf_is_not_passed_off_as_text(self):
        """Cumhurbaşkanı kararları are scans with no ToUnicode map.

        pypdf still returns a few hundred characters for them — control codes
        from the embedded font's own encoding. Reporting that as the full text
        of a Cumhurbaşkanı kararı would be worse than reporting nothing.
        """
        garbage = "\x1a\x0e\r\x1a$\t#\x16\x1f#\x19\x18" * 40
        assert _looks_like_text(garbage) is False
        assert _looks_like_text("MADDE 1- Bu Yönetmeliğin amacı… " * 20) is True

    def test_missing_document_reported(self):
        """Nothing on any of the three routes → unavailable, not a fake hit."""
        async def _get(url, *a, **k):
            if url.endswith(".pdf"):
                return _resp(status=404, headers={})
            return _resp(status=404, headers={})

        mc = _patched(get=_get)
        try:
            doc = asyncio.run(MevzuatGovClient().get_document("1.5.999999"))
        finally:
            mc.stop()
        assert doc.content_status.value == "unavailable"
        warns = (doc.metadata or {}).get("_emsal_warnings", [])
        assert any("bulunamadı" in w for w in warns), warns
