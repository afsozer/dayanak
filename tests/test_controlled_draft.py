"""Tests for v0.8 controlled draft, DOCX export validation, and export bundle.

Covers:
- prepare_petition_outline: section generation, placeholders, authority filtering
- prepare_controlled_petition_draft: draft output, footnotes, warnings, scoring
- No metadata-only leak: citation_only never appears in direct quotes
- Placeholders preserved in draft output
- prepare_docx_export: ZIP valid, disclaimer present, footnotes consistent
- prepare_export_package_bundle: manifest validation, post-verification
- CLI and MCP imports
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.petition import (
    prepare_controlled_petition_draft,
    prepare_drafting_input_pack,
    prepare_petition_outline,
    PLACEHOLDER_PATTERN,
)
from emsal_mcp.exporter import prepare_docx_export, prepare_export_package_bundle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(**kwargs: Any) -> Document:
    defaults: dict[str, Any] = {
        "source": "test_source",
        "document_id": "doc-001",
        "title": "Test Decision",
        "court": "Yargıtay",
        "chamber": "3. Hukuk Dairesi",
        "decision_date": "2024-06-15",
        "esas_no": "2024/12345",
        "karar_no": "2024/5678",
        "source_url": "https://example.com/doc/001",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": "This is test full text content for the decision. " * 5,
    }
    defaults.update(kwargs)
    return Document(**defaults)


def _make_metadata_only_doc(**kwargs: Any) -> Document:
    return _make_doc(
        document_id="meta-001",
        title="Metadata Only Document",
        content_status=ContentStatus.METADATA_ONLY,
        full_text=None,
        markdown=None,
        **kwargs,
    )


def _make_citation_only_doc(**kwargs: Any) -> Document:
    """A document classified as citation_only.

    citation_only requires either:
    - citation_check passes but content is not full_text/html_markdown (PDF_LINK_ONLY with metadata)
    - citation_check passes, content is full_text but text < 50 chars

    We use a short full_text document so citation_check passes but petition_ready
    threshold (>= 50 chars) is not met.
    """
    return _make_doc(
        document_id="cite-001",
        title="Citation Only Document",
        content_status=ContentStatus.FULL_TEXT,
        full_text="Short text.",  # < 50 chars → citation_only, not petition_ready
        markdown=None,
        **kwargs,
    )


def _build_pack(tmp_path: Path, docs: list[Document]) -> Path:
    """Helper to create a petition pack and return its path."""
    result = prepare_drafting_input_pack(
        matter="Test Matter",
        issue="Test Issue",
        documents=docs,
        out_dir=tmp_path / "pack",
    )
    return Path(result["out_dir"])


# ---------------------------------------------------------------------------
# Tests: prepare_petition_outline
# ---------------------------------------------------------------------------

class TestPreparePetitionOutline:
    def test_creates_outline_json(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_petition_outline(pack_dir, out_dir=tmp_path / "outline_out")
        assert result["ok"] is True
        assert Path(result["outline_path"]).exists()

    def test_outline_has_sections(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_petition_outline(pack_dir, out_dir=tmp_path / "outline_out")
        outline = json.loads(Path(result["outline_path"]).read_text(encoding="utf-8"))
        assert len(outline["sections"]) >= 5
        section_ids = [s["id"] for s in outline["sections"]]
        assert "header" in section_ids
        assert "bibliography" in section_ids
        assert "decisions" in section_ids

    def test_petition_ready_count(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_petition_outline(pack_dir, out_dir=tmp_path / "outline_out")
        assert result["petition_ready_count"] == 1

    def test_citation_only_in_bibliography(self, tmp_path: Path):
        docs = [_make_doc(), _make_citation_only_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        result = prepare_petition_outline(pack_dir, out_dir=tmp_path / "outline_out")
        outline = json.loads(Path(result["outline_path"]).read_text(encoding="utf-8"))
        bib = next(s for s in outline["sections"] if s["id"] == "bibliography")
        cite_only_entries = [
            a for a in bib["authorities"] if a["classification"] == "citation_only"
        ]
        assert len(cite_only_entries) >= 1
        # citation_only entries should have warning
        for entry in cite_only_entries:
            assert entry["warning"] is not None

    def test_placeholders_tracked(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_petition_outline(pack_dir, out_dir=tmp_path / "outline_out")
        assert result["placeholder_total"] > 0

    def test_outline_json_valid(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_petition_outline(pack_dir, out_dir=tmp_path / "outline_out")
        outline = json.loads(Path(result["outline_path"]).read_text(encoding="utf-8"))
        assert "version" in outline
        assert "sections" in outline
        assert "matter" in outline
        assert "issue" in outline

    def test_missing_pack_dir(self, tmp_path: Path):
        result = prepare_petition_outline(tmp_path / "nonexistent")
        assert result["ok"] is False
        assert "errorCode" in result

    def test_disclaimer_section_present(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_petition_outline(pack_dir, out_dir=tmp_path / "outline_out")
        outline = json.loads(Path(result["outline_path"]).read_text(encoding="utf-8"))
        header = next(s for s in outline["sections"] if s["id"] == "header")
        assert header["type"] == "disclaimer"


# ---------------------------------------------------------------------------
# Tests: prepare_controlled_petition_draft
# ---------------------------------------------------------------------------

class TestPrepareControlledPetitionDraft:
    def test_creates_all_output_files(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        assert result["ok"] is True
        assert Path(result["draft_md_path"]).exists()
        assert Path(result["draft_json_path"]).exists()
        assert Path(result["footnotes_path"]).exists()
        assert Path(result["warnings_path"]).exists()

    def test_draft_md_has_disclaimer(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        draft_text = Path(result["draft_md_path"]).read_text(encoding="utf-8")
        assert "emsal-mcp tarafından otomatik" in draft_text.lower()

    def test_draft_json_has_required_fields(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        meta = json.loads(Path(result["draft_json_path"]).read_text(encoding="utf-8"))
        assert "paragraph_count" in meta
        assert "section_count" in meta
        assert "footnote_count" in meta
        assert "placeholder_count" in meta
        assert "blocking_warning_count" in meta
        assert "readiness_score" in meta
        assert "readiness_level" in meta
        assert "finalization_risk_score" in meta

    def test_footnotes_only_from_petition_ready(self, tmp_path: Path):
        docs = [_make_doc(), _make_citation_only_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        footnotes = json.loads(Path(result["footnotes_path"]).read_text(encoding="utf-8"))
        # Only petition_ready authorities should be in footnotes
        for fn in footnotes["footnotes"]:
            assert fn["classification"] == "petition_ready"
        # citation_only should appear in bibliography only
        bib_refs = footnotes.get("citation_only_bibliography", [])
        assert len(bib_refs) >= 1

    def test_no_metadata_only_leak_in_direct_quotes(self, tmp_path: Path):
        """citation_only content must NOT appear as direct quotes in draft."""
        docs = [_make_doc(), _make_citation_only_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        draft_text = Path(result["draft_md_path"]).read_text(encoding="utf-8")
        # citation_only document ID should not appear outside comments/bibliography
        lines = draft_text.splitlines()
        in_bibliography = False
        for line in lines:
            if "## Kaynakça" in line:
                in_bibliography = True
            if in_bibliography:
                continue
            # Outside bibliography: citation_only doc_id should not appear as content
            # It may appear in HTML comments (<!-- Kaynak: ... -->), which is fine
            if line.strip().startswith("<!--"):
                continue
            assert "cite-001" not in line, (
                f"citation_only doc 'cite-001' found outside bibliography: {line}"
            )

    def test_placeholders_preserved(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        draft_text = Path(result["draft_md_path"]).read_text(encoding="utf-8")
        placeholders = PLACEHOLDER_PATTERN.findall(draft_text)
        assert len(placeholders) > 0

    def test_warnings_json_structure(self, tmp_path: Path):
        docs = [_make_doc(), _make_citation_only_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        warnings = json.loads(Path(result["warnings_path"]).read_text(encoding="utf-8"))
        assert "blocking_count" in warnings
        assert "warning_count" in warnings
        assert "info_count" in warnings
        assert "warnings" in warnings
        # Should have info-level warning for citation_only
        info_warnings = [w for w in warnings["warnings"] if w["level"] == "info"]
        assert len(info_warnings) >= 1

    def test_readiness_scoring(self, tmp_path: Path):
        docs = [_make_doc(), _make_citation_only_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        meta = json.loads(Path(result["draft_json_path"]).read_text(encoding="utf-8"))
        assert 0.0 <= meta["readiness_score"] <= 1.0
        assert meta["readiness_level"] in ("high", "medium", "low", "none")
        assert 0.0 <= meta["finalization_risk_score"] <= 1.0

    def test_no_petition_ready_blocks(self, tmp_path: Path):
        docs = [_make_metadata_only_doc(), _make_citation_only_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        meta = json.loads(Path(result["draft_json_path"]).read_text(encoding="utf-8"))
        assert meta["blocking_warning_count"] > 0
        warnings = json.loads(Path(result["warnings_path"]).read_text(encoding="utf-8"))
        blocking = [w for w in warnings["warnings"] if w["level"] == "blocking"]
        assert len(blocking) > 0

    def test_readiness_level_mapping(self, tmp_path: Path):
        # All petition_ready → high
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        meta = json.loads(Path(result["draft_json_path"]).read_text(encoding="utf-8"))
        assert meta["readiness_level"] == "high"

    def test_missing_pack_dir(self, tmp_path: Path):
        result = prepare_controlled_petition_draft(tmp_path / "nonexistent")
        assert result["ok"] is False

    def test_draft_json_file_references(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        meta = json.loads(Path(result["draft_json_path"]).read_text(encoding="utf-8"))
        files = meta.get("files", {})
        assert Path(files["draft_md"]).exists()
        assert Path(files["draft_json"]).exists()
        assert Path(files["footnotes_json"]).exists()
        assert Path(files["warnings_json"]).exists()


# ---------------------------------------------------------------------------
# Tests: prepare_docx_export
# ---------------------------------------------------------------------------

class TestPrepareDocxExport:
    def test_export_from_draft_path(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_docx_export(
            draft_path=draft_result["draft_md_path"],
            out_path=tmp_path / "output.docx",
            pack_dir=str(pack_dir),
        )
        assert result["ok"] is True
        assert result["checksum_sha256"]
        assert result["file_size"] > 0

    def test_export_from_draft_json(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        draft_json = json.loads(Path(draft_result["draft_json_path"]).read_text(encoding="utf-8"))
        result = prepare_docx_export(
            draft_json=draft_json,
            out_path=tmp_path / "output.docx",
            pack_dir=str(pack_dir),
        )
        assert result["ok"] is True

    def test_docx_zip_valid(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_docx_export(
            draft_path=draft_result["draft_md_path"],
            out_path=tmp_path / "output.docx",
        )
        assert result["validation"]["zip_valid"] is True

    def test_docx_disclaimer_present(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_docx_export(
            draft_path=draft_result["draft_md_path"],
            out_path=tmp_path / "output.docx",
        )
        assert result["validation"]["disclaimer_present"] is True

    def test_docx_placeholders_preserved(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_docx_export(
            draft_path=draft_result["draft_md_path"],
            out_path=tmp_path / "output.docx",
        )
        assert result["validation"]["placeholders_preserved"] is True

    def test_docx_footnotes_consistent(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_docx_export(
            draft_path=draft_result["draft_md_path"],
            out_path=tmp_path / "output.docx",
            pack_dir=str(pack_dir),
        )
        assert result["validation"]["footnotes_consistent"] is True

    def test_docx_export_readiness(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_docx_export(
            draft_path=draft_result["draft_md_path"],
            out_path=tmp_path / "output.docx",
            pack_dir=str(pack_dir),
        )
        assert result["validation"]["export_readiness"] is True

    def test_docx_checksum_sha256(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_docx_export(
            draft_path=draft_result["draft_md_path"],
            out_path=tmp_path / "output.docx",
        )
        docx_path = Path(result["out_path"])
        actual = hashlib.sha256(docx_path.read_bytes()).hexdigest()
        assert result["checksum_sha256"] == actual

    def test_missing_draft_path(self, tmp_path: Path):
        result = prepare_docx_export(draft_path=str(tmp_path / "nonexistent.md"))
        assert "error" in result

    def test_no_inputs_returns_error(self):
        result = prepare_docx_export()
        assert "error" in result

    def test_validation_warnings_list(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_docx_export(
            draft_path=draft_result["draft_md_path"],
            out_path=tmp_path / "output.docx",
        )
        assert isinstance(result["validation"]["validation_warnings"], list)


# ---------------------------------------------------------------------------
# Tests: prepare_export_package_bundle
# ---------------------------------------------------------------------------

class TestPrepareExportPackageBundle:
    def test_creates_bundle(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_export_package_bundle(
            pack_dir=pack_dir,
            draft_dir=tmp_path / "draft_out",
            out_dir=tmp_path / "bundle",
        )
        assert result["ok"] is True
        assert Path(result["bundle_dir"]).exists()

    def test_bundle_has_required_files(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_export_package_bundle(
            pack_dir=pack_dir,
            draft_dir=tmp_path / "draft_out",
            out_dir=tmp_path / "bundle",
        )
        bundle = Path(result["bundle_dir"])
        assert (bundle / "petition-pack.json").exists()
        assert (bundle / "manifest.json").exists()
        assert (bundle / "hash-manifest.json").exists()
        assert (bundle / "verification.txt").exists()

    def test_bundle_manifest_valid(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_export_package_bundle(
            pack_dir=pack_dir,
            draft_dir=tmp_path / "draft_out",
            out_dir=tmp_path / "bundle",
        )
        bundle = Path(result["bundle_dir"])
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        assert "version" in manifest
        assert "files" in manifest
        assert "file_count" in manifest
        assert manifest["version"] == "0.8.0"

    def test_bundle_hash_manifest_valid(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_export_package_bundle(
            pack_dir=pack_dir,
            draft_dir=tmp_path / "draft_out",
            out_dir=tmp_path / "bundle",
        )
        bundle = Path(result["bundle_dir"])
        hash_manifest = json.loads(
            (bundle / "hash-manifest.json").read_text(encoding="utf-8")
        )
        for fname, expected_hash in hash_manifest.items():
            fpath = bundle / fname
            assert fpath.exists(), f"File {fname} referenced in hash-manifest missing"
            actual = hashlib.sha256(fpath.read_bytes()).hexdigest()
            assert actual == expected_hash, f"Hash mismatch for {fname}"

    def test_bundle_verification_txt(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_export_package_bundle(
            pack_dir=pack_dir,
            draft_dir=tmp_path / "draft_out",
            out_dir=tmp_path / "bundle",
        )
        bundle = Path(result["bundle_dir"])
        verification = (bundle / "verification.txt").read_text(encoding="utf-8")
        assert "DOĞRULAMA DOSYASI" in verification
        assert "SHA-256" in verification

    def test_bundle_post_verification(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_export_package_bundle(
            pack_dir=pack_dir,
            draft_dir=tmp_path / "draft_out",
            out_dir=tmp_path / "bundle",
        )
        assert result["post_verification"]["ok"] is True
        checks = result["post_verification"]["checks"]
        assert checks["hash_manifest_valid"]["ok"] is True
        assert checks["required_files_present"]["ok"] is True
        assert checks["manifest_valid_json"]["ok"] is True

    def test_bundle_includes_draft_files(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_export_package_bundle(
            pack_dir=pack_dir,
            draft_dir=tmp_path / "draft_out",
            out_dir=tmp_path / "bundle",
        )
        files = result["files"]
        assert "draft.md" in files
        assert "draft.json" in files
        assert "footnotes.json" in files

    def test_bundle_with_docx(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        draft_result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        docx_result = prepare_docx_export(
            draft_path=draft_result["draft_md_path"],
            out_path=tmp_path / "draft_out" / "draft.docx",
            pack_dir=str(pack_dir),
        )
        result = prepare_export_package_bundle(
            pack_dir=pack_dir,
            draft_dir=tmp_path / "draft_out",
            docx_path=docx_result["out_path"],
            out_dir=tmp_path / "bundle",
        )
        assert "draft.docx" in result["files"]
        # Post verification should check DOCX zip
        checks = result["post_verification"]["checks"]
        assert "docx_zip_valid" in checks
        assert checks["docx_zip_valid"]["ok"] is True

    def test_bundle_source_documents(self, tmp_path: Path):
        pack_dir = _build_pack(tmp_path, [_make_doc()])
        prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        result = prepare_export_package_bundle(
            pack_dir=pack_dir,
            draft_dir=tmp_path / "draft_out",
            out_dir=tmp_path / "bundle",
        )
        bundle = Path(result["bundle_dir"])
        src_dir = bundle / "source-documents"
        assert src_dir.exists()
        src_files = list(src_dir.glob("*.md"))
        assert len(src_files) >= 1

    def test_missing_pack_dir(self, tmp_path: Path):
        result = prepare_export_package_bundle(tmp_path / "nonexistent")
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Tests: No metadata-only leak
# ---------------------------------------------------------------------------

class TestNoMetadataLeak:
    def test_citation_only_not_in_draft_body(self, tmp_path: Path):
        """citation_only authorities must not contribute direct quotes."""
        docs = [_make_doc(), _make_citation_only_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        draft_text = Path(result["draft_md_path"]).read_text(encoding="utf-8")
        # The citation_only doc's full_text should NOT appear
        cite_only_text = "Citation Only Document"
        # It may appear in the bibliography section only
        in_bib = False
        for line in draft_text.splitlines():
            if "## Kaynakça" in line:
                in_bib = True
            if in_bib:
                continue
            assert cite_only_text not in line, (
                f"citation_only text found outside bibliography: {line}"
            )

    def test_footnotes_json_no_citation_only(self, tmp_path: Path):
        docs = [_make_doc(), _make_citation_only_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        footnotes = json.loads(Path(result["footnotes_path"]).read_text(encoding="utf-8"))
        for fn in footnotes["footnotes"]:
            assert fn["classification"] != "citation_only"


# ---------------------------------------------------------------------------
# Tests: Placeholder preservation
# ---------------------------------------------------------------------------

class TestPlaceholderPreservation:
    def test_all_skeleton_placeholders_in_draft(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        skeleton = (pack_dir / "draft-skeleton.md").read_text(encoding="utf-8")
        skeleton_placeholders = set(PLACEHOLDER_PATTERN.findall(skeleton))

        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        draft_text = Path(result["draft_md_path"]).read_text(encoding="utf-8")
        draft_placeholders = set(PLACEHOLDER_PATTERN.findall(draft_text))

        # All skeleton placeholders should appear in draft
        for ph in skeleton_placeholders:
            assert ph in draft_placeholders, f"Placeholder {ph} missing from draft"

    def test_draft_json_placeholder_count(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _build_pack(tmp_path, docs)
        result = prepare_controlled_petition_draft(pack_dir, out_dir=tmp_path / "draft_out")
        meta = json.loads(Path(result["draft_json_path"]).read_text(encoding="utf-8"))
        draft_text = Path(result["draft_md_path"]).read_text(encoding="utf-8")
        actual_count = len(PLACEHOLDER_PATTERN.findall(draft_text))
        assert meta["placeholder_count"] == actual_count


# ---------------------------------------------------------------------------
# Tests: CLI / MCP integration
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_cli_import(self):
        from emsal_mcp.cli import app
        assert app is not None

    def test_new_functions_importable(self):
        from emsal_mcp.petition import (
            prepare_controlled_petition_draft,
            prepare_petition_outline,
        )
        from emsal_mcp.exporter import (
            prepare_docx_export,
            prepare_export_package_bundle,
        )
        assert callable(prepare_petition_outline)
        assert callable(prepare_controlled_petition_draft)
        assert callable(prepare_docx_export)
        assert callable(prepare_export_package_bundle)


class TestMCPServerIntegration:
    def test_server_import(self):
        from emsal_mcp.server import main
        assert callable(main)

    def test_version_bumped(self):
        from emsal_mcp import __version__
        from packaging.version import Version
        assert Version(__version__) >= Version("0.10.0")
