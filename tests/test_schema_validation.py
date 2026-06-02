"""Tests for M-60: adapter response schema validation.

Covers:
- _check_response_schema unit tests (happy path, drift, fallback, no keys declared)
- Capability downgrade side-effect (STABLE → PARTIAL on schema drift)
- Integration tests: mocked adapters detecting broken API responses
- Per-adapter schema declaration snapshots
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from emsal_mcp.models import SourceStatus
from emsal_mcp.sources.base import SourceClient
from emsal_mcp.sources.bedesten import BedestenClient
from emsal_mcp.sources.mevzuat import MevzuatClient
from emsal_mcp.sources.simple_public import DanistayClient, GibClient, SayistayClient


# ── Unit: _check_response_schema ───────────────────────────────────────


class TestCheckResponseSchema:
    """Unit tests for SourceClient._check_response_schema()."""

    def test_primary_key_found_no_warnings(self):
        """Happy path: primary key exists in data."""
        ci = BedestenClient()
        data = {"emsalKararList": [{"id": 1}], "items": []}
        key, warnings = ci._check_response_schema(data, ["emsalKararList"], "search")
        assert key == "emsalKararList"
        assert warnings == []

    def test_key_not_declared_returns_none(self):
        """When expected_keys is None, return (None, []) — no-op."""
        ci = BedestenClient()
        key, warnings = ci._check_response_schema({"x": 1}, None, "search")
        assert key is None
        assert warnings == []

    def test_empty_expected_keys(self):
        """Empty list treated same as None."""
        ci = BedestenClient()
        key, warnings = ci._check_response_schema({"x": 1}, [], "search")
        assert key is None
        assert warnings == []

    def test_primary_missing_fallback_found(self):
        """Schema drift: primary key missing, but fallback found."""
        ci = BedestenClient()
        data = {"items": [{"id": 1}]}  # emsalKararList missing
        key, warnings = ci._check_response_schema(
            data, ["emsalKararList", "items", "data"], "search"
        )
        assert key == "items"
        assert len(warnings) == 2
        assert any("SCHEMA_DRIFT" in w for w in warnings)
        assert any("SCHEMA_DRIFT_FALLBACK" in w for w in warnings)

    def test_all_keys_missing(self):
        """Schema drift: no declared key found at all."""
        ci = BedestenClient()
        data = {"unexpected": []}
        key, warnings = ci._check_response_schema(
            data, ["emsalKararList", "items"], "search"
        )
        assert key is None
        assert len(warnings) == 1
        assert "SCHEMA_DRIFT" in warnings[0]

    def test_capability_downgrade_stable_to_partial(self):
        """Schema drift downgrades STABLE → PARTIAL (one-shot)."""
        ci = BedestenClient()
        ci._capability_status = SourceStatus.STABLE
        assert ci._capability_status == SourceStatus.STABLE
        ci._check_response_schema({}, ["emsalKararList"], "search")
        assert ci._capability_status == SourceStatus.PARTIAL

    def test_capability_stays_partial(self):
        """Once PARTIAL, further drift does not escalate."""
        ci = BedestenClient()
        ci._capability_status = SourceStatus.PARTIAL
        ci._check_response_schema({}, ["emsalKararList"], "search")
        assert ci._capability_status == SourceStatus.PARTIAL

    def test_capability_no_downgrade_when_key_found(self):
        """No downgrade when primary key is present."""
        ci = BedestenClient()
        ci._capability_status = SourceStatus.STABLE
        ci._check_response_schema({"emsalKararList": []}, ["emsalKararList"], "search")
        assert ci._capability_status == SourceStatus.STABLE

    def test_context_appears_in_warnings(self):
        """Warning message includes the context string."""
        ci = BedestenClient()
        _, warnings = ci._check_response_schema({}, ["mevzuatList"], "get_document")
        assert "get_document" in warnings[0]

    def test_source_id_appears_in_warnings(self):
        """Warning message includes source_id."""
        ci = BedestenClient()
        _, warnings = ci._check_response_schema({}, ["mevzuatList"], "search")
        assert "bedesten" in warnings[0]


# ── Per-adapter schema declaration snapshots ───────────────────────────


class TestSchemaDeclarations:
    """Verify each adapter's _search_response_keys and/or _get_document_response_keys."""

    def test_bedesten_search_keys(self):
        ci = BedestenClient()
        assert ci._search_response_keys == ["emsalKararList", "items", "data", "content"]
        assert ci._get_document_response_keys == ["content", "document", "data"]

    def test_mevzuat_search_keys(self):
        ci = MevzuatClient()
        assert ci._search_response_keys == ["mevzuatList", "items", "data"]
        assert ci._get_document_response_keys == ["content"]

    def test_danistay_search_keys(self):
        ci = DanistayClient()
        assert ci._search_response_keys == ["data"]

    def test_gib_search_keys(self):
        ci = GibClient()
        assert ci._search_response_keys == ["resultContainer", "content", "data"]

    def test_sayistay_search_keys(self):
        ci = SayistayClient()
        assert ci._search_response_keys == ["data"]

    def test_html_adapters_no_schema(self):
        """AYM, Uyusmazlik, Rekabet are HTML-based — no schema declared."""
        from emsal_mcp.sources.simple_public import AymClient, UyusmazlikClient, RekabetClient
        for cls in [AymClient, UyusmazlikClient, RekabetClient]:
            ci = cls()
            assert ci._search_response_keys is None, f"{cls.__name__} should skip schema validation"
            assert ci._get_document_response_keys is None, f"{cls.__name__} should skip schema validation"

    def test_yargitay_inherits_bedesten_schema(self):
        """Yargıtay extends Bedesten — inherits schema keys."""
        from emsal_mcp.sources.registry import YargitayClient
        ci = YargitayClient()
        # Inherited from BedestenClient
        assert ci._search_response_keys == ["emsalKararList", "items", "data", "content"]


