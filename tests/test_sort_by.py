"""Tests for sort_by (relevance vs date) in Bedesten & Mevzuat clients.

Yargı-MCP parity Görev 2: relevance should be the default when a phrase is
present (so the actual matching decisions surface first), date only when
filter-only lookups are performed.
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
    return resp


def _run_search(client, query, **kw):
    captured: list[dict] = []

    async def _capture(*a, **k):
        captured.append(k.get("json", {}))
        return _mock_resp({"data": {"emsalKararList": [{"id": "1", "itemType": {"description": "Y"}}]}})

    with patch("emsal_mcp.sources.bedesten.client") as mc:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture)))
        cm.__aexit__ = AsyncMock(return_value=False)
        mc.return_value = cm
        asyncio.run(client.search(query, limit=5, **kw))
    return captured[0]["data"] if captured else {}


class TestBedestenSortBy:
    def test_phrase_present_defaults_to_relevance(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        dp = _run_search(BedestenClient(), "+tahliye +geçerlilik")
        # relevance → no sortFields sent (Solr uses score default)
        assert "sortFields" not in dp
        assert "sortDirection" not in dp

    def test_empty_phrase_defaults_to_date(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        dp = _run_search(BedestenClient(), "")
        assert dp.get("sortFields") == ["KARAR_TARIHI"]
        assert dp.get("sortDirection") == "desc"

    def test_sort_by_date_forced(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        dp = _run_search(BedestenClient(), "tazminat", sort_by="date")
        assert dp.get("sortFields") == ["KARAR_TARIHI"]

    def test_sort_by_relevance_forced(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        dp = _run_search(BedestenClient(), "tazminat", sort_by="relevance")
        assert "sortFields" not in dp

    def test_invalid_sort_by_falls_back(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        dp = _run_search(BedestenClient(), "tazminat", sort_by="bogus")
        # query present + invalid → relevance default
        assert "sortFields" not in dp


class TestMevzuatSortBy:
    def _run(self, query, **kw):
        from emsal_mcp.sources.mevzuat import MevzuatClient
        captured: list[dict] = []

        async def _capture(*a, **k):
            captured.append(k.get("json", {}))
            return _mock_resp({"data": {"mevzuatList": [{"documentId": "m1", "mevzuatAdi": "X"}]}})

        with patch("emsal_mcp.sources.base.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            asyncio.run(MevzuatClient().search(query, limit=5, **kw))
        return captured[0]["data"] if captured else {}

    def test_phrase_present_defaults_to_relevance(self):
        dp = self._run("kişisel veri")
        assert "sortFields" not in dp

    def test_empty_phrase_defaults_to_date(self):
        dp = self._run("")
        assert dp.get("sortFields") == ["RESMI_GAZETE_TARIHI"]

    def test_sort_by_date_forced(self):
        dp = self._run("veri", sort_by="date")
        assert dp.get("sortFields") == ["RESMI_GAZETE_TARIHI"]

    def test_sort_by_kayit_tarihi(self):
        dp = self._run("veri", sort_by="kayit_tarihi")
        assert dp.get("sortFields") == ["KAYIT_TARIHI"]
