"""Parity V2b — AYM KBB API ve HUDOC arama adaptörleri (offline testler).

Fixture'lar 2026-07-15 tarihli canlı yanıtlardan alınmıştır
(PARITY_V2_RAPOR.md Görev 5b/7b).
"""
from __future__ import annotations

import pytest

from emsal_mcp.models import ContentStatus
from emsal_mcp.sources.aihm import AihmClient
from emsal_mcp.sources.simple_public import AymClient


# ── AYM KBB fixtures ─────────────────────────────────────────────────

AYM_SEARCH_ITEM = {
    "kararTipi": "BireyselBasvuru",
    "id": "5307d3dc-741e-7c58-decb-296e6f8835ca",
    "eskiDBID": 12843,
    "basvuruNo": "2019/2890",
    "kararTarihi": "2023-10-25",
    "yayinTarihi": "2024-01-02T00:00:00",
    "resmiGazeteTarihi": "2024-01-03",
    "basvuruAdi": "ALİ KÖMÜRCÜ VE DİĞERLERİ",
    "kararKonusu": "<p>Başvuru, kamulaştırma nedeniyle mülkiyet hakkının ihlal edildiği iddiasına ilişkindir.</p>",
    "highlightCount": 62,
}


class TestAymKbb:
    def test_to_result_maps_fields(self):
        r = AymClient()._to_result(AYM_SEARCH_ITEM)
        assert r.document_id == "5307d3dc-741e-7c58-decb-296e6f8835ca"
        assert r.esas_no == "2019/2890"
        assert "ALİ KÖMÜRCÜ" in r.title
        assert "kamulaştırma" in (r.summary or "")
        assert "<p>" not in (r.summary or "")
        assert r.metadata["kararTipi"] == "BireyselBasvuru"
        assert r.content_status == ContentStatus.METADATA_ONLY
        assert r.source_url.endswith("?id=5307d3dc-741e-7c58-decb-296e6f8835ca")

    def test_build_body_defaults(self):
        body = AymClient()._build_body("mülkiyet hakkı", limit=10, page=1, filters={})
        assert body == {"page": 0, "size": 10, "query": "mülkiyet hakkı"}

    def test_build_body_decision_type_and_sort(self):
        body = AymClient()._build_body(
            "vergi", limit=5, page=3,
            filters={"decision_type": "norm_denetimi", "sort_by": "date"},
        )
        assert body["page"] == 2
        assert body["kararTipi"] == "NormDenetimi"
        assert body["sort"] == "kararTarihi"
        assert body["order"] == "desc"

    def test_build_body_empty_query_omitted(self):
        body = AymClient()._build_body("", limit=5, page=1, filters={})
        assert "query" not in body

    def test_browser_headers_for_waf(self):
        h = AymClient()._headers
        assert h["User-Agent"].startswith("Mozilla/5.0")
        assert h["Origin"] == "https://kararlarbilgibankasi.anayasa.gov.tr"


# ── HUDOC fixtures ───────────────────────────────────────────────────

class TestHudocQueryBuilder:
    def test_default_turkey(self):
        q = AihmClient()._build_query("", {})
        assert q == 'contentsitename:ECHR AND (respondent:"TUR")'

    def test_hepsi_skips_respondent(self):
        q = AihmClient()._build_query("", {"ulke": "HEPSI"})
        assert q == "contentsitename:ECHR"

    def test_field_filters(self):
        q = AihmClient()._build_query(
            "torture", {"madde": "3", "ihlal": "3", "dava_adi": "Kavala", "dil": "ENG"},
        )
        assert '(article:"3")' in q
        assert '(violation:"3")' in q
        assert '(docname:"Kavala")' in q
        assert '(languageisocode:"ENG")' in q
        assert q.endswith("AND (torture)")

    def test_dates(self):
        q = AihmClient()._build_query("", {"start_date": "2020-01-01", "end_date": "2021-12-31"})
        assert '(kpdate>="2020-01-01T00:00:00")' in q
        assert '(kpdate<="2021-12-31T23:59:59")' in q

    def test_quote_stripping(self):
        q = AihmClient()._build_query("", {"dava_adi": 'Ka"vala'})
        assert '(docname:"Kavala")' in q


def test_hudoc_search_page_parses_fixture(monkeypatch):
    fixture = {
        "resultcount": 31,
        "results": [
            {"columns": {
                "itemid": "001-250895", "docname": "KAVALA v. TÜRKİYE (No. 2)",
                "appno": "2170/24", "kpdate": "2026-01-19T00:00:00",
                "conclusion": "", "doctype": "HEGCQP",
                "languageisocode": "ENG", "importance": "4",
            }},
            {"columns": {"docname": "itemid eksik — atlanmalı"}},
        ],
    }

    class FakeResponse:
        status_code = 200
        headers: dict = {}
        def json(self):
            return fixture
        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, **kw):
            assert "/app/query/results" in url
            assert kw["params"]["query"].startswith("contentsitename:ECHR")
            return FakeResponse()

    import asyncio

    monkeypatch.setattr("emsal_mcp.sources.aihm.client", lambda: FakeClient())
    sp = asyncio.run(AihmClient().search_page("", limit=10, dava_adi="Kavala"))
    assert sp.total == 31
    assert len(sp.results) == 1
    r = sp.results[0]
    assert r.document_id == "001-250895"
    assert r.esas_no == "2170/24"
    assert r.decision_date == "2026-01-19"
    assert r.metadata["languageisocode"] == "ENG"


