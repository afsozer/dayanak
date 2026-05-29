"""Tests for M-14: Draft Diff & Versioning.

Covers diff_drafts, track_placeholders, get_fill_report, and
save_draft_version.  No live network calls.
"""
from __future__ import annotations

import json
from pathlib import Path

from emsal_mcp.draft_diff import (
    diff_drafts,
    get_fill_report,
    save_draft_version,
    track_placeholders,
)


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------

DRAFT_V1 = """\
# Dilekçe Taslağı

## Başlık

{{DILEKCE_BASLIK}}

## Mahkeme

{{MAHKEME_ADRES}}

## Taraflar

- **Davacı**: {{DAVACI_AD_SOYAD}}

- **Davalı**: {{DALI_AD_SOYAD}}

## Açıklamalar

{{ACIKLAMALAR_BASLIK}}

## Sonuç ve Talep

{{SONUC_VE_TALEP}}

## Ekler

{{EKLER}}

---
> Taslak emsal-mcp v0.8.0 tarafından oluşturulmuştur.
> Bu taslak avukat denetimi gerektirir.
> {{}} içindeki alanlar doğrulanmış bilgilerle doldurulmalıdır.
"""

DRAFT_V2 = """\
# Dilekçe Taslağı

## Başlık

Tazminat Davası Dilekçesi

## Mahkeme

{{MAHKEME_ADRES}}

## Taraflar

- **Davacı**: Ahmet Yılmaz

- **Davalı**: {{DALI_AD_SOYAD}}

## Açıklamalar

İş sözleşmesinin haksız feshi nedeniyle tazminat talebi.

## Sonuç ve Talep

{{SONUC_VE_TALEP}}

## Ekler

{{EKLER}}

---
> Taslak emsal-mcp v0.8.0 tarafından oluşturulmuştur.
> Bu taslak avukat denetimi gerektirir.
> {{}} içindeki alanlar doğrulanmış bilgilerle doldurulmalıdır.
"""

DRAFT_EMPTY = ""


