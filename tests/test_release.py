"""Tests for release module — smoke, dashboard, history, command center, version bump."""
from __future__ import annotations

import json
from pathlib import Path

from emsal_mcp import __version__
from emsal_mcp.release import (
    archive_release,
    compare_history,
    final_v1_readiness,
    generate_release_summary,
    readiness_dashboard,
    release_command_center,
    release_notes,
    release_smoke,
    version_bump,
    write_history,
)


class TestVersionBump:
    """Tests for version_bump()."""

    def test_patch_bump_default(self):
        result = version_bump()
        assert result["ok"] is True
        assert result["bump_type"] == "patch"
        assert result["current_version"] == __version__
        parts = result["next_version"].split(".")
        assert len(parts) == 3

    def test_major_bump(self):
        result = version_bump(major=True, minor=False, patch=False)
        assert result["ok"] is True
        assert result["bump_type"] == "major"
        current_parts = __version__.split(".")
        next_parts = result["next_version"].split(".")
        assert int(next_parts[0]) == int(current_parts[0]) + 1
        assert next_parts[1] == "0"
        assert next_parts[2] == "0"

    def test_minor_bump(self):
        result = version_bump(minor=True, major=False, patch=False)
        assert result["ok"] is True
        assert result["bump_type"] == "minor"
        current_parts = __version__.split(".")
        next_parts = result["next_version"].split(".")
        assert int(next_parts[1]) == int(current_parts[1]) + 1
        assert next_parts[2] == "0"

    def test_multiple_flags_fails(self):
        result = version_bump(major=True, minor=True)
        assert result["ok"] is False
        assert "error" in result

    def test_all_flags_fails(self):
        result = version_bump(major=True, minor=True, patch=True)
        assert result["ok"] is False

    def test_no_flags_fails(self):
        result = version_bump(major=False, minor=False, patch=False)
        assert result["ok"] is False


class TestReleaseSmoke:
    """Tests for release_smoke()."""

    def test_smoke_runs(self):
        result = release_smoke()
        assert "ok" in result
        assert result["version"] == __version__
        assert "checks" in result
        assert "sources_registered" in result["checks"]
        assert "offline_smoke" in result["checks"]
        assert "cache_integrity" in result["checks"]
        assert "source_smoke" in result["checks"]

    def test_smoke_has_boolean_fields(self):
        result = release_smoke()
        assert isinstance(result["checks"]["source_smoke_ok"], bool)
        assert isinstance(result["checks"]["citation_safety"], bool)
        assert isinstance(result["checks"]["udf"], bool)
        assert isinstance(result["checks"]["mcp_surface"], bool)


class TestReadinessDashboard:
    """Tests for readiness_dashboard()."""

    def test_dashboard_structure(self):
        result = readiness_dashboard()
        assert "ok" in result
        assert result["version"] == __version__
        assert "readiness_score" in result
        assert "release_decision" in result
        assert "smoke" in result
        assert "risks" in result
        assert isinstance(result["risks"], list)

    def test_dashboard_decision_boundaries(self):
        result = readiness_dashboard()
        if result["readiness_score"] >= 80:
            assert result["release_decision"] == "ship"
        else:
            assert result["release_decision"] == "review"


class TestWriteHistory:
    """Tests for write_history()."""

    def test_write_creates_file(self, tmp_path):
        result = write_history(tmp_path)
        assert result["path"]
        path = Path(result["path"])
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == __version__
        assert "sha256" in data
        assert "dashboard" in data

    def test_write_with_custom_dashboard(self, tmp_path):
        custom = {"ok": True, "readiness_score": 95}
        result = write_history(tmp_path, dashboard=custom)
        data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        assert data["dashboard"]["readiness_score"] == 95


class TestCompareHistory:
    """Tests for compare_history()."""

    def test_compare_same_score(self, tmp_path):
        hist1 = write_history(tmp_path / "v1")
        hist2 = write_history(tmp_path / "v2")
        result = compare_history(hist1["path"], hist2["path"])
        assert result["ok"] is True
        assert result["score_delta"] == 0
        assert result["regression"] is False

    def test_compare_regression(self, tmp_path):
        d1 = tmp_path / "high"
        d1.mkdir()
        d2 = tmp_path / "low"
        d2.mkdir()
        rec_high = {"version": __version__, "dashboard": {"readiness_score": 100}}
        rec_low = {"version": __version__, "dashboard": {"readiness_score": 50}}
        p1 = d1 / "history.json"
        p2 = d2 / "history.json"
        p1.write_text(json.dumps(rec_high), encoding="utf-8")
        p2.write_text(json.dumps(rec_low), encoding="utf-8")
        result = compare_history(p1, p2)
        assert result["regression"] is True
        assert result["score_delta"] == -50


