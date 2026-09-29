"""Resmi Gazete baslik dizini (rg_index) — agsiz testler (httpx.MockTransport)."""
from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest

from emsal_mcp import rg_index as R

pytestmark = [pytest.mark.unit]


def _page(day: str, sayi: str, items: list[tuple[str, str, str]], muk: bool = False) -> bytes:
    """items: (dosya_adi, kategori, baslik)."""
    body = ["<html><head><meta http-equiv=\"Content-Type\" content=\"text/html; charset=windows-1254\"></head><body>"]
    body.append(f"<p>1 Aralık 2025 Tarihli ve {sayi} Sayılı Resmî Gazete"
                f"{' - Mükerrer' if muk else ''}</p>")
    body.append("<p><b><u>YÜRÜTME VE İDARE BÖLÜMÜ</u></b></p>")
    last = None
    for href, kat, baslik in items:
        if kat != last:
            body.append(f"<p><b><u>{kat}</u></b></p>")
            last = kat
        body.append(f'<p><a href="{href}">&#8212;&nbsp; {baslik}</a></p>')
    body.append("</body></html>")
    return "".join(body).encode("windows-1254", errors="replace")


AAUT = "Avukatlık Asgari Ücret Tarifesi"


def _site(pages: dict[str, bytes], fail: dict[str, list[int]] | None = None):
    """{sayfa: html}; olmayan 404. ``fail``: sayfa -> sirayla donecek durum kodlari."""
    fail = fail or {}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1].removesuffix(".htm")
        calls.append(name)
        if fail.get(name):
            return httpx.Response(fail[name].pop(0))
        if name in pages:
            return httpx.Response(200, content=pages[name])
        return httpx.Response(404)

    fetcher = IndexFetcherFactory(handler)
    return fetcher, calls


