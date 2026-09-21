"""Tests for source_url format (mevzuat.adalet.gov.tr/ictihat/{id}).

emsal-mcp now returns the browsable mevzuat.adalet.gov.tr emsal-karar viewer
URL (same as hosted yargı-mcp), keeping the legacy emsal.uyap.gov.tr link as
alternate_url in metadata.
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


class TestSourceUrlFormat:
    def test_search_uses_mevzuat_adalet_url(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_resp({"data": {"emsalKararList": [
            {"id": "ABC123", "itemType": {"description": "Yargıtay"}}
        ]}})
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test", limit=5))
        assert results[0].source_url == "https://mevzuat.adalet.gov.tr/ictihat/ABC123"
        assert results[0].metadata.get("alternate_url") == "https://emsal.uyap.gov.tr/getDokuman?id=ABC123"

    def test_get_document_uses_mevzuat_adalet_url(self):
        import base64
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        html = "<html><body><p>" + "x" * 100 + "</p></body></html>"
        encoded = base64.b64encode(html.encode()).decode()
        mock_resp = _mock_resp({"data": {"title": "T", "content": encoded, "mimeType": "text/html"}})
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            doc = asyncio.run(ci.get_document("DOC456"))
        assert doc.source_url == "https://mevzuat.adalet.gov.tr/ictihat/DOC456"
        assert doc.metadata.get("alternate_url") == "https://emsal.uyap.gov.tr/getDokuman?id=DOC456"
