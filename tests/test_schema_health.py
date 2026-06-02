"""Tests for M-61: source health monitoring — schema signature persistence.

Covers:
- _schema_signature() computation
- Schema signature persistence (_load_schema_sigs / _save_schema_sigs)
- Smoke output includes schema_health with per-source schema info
- Cross-run signature drift detection
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit]

from emsal_mcp.models import SourceSmokeResult, SourceStatus
from emsal_mcp.sources.base import (
    _load_schema_sigs,
    _save_schema_sigs,
    _schema_sig_path,
    _SCHEMA_SIG_FILENAME,
)
from emsal_mcp.sources.bedesten import BedestenClient
from emsal_mcp.sources.mevzuat import MevzuatClient
from emsal_mcp.sources.registry import smoke_all_sync


# ── Schema signature computation ────────────────────────────────────────


class TestSchemaSignature:
    """Unit tests for SourceClient._schema_signature()."""

    def test_returns_hash_for_declared_keys(self):
        ci = BedestenClient()
        sig = ci._schema_signature()
        assert sig is not None
        assert len(sig) == 16  # hex digest[:16]

    def test_same_keys_produce_same_hash(self):
        """Deterministic: same declared keys → same signature."""
        a = BedestenClient()
        b = BedestenClient()
        assert a._schema_signature() == b._schema_signature()

    def test_different_keys_produce_different_hash(self):
        """Different declared keys → different signature."""
        bedesten = BedestenClient()
        mevzuat = MevzuatClient()
        assert bedesten._schema_signature() != mevzuat._schema_signature()

    def test_returns_none_when_no_keys(self):
        """Adapter with no schema declaration returns None."""
        from emsal_mcp.sources.simple_public import AymClient
        ci = AymClient()
        assert ci._schema_signature() is None

    def test_hash_stable_across_instances(self):
        """Signature should be stable across multiple instances."""
        sigs = [BedestenClient()._schema_signature() for _ in range(5)]
        assert len(set(sigs)) == 1


# ── Schema signature persistence ────────────────────────────────────────


class TestSchemaSigPersistence:
    """Test _load_schema_sigs / _save_schema_sigs functions."""

    def test_load_returns_empty_when_no_file(self, tmp_path):
        """Missing file returns empty dict."""
        with patch("emsal_mcp.sources.base._schema_sig_path", return_value=tmp_path / "nonexistent.json"):
            result = _load_schema_sigs()
            assert result == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        """Save then load should return same data."""
        sig_file = tmp_path / "test_sigs.json"
        sigs = {"bedesten": "abc123", "mevzuat": "def456"}
        with patch("emsal_mcp.sources.base._schema_sig_path", return_value=sig_file):
            _save_schema_sigs(sigs)
            assert sig_file.exists()
            loaded = _load_schema_sigs()
            assert loaded == sigs

    def test_load_handles_corrupt_file(self, tmp_path):
        """Corrupt JSON file returns empty dict."""
        sig_file = tmp_path / "corrupt.json"
        sig_file.write_text("not json {{{")
        with patch("emsal_mcp.sources.base._schema_sig_path", return_value=sig_file):
            result = _load_schema_sigs()
            assert result == {}

    def test_sig_path_is_in_emsal_mcp_dir(self):
        """Path should be under ~/.emsal_mcp/."""
        p = _schema_sig_path()
        assert _SCHEMA_SIG_FILENAME in str(p)
        assert ".emsal_mcp" in str(p)

    def test_save_creates_parent_directory(self, tmp_path):
        """Saving should create parent dir if missing."""
        sig_file = tmp_path / "nested" / "dir" / "sigs.json"
        with patch("emsal_mcp.sources.base._schema_sig_path", return_value=sig_file):
            _save_schema_sigs({"test": "hash1"})
            assert sig_file.exists()
            loaded = _load_schema_sigs()
            assert loaded == {"test": "hash1"}


# ── Smoke output includes schema health ─────────────────────────────────


class TestSmokeSchemaHealth:
    """Verify that smoke() output includes schema_health per source."""

    def test_bedesten_smoke_has_schema_health(self):
        ci = BedestenClient()
        result = asyncio.run(ci.smoke(online=False))
        assert isinstance(result, SourceSmokeResult)
        assert result.schema_health is not None
        sh = result.schema_health
        assert sh["schema_declared"] is True
        assert "emsalKararList" in sh["declared_search_keys"]
        assert "content" in sh["declared_get_document_keys"]
        assert sh["schema_signature"] is not None
        assert "drift_detected" in sh

    def test_mevzuat_smoke_has_schema_health(self):
        ci = MevzuatClient()
        result = asyncio.run(ci.smoke(online=False))
        sh = result.schema_health
        assert sh is not None
        assert "mevzuatList" in sh["declared_search_keys"]
        assert sh["schema_signature"] is not None

    def test_aym_smoke_no_schema_health(self):
        """HTML-based adapter: no schema keys declared → schema_health None."""
        from emsal_mcp.sources.simple_public import AymClient
        ci = AymClient()
        result = asyncio.run(ci.smoke(online=False))
        # AYM has no schema declared — schema_health should be None
        assert result.schema_health is None

    def test_capability_partial_reflected_in_schema_health(self):
        """When capability is PARTIAL (schema drift), schema_health reflects it."""
        ci = BedestenClient()
        ci._capability_status = SourceStatus.PARTIAL
        result = asyncio.run(ci.smoke(online=False))
        assert result.schema_health["drift_detected"] is True


# ── Cross-run signature drift detection ────────────────────────────────


class TestCrossRunSignatureDrift:
    """When schema declaration changes between runs, smoke should warn."""

    def test_first_run_saves_signature(self, tmp_path):
        """First run saves the signature; no warning expected."""
        sig_file = tmp_path / "sig_test.json"
        with patch("emsal_mcp.sources.base._schema_sig_path", return_value=sig_file):
            ci = BedestenClient()
            result = asyncio.run(ci.smoke(online=False))
            # First run: previous_signature should be None
            assert result.schema_health["previous_signature"] is None
            # Should have saved the signature
            saved = _load_schema_sigs()
            assert "bedesten" in saved

    def test_second_run_detects_no_change(self, tmp_path):
        """Second run with same keys: no drift detected, no warning."""
        sig_file = tmp_path / "sig_test.json"
        with patch("emsal_mcp.sources.base._schema_sig_path", return_value=sig_file):
            # First run
            ci1 = BedestenClient()
            asyncio.run(ci1.smoke(online=False))
            # Second run — same keys
            ci2 = BedestenClient()
            result = asyncio.run(ci2.smoke(online=False))
            assert result.schema_health["drift_detected"] is False
            # No warnings about schema change
            schema_warnings = [w for w in result.warnings if "schema" in w.lower()]
            assert len(schema_warnings) == 0

    def test_schema_change_between_runs_detected(self, tmp_path):
        """If signature changes between runs, smoke should warn."""
        sig_file = tmp_path / "sig_test.json"
        with patch("emsal_mcp.sources.base._schema_sig_path", return_value=sig_file):
            # First run
            ci1 = BedestenClient()
            asyncio.run(ci1.smoke(online=False))
            # Second run — keys changed
            ci2 = BedestenClient()
            ci2._search_response_keys = ["yeniKey"]  # simulate schema change
            result = asyncio.run(ci2.smoke(online=False))
            assert result.schema_health["drift_detected"] is True
            assert result.schema_health["drift_detail"] is not None
            assert "Schema declaration changed" in result.schema_health["drift_detail"]


# ── smoke_all_sync includes schema health ──────────────────────────────


class TestSmokeAllSchemaHealth:
    """smoke_all_sync should include schema_health for each source."""

    def test_all_sources_have_schema_health_when_declared(self):
        sources_with_schema = {"bedesten", "yargitay", "mevzuat", "danistay", "gib", "sayistay"}
        results = smoke_all_sync(online=False)
        for r in results:
            if r["source_id"] in sources_with_schema:
                assert r.get("schema_health") is not None, (
                    f"{r['source_id']} should have schema_health"
                )
                sh = r["schema_health"]
                assert "schema_declared" in sh
                assert sh["schema_declared"] is True
