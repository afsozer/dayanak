"""Tests for Bedesten upstream-error detection (Yargı-MCP parity Görev 3).

Bedesten faults as {"data": null, "metadata": {"FMTY": "ERROR", ...}}
must surface as a structured error, NOT be silently swallowed into an
empty result list (which the LLM misreads as "no precedent exists").
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.sources.base import (
    BedestenUpstreamError,
    check_bedesten_response_error,
)


def _mock_resp(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.url = "http://mock"
    resp.request = MagicMock()
    return resp


class TestCheckBedestenResponseError:
    def test_error_flag_raises(self):
        with pytest.raises(BedestenUpstreamError) as ei:
            check_bedesten_response_error(
                {"data": None, "metadata": {"FMTY": "ERROR", "FMC": "ADALET_RUNTIME_EXCEPTION"}},
                source="bedesten",
            )
        assert ei.value.fmc == "ADALET_RUNTIME_EXCEPTION"
        assert ei.value.source == "bedesten"

    def test_error_flag_with_fmte(self):
        with pytest.raises(BedestenUpstreamError) as ei:
            check_bedesten_response_error(
                {"data": None, "metadata": {"FMTY": "ERROR", "FMC": "X", "FMTE": "solr io"}},
            )
        assert ei.value.fmte == "solr io"

    def test_null_data_without_error_not_raised(self):
        # data: null WITHOUT ERROR flag = legitimately empty (past last page)
        check_bedesten_response_error({"data": None, "metadata": {"FMTY": "OK"}})

    def test_normal_response_not_raised(self):
        check_bedesten_response_error({"data": {"emsalKararList": []}, "metadata": {"FMTY": "OK"}})

    def test_no_metadata_not_raised(self):
        check_bedesten_response_error({"data": {"items": []}})

    def test_non_dict_not_raised(self):
        check_bedesten_response_error("not a dict")  # type: ignore[arg-type]
        check_bedesten_response_error(None)  # type: ignore[arg-type]

    def test_lowercase_error_also_caught(self):
        with pytest.raises(BedestenUpstreamError):
            check_bedesten_response_error(
                {"metadata": {"FMTY": "error", "FMC": "X"}},
            )


class TestBedestenSearchUpstreamError:
    def test_search_raises_on_upstream_error(self):
        """After retry, persistent upstream error propagates (not empty list)."""
        from emsal_mcp.sources import bedesten as bedesten_mod
        from emsal_mcp.sources.bedesten import BedestenClient
        BedestenUpstreamErr = bedesten_mod.BedestenUpstreamError
        ci = BedestenClient()
        ci._upstream_retry_delay = 0.0  # no real sleep during the retry
        err_resp = _mock_resp({
            "data": None,
            "metadata": {"FMTY": "ERROR", "FMC": "ADALET_RUNTIME_EXCEPTION", "FMTE": "solr io"},
        })
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=err_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            with pytest.raises(Exception) as ei:
                asyncio.run(ci.search("test", limit=5))
        # Match by class name (not identity) so the test is robust to the
        # module re-import that test_tool_surface performs mid-suite.
        assert type(ei.value).__name__ == "BedestenUpstreamError"
        assert ei.value.fmc == "ADALET_RUNTIME_EXCEPTION"

    def test_search_retries_then_succeeds(self):
        """First call faults, retry succeeds → returns results."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        ci._upstream_retry_delay = 0.0
        err_resp = _mock_resp({
            "data": None,
            "metadata": {"FMTY": "ERROR", "FMC": "ADALET_RUNTIME_EXCEPTION"},
        })
        ok_resp = _mock_resp({
            "data": {"emsalKararList": [{"id": "1", "itemType": {"description": "Yargıtay"}}]}
        })
        responses = iter([err_resp, ok_resp])
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=lambda *a, **k: next(responses))))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test", limit=5))
        assert len(results) == 1
        assert results[0].document_id == "1"


class TestMevzuatSearchUpstreamError:
    def test_search_raises_on_upstream_error(self):
        from emsal_mcp.sources.mevzuat import MevzuatClient
        mc_client = MevzuatClient()
        mc_client._upstream_retry_delay = 0.0
        err_resp = _mock_resp({
            "data": None,
            "metadata": {"FMTY": "ERROR", "FMC": "ADALET_RUNTIME_EXCEPTION"},
        })
        with patch("emsal_mcp.sources.base.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=err_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            with pytest.raises(Exception) as ei:
                asyncio.run(mc_client.search("test"))
        assert type(ei.value).__name__ == "BedestenUpstreamError"