def IndexFetcherFactory(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return R.IndexFetcher(delay=0, retries=2, backoff=0, http=http)


@pytest.fixture()
def db(tmp_path):
    conn = R.connect(tmp_path / "rg.sqlite3")
    yield conn
    conn.close()


def _run(coro):
    return asyncio.run(coro)


PAGES = {
    "20251201": _page("20251201", "33094", [
        ("20251201-1.htm", "TEBLİĞLER", AAUT + " (2026)"),
        ("20251201-2.pdf", "TEBLİĞLER", "Dahilde İşleme İzin Belgelerinin Listesi"),
        ("20251201-3.htm", "YÖNETMELİKLER", "Piri Reis Üniversitesi Yönetmeliği"),
    ]),
    "20251201m1": _page("20251201", "33094", [
        ("20251201M1-1.pdf", "KARARLAR", "Asgari Ücret Destek Kararı"),
    ], muk=True),
    "20251202": _page("20251202", "33095", [
        ("20251202-1.htm", "KANUNLAR", "Vergi Usul Kanunu Değişiklik"),
    ]),
}


class TestSchemaAndInsert:
    def test_schema_and_parse_insert(self, db):
        fetcher, _ = _site(PAGES)
        r = _run(R.fetch_day(fetcher, db, "20251201"))
        assert r["ogeler"] == 4
        assert r["durumlar"] == {"20251201": "ok", "20251201m1": "ok", "20251201m2": "404"}
        cols = {c[1] for c in db.execute("PRAGMA table_info(rg_ogeler)")}
        assert {"item_id", "tarih", "sayi_no", "mukerrer", "bolum", "kategori", "baslik",
                "url", "ext", "cekilme_zamani"} <= cols
        row = db.execute("SELECT * FROM rg_ogeler WHERE item_id='20251201m1-1'").fetchone()
        assert row["mukerrer"] == 1 and row["sayi_no"] == "33094"
        assert row["ext"] == "pdf" and row["url"].endswith("/2025/12/20251201m1-1.pdf")
        main = db.execute("SELECT * FROM rg_ogeler WHERE item_id='20251201-1'").fetchone()
        assert main["kategori"] == "TEBLİĞLER" and main["bolum"] == "YÜRÜTME VE İDARE BÖLÜMÜ"
        assert main["mukerrer"] == 0 and main["tarih"] == "2025-12-01"

    def test_refetch_replaces_page_rows(self, db):
        fetcher, _ = _site(PAGES)
        _run(R.fetch_day(fetcher, db, "20251201"))
        _run(R.fetch_day(fetcher, db, "20251201"))
        assert db.execute("SELECT COUNT(*) FROM rg_ogeler").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM rg_fts").fetchone()[0] == 4


class TestSearch:
    @pytest.fixture()
    def filled(self, db):
        fetcher, _ = _site(PAGES)
        for d in ("20251201", "20251202"):
            _run(R.fetch_day(fetcher, db, d))
        return db

    def test_accent_insensitive_match(self, filled):
        total, rows = R.search_index(filled, "asgari ucret")
        ids = {r["item_id"] for r in rows}
        assert total == 2 and ids == {"20251201-1", "20251201m1-1"}

    def test_dotless_i_and_capitals(self, filled):
        total, _ = R.search_index(filled, "AVUKATLIK TARİFESİ")
        assert total == 1

    def test_prefix_and_phrase(self, filled):
        assert R.search_index(filled, "tarife")[0] == 1
        assert R.search_index(filled, '"asgari ücret tarifesi"')[0] == 1
        assert R.search_index(filled, '"tarifesi asgari"')[0] == 0

    def test_operator_junk_is_sanitized(self, filled):
        assert R.search_index(filled, "asgari AND (ücret) OR *")[0] >= 1
        assert R.search_index(filled, "   ")[0] == 0

    def test_date_range_filter(self, filled):
        assert R.search_index(filled, "kanunu", date_from="2025-12-02")[0] == 1
        assert R.search_index(filled, "kanunu", date_to="2025-12-01")[0] == 0
        assert R.search_index(filled, "asgari", date_from="2025-12-02", date_to="2025-12-31")[0] == 0

    def test_pagination_and_sort(self, filled):
        total, rows = R.search_index(filled, "asgari", limit=1, page=1, sort_by="date")
        assert total == 2 and len(rows) == 1
        _, rows2 = R.search_index(filled, "asgari", limit=1, page=2, sort_by="date")
        assert rows[0]["item_id"] != rows2[0]["item_id"]
        _, none = R.search_index(filled, "asgari", limit=1, page=3)
        assert none == []

    def test_range_listing_without_query(self, filled):
        total, rows = R.search_index(filled, "", date_from="2025-12-01", date_to="2025-12-02", limit=50)
        assert total == 5 and rows[0]["tarih"] == "2025-12-02"
        assert R.search_index(filled, "")[0] == 0   # tarihsiz+sorgusuz: bos


class TestBackfill:
    def test_404_day_recorded_and_not_refetched(self, db):
        fetcher, calls = _site(PAGES)
        st = _run(R.backfill(db, date(2025, 11, 30), date(2025, 12, 2), fetcher=fetcher))
        assert st["gun_404"] == 1 and st["islenen_gun"] == 3 and st["oge"] == 5
        row = db.execute("SELECT durum, oge_sayisi FROM rg_gunler WHERE sayfa='20251130'").fetchone()
        assert (row["durum"], row["oge_sayisi"]) == ("404", 0)
        n = len(calls)
        st2 = _run(R.backfill(db, date(2025, 11, 30), date(2025, 12, 2), fetcher=fetcher))
        assert st2["islenen_gun"] == 0 and st2["atlanan_gun"] == 3
        assert len(calls) == n, "bitmis gunler yeniden sorulmamali"

    def test_resumes_where_it_left(self, db):
        fetcher, calls = _site(PAGES)
        _run(R.backfill(db, date(2025, 12, 1), date(2025, 12, 1), fetcher=fetcher))
        calls.clear()
        st = _run(R.backfill(db, date(2025, 12, 1), date(2025, 12, 2), fetcher=fetcher))
        assert st["islenen_gun"] == 1 and st["atlanan_gun"] == 1
        assert "20251201" not in calls and "20251202" in calls

    def test_transient_error_is_retried_then_recorded_as_hata(self, db):
        fetcher, _ = _site(PAGES, fail={"20251202": [503, 503, 503]})
        st = _run(R.backfill(db, date(2025, 12, 2), date(2025, 12, 2), fetcher=fetcher))
        assert st["gun_hata"] == 1
        assert db.execute("SELECT durum FROM rg_gunler WHERE sayfa='20251202'").fetchone()[0] == "hata"
        # sonraki kosuda 'hata' gunu yeniden denenir ve duzelir
        fetcher2, _ = _site(PAGES)
        st = _run(R.backfill(db, date(2025, 12, 2), date(2025, 12, 2), fetcher=fetcher2))
        assert st["gun_hata"] == 0 and st["oge"] == 1

    def test_429_backs_off_and_succeeds(self, db):
        fetcher, calls = _site(PAGES, fail={"20251202": [429]})
        st = _run(R.backfill(db, date(2025, 12, 2), date(2025, 12, 2), fetcher=fetcher))
        assert st["oge"] == 1 and st["429"] == 1

    def test_refresh_from_refetches_recent_404(self, db):
        fetcher, _ = _site({})
        _run(R.backfill(db, date(2025, 12, 2), date(2025, 12, 2), fetcher=fetcher))
        fetcher2, _ = _site(PAGES)
        st = _run(R.backfill(db, date(2025, 12, 2), date(2025, 12, 2), fetcher=fetcher2,
                             refresh_from=date(2025, 12, 1)))
        assert st["oge"] == 1

    def test_clamps_to_archive_start(self, db):
        fetcher, calls = _site({})
        st = _run(R.backfill(db, date(1999, 1, 1), date(2000, 6, 27), fetcher=fetcher))
        assert st["islenen_gun"] == 1 and calls[0] == "20000627"

    def test_status(self, db):
        fetcher, _ = _site(PAGES)
        _run(R.backfill(db, date(2025, 11, 30), date(2025, 12, 2), fetcher=fetcher))
        s = R.index_status(db)
        assert s["oge_sayisi"] == 5 and s["en_eski_oge_tarihi"] == "2025-12-01"
        assert s["gun_durumlari"]["404"] >= 1


class TestParsing:
    def test_header_and_mukerrer(self):
        from emsal_mcp.sources.resmigazete import parse_issue_header
        html = "<b>9 Mart 2023 Tarihli ve 32127 Sayılı Resmî\n Gazete - Mükerrer</b>"
        assert parse_issue_header(html) == ("32127", True)
        assert parse_issue_header("<b>1 Aralık 2025 Tarihli ve 33094 Sayılı Resmî Gazete</b>") == ("33094", False)

    def test_split_span_heading_is_joined(self):
        from emsal_mcp.sources.resmigazete import ResmiGazeteClient
        html = ('<p><u><span>MİLL</span><span>ETLERARASI ANDLAŞMALAR</span></u></p>'
                '<p><a href="20230309M1-1.pdf">&#8212; Bir Karar</a></p>')
        it = ResmiGazeteClient()._parse_index(html, "20230309")[0]
        assert it["category"] == "MİLLETLERARASI ANDLAŞMALAR"
        assert it["id"] == "20230309m1-1"

    def test_legacy_single_page_format(self):
        html = ('<html><body><p><u>YÜRÜTME VE İDARE BÖLÜMÜ</u></p>'
                '<p><b><u>Tebliğ</u></b></p>'
                '<p><a href="#2">— Bir Tebliğ Başlığı</a></p></body></html>')
        items = R.parse_issue(html, "20010102")
        assert items[0]["id"] == "20010102-2" and items[0]["category"] == "Tebliğ"
        assert items[0]["url"].endswith("/2001/01/20010102.htm#2")

    def test_decode_forces_1254_for_latin1_declarations(self):
        raw = '<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">Şişli'.encode("windows-1254")
        assert "Şişli" in R.decode_page(raw)


class TestSearchPageIntegration:
    """ResmiGazeteClient.search_page: aralik/tarihsiz sorgu -> yerel dizin."""

    @pytest.fixture()
    def indexed(self, tmp_path, monkeypatch):
        path = tmp_path / "rg.sqlite3"
        monkeypatch.setenv("EMSAL_RG_DB_PATH", str(path))
        conn = R.connect(path)
        fetcher, _ = _site(PAGES)
        for d in ("20251201", "20251202"):
            _run(R.fetch_day(fetcher, conn, d))
        conn.close()
        return path

    def _search(self, **kw):
        from emsal_mcp.sources.resmigazete import ResmiGazeteClient
        return _run(ResmiGazeteClient().search_page(**kw))

    def test_range_query_uses_index(self, indexed):
        sp = self._search(query="asgari ücret", limit=1, page=1,
                          karar_tarihi_start="2025-11-01", karar_tarihi_end="2025-12-31")
        assert sp.total == 2 and sp.total_pages == 2 and len(sp.results) == 1
        r = sp.results[0]
        assert r.decision_date == "2025-12-01" and r.metadata["sayi_no"] == "33094"
        assert r.metadata["kaynak"] == "yerel_baslik_dizini" and r.document_id

    def test_no_dates_searches_whole_index(self, indexed):
        sp = self._search(query="vergi usul")
        assert sp.total == 1 and sp.results[0].document_id == "20251202-1"

    def test_start_only_gets_range_warning(self, indexed):
        sp = self._search(query="asgari", karar_tarihi_start="2025-12-01")
        assert sp.total == 2 and any("bugün arası" in w for w in sp.warnings)

    def test_missing_index_falls_back_with_warning(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EMSAL_RG_DB_PATH", str(tmp_path / "yok.sqlite3"))
        from unittest.mock import AsyncMock, MagicMock, patch
        resp = MagicMock(status_code=404)
        cm = AsyncMock()
        cm.__aenter__.return_value.get = AsyncMock(return_value=resp)
        with patch("emsal_mcp.sources.resmigazete.client", return_value=cm):
            sp = self._search(query="asgari", karar_tarihi_start="2025-12-01",
                              karar_tarihi_end="2025-12-31")
        assert sp.total == 0
        assert any("kurulu değil" in w for w in sp.warnings)
        assert not (tmp_path / "yok.sqlite3").exists(), "arama dizin dosyasi yaratmamali"

    def test_single_day_query_keeps_live_path(self, indexed):
        from unittest.mock import AsyncMock, MagicMock, patch
        resp = MagicMock(status_code=404)
        cm = AsyncMock()
        cm.__aenter__.return_value.get = AsyncMock(return_value=resp)
        with patch("emsal_mcp.sources.resmigazete.client", return_value=cm) as c:
            sp = self._search(query="asgari", date="2025-12-01")
        assert c.called and sp.total == 0
