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
                captured.append({"filters": f})
                return []

        search_legislation("kişisel verilerin korunması", sources_override={"mevzuat": FakeClient()})
        assert "mevzuat_no" not in captured[0]["filters"]
