"""Tests for release module — final_v1_readiness only (M-103)."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp import __version__
from emsal_mcp.release import final_v1_readiness


class TestFinalV1Readiness:
    """Tests for final_v1_readiness()."""

    def test_v1_readiness_structure(self):
        result = final_v1_readiness()
        assert result["ok"] is True
        assert "ready" in result
        assert "criteria" in result
        assert "blocking_issues" in result
        assert "recommendation" in result
        assert "checks" in result

    def test_v1_criteria_keys(self):
        result = final_v1_readiness()
        criteria = result["criteria"]
        assert "all_modules_importable" in criteria
        assert "has_stable_sources" in criteria
        assert "release_smoke_ok" in criteria
        assert "no_unavailable_sources" in criteria

    def test_v1_recommendation_format(self):
        result = final_v1_readiness()
        rec = result["recommendation"]
        assert isinstance(rec, str)
        assert len(rec) > 0

    def test_v1_version_field(self):
        result = final_v1_readiness()
        assert result["version"] == __version__

    def test_v1_generated_at(self):
        result = final_v1_readiness()
        assert "generated_at" in result

    def test_v1_readiness_json(self):
        """Test --json compatible output."""
        result = final_v1_readiness()
        assert "ok" in result
        assert isinstance(result["ok"], bool)
        assert isinstance(result["ready"], bool)
        assert isinstance(result["criteria"], dict)
        assert isinstance(result["blocking_issues"], list)