class TestReleaseNotes:
    """Tests for release_notes()."""

    def test_notes_is_string(self):
        notes = release_notes()
        assert isinstance(notes, str)
        assert __version__ in notes
        assert "Release Notes" in notes

    def test_notes_has_risks_section(self):
        notes = release_notes()
        assert "Riskler" in notes


class TestArchiveRelease:
    """Tests for archive_release()."""

    def test_archive_creates_files(self, tmp_path):
        result = archive_release(tmp_path)
        assert result["ok"] is True
        assert (tmp_path / "dashboard.json").exists()
        assert (tmp_path / "release-notes.md").exists()
        assert (tmp_path / "archive-manifest.json").exists()

    def test_archive_manifest_content(self, tmp_path):
        archive_release(tmp_path)
        manifest = json.loads((tmp_path / "archive-manifest.json").read_text(encoding="utf-8"))
        assert manifest["version"] == __version__
        assert "dashboard.json" in manifest["files"]


class TestReleaseCommandCenter:
    """Tests for release_command_center()."""

    def test_command_center_structure(self):
        result = release_command_center()
        assert "ok" in result
        assert "overall_readiness" in result
        assert "checks" in result
        assert "warnings" in result
        assert "recommended_actions" in result
        assert result["version"] == __version__

    def test_command_center_has_all_checks(self):
        result = release_command_center()
        checks = result["checks"]
        assert "release_smoke" in checks
        assert "source_capabilities" in checks
        assert "module_imports" in checks
        assert "search_index" in checks
        assert "chambers" in checks
        assert "udf_toolkit" in checks

    def test_command_center_readiness_range(self):
        result = release_command_center()
        assert 0 <= result["overall_readiness"] <= 100

    def test_command_center_with_none_cache(self):
        result = release_command_center(cache=None)
        assert result["ok"] in (True, False)
        assert isinstance(result["checks"], dict)


class TestFinalV1Readiness:
    """Tests for final_v1_readiness()."""

    def test_v1_readiness_structure(self):
        result = final_v1_readiness()
        assert result["ok"] is True
        assert "ready" in result
        assert "criteria" in result
        assert "blocking_issues" in result
        assert "recommendation" in result
        assert "command_center" in result

    def test_v1_criteria_keys(self):
        result = final_v1_readiness()
        criteria = result["criteria"]
        assert "all_modules_importable" in criteria
        assert "has_stable_sources" in criteria
        assert "release_smoke_ok" in criteria
        assert "only_kik_unavailable" in criteria

    def test_v1_recommendation_format(self):
        result = final_v1_readiness()
        rec = result["recommendation"]
        assert isinstance(rec, str)
        assert len(rec) > 0


class TestGenerateReleaseSummary:
    """Tests for generate_release_summary()."""

    def test_summary_structure(self):
        result = generate_release_summary()
        assert result["ok"] is True
        assert result["version"] == __version__
        assert "markdown_summary" in result
        assert "json_summary" in result

    def test_summary_markdown_content(self):
        result = generate_release_summary()
        md = result["markdown_summary"]
        assert __version__ in md
        assert "Modules" in md
        assert "Sources" in md

    def test_summary_json_fields(self):
        result = generate_release_summary()
        js = result["json_summary"]
        assert js["version"] == __version__
        assert "modules" in js
        assert "sources" in js
        assert "readiness" in js


class TestRecommendedActions:
    """Tests for _get_recommended_actions via integration."""

    def test_low_readiness_actions(self):
        from emsal_mcp.release import _get_recommended_actions
        actions = _get_recommended_actions([], 0.3)
        assert any("KRİTİK" in a for a in actions)

    def test_medium_readiness_actions(self):
        from emsal_mcp.release import _get_recommended_actions
        actions = _get_recommended_actions(["warn1"], 0.7)
        assert any("UYARI" in a for a in actions)

    def test_high_readiness_with_warnings(self):
        from emsal_mcp.release import _get_recommended_actions
        actions = _get_recommended_actions(["warn1"], 0.9)
        assert any("BİLGİ" in a for a in actions)

    def test_perfect_readiness_no_warnings(self):
        from emsal_mcp.release import _get_recommended_actions
        actions = _get_recommended_actions([], 1.0)
        assert any("Tüm kontroller başarılı" in a for a in actions)