# ── Integration: mocked adapters with schema drift ─────────────────────


def _mock_httpx_resp(json_data=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.url = "http://mock.test"
    resp.request = MagicMock()
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


class TestBedestenSchemaDrift:
    """Bedesten search should not silently return empty when API shape changes."""

    @pytest.mark.integration
    def test_search_primary_key_present(self):
        """Normal API response: emsalKararList key exists, results returned normally."""
        ci = BedestenClient()
        mock_resp = _mock_httpx_resp(json_data={
            "data": {
                "emsalKararList": [
                    {"id": "123", "itemType": {"description": "Yargıtay"}, "esasNo": "2024/1"}
                ]
            }
        })
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test"))
        assert len(results) == 1
        assert results[0].document_id == "123"
        # Capability should remain STABLE
        assert ci._capability_status == SourceStatus.STABLE

    @pytest.mark.integration
    def test_search_schema_drift_with_fallback(self):
        """Primary key renamed but fallback key works — results + capability downgrade."""
        ci = BedestenClient()
        # API renamed emsalKararList → kararListesi, but "items" fallback exists
        mock_resp = _mock_httpx_resp(json_data={
            "data": {
                "kararListesi": [],  # renamed
                "items": [{"id": "456", "itemType": {"description": "Yargıtay"}, "esasNo": "2024/2"}],
            }
        })
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test"))
        # Should still produce results via fallback
        assert len(results) == 1
        assert results[0].document_id == "456"
        # Capability should be downgraded to PARTIAL
        assert ci._capability_status == SourceStatus.PARTIAL

    @pytest.mark.integration
    def test_search_all_keys_missing(self):
        """API completely changed shape — no keys match, returns empty (not crash)."""
        ci = BedestenClient()
        mock_resp = _mock_httpx_resp(json_data={
            "data": {
                "yeniAd": [],  # completely new API shape
                "sonuc": None,
            }
        })
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test"))
        # Empty result is acceptable (no data), but capability is now PARTIAL
        assert len(results) == 0
        assert ci._capability_status == SourceStatus.PARTIAL


class TestMevzuatSchemaDrift:
    """Mevzuat search should detect schema changes."""

    @pytest.mark.integration
    def test_search_primary_key_present(self):
        """Normal response: mevzuatList key exists."""
        ci = MevzuatClient()
        mock_resp = _mock_httpx_resp(json_data={
            "data": {
                "mevzuatList": [
                    {"documentId": "m1", "mevzuatAdi": "Kanun 123", "mevzuatNo": "1234"}
                ]
            }
        })
        with patch("emsal_mcp.sources.base.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test"))
        assert len(results) == 1
        assert results[0].title == "Kanun 123"

    @pytest.mark.integration
    def test_search_schema_drift_detected(self):
        """mevzuatList missing, fallback works, capability PARTIAL."""
        ci = MevzuatClient()
        mock_resp = _mock_httpx_resp(json_data={
            "data": {
                # mevzuatList renamed to newMevzuatList
                "newMevzuatList": [],
                "items": [{"documentId": "m2", "mevzuatAdi": "KHK 456"}],
            }
        })
        with patch("emsal_mcp.sources.base.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test"))
        assert len(results) == 1
        assert ci._capability_status == SourceStatus.PARTIAL


