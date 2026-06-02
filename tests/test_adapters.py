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
    get_source,
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

    def test_kik_smoke_search_not_callable(self):
        kik = registry()["kik"]
        result = asyncio.run(kik.smoke(online=False))
        assert result.search_callable is False
        assert result.get_document_callable is True

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
        "gib", "uyusmazlik", "rekabet", "sayistay", "kik",
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
    def test_search_fallback_empty(self):
        from emsal_mcp.sources.simple_public import AymClient
        ac = AymClient()
        mock_resp = _mock_httpx_response(text="<html>No structured results here</html>")
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ac.search("nonexistent"))
        assert len(results) == 1
        assert results[0].content_status == ContentStatus.METADATA_ONLY

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


class TestKikSmoke:
    def test_kik_smoke(self):
        kik = get_source("kik")
        result = asyncio.run(kik.smoke(online=False))
        assert result.source_id == "kik"
        assert result.offline_ok is True
        assert result.search_callable is False
        assert result.get_document_callable is True


# ── No error HTML marked citation-safe ────────────────────────────────


class TestNoErrorHtmlCitationSafe:
    """Error/placeholder documents should never be marked as citation-safe."""

    def test_kik_search_not_usable(self):
        kik = get_source("kik")
        results = asyncio.run(kik.search("test"))
        for r in results:
            assert r.content_status in (ContentStatus.UNAVAILABLE, ContentStatus.METADATA_ONLY)
            assert r.recommended_next_step is not None

    def test_kik_document_not_usable(self):
        kik = get_source("kik")
        doc = asyncio.run(kik.get_document("123"))
        assert doc.quote_usable is False
        assert doc.draft_usable is False


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


# ── KIK graceful contract ─────────────────────────────────────────────


class TestKikGraceful:
    def test_kik_in_capabilities(self):
        caps = capabilities()
        kik = [c for c in caps if c["source_id"] == "kik"]
        assert len(kik) == 1
        assert kik[0]["status"] == "unavailable"
        assert kik[0]["supports_search"] is False

    def test_kik_search_contract(self):
        kik = get_source("kik")
        results = asyncio.run(kik.search("test"))
        assert len(results) == 1
        sr = results[0]
        assert sr.content_status == ContentStatus.UNAVAILABLE
        assert sr.recommended_next_step is not None

    def test_kik_document_contract(self):
        kik = get_source("kik")
        doc = asyncio.run(kik.get_document("test"))
        assert doc.content_status == ContentStatus.METADATA_ONLY
        assert doc.quote_usable is False


# ── KIK optional token activation (M-16) ─────────────────────────────