def _create_draft_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Create v1 and v2 draft files in tmp_path."""
    draft_a = tmp_path / "draft_v1.md"
    draft_b = tmp_path / "draft_v2.md"
    draft_a.write_text(DRAFT_V1, encoding="utf-8")
    draft_b.write_text(DRAFT_V2, encoding="utf-8")
    return draft_a, draft_b


# ===========================================================================
# Tests: diff_drafts
# ===========================================================================


def test_diff_drafts_detects_added_lines(tmp_path: Path):
    """New content in v2 should show up as added lines in the diff."""
    draft_a, draft_b = _create_draft_pair(tmp_path)
    result = diff_drafts(draft_a, draft_b)

    assert result["ok"] is True
    assert len(result["diff_lines"]) > 0
    assert "Tazminat Davası" in result["unified_diff"]


def test_diff_drafts_detects_removed_lines(tmp_path: Path):
    """Content in v1 that is gone in v2 should appear as removed."""
    draft_a, draft_b = _create_draft_pair(tmp_path)
    result = diff_drafts(draft_a, draft_b)

    # {{DILEKCE_BASLIK}} is in v1 but not in v2
    assert "{{DILEKCE_BASLIK}}" in result["unified_diff"]
    assert result["changes"]["placeholders_removed"] >= 1


def test_diff_drafts_detects_filled_placeholders(tmp_path: Path):
    """Placeholders present in v1 but absent in v2 count as filled."""
    draft_a, draft_b = _create_draft_pair(tmp_path)
    result = diff_drafts(draft_a, draft_b)

    filled = result["placeholders_filled"]
    assert "DILEKCE_BASLIK" in filled
    assert "DAVACI_AD_SOYAD" in filled
    assert "ACIKLAMALAR_BASLIK" in filled
    assert result["changes"]["placeholders_filled"] >= 3


def test_diff_drafts_nonexistent_draft():
    """Non-existent path returns structured error."""
    result = diff_drafts("/nonexistent/a.md", "/nonexistent/b.md")
    assert result["ok"] is False
    assert "errorCode" in result


def test_diff_drafts_empty_draft(tmp_path: Path):
    """Empty draft file should still produce a valid diff."""
    draft_a = tmp_path / "empty_a.md"
    draft_b = tmp_path / "empty_b.md"
    draft_a.write_text(DRAFT_V1, encoding="utf-8")
    draft_b.write_text(DRAFT_EMPTY, encoding="utf-8")

    result = diff_drafts(draft_a, draft_b)
    assert result["ok"] is True
    assert result["changes"]["placeholders_removed"] >= 1


def test_diff_drafts_identical_drafts(tmp_path: Path):
    """Identical drafts produce empty diff with a warning."""
    draft_a, _ = _create_draft_pair(tmp_path)
    draft_copy = tmp_path / "draft_copy.md"
    draft_copy.write_text(DRAFT_V1, encoding="utf-8")

    result = diff_drafts(draft_a, draft_copy)
    assert result["ok"] is True
    assert result["unified_diff"] == ""
    assert any("No differences" in w for w in result["warnings"])


# ===========================================================================
# Tests: track_placeholders
# ===========================================================================


def test_track_placeholders_count_filled_vs_unfilled(tmp_path: Path):
    """Count matches the number of unique placeholders."""
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT_V1, encoding="utf-8")

    result = track_placeholders(draft)

    assert result["ok"] is True
    assert result["total_placeholders"] >= 6
    assert result["unfilled"] == result["total_placeholders"]
    assert result["filled"] == 0


def test_track_placeholders_all_filled(tmp_path: Path):
    """When no raw placeholders remain, ready_for_submission is True."""
    draft = tmp_path / "draft.md"
    draft.write_text("Bu metinde hic placeholder yok.", encoding="utf-8")

    result = track_placeholders(draft)

    assert result["ok"] is True
    assert result["total_placeholders"] == 0
    assert result["ready_for_submission"] is True
    assert result["fill_ratio"] == 1.0


def test_track_placeholders_some_unfilled(tmp_path: Path):
    """Partial fill → ready_for_submission is False."""
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT_V2, encoding="utf-8")

    result = track_placeholders(draft)

    assert result["ok"] is True
    assert result["unfilled"] >= 3
    assert result["ready_for_submission"] is False
    assert result["fill_ratio"] < 1.0


def test_track_placeholders_sections_mapped(tmp_path: Path):
    """Each placeholder is mapped to a section label."""
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT_V1, encoding="utf-8")

    result = track_placeholders(draft)

    sections = {p["section"] for p in result["placeholders"]}
    assert "MAHKEME" in sections or "BASLIK" in sections


def test_track_placeholders_nonexistent_draft():
    """Non-existent path returns structured error."""
    result = track_placeholders("/nonexistent/draft.md")
    assert result["ok"] is False
    assert "errorCode" in result


# ===========================================================================
# Tests: get_fill_report
# ===========================================================================


def test_get_fill_report_lists_unfilled_with_context(tmp_path: Path):
    """Unfilled placeholders appear in items with context text."""
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT_V1, encoding="utf-8")

    result = get_fill_report(draft)

    assert result["ok"] is True
    assert result["unfilled"] >= 6
    for item in result["items"]:
        if item["status"] == "unfilled":
            assert item["context"]  # should have some context text
            break


def test_get_fill_report_readiness(tmp_path: Path):
    """Readiness level reflects fill ratio."""
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT_V1, encoding="utf-8")

    result = get_fill_report(draft)
    assert result["readiness"] in {"ready", "nearly_ready", "in_progress", "early_draft"}


def test_get_fill_report_nonexistent_draft():
    """Non-existent path returns structured error."""
    result = get_fill_report("/nonexistent/draft.md")
    assert result["ok"] is False
    assert "errorCode" in result


def test_get_fill_report_with_pack_dir(tmp_path: Path):
    """When pack_dir is provided, suggestions dict is populated."""
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT_V1, encoding="utf-8")

    # Create a minimal pack directory with citation-bank.md
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "citation-bank.md").write_text(
        "# Citation Bank\n\n- **DAVACI** kaynak\n- **MAHKEME** referans\n",
        encoding="utf-8",
    )

    result = get_fill_report(draft, pack_dir=pack_dir)
    assert result["ok"] is True
    assert isinstance(result["suggestions"], dict)


# ===========================================================================
# Tests: save_draft_version
# ===========================================================================


def test_save_draft_version_creates_directory(tmp_path: Path):
    """save_draft_version creates a versioned subdirectory."""
    draft_dir = tmp_path / "my_draft"
    draft_dir.mkdir()
    (draft_dir / "draft.md").write_text(DRAFT_V1, encoding="utf-8")

    result = save_draft_version(draft_dir)

    assert result["ok"] is True
    version_dir = Path(result["version_dir"])
    assert version_dir.exists()
    assert (version_dir / "draft.md").exists()


def test_save_draft_version_stores_metadata(tmp_path: Path):
    """Version metadata JSON is written with required fields."""
    draft_dir = tmp_path / "my_draft"
    draft_dir.mkdir()
    (draft_dir / "draft.md").write_text(DRAFT_V1, encoding="utf-8")

    result = save_draft_version(draft_dir, version_label="test-v1")

    assert result["ok"] is True
    meta_path = Path(result["metadata_path"])
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["version_label"] == "test-v1"
    assert "version_id" in meta
    assert "created_at" in meta
    assert "files_copied" in meta


def test_save_draft_version_nonexistent_dir():
    """Non-existent directory returns structured error."""
    result = save_draft_version("/nonexistent/dir")
    assert result["ok"] is False
    assert "errorCode" in result


def test_save_draft_version_not_a_directory(tmp_path: Path):
    """File path instead of directory returns structured error."""
    f = tmp_path / "not_a_dir.md"
    f.write_text("content", encoding="utf-8")

    result = save_draft_version(f)
    assert result["ok"] is False
    assert "errorCode" in result


def test_save_draft_version_copies_subdirs(tmp_path: Path):
    """Subdirectories within draft_dir are copied."""
    draft_dir = tmp_path / "my_draft"
    draft_dir.mkdir()
    (draft_dir / "draft.md").write_text(DRAFT_V1, encoding="utf-8")
    sub = draft_dir / "source-documents"
    sub.mkdir()
    (sub / "doc1.md").write_text("# Doc 1", encoding="utf-8")

    result = save_draft_version(draft_dir)

    assert result["ok"] is True
    assert "source-documents/" in result["files_copied"]
    version_dir = Path(result["version_dir"])
    assert (version_dir / "source-documents" / "doc1.md").exists()


def test_save_draft_version_skips_dot_versions(tmp_path: Path):
    """.versions directory itself is not copied."""
    draft_dir = tmp_path / "my_draft"
    draft_dir.mkdir()
    (draft_dir / "draft.md").write_text(DRAFT_V1, encoding="utf-8")
    (draft_dir / ".versions").mkdir()

    result = save_draft_version(draft_dir)

    assert result["ok"] is True
    assert ".versions" not in result["files_copied"]


def test_save_draft_version_label_sanitized(tmp_path: Path):
    """Special characters in label are sanitized."""
    draft_dir = tmp_path / "my_draft"
    draft_dir.mkdir()
    (draft_dir / "draft.md").write_text(DRAFT_V1, encoding="utf-8")

    result = save_draft_version(draft_dir, version_label="v2.0 (final!)")

    assert result["ok"] is True
    vid = result["version_id"]
    # The label part should be sanitized
    assert "final" in vid.lower()
    assert "!" not in vid


# ===========================================================================
# Tests: Import compatibility (CLI and MCP)
# ===========================================================================


def test_imports_from_cli():
    """Verify that cli.py can import draft_diff functions."""
    from emsal_mcp.cli import draft_app  # noqa: F401

    assert draft_app is not None


def test_imports_from_server():
    """Verify that server.py can import draft_diff functions."""
    from emsal_mcp.server import main  # noqa: F401

    assert main is not None