# ── Görev 8a/8b/8c — kurum kaynakları (offline fixtures) ────────────
# Fixture'lar 2026-07-16 canlı yanıtlarından alınmıştır.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _resp(json_data=None, text=""):
    m = MagicMock()
    m.status_code = 200
    m.headers = {}
    m.text = text
    m.json = MagicMock(return_value=json_data)
    m.raise_for_status = MagicMock(return_value=None)
    return m


def _client_cm(get=None, post=None):
    cm = AsyncMock()
    inner = MagicMock()
    if get is not None:
        inner.get = AsyncMock(return_value=get)
    if post is not None:
        inner.post = AsyncMock(return_value=post)
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, inner


class TestGibSearchPage:
    def test_total_and_page_mapping(self):
        from emsal_mcp.sources.simple_public import GibClient
        fixture = {
            "resultContainer": {
                "content": [{
                    "id": 38965,
                    "title": "Hurda haldeki baskı devre kartlarının ithalinde KDV uygulaması hk.",
                    "description": "KDV açıklaması",
                    "ozelgeTarih": "2026-05-22", "ozelgeNo": "E-123", "kanunNo": "3065",
                    "siteLink": "https://gib.gov.tr/mevzuat/kanun/436/ozelge/38965",
                }],
                "totalElements": 7736, "totalPages": 2579,
            }
        }
        cm, inner = _client_cm(post=_resp(json_data=fixture))
        with patch("emsal_mcp.sources.simple_public.client", return_value=cm):
            sp = asyncio.run(GibClient().search_page("KDV", limit=3, page=2))
        assert sp.total == 7736
        assert sp.total_pages == 2579
        assert sp.results[0].document_id == "38965"
        # 1-tabanlı page=2 → upstream ?page=1
        called_url = inner.post.call_args[0][0]
        assert "page=1" in called_url


BTK_CARD_HTML = """
<h3 class="card-title">Çağrı Merkezi Hizmet Kalitesi Yükümlülükleri</h3>
<div><span>Karar tarihi ve no</span><span>02.04.2026 - 2026/İK-THD/89</span></div>
<div><span>Yayım Tarihi</span><span>01.07.2026</span></div>
<div><span>Dosya</span><a href="https://www.btk.gov.tr/s3/web-btk-site/x/2026/07/abc.pdf">indir</a></div>
</div></div></div>
"""


class TestBtkSearchPage:
    def _run(self, query=""):
        from emsal_mcp.sources.simple_public import BtkClient
        cm, _ = _client_cm(get=_resp(text=BTK_CARD_HTML))
        with patch("emsal_mcp.sources.simple_public.client", return_value=cm):
            return asyncio.run(BtkClient().search_page(query, limit=10))

    def test_card_parse(self):
        sp = self._run()
        assert len(sp.results) == 1
        r = sp.results[0]
        assert r.karar_no == "2026/İK-THD/89"
        assert "Çağrı Merkezi" in r.title
        assert r.metadata["pdfUrl"].endswith("abc.pdf")
        assert r.content_status == ContentStatus.PDF_LINK_ONLY
        assert sp.total is None  # BTK toplam sayı vermiyor — uydurulmamalı

    def test_local_query_filter(self):
        assert len(self._run("çağrı merkezi").results) == 1
        assert self._run("numara taşınabilirliği").results == []


class TestRekabetSearchPage:
    def test_total_parse(self):
        from emsal_mcp.sources.simple_public import RekabetClient
        html = """
        <div>Toplam : 10283</div>
        <table class="equalDivide"><tr><td>
        <a href="/Karar?kararId=abc-123">Hakim durum kararı</a> 01.02.2026
        </td></tr></table>
        """
        cm, _ = _client_cm(get=_resp(text=html))
        with patch("emsal_mcp.sources.simple_public.client", return_value=cm):
            sp = asyncio.run(RekabetClient().search_page("hakim durum", limit=5))
        assert sp.total == 10283
        assert sp.total_pages == 2057
        assert sp.results[0].document_id == "abc-123"


def test_btk_pdf_extractor_import_path():
    # Regresyon: `.pdf_extractor` (yanlış, sources altı) yerine
    # `emsal_mcp.pdf_extractor` import edilmeli — 8b denetiminde yakalanan hata.
    import inspect
    from emsal_mcp.sources import simple_public
    src = inspect.getsource(simple_public)
    assert "from .pdf_extractor import" not in src
    assert "from emsal_mcp.pdf_extractor import" in src
