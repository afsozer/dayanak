"""Tests for mevzuat search parity (Yargı-MCP parity Görev 5).

- mevzuat_adi: title-only search (drops body phrase)
- mevzuat_no: direct number lookup
- mevzuat_tur_list: multi-type filter
- abbreviation routing: "TCK" / "KVKK" → mevzuat_no
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.integration]


def _mock_resp(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.url = "http://mock"
    resp.request = MagicMock()
    return resp


def _run_mevzuat_search(query="kişisel veri", **kw):
    from emsal_mcp.sources.mevzuat import MevzuatClient
    captured: list[dict] = []

    async def _capture(*a, **k):
        captured.append(k.get("json", {}))
        return _mock_resp({"data": {"mevzuatList": [{"documentId": "m1", "mevzuatAdi": "KVKK", "mevzuatNo": "6698"}]}})

    with patch("emsal_mcp.sources.base.client") as mc:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture)))
        cm.__aexit__ = AsyncMock(return_value=False)
        mc.return_value = cm
        asyncio.run(MevzuatClient().search(query, limit=5, **kw))
    return captured[0]["data"] if captured else {}


class TestMevzuatAdi:
    def test_title_search_drops_phrase(self):
        dp = _run_mevzuat_search(query="kişisel veri", mevzuat_adi="kişisel veri")
        assert dp.get("mevzuatAdi") == "kişisel veri"
        # phrase dropped so body-text search doesn't bury the law
        assert "phrase" not in dp

    def test_title_search_kept_empty(self):
        dp = _run_mevzuat_search(query="", mevzuat_adi="kişisel veri")
        assert dp.get("mevzuatAdi") == "kişisel veri"


class TestMevzuatNo:
    def test_mevzuat_no_passed(self):
        dp = _run_mevzuat_search(query="", mevzuat_no="6698")
        assert dp.get("mevzuatNo") == "6698"

    def test_mevzuat_no_empty_ignored(self):
        dp = _run_mevzuat_search(query="veri", mevzuat_no="")
        assert "mevzuatNo" not in dp


class TestMevzuatTurList:
    def test_multi_type(self):
        dp = _run_mevzuat_search(query="veri", mevzuat_tur_list=["KANUN", "KHK"])
        assert dp.get("mevzuatTurList") == ["KANUN", "KHK"]

    def test_legacy_type_still_works(self):
        dp = _run_mevzuat_search(query="veri", type="KANUN")
        assert dp.get("mevzuatTurList") == ["KANUN"]


class TestAbbreviationRouting:
    def test_tck_routes_to_5237(self):
        from emsal_mcp.legislation import search_legislation
        captured: list[dict] = []

        class FakeClient:
            async def search(self, q, limit=10, **f):
                captured.append({"query": q, "filters": f})
                return []

        result = search_legislation("TCK 157", sources_override={"mevzuat": FakeClient()})
        # mevzuat_no should be 5237 (TCK)
        assert captured[0]["filters"].get("mevzuat_no") == "5237"
        assert any("5237" in w for w in result["warnings"])

    def test_kvkk_routes_to_6698(self):
        from emsal_mcp.legislation import search_legislation
        captured: list[dict] = []

        class FakeClient:
            async def search(self, q, limit=10, **f):
                captured.append({"filters": f})
                return []

        search_legislation("KVKK", sources_override={"mevzuat": FakeClient()})
        assert captured[0]["filters"].get("mevzuat_no") == "6698"

    def test_plain_query_not_rerouted(self):
        from emsal_mcp.legislation import search_legislation
        captured: list[dict] = []

        class FakeClient:
            async def search(self, q, limit=10, **f):
                captured.append({"query": q, "filters": f})
                return []

        search_legislation("kişisel verilerin korunması", sources_override={"mevzuat": FakeClient()})
        assert "mevzuat_no" not in captured[0]["filters"]

    def test_mevzuat_no_drops_phrase(self):
        """When mevzuat_no is given, the body phrase is dropped so Bedesten
        doesn't apply it as a filter that suppresses the number match.
        Discovered during end-to-end parity verification."""
        from emsal_mcp.legislation import search_legislation
        captured: list[dict] = []

        class FakeClient:
            async def search(self, q, limit=10, **f):
                captured.append({"query_passed": q, "filters": f})
                return []

        search_legislation("KVKK", mevzuat_no="6698", sources_override={"mevzuat": FakeClient()})
        # query should be emptied (number lookup takes priority over phrase)
        assert captured[0]["query_passed"] == ""
        assert captured[0]["filters"].get("mevzuat_no") == "6698"


class TestSearchPage:
    """``search()`` returns a bare list, so Bedesten's own total was dropped.

    Measured 05.09.2026: ``{"data": {"mevzuatList": [...], "total": 1860,
    "start": 0}}`` for mevzuatAdi="Kanun". A caller asking for 10 hits could
    not tell 10-of-1860 from 10-of-10.
    """

    @staticmethod
    def _run(total, n=3, **kw):
        from emsal_mcp.sources.mevzuat import MevzuatClient

        payload = {"data": {
            "mevzuatList": [
                {"documentId": f"m{i}", "mevzuatAdi": f"KANUN {i}", "mevzuatNo": str(i)}
                for i in range(n)
            ],
            "start": 0,
        }}
        if total is not None:
            payload["data"]["total"] = total

        async def _post(*a, **k):
            return _mock_resp(payload)

        with patch("emsal_mcp.sources.base.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_post)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            return asyncio.run(MevzuatClient().search_page("kanun", limit=10, **kw))

    def test_total_and_page_count_surface(self):
        page = self._run(total=1860)
        assert page.total == 1860
        assert page.page_size == 10
        assert page.total_pages == 186
        assert len(page.results) == 3

    def test_missing_total_is_none_not_zero(self):
        """No total upstream must not be reported as "0 sonuç"."""
        page = self._run(total=None)
        assert page.total is None
        assert page.total_pages is None
        assert len(page.results) == 3

    def test_search_still_returns_a_plain_list(self):
        """The list contract is unchanged; search_page is additive."""
        from emsal_mcp.sources.mevzuat import MevzuatClient

        async def _post(*a, **k):
            return _mock_resp({"data": {"mevzuatList": [
                {"documentId": "m1", "mevzuatAdi": "KVKK", "mevzuatNo": "6698"},
            ], "total": 7}})

        with patch("emsal_mcp.sources.base.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_post)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            out = asyncio.run(MevzuatClient().search("kvkk", limit=5))
        assert isinstance(out, list)
        assert out[0].document_id == "m1"