class TestKikOptionalToken:
    """Tests for the optional token-based KİK activation layer."""

    def test_kik_no_token_unavailable(self, monkeypatch):
        """Without token, KIK is UNAVAILABLE — current default behaviour."""
        monkeypatch.delenv("KIK_API_TOKEN", raising=False)
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        assert client._capability_status.value == "unavailable"
        assert client._supports_search is False
        assert client._token is None

    def test_kik_with_kik_api_token(self, monkeypatch):
        """KIK_API_TOKEN env var activates KIK to EXPERIMENTAL."""
        monkeypatch.setenv("KIK_API_TOKEN", "test-token-kik")
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        assert client._capability_status.value == "experimental"
        assert client._supports_search is True
        assert client._token == "test-token-kik"

    def test_kik_with_ekap_api_token(self, monkeypatch):
        """EKAP_API_TOKEN env var also activates KIK (fallback)."""
        monkeypatch.setenv("EKAP_API_TOKEN", "test-token-ekap")
        monkeypatch.delenv("KIK_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        assert client._capability_status.value == "experimental"
        assert client._supports_search is True
        assert client._token == "test-token-ekap"

    def test_kik_kik_token_preferred_over_ekap(self, monkeypatch):
        """KIK_API_TOKEN takes precedence over EKAP_API_TOKEN."""
        monkeypatch.setenv("KIK_API_TOKEN", "kik-first")
        monkeypatch.setenv("EKAP_API_TOKEN", "ekap-second")
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        assert client._token == "kik-first"

    def test_kik_search_returns_empty_when_no_token(self, monkeypatch):
        """search() returns one UNAVAILABLE placeholder result when no token."""
        monkeypatch.delenv("KIK_API_TOKEN", raising=False)
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        results = asyncio.run(client.search("test query"))
        assert len(results) == 1
        assert results[0].content_status == ContentStatus.UNAVAILABLE

    def test_kik_search_with_token_handles_api_error(self, monkeypatch):
        """With token, search() catches API errors gracefully."""
        monkeypatch.setenv("KIK_API_TOKEN", "test-token")
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        # Mock the HTTP call to raise
        with patch.object(client, "_search_with_token", new_callable=AsyncMock) as mock_search:
            mock_search.side_effect = Exception("Connection refused")
            results = asyncio.run(client.search("test"))
        assert len(results) == 1
        assert results[0].content_status == ContentStatus.UNAVAILABLE
        assert "başarısız" in results[0].summary.lower()

    def test_kik_smoke_no_token(self, monkeypatch):
        """Smoke without token: offline_ok, search not callable."""
        monkeypatch.delenv("KIK_API_TOKEN", raising=False)
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        result = asyncio.run(client.smoke(online=False))
        assert result.offline_ok is True
        assert result.search_callable is False
        assert result.get_document_callable is True

    def test_kik_smoke_with_token_offline(self, monkeypatch):
        """Smoke with token but offline: still offline_ok."""
        monkeypatch.setenv("KIK_API_TOKEN", "test-token")
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        result = asyncio.run(client.smoke(online=False))
        assert result.offline_ok is True
        assert result.search_callable is True

    def test_kik_smoke_online_no_network(self, monkeypatch):
        """Smoke with token + online=True but network fails: online_ok=False."""
        monkeypatch.setenv("KIK_API_TOKEN", "test-token")
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        # Mock httpx.AsyncClient at the httpx module level
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("Server error"))
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_http):
            result = asyncio.run(client.smoke(online=True))
        assert result.offline_ok is True
        assert result.online_ok is False
        assert len(result.warnings) > 0

    def test_kik_capability_model_no_token(self, monkeypatch):
        """Capability model reflects UNAVAILABLE when no token."""
        monkeypatch.delenv("KIK_API_TOKEN", raising=False)
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        cap = client.capability_model()
        assert cap.status.value == "unavailable"
        assert cap.supports_search is False
        assert cap.live_smoke_recommended is False
        assert len(cap.known_limitations) > 0

    def test_kik_capability_model_with_token(self, monkeypatch):
        """Capability model reflects EXPERIMENTAL when token present."""
        monkeypatch.setenv("KIK_API_TOKEN", "test-token")
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        cap = client.capability_model()
        assert cap.status.value == "experimental"
        assert cap.supports_search is True
        assert cap.live_smoke_recommended is True
        assert len(cap.known_limitations) > 0

    def test_kik_get_document_no_token(self, monkeypatch):
        """get_document without token returns metadata-only placeholder."""
        monkeypatch.delenv("KIK_API_TOKEN", raising=False)
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        doc = asyncio.run(client.get_document("123"))
        assert doc.content_status == ContentStatus.METADATA_ONLY
        assert doc.document_id == "123"

    def test_kik_get_document_with_token_error(self, monkeypatch):
        """get_document with token handles API errors gracefully."""
        monkeypatch.setenv("KIK_API_TOKEN", "test-token")
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        client = _KikClient()
        with patch.object(client, "_get_document_with_token", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Timeout")
            doc = asyncio.run(client.get_document("456"))
        assert doc.content_status == ContentStatus.UNAVAILABLE
        assert doc.document_id == "456"

    def test_kik_registry_uses_new_client(self, monkeypatch):
        """Registry returns _KikClient (not old _KikUnavailableClient)."""
        monkeypatch.delenv("KIK_API_TOKEN", raising=False)
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        from emsal_mcp.sources.registry import _KikClient
        kik = get_source("kik")
        assert isinstance(kik, _KikClient)
        assert kik.source_id == "kik"

    def test_kik_known_limitations_vary_by_token(self, monkeypatch):
        """Known limitations differ based on token presence."""
        from emsal_mcp.sources.registry import _KikClient

        monkeypatch.delenv("KIK_API_TOKEN", raising=False)
        monkeypatch.delenv("EKAP_API_TOKEN", raising=False)
        client_no_token = _KikClient()
        lims_no_token = client_no_token._known_limitations

        monkeypatch.setenv("KIK_API_TOKEN", "tok")
        client_with_token = _KikClient()
        lims_with_token = client_with_token._known_limitations

        assert lims_no_token != lims_with_token
        assert any("Token yapılandırılmadı" in lim for lim in lims_no_token)
        assert any("EXPERIMENTAL" in lim for lim in lims_with_token)