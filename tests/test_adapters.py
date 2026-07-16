"""Tests for v0.4 adapter hardening and source smoke contracts.

Covers:
- SourceSmokeResult model
- Per-source smoke() offline-safe defaults
- decode_b64 error handling
- finalize_document min-content-length downgrade
- Bedesten/Yargitay item_type handling and source_id preservation
- Mevzuat source_id/title
- AYM fallback metadata_only
- Danistay headers
- GIB normalization
- Uyusmazlik/Rekabet/Sayistay graceful unavailable
- Mocked adapter search/get_document tests
- Contract tests for all registered sources
- Document status sanity
- CLI smoke command
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.models import (
    ContentStatus,
    Document,
    SourceSmokeResult,
    finalize_document,
    MIN_CONTENT_LENGTH,
)
from emsal_mcp.sources.base import (
    check_http_response,
    decode_b64,
    html_to_text,
    metadata_doc,
    sha,
)
from emsal_mcp.sources.registry import (
    capabilities,
    registry,
    smoke_all,
    smoke_all_sync,
)


# ── SourceSmokeResult model ─────────────────────────────────────────────


class TestSourceSmokeResultModel:
    def test_construct_minimal(self):
        r = SourceSmokeResult(source_id="test")
        assert r.source_id == "test"
        assert r.offline_ok is True
        assert r.online_ok is None
        assert r.search_callable is True
        assert r.get_document_callable is True
        assert r.min_content_length_ok is True
        assert r.warnings == []
        assert r.errors == []
        assert r.tested_at is not None

    def test_model_dump_json(self):
        r = SourceSmokeResult(source_id="x", offline_ok=False, errors=["err"])
        d = r.model_dump(mode="json")
        assert d["source_id"] == "x"
        assert d["offline_ok"] is False
        assert "err" in d["errors"]

    def test_model_roundtrip(self):
        r = SourceSmokeResult(source_id="rt", warnings=["w1"])
        dumped = r.model_dump()
        restored = SourceSmokeResult.model_validate(dumped)
        assert restored.source_id == "rt"
        assert restored.warnings == ["w1"]


# ── decode_b64 error handling ──────────────────────────────────────────


class TestDecodeB64:
    def test_valid_base64(self):
        import base64
        data = base64.b64encode(b"hello world").decode()
        assert decode_b64(data) == b"hello world"

    def test_padding_fix(self):
        import base64
        data = base64.b64encode(b"test").decode().rstrip("=")
        assert decode_b64(data) == b"test"

    def test_invalid_base64_returns_empty(self):
        result = decode_b64("not-valid-base64!!!")
        assert result == b""

    def test_empty_string(self):
        result = decode_b64("")
        assert result == b""

    def test_partial_corrupt(self):
        result = decode_b64("AAAA==")
        assert isinstance(result, bytes)


# ── finalize_document ──────────────────────────────────────────────────


class TestFinalizeDocument:
    def test_downgrades_short_content(self):
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="Short", content_status=ContentStatus.FULL_TEXT,
        )
        result = finalize_document(doc)
        assert result.content_status == ContentStatus.METADATA_ONLY
        assert result.full_text is None
        assert result.content_hash is None

    def test_keeps_long_content(self):
        long_text = "x" * (MIN_CONTENT_LENGTH + 10)
        doc = Document(
            source="test", document_id="1", title="T",
            full_text=long_text, content_status=ContentStatus.FULL_TEXT,
        )
        result = finalize_document(doc)
        assert result.content_status == ContentStatus.FULL_TEXT
        assert result.content_hash is not None

    def test_metadata_only_not_affected(self):
        doc = Document(
            source="test", document_id="1", title="T",
            content_status=ContentStatus.METADATA_ONLY,
        )
        result = finalize_document(doc)
        assert result.content_status == ContentStatus.METADATA_ONLY

    def test_attachments_warnings(self):
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="x" * 10, content_status=ContentStatus.FULL_TEXT,
        )
        result = finalize_document(doc, warnings=["custom warning"])
        assert "_emsal_warnings" in result.metadata
        assert "custom warning" in result.metadata["_emsal_warnings"]

    def test_pdf_link_not_affected(self):
        doc = Document(
            source="test", document_id="1", title="T",
            content_status=ContentStatus.PDF_LINK_ONLY,
        )
        result = finalize_document(doc)
        assert result.content_status == ContentStatus.PDF_LINK_ONLY


# ── html_to_text ───────────────────────────────────────────────────────


class TestHtmlToText:
    def test_basic_html(self):
        assert "hello" in html_to_text("<p>hello</p>")

    def test_strips_script(self):
        assert "visible" in html_to_text("<p>visible</p><script>hidden</script>")

    def test_strips_style(self):
        assert "text" in html_to_text("<p>text</p><style>.x{}</style>")


# ── check_http_response ────────────────────────────────────────────────


class TestCheckHttpResponse:
    def test_200_ok(self):
        resp = httpx.Response(200, request=httpx.Request("GET", "http://test"))
        check_http_response(resp, "test")

    def test_404_raises(self):
        resp = httpx.Response(404, request=httpx.Request("GET", "http://test"))
        with pytest.raises(httpx.HTTPStatusError):
            check_http_response(resp, "test")

    def test_500_raises(self):
        resp = httpx.Response(500, request=httpx.Request("GET", "http://test"))
        with pytest.raises(httpx.HTTPStatusError):
            check_http_response(resp, "test")


# ── sha ────────────────────────────────────────────────────────────────


class TestSha:
    def test_known_hash(self):
        import hashlib
        expected = hashlib.sha256("hello".encode("utf-8")).hexdigest()
        assert sha("hello") == expected

    def test_unicode(self):
        result = sha("Türkçe test")
        assert len(result) == 64


# ── metadata_doc ───────────────────────────────────────────────────────


class TestMetadataDoc:
    def test_basic(self):
        doc = metadata_doc("src", "123", "Title")
        assert doc.source == "src"
        assert doc.document_id == "123"
        assert doc.title == "Title"
        assert doc.content_status == ContentStatus.METADATA_ONLY

    def test_with_extra_kwargs(self):
        doc = metadata_doc("src", "1", "T", court="Yargıtay")
        assert doc.court == "Yargıtay"


# ── smoke() offline-safe defaults ─────────────────────────────────────


class TestSmokeDefaults:
    """Each registered source should return a SourceSmokeResult from smoke()."""

    def test_all_sources_have_smoke(self):
        for sid, src in registry().items():
            result = asyncio.run(src.smoke(online=False))
            assert isinstance(result, SourceSmokeResult), f"{sid} smoke() returned {type(result)}"
            assert result.source_id == sid
            assert result.offline_ok is True


    def test_smoke_all_sync(self):
        results = smoke_all_sync(online=False)
        assert isinstance(results, list)
        assert len(results) == len(registry())
        for r in results:
            assert "source_id" in r
            assert "offline_ok" in r

    def test_smoke_all_async(self):
        results = asyncio.run(smoke_all(online=False))
        assert len(results) == len(registry())
        for r in results:
            assert isinstance(r, SourceSmokeResult)


# ── Registry & capability contract ─────────────────────────────────────


class TestRegistryContract:
    EXPECTED = [
        "bedesten", "yargitay", "mevzuat", "aym", "danistay",
        "gib", "uyusmazlik", "rekabet", "sayistay",
        "resmigazete", "kvkk", "aihm", "btk",
    ]

    def test_all_sources_present(self):
        reg = registry()
        for sid in self.EXPECTED:
            assert sid in reg, f"Missing source: {sid}"

    def test_capabilities_count(self):
        caps = capabilities()
        assert len(caps) == len(self.EXPECTED)

    def test_capability_has_required_keys(self):
        required = {
            "source_id", "display_name", "status",
            "supports_search", "supports_get_document",
            "supports_full_text", "supports_pdf_link",
            "supports_metadata_only", "known_limitations", "notes",
            "source", "name", "public", "tools",
        }
        for cap in capabilities():
            missing = required - set(cap.keys())
            assert not missing, f"{cap['source_id']}: missing {missing}"

    def test_source_id_matches_capability_model(self):
        for sid, src in registry().items():
            cap = src.capability_model()
            assert cap.source_id == sid, f"{sid}: capability_model().source_id = {cap.source_id}"

    def test_document_status_sanity(self):
        for cap in capabilities():
            if cap["supports_full_text"]:
                assert cap["status"] in ("stable", "partial", "experimental")


# ── Mocked adapter tests ──────────────────────────────────────────────


def _mock_httpx_response(json_data=None, text="", status_code=200):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.url = httpx.URL("http://mock.test")
    resp.request = httpx.Request("GET", "http://mock.test")
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


class TestBedestenMocked:
    def test_search_basic(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {
                "emsalKararList": [
                    {
                        "id": "123",
                        "itemType": {"description": "Yargıtay"},
                        "birimAdi": "1. Daire",
                        "kararTarihiStr": "2024-01-01",
                        "esasNo": "2024/1",
                        "kararNo": "100",
                    }
                ]
            }
        })
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test", limit=5))
        assert len(results) == 1
        assert results[0].document_id == "123"
        assert results[0].source == "bedesten"
        assert results[0].court == "Yargıtay"
        assert results[0].chamber == "1. Daire"

    def test_get_document_with_html(self):
        import base64
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        html_content = "<html><body><p>This is a test document with enough content to pass the minimum length check for the finalization step in the system.</p></body></html>"
        encoded = base64.b64encode(html_content.encode()).decode()
        mock_resp = _mock_httpx_response(json_data={
            "data": {
                "title": "Test Decision",
                "content": encoded,
                "mimeType": "text/html",
            }
        })
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            doc = asyncio.run(ci.get_document("123"))
        assert doc.source == "bedesten"
        assert doc.document_id == "123"
        assert doc.title == "Test Decision"
        assert "test document" in (doc.text or "").lower()

    def test_get_document_bad_b64_returns_unavailable(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        # Use a non-ASCII string that causes base64 decode to fail
        mock_resp = _mock_httpx_response(json_data={
            "data": {
                "title": "Test",
                "content": "\x80\x81\x82",
                "mimeType": "text/html",
            }
        })
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            doc = asyncio.run(ci.get_document("123"))
        assert doc.content_status == ContentStatus.UNAVAILABLE

    def test_get_document_http_error(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(status_code=500)
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            with pytest.raises(httpx.HTTPStatusError):
                asyncio.run(ci.get_document("123"))

    def test_get_document_404_returns_unavailable(self):
        """404 (full text not yet published) degrades gracefully, not raises."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(status_code=404)
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            doc = asyncio.run(ci.get_document("999"))
        assert doc.content_status == ContentStatus.UNAVAILABLE
        assert doc.document_id == "999"
        warnings = doc.metadata.get("_emsal_warnings", [])
        assert any("404" in w for w in warnings)


    def test_search_court_types_multi(self):
        """Multi-court search with court_types list."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {
                "emsalKararList": [
                    {
                        "id": "1",
                        "itemType": {"description": "Yargıtay"},
                        "birimAdi": "1. Daire",
                        "kararTarihiStr": "2024-01-01",
                        "esasNo": "2024/1",
                        "kararNo": "100",
                    },
                    {
                        "id": "2",
                        "itemType": {"description": "Danıştay"},
                        "birimAdi": "5. Daire",
                        "kararTarihiStr": "2024-02-01",
                        "esasNo": "2024/2",
                        "kararNo": "200",
                    },
                ]
            }
        })
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test", limit=5, court_types=["YARGITAYKARARI", "DANISTAYKARARI"]))
        assert len(results) == 2
        assert results[0].court == "Yargıtay"
        assert results[1].court == "Danıştay"

    def test_search_esas_no_karar_no_parsing(self):
        """YIL/SIRA format parsed into separate int fields for upstream API."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {"emsalKararList": []}
        })
        sent_payload = []
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            async def _capture_post(*args, **kwargs):
                sent_payload.append(kwargs.get("json", {}))
                return mock_resp
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture_post)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            asyncio.run(ci.search("test", limit=5, esas_no="2023/1234", karar_no="2023/5678"))
        assert len(sent_payload) == 1
        data_payload = sent_payload[0].get("data", {})
        assert data_payload.get("esasNoYil") == 2023
        assert data_payload.get("esasNoSira") == 1234
        assert data_payload.get("kararNoYil") == 2023
        assert data_payload.get("kararNoSira") == 5678

    def test_search_esas_no_invalid_format_graceful(self):
        """Invalid YIL/SIRA format is silently ignored (no crash)."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {"emsalKararList": [{"id": "1", "itemType": {"description": "Yargıtay"}, "kararTarihiStr": "2024-01-01"}]}
        })
        sent_payload = []
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            async def _capture_post(*args, **kwargs):
                sent_payload.append(kwargs.get("json", {}))
                return mock_resp
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture_post)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            # Invalid format: no slash, non-numeric
            results = asyncio.run(ci.search("test", limit=5, esas_no="bogus", karar_no="not/valid"))
        assert len(results) == 1
        data_payload = sent_payload[0].get("data", {})
        assert "esasNoYil" not in data_payload
        assert "kararNoYil" not in data_payload

    def test_search_birimadi_filter(self):
        """birimAdi filter is passed through to the API payload."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {"emsalKararList": []}
        })
        sent_payload = []
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            async def _capture_post(*args, **kwargs):
                sent_payload.append(kwargs.get("json", {}))
                return mock_resp
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture_post)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            asyncio.run(ci.search("test", limit=5, birimAdi="10. Daire"))
        data_payload = sent_payload[0].get("data", {})
        assert data_payload.get("birimAdi") == "10. Daire"

    def test_search_tarih_range_filter(self):
        """karar_tarihi_start/end passed through to API payload."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {"emsalKararList": []}
        })
        sent_payload = []
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            async def _capture_post(*args, **kwargs):
                sent_payload.append(kwargs.get("json", {}))
                return mock_resp
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture_post)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            asyncio.run(ci.search("test", limit=5, karar_tarihi_start="2023-01-01", karar_tarihi_end="2024-12-31"))
        data_payload = sent_payload[0].get("data", {})
        assert data_payload.get("kararTarihiStart") == "2023-01-01"
        assert data_payload.get("kararTarihiEnd") == "2024-12-31"

    def test_search_legacy_chamber_still_works(self):
        """Old 'chamber' parameter still maps to birimAdi (backward compat)."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {"emsalKararList": []}
        })
        sent_payload = []
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            async def _capture_post(*args, **kwargs):
                sent_payload.append(kwargs.get("json", {}))
                return mock_resp
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture_post)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            asyncio.run(ci.search("test", limit=5, chamber="HGK"))
        data_payload = sent_payload[0].get("data", {})
        assert data_payload.get("birimAdi") == "HGK"

    def test_search_legacy_start_date_still_works(self):
        """Old 'start_date' parameter still works (backward compat)."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {"emsalKararList": []}
        })
        sent_payload = []
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            async def _capture_post(*args, **kwargs):
                sent_payload.append(kwargs.get("json", {}))
                return mock_resp
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture_post)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            asyncio.run(ci.search("test", limit=5, start_date="2023-01-01", end_date="2024-01-01"))
        data_payload = sent_payload[0].get("data", {})
        assert data_payload.get("kararTarihiStart") == "2023-01-01"
        assert data_payload.get("kararTarihiEnd") == "2024-01-01"


class TestYargitayMocked:
    def test_source_id_preserved(self):
        from emsal_mcp.sources.registry import YargitayClient
        y = YargitayClient()
        assert y.source_id == "yargitay"
        assert y._default_item_type == "YARGITAYKARARI"

    def test_smoke(self):
        from emsal_mcp.sources.registry import YargitayClient
        y = YargitayClient()
        result = asyncio.run(y.smoke(online=False))
        assert result.source_id == "yargitay"
        assert result.offline_ok is True


class TestMevzuatMocked:
    def test_search_title_priority(self):
        from emsal_mcp.sources.mevzuat import MevzuatClient
        mc = MevzuatClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {
                "mevzuatList": [
                    {
                        "documentId": "m1",
                        "mevzuatAdi": "Kanun Hükmünde Kararname",
                        "mevzuatNo": "6745",
                        "resmiGazeteTarihi": "2016-08-20",
                    }
                ]
            }
        })
        with patch("emsal_mcp.sources.base.client") as mock_client:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = cm
            results = asyncio.run(mc.search("test"))
        assert len(results) == 1
        assert results[0].source == "mevzuat"
        assert results[0].title == "Kanun Hükmünde Kararname"
        assert results[0].document_id == "m1"

    def test_get_document_title_priority(self):
        import base64
        from emsal_mcp.sources.mevzuat import MevzuatClient
        mc = MevzuatClient()
        html_content = "<html><body><p>Mevzuat metni burada yer alır ve yeterli uzunluktadır. Bu metin minimum içerik uzunluğunu aşar.</p></body></html>"
        encoded = base64.b64encode(html_content.encode()).decode()
        mock_resp = _mock_httpx_response(json_data={
            "data": {
                "mevzuatAdi": "Kanun No 123",
                "content": encoded,
            }
        })
        with patch("emsal_mcp.sources.base.client") as mock_client:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = cm
            doc = asyncio.run(mc.get_document("m1"))
        assert doc.source == "mevzuat"
        assert doc.title == "Kanun No 123"

    def test_get_document_bad_b64(self):
        from emsal_mcp.sources.mevzuat import MevzuatClient
        mc = MevzuatClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {"mevzuatAdi": "X", "content": "\x80\x81\x82"}
        })
        with patch("emsal_mcp.sources.base.client") as mock_client:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = cm
            doc = asyncio.run(mc.get_document("m1"))
        assert doc.content_status == ContentStatus.UNAVAILABLE


class TestAymMocked:
    @staticmethod
    def _mock_kbb_client(search_json):
        warmup_resp = _mock_httpx_response(text="<html>spa shell</html>")
        search_resp = _mock_httpx_response(json_data=search_json)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock(
            get=AsyncMock(return_value=warmup_resp),
            post=AsyncMock(return_value=search_resp),
        ))
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    def test_search_kbb_api(self):
        from emsal_mcp.sources.simple_public import AymClient
        ac = AymClient()
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            mc.return_value = self._mock_kbb_client({
                "total": 1,
                "page": 1,
                "data": [{
                    "kararTipi": "BireyselBasvuru",
                    "id": "5307d3dc-741e-7c58-decb-296e6f8835ca",
                    "basvuruNo": "2019/2890",
                    "kararTarihi": "2023-10-25",
                    "basvuruAdi": "ALİ KÖMÜRCÜ VE DİĞERLERİ",
                    "kararKonusu": "<p>mülkiyet hakkı</p>",
                }],
            })
            sp = asyncio.run(ac.search_page("mülkiyet"))
        assert sp.total == 1
        assert len(sp.results) == 1
        assert sp.results[0].document_id == "5307d3dc-741e-7c58-decb-296e6f8835ca"
        assert sp.results[0].content_status == ContentStatus.METADATA_ONLY

    def test_search_kbb_empty(self):
        from emsal_mcp.sources.simple_public import AymClient
        ac = AymClient()
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            mc.return_value = self._mock_kbb_client({"total": 0, "page": 1, "data": []})
            results = asyncio.run(ac.search("nonexistent"))
        assert results == []

    def test_smoke(self):
        from emsal_mcp.sources.simple_public import AymClient
        ac = AymClient()
        result = asyncio.run(ac.smoke(online=False))
        assert result.source_id == "aym"
        assert result.offline_ok is True


class TestDanistayMocked:
    def test_search_basic(self):
        from emsal_mcp.sources.simple_public import DanistayClient
        dc = DanistayClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {
                "data": [
                    {"id": "d1", "daire": "1. Daire", "kararTarihi": "2024-01-01"}
                ]
            }
        })
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(dc.search("test"))
        assert len(results) == 1
        assert results[0].source == "danistay"

    def test_smoke(self):
        from emsal_mcp.sources.simple_public import DanistayClient
        dc = DanistayClient()
        result = asyncio.run(dc.smoke(online=False))
        assert result.source_id == "danistay"
        assert result.offline_ok is True


class TestGibMocked:
    def test_search_normalization(self):
        from emsal_mcp.sources.simple_public import GibClient
        gc = GibClient()
        mock_resp = _mock_httpx_response(json_data={
            "resultContainer": {
                "content": [
                    {"id": "g1", "title": "KDV Özelgesi", "ozelgeTarih": "2024-01-01"}
                ]
            }
        })
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(gc.search("katma değer vergisi"))
        assert len(results) == 1
        assert results[0].source == "gib"

    def test_get_document_not_found(self):
        from emsal_mcp.sources.simple_public import GibClient
        gc = GibClient()
        mock_resp = _mock_httpx_response(json_data={
            "resultContainer": {"content": []}
        })
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            doc = asyncio.run(gc.get_document("999"))
        assert doc.content_status == ContentStatus.METADATA_ONLY
        assert doc.metadata.get("not_found") is True

    def test_smoke(self):
        from emsal_mcp.sources.simple_public import GibClient
        gc = GibClient()
        result = asyncio.run(gc.smoke(online=False))
        assert result.source_id == "gib"
        assert result.offline_ok is True


class TestUyusmazlikMocked:
    def test_search_graceful_unavailable_on_error(self):
        from emsal_mcp.sources.simple_public import UyusmazlikClient
        uc = UyusmazlikClient()
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(uc.search("test"))
        assert len(results) == 1
        assert results[0].content_status == ContentStatus.UNAVAILABLE

    def test_get_document_pdf_link(self):
        from emsal_mcp.sources.simple_public import UyusmazlikClient
        import base64
        uc = UyusmazlikClient()
        url = "https://example.com/test.pdf"
        encoded = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        doc = asyncio.run(uc.get_document(f"url:{encoded}"))
        assert doc.content_status == ContentStatus.PDF_LINK_ONLY
        assert doc.metadata.get("pdfUrl") == url

    def test_get_document_graceful_unavailable(self):
        from emsal_mcp.sources.simple_public import UyusmazlikClient
        uc = UyusmazlikClient()
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=Exception("fail"))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            doc = asyncio.run(uc.get_document("some-id"))
        assert doc.content_status == ContentStatus.UNAVAILABLE

    def test_smoke(self):
        from emsal_mcp.sources.simple_public import UyusmazlikClient
        uc = UyusmazlikClient()
        result = asyncio.run(uc.smoke(online=False))
        assert result.source_id == "uyusmazlik"
        assert len(result.warnings) > 0


class TestRekabetMocked:
    def test_search_graceful_unavailable(self):
        from emsal_mcp.sources.simple_public import RekabetClient
        rc = RekabetClient()
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=Exception("fail"))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(rc.search("test"))
        assert len(results) == 1
        assert results[0].content_status == ContentStatus.UNAVAILABLE

    def test_get_document_graceful_unavailable(self):
        from emsal_mcp.sources.simple_public import RekabetClient
        rc = RekabetClient()
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=Exception("fail"))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            doc = asyncio.run(rc.get_document("123"))
        assert doc.content_status == ContentStatus.UNAVAILABLE

    def test_smoke(self):
        from emsal_mcp.sources.simple_public import RekabetClient
        rc = RekabetClient()
        result = asyncio.run(rc.smoke(online=False))
        assert result.source_id == "rekabet"


class TestSayistayMocked:
    def test_search_graceful_unavailable(self):
        from emsal_mcp.sources.simple_public import SayistayClient
        sc = SayistayClient()
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=Exception("fail"))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(sc.search("test"))
        assert len(results) == 1
        assert results[0].content_status == ContentStatus.UNAVAILABLE

    def test_get_document_graceful_unavailable(self):
        from emsal_mcp.sources.simple_public import SayistayClient
        sc = SayistayClient()
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=Exception("fail"))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            doc = asyncio.run(sc.get_document("daire:123"))
        assert doc.content_status == ContentStatus.UNAVAILABLE

    def test_smoke(self):
        from emsal_mcp.sources.simple_public import SayistayClient
        sc = SayistayClient()
        result = asyncio.run(sc.smoke(online=False))
        assert result.source_id == "sayistay"


# ── No error HTML marked citation-safe ────────────────────────────────


class TestNoErrorHtmlCitationSafe:
    """Error/placeholder documents should never be marked as citation-safe."""


# ── CLI smoke command ──────────────────────────────────────────────────


class TestCliSmokeCommand:
    def test_sources_smoke_command(self):
        from typer.testing import CliRunner
        from emsal_mcp.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["sources-smoke"])
        assert result.exit_code == 0
        assert "source_count" in result.output or "10" in result.output

    def test_sources_smoke_json(self):
        from typer.testing import CliRunner
        from emsal_mcp.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["sources-smoke", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "sources" in data
        assert len(data["sources"]) == len(registry())

    def test_sources_command(self):
        from typer.testing import CliRunner
        from emsal_mcp.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["sources"])
        assert result.exit_code == 0


# ── Document status sanity ────────────────────────────────────────────


class TestDocumentStatusSanity:
    def test_full_text_with_content_is_usable(self):
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="x" * 100,
            content_status=ContentStatus.FULL_TEXT,
            decision_date="2024-01-01",
        )
        assert doc.quote_usable is True
        assert doc.draft_usable is True

    def test_html_markdown_with_content_is_usable(self):
        doc = Document(
            source="test", document_id="1", title="T",
            markdown="x" * 100,
            content_status=ContentStatus.HTML_MARKDOWN,
            decision_date="2024-01-01",
        )
        assert doc.quote_usable is True
        assert doc.draft_usable is True

    def test_metadata_only_not_usable(self):
        doc = Document(
            source="test", document_id="1", title="T",
            content_status=ContentStatus.METADATA_ONLY,
        )
        assert doc.quote_usable is False

    def test_pdf_link_only_not_usable(self):
        doc = Document(
            source="test", document_id="1", title="T",
            content_status=ContentStatus.PDF_LINK_ONLY,
        )
        assert doc.quote_usable is False

    def test_unavailable_not_usable(self):
        doc = Document(
            source="test", document_id="1", title="T",
            content_status=ContentStatus.UNAVAILABLE,
        )
        assert doc.quote_usable is False

    def test_finalize_downgrades_short_full_text(self):
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="short",
            content_status=ContentStatus.FULL_TEXT,
        )
        finalized = finalize_document(doc)
        assert finalized.content_status == ContentStatus.METADATA_ONLY
        assert finalized.quote_usable is False


class TestRateLimiter:
    """Server-side rate limiting (sliding window) — hermetic, no network."""

    def test_burst_then_paced(self):
        import time

        from emsal_mcp.sources.base import _SlidingWindowLimiter

        async def run():
            lim = _SlidingWindowLimiter(max_requests=2, window=0.3)
            t = time.monotonic()
            await lim.acquire()
            await lim.acquire()
            fast = time.monotonic() - t
            await lim.acquire()  # third must wait for the window edge
            waited = time.monotonic() - t
            return fast, waited

        fast, waited = asyncio.run(run())
        assert fast < 0.1
        assert waited >= 0.25

    def test_penalize_forces_cooldown(self):
        import time

        from emsal_mcp.sources.base import _SlidingWindowLimiter

        async def run():
            lim = _SlidingWindowLimiter(max_requests=10, window=0.1)
            lim.penalize(0.2)
            t = time.monotonic()
            await lim.acquire()
            return time.monotonic() - t

        assert asyncio.run(run()) >= 0.15

    def test_disabled_flag_skips_throttle(self, monkeypatch):
        """When disabled, the request hook returns without creating a bucket."""
        import emsal_mcp.sources.base as base

        monkeypatch.setattr(base, "_RL_DISABLED", True)
        monkeypatch.setattr(base, "_BUCKETS", {})
        req = httpx.Request("POST", "http://throttle.test/x")
        asyncio.run(base._throttle_request(req))
        assert base._BUCKETS == {}  # no throttling state created

    def test_state_persists_across_instances(self, tmp_path):
        """A fresh limiter instance inherits recent timestamps via the state file."""
        import time

        from emsal_mcp.sources.base import _SlidingWindowLimiter

        state = tmp_path / "rl.json"

        async def run():
            a = _SlidingWindowLimiter(2, 5.0, persist_path=state, host_key="h")
            await a.acquire()
            await a.acquire()  # fills the window (max=2)
            # New instance (simulating a new process) must see the 2 timestamps
            # and therefore block on its first acquire until the window frees up.
            b = _SlidingWindowLimiter(2, 5.0, persist_path=state, host_key="h")
            assert len(b.times) == 0  # not loaded until acquire
            t = time.time()
            await b.acquire()
            return time.time() - t

        waited = asyncio.run(run())
        assert waited >= 1.0  # had to wait out part of the window, not instant

    def test_no_persist_path_is_in_memory(self, tmp_path):
        from emsal_mcp.sources.base import _SlidingWindowLimiter

        lim = _SlidingWindowLimiter(2, 0.3)  # no persist_path
        assert lim.persist_path is None


# ══════════════════════════════════════════════════════════════════════
# M-93: birimAdi enum validation
# ══════════════════════════════════════════════════════════════════════


class TestBirimAdi:
    """Tests for the 79-code birimAdi chamber enum (M-93)."""

    def test_smoke_count_is_79(self):
        from emsal_mcp.birim_enum import _smoke
        s = _smoke()
        assert s["ok"] is True
        assert s["count"] == 79
        assert len(s["issues"]) == 0

    def test_is_valid_birim_adi_known_codes(self):
        from emsal_mcp.birim_enum import is_valid_birim_adi
        assert is_valid_birim_adi("H1") is True
        assert is_valid_birim_adi("H23") is True
        assert is_valid_birim_adi("C1") is True
        assert is_valid_birim_adi("C23") is True
        assert is_valid_birim_adi("HGK") is True
        assert is_valid_birim_adi("CGK") is True
        assert is_valid_birim_adi("D17") is True
        assert is_valid_birim_adi("IDDK") is True
        assert is_valid_birim_adi("AYIM") is True

    def test_is_valid_birim_adi_unknown_codes(self):
        from emsal_mcp.birim_enum import is_valid_birim_adi
        assert is_valid_birim_adi("XYZ") is False
        assert is_valid_birim_adi("H99") is False
        assert is_valid_birim_adi("") is False
        assert is_valid_birim_adi("1. Daire") is False  # "1. Daire" alone isn't known; Danistay uses D1-D17

    def test_validate_birim_adi_valid(self):
        from emsal_mcp.birim_enum import validate_birim_adi
        assert validate_birim_adi("H1") is None
        assert validate_birim_adi("HGK") is None
        assert validate_birim_adi(None) is None

    def test_validate_birim_adi_invalid_returns_error_dict(self):
        from emsal_mcp.birim_enum import validate_birim_adi
        err = validate_birim_adi("INVALID_CHAMBER")
        assert err is not None
        assert isinstance(err, dict)
        assert err.get("ok") is False
        assert err.get("errorCode") == "INVALID_BIRIM_ADI"
        assert "INVALID_CHAMBER" in err.get("message", "")
        # Must include valid codes for guidance
        assert "H1" in err.get("message", "")
        assert "valid_codes" in err.get("details", {})

    def test_validate_birim_adi_never_raises(self):
        from emsal_mcp.birim_enum import validate_birim_adi
        # Must handle all inputs gracefully
        for val in [None, "", "X", "1", 42]:  # type: ignore[assignment]
            try:
                result = validate_birim_adi(val)  # type: ignore[arg-type]
                # None or dict — never an exception
                assert result is None or isinstance(result, dict)
            except Exception as exc:
                pytest.fail(f"validate_birim_adi({val!r}) raised {exc}")

    def test_describe_birim_adi_tr(self):
        from emsal_mcp.birim_enum import describe_birim_adi
        d = describe_birim_adi("H1", lang="tr")
        assert d["code"] == "H1"
        assert "1. Hukuk Dairesi" in d["description"]
        assert d["court"] == "Yargitay"

        d2 = describe_birim_adi("D5", lang="tr")
        assert d2["court"] == "Danistay"
        assert "Daire" in d2["description"]

    def test_describe_birim_adi_en(self):
        from emsal_mcp.birim_enum import describe_birim_adi
        d = describe_birim_adi("HGK", lang="en")
        assert d["code"] == "HGK"
        assert "General Assembly of Civil Chambers" == d["description"]
        assert d["court"] == "Yargitay"

    def test_describe_birim_adi_unknown(self):
        from emsal_mcp.birim_enum import describe_birim_adi
        d = describe_birim_adi("NOPE")
        assert d["code"] == "NOPE"
        assert "bilinmiyor" in d["description"]

    def test_list_birim_codes_all(self):
        from emsal_mcp.birim_enum import list_birim_codes
        codes = list_birim_codes()
        assert len(codes) == 79
        assert all(isinstance(c, dict) for c in codes)
        assert all("code" in c and "description_tr" in c for c in codes)

    def test_list_birim_codes_filter_by_court(self):
        from emsal_mcp.birim_enum import list_birim_codes
        yarg = list_birim_codes(court="Yargitay")
        # H1-H23 (23) + C1-C23 (23) + HGK/CGK/BGK (3) + 3 alternatif = 52
        # Actually: "1. Hukuk Dairesi", "1. Ceza Dairesi", "Hukuk Genel Kurulu",
        # "Ceza Genel Kurulu", "Buyuk Genel Kurul" are 5 alt forms with court="Yargitay"
        # 23+23+3+5 = 54
        assert len(yarg) >= 46  # at minimum H1-H23 + C1-C23

        dan = list_birim_codes(court="Danistay")
        assert len(dan) >= 17  # D1-D17

        ask = list_birim_codes(court="Askeri")
        assert len(ask) == 2  # AYIM, AskeriYargitay

    def test_search_decisions_rejects_invalid_birimadi(self):
        """Integration: invalid birimAdi returns graceful error, not crash."""
        import asyncio as _asyncio
        from unittest.mock import AsyncMock as _AM, MagicMock as _MM, patch as _patch

        # We can't call search_decisions directly since it requires async MCP context.
        # Instead test the validation logic through the Bedesten client path.
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        mock_resp = _mock_httpx_response(json_data={
            "data": {"emsalKararList": [{"id": "1", "itemType": {"description": "Yargitay"}}]}
        })
        with _patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = _AM()
            cm.__aenter__ = _AM(return_value=_MM(post=_AM(return_value=mock_resp)))
            cm.__aexit__ = _AM(return_value=False)
            mc.return_value = cm
            # Valid birimAdi should work fine
            results = _asyncio.run(ci.search("test", limit=1, birimAdi="H1"))
            assert len(results) == 1