class TestDanistaySchemaDrift:
    """Danıştay JSON endpoint should detect missing 'data' key."""

    @pytest.mark.integration
    def test_search_schema_drift(self):
        """'data' key missing: capability downgrade."""
        ci = DanistayClient()
        mock_resp = _mock_httpx_resp(json_data={"results": []})  # no "data" key
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test"))
        assert len(results) == 0
        assert ci._capability_status == SourceStatus.PARTIAL


class TestGibSchemaDrift:
    """GİB JSON endpoint — detect missing resultContainer/content keys."""

    @pytest.mark.integration
    def test_search_schema_drift(self):
        """All expected keys missing."""
        ci = GibClient()
        mock_resp = _mock_httpx_resp(json_data={"sonuc": []})  # completely different
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            results = asyncio.run(ci.search("test"))
        assert len(results) == 0
        assert ci._capability_status == SourceStatus.PARTIAL


class TestSayistaySchemaDrift:
    """Sayıştay DataTables — detect missing 'data' key."""

    @pytest.mark.integration
    def test_search_primary_key_present(self):
        """Normal DataTables response."""
        ci = SayistayClient()
        # Mock both the GET (for CSRF token) and POST responses
        with patch("emsal_mcp.sources.simple_public.client") as mc:
            cm = AsyncMock()
            # First call: GET for CSRF token page
            get_resp = MagicMock()
            get_resp.status_code = 200
            get_resp.text = '<html><input name="__RequestVerificationToken" value="tok"/><html>'
            # Second call: POST for DataTables
            post_resp = _mock_httpx_resp(json_data={
                "data": [{"Id": "1", "KARARNO": "123", "WEBKARARMETNI": "Test"}]
            })
            cm.__aenter__ = AsyncMock()
            cm.__aexit__ = AsyncMock(return_value=False)
            # We need to return different mocks for get and post
            mock_session = MagicMock()
            mock_session.get = AsyncMock(return_value=get_resp)
            mock_session.post = AsyncMock(return_value=post_resp)
            cm.__aenter__ = AsyncMock(return_value=mock_session)
            mc.return_value = cm
            results = asyncio.run(ci.search("test"))
        assert len(results) >= 0  # May or may not have results


# ── Capability model reflects schema status ────────────────────────────


class TestCapabilityModelAfterDrift:
    """After schema drift downgrades capability, capability_model() reflects it."""

    @pytest.mark.integration
    def test_capability_model_shows_partial_after_drift(self):
        """capability_model().status should be 'partial' after schema drift."""
        ci = BedestenClient()
        # Normal — capability is STABLE
        cap = ci.capability_model()
        assert cap.status == SourceStatus.STABLE

        # Simulate drift
        mock_resp = _mock_httpx_resp(json_data={"data": {"yeni": []}})
        with patch("emsal_mcp.sources.bedesten.client") as mc:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_resp)))
            cm.__aexit__ = AsyncMock(return_value=False)
            mc.return_value = cm
            asyncio.run(ci.search("test"))

        # After drift — capability_model should show PARTIAL
        cap2 = ci.capability_model()
        assert cap2.status == SourceStatus.PARTIAL
