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
