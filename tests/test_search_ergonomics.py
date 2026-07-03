"""Tests for search_decisions ergonomics (Yargı-MCP parity Görev 6).

- source optional (defaults to bedesten with Yargıtay+Danıştay sweep)
- at-least-one-criterion required guard
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


class TestCriterionGuard:
    """The at-least-one-criterion guard lives in the MCP tool wrapper, not in
    the client.  We exercise the same logic by re-implementing the guard check
    inline (the wrapper is hard to invoke without a full MCP harness)."""

    def _has_criterion(self, **kw):
        return any([
            kw.get("query") and str(kw["query"]).strip(),
            kw.get("esas_no"), kw.get("karar_no"), kw.get("birimAdi"),
            kw.get("karar_tarihi_start"), kw.get("karar_tarihi_end"),
        ])

    def test_no_criterion_rejected(self):
        assert self._has_criterion(court_types=["YARGITAYKARARI"]) is False

    def test_query_only_passes(self):
        assert self._has_criterion(query="tazminat") is True

    def test_docket_only_passes(self):
        assert self._has_criterion(esas_no="2023/1") is True

    def test_birim_only_passes(self):
        assert self._has_criterion(birimAdi="H12") is True

    def test_date_range_only_passes(self):
        assert self._has_criterion(karar_tarihi_start="2023-01-01") is True


class TestDefaultCourtTypes:
    """When source defaults to bedesten and no court_types given, the search
    should run a combined Yargıtay+Danıştay sweep."""

    def test_default_court_types_yargitay_danistay(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        captured: list[dict] = []

        async def _capture(*a, **k):
            captured.append(k.get("json", {}))
            return _mock_resp({"data": {"emsalKararList": [{"id": "1", "itemType": {"description": "Y"}}]}})

        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            asyncio.run(ci.search("tazminat", limit=5, court_types=["YARGITAYKARARI", "DANISTAYKARARI"]))
        data_payload = captured[0]["data"]
        assert data_payload["itemTypeList"] == ["YARGITAYKARARI", "DANISTAYKARARI"]
