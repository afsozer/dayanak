"""Tests for v0.7 petition pack workflow.

Uses fake Documents; ensures metadata_only/pdf_only never draft usable;
inspect fails when instructions missing no-invention rule; placeholders
preserved.  No live network calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.petition import (
    _classify_authority,
    _generate_petition_instructions,
    build_multi_issue_pack,
    inspect_multi_issue_pack,
    inspect_petition_pack,
    prepare_drafting_input_pack,
)


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


def _make_pdf_only_doc(**kwargs: Any) -> Document:
    return _make_doc(
        document_id="pdf-001",
        title="PDF Only Document",
        content_status=ContentStatus.PDF_LINK_ONLY,
        full_text=None,
        markdown=None,
        **kwargs,
    )


def _make_unavailable_doc(**kwargs: Any) -> Document:
    return _make_doc(
        document_id="unavail-001",
        title="Unavailable Document",
        content_status=ContentStatus.UNAVAILABLE,
        full_text=None,
        markdown=None,
        decision_date=None,
        esas_no=None,
        karar_no=None,
        source_url=None,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests: _classify_authority
# ---------------------------------------------------------------------------

class TestClassifyAuthority:
    def test_full_text_is_petition_ready(self):
        doc = _make_doc()
        assert _classify_authority(doc) == "petition_ready"

    def test_metadata_only_is_citation_only(self):
        doc = _make_metadata_only_doc()
        cat = _classify_authority(doc)
        assert cat in ("citation_only", "research_lead_only")

    def test_pdf_only_is_citation_only_or_research(self):
        doc = _make_pdf_only_doc()
        cat = _classify_authority(doc)
        assert cat in ("citation_only", "research_lead_only")

    def test_unavailable_is_excluded(self):
        doc = _make_unavailable_doc()
        assert _classify_authority(doc) == "excluded"

    def test_metadata_only_never_petition_ready(self):
        """metadata_only documents must NEVER be petition_ready."""
        doc = _make_metadata_only_doc()
        assert _classify_authority(doc) != "petition_ready"

    def test_pdf_only_never_petition_ready(self):
        """pdf_only documents must NEVER be petition_ready."""
        doc = _make_pdf_only_doc()
        assert _classify_authority(doc) != "petition_ready"

    def test_html_markdown_is_petition_ready(self):
        doc = _make_doc(
            content_status=ContentStatus.HTML_MARKDOWN,
            full_text=None,
            markdown="This is markdown content for testing purposes. " * 5,
        )
        assert _classify_authority(doc) == "petition_ready"


# ---------------------------------------------------------------------------
# Tests: prepare_drafting_input_pack
# ---------------------------------------------------------------------------

class TestPrepareDraftingInputPack:
    def test_creates_all_required_files(self, tmp_path: Path):
        docs = [_make_doc(), _make_metadata_only_doc()]
        result = prepare_drafting_input_pack(
            matter="Test Matter",
            issue="Test Issue",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        assert pack_dir.exists()
        assert (pack_dir / "petition-brief.json").exists()
        assert (pack_dir / "citation-bank.md").exists()
        assert (pack_dir / "argument-map.md").exists()
        assert (pack_dir / "petition-instructions.md").exists()
        assert (pack_dir / "draft-skeleton.md").exists()
        assert (pack_dir / "petition-pack.json").exists()

    def test_returns_correct_structure(self, tmp_path: Path):
        docs = [_make_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        assert result["ok"] is True
        assert "out_dir" in result
        assert "draft_safe" in result
        assert "counts" in result
        assert "classifications" in result
        assert "files" in result
        assert "warnings" in result

    def test_draft_safe_when_petition_ready(self, tmp_path: Path):
        docs = [_make_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        assert result["draft_safe"] is True
        assert result["counts"]["petition_ready"] == 1

    def test_not_draft_safe_when_only_metadata(self, tmp_path: Path):
        docs = [_make_metadata_only_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        assert result["draft_safe"] is False
        assert result["counts"]["petition_ready"] == 0

    def test_not_draft_safe_when_only_pdf(self, tmp_path: Path):
        docs = [_make_pdf_only_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        assert result["draft_safe"] is False

    def test_metadata_only_pdf_only_never_draft_safe(self, tmp_path: Path):
        """Combined metadata_only and pdf_only must never be draft_safe."""
        docs = [_make_metadata_only_doc(), _make_pdf_only_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        assert result["draft_safe"] is False

    def test_excluded_docs_not_in_source_documents(self, tmp_path: Path):
        docs = [_make_doc(), _make_unavailable_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        src_dir = pack_dir / "source-documents"
        assert src_dir.exists()
        src_files = list(src_dir.glob("*.md"))
        # Only the available doc should be written
        assert len(src_files) == 1

    def test_citation_bank_only_safe(self, tmp_path: Path):
        docs = [_make_doc(), _make_metadata_only_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        bank = (pack_dir / "citation-bank.md").read_text(encoding="utf-8")
        assert "Citation Bank" in bank

    def test_instructions_contain_no_invention(self, tmp_path: Path):
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=[],
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        instructions = (pack_dir / "petition-instructions.md").read_text(encoding="utf-8")
        assert "uydurma" in instructions.lower() or "no-invention" in instructions.lower()

    def test_skeleton_has_placeholders(self, tmp_path: Path):
        docs = [_make_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        skeleton = (pack_dir / "draft-skeleton.md").read_text(encoding="utf-8")
        import re
        placeholders = re.findall(r"\{\{[^}]+\}\}", skeleton)
        assert len(placeholders) > 0

    def test_petition_brief_json_valid(self, tmp_path: Path):
        docs = [_make_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        brief = json.loads((pack_dir / "petition-brief.json").read_text(encoding="utf-8"))
        assert brief["version"] in ("0.7.0", "0.8.0")
        assert brief["matter"] == "M"
        assert brief["issue"] == "I"
        assert brief["draft_safe"] is True

    def test_pack_meta_json_valid(self, tmp_path: Path):
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=[_make_doc()],
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        meta = json.loads((pack_dir / "petition-pack.json").read_text(encoding="utf-8"))
        assert meta["version"] in ("0.7.0", "0.8.0")
        assert "classification_counts" in meta
        assert "files" in meta

    def test_hash_manifest_if_source_docs(self, tmp_path: Path):
        docs = [_make_doc()]
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        manifest_path = pack_dir / "hash-manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(manifest) >= 1

    def test_empty_documents(self, tmp_path: Path):
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=[],
            out_dir=tmp_path / "pack",
        )
        assert result["ok"] is True
        assert result["draft_safe"] is False
        assert result["counts"]["petition_ready"] == 0

    def test_cache_logging(self, tmp_path: Path):
        """Verify cache.log is called when cache is provided."""
        class FakeCache:
            def __init__(self):
                self.logs = []
            def log(self, action, payload):
                self.logs.append((action, payload))

        cache = FakeCache()
        prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=[_make_doc()],
            out_dir=tmp_path / "pack",
            cache=cache,
        )
        assert len(cache.logs) == 1
        assert cache.logs[0][0] == "prepare_drafting_input_pack"

    def test_research_bundle_loading(self, tmp_path: Path):
        """Test loading documents from a research bundle directory."""
        bundle_dir = tmp_path / "research"
        bundle_dir.mkdir()
        results = [
            {
                "source": "fake",
                "document_id": "doc1",
                "title": "Doc 1",
                "court": "Test Court",
                "content_status": "full_text",
                "source_url": "https://example.com/1",
            },
            {
                "source": "fake",
                "document_id": "doc2",
                "title": "Doc 2",
                "content_status": "metadata_only",
            },
        ]
        (bundle_dir / "results.json").write_text(
            json.dumps(results), encoding="utf-8"
        )
        result = prepare_drafting_input_pack(
            matter="M",
            issue="I",
            research_bundle_dir=str(bundle_dir),
            out_dir=tmp_path / "pack",
        )
        assert result["ok"] is True
        assert result["authority_count"] == 2


# ---------------------------------------------------------------------------
# Tests: inspect_petition_pack
# ---------------------------------------------------------------------------

class TestInspectPetitionPack:
    def test_valid_pack_ok(self, tmp_path: Path):
        docs = [_make_doc()]
        prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        result = inspect_petition_pack(tmp_path / "pack")
        assert result["ok"] is True
        assert result["draft_safe"] is True
        assert result["errors"] == []

    def test_missing_required_files(self, tmp_path: Path):
        pack_dir = tmp_path / "empty_pack"
        pack_dir.mkdir()
        result = inspect_petition_pack(pack_dir)
        assert result["ok"] is False
        assert len(result["errors"]) >= len([
            "petition-brief.json",
            "citation-bank.md",
            "argument-map.md",
            "petition-instructions.md",
            "draft-skeleton.md",
            "petition-pack.json",
        ])

    def test_instructions_missing_no_invention_rule(self, tmp_path: Path):
        """Inspect fails when instructions file is missing no-invention rule."""
        pack_dir = tmp_path / "bad_pack"
        pack_dir.mkdir()
        # Create minimal files
        for fname in [
            "petition-brief.json",
            "citation-bank.md",
            "argument-map.md",
            "draft-skeleton.md",
            "petition-pack.json",
        ]:
            if fname.endswith(".json"):
                (pack_dir / fname).write_text("{}", encoding="utf-8")
            else:
                (pack_dir / fname).write_text("# Content", encoding="utf-8")
        # Write instructions WITHOUT no-invention rule
        (pack_dir / "petition-instructions.md").write_text(
            "# Instructions\n\nJust do stuff.\n", encoding="utf-8"
        )
        result = inspect_petition_pack(pack_dir)
        assert result["ok"] is False
        assert any("no-invention" in e.lower() for e in result["errors"])

    def test_placeholders_preserved(self, tmp_path: Path):
        docs = [_make_doc()]
        prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        result = inspect_petition_pack(tmp_path / "pack")
        checks = result["checks"]
        assert "placeholdersInDraftSkeleton" in checks
        assert checks["placeholdersInDraftSkeleton"]["count"] > 0
        assert checks["placeholdersInDraftSkeleton"]["ok"] is True

    def test_metadata_only_not_draft_safe(self, tmp_path: Path):
        docs = [_make_metadata_only_doc()]
        prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        result = inspect_petition_pack(tmp_path / "pack")
        assert result["draft_safe"] is False
        assert result["checks"]["metadataOnlyDraftUsable"]["ok"] is True
        # ok is True because there are no petition_ready docs when there are
        # metadata_only docs — the check is about whether metadata_only is
        # incorrectly marked as draft usable

    def test_hash_manifest_valid(self, tmp_path: Path):
        docs = [_make_doc()]
        prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        result = inspect_petition_pack(tmp_path / "pack")
        assert result["checks"]["hashManifestValid"]["ok"] is True
        assert result["checks"]["hashManifestValid"]["mismatches"] == []

    def test_hash_manifest_tampered(self, tmp_path: Path):
        docs = [_make_doc()]
        prepare_drafting_input_pack(
            matter="M",
            issue="I",
            documents=docs,
            out_dir=tmp_path / "pack",
        )
        pack_dir = tmp_path / "pack"
        # Tamper with a source document
        src_files = list((pack_dir / "source-documents").glob("*.md"))
        if src_files:
            src_files[0].write_text("TAMPERED", encoding="utf-8")
        result = inspect_petition_pack(pack_dir)
        assert result["checks"]["hashManifestValid"]["ok"] is False

    def test_checks_structure(self, tmp_path: Path):
        result = inspect_petition_pack(tmp_path / "nonexistent")
        assert "checks" in result
        checks = result["checks"]
        assert "placeholdersInDraftSkeleton" in checks
        assert "petitionInstructionsForbidsInvention" in checks
        assert "citationBankOnlySafeDocs" in checks
        assert "hashManifestValid" in checks
        assert "metadataOnlyDraftUsable" in checks
        assert "legislationVerifiedPlaceholder" in checks


# ---------------------------------------------------------------------------
# Tests: _generate_petition_instructions
# ---------------------------------------------------------------------------

class TestPetitionInstructions:
    def test_contains_no_invention_rule(self):
        instructions = _generate_petition_instructions()
        assert "uydurma" in instructions.lower() or "no-invention" in instructions.lower()

    def test_contains_no_fabrication(self):
        instructions = _generate_petition_instructions()
        assert "uydurma" in instructions.lower() or "no fabrication" in instructions.lower()

    def test_contains_metadata_rule(self):
        instructions = _generate_petition_instructions()
        assert "metadata" in instructions.lower()


# ---------------------------------------------------------------------------
# Tests: CLI / MCP integration (import check)
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_cli_import(self):
        from emsal_mcp.cli import app
        assert app is not None

    def test_petition_functions_importable(self):
        from emsal_mcp.petition import (
            inspect_petition_pack,
            prepare_drafting_input_pack,
        )
        assert callable(prepare_drafting_input_pack)
        assert callable(inspect_petition_pack)


class TestMCPServerIntegration:
    def test_server_import(self):
        from emsal_mcp.server import main
        assert callable(main)


# ---------------------------------------------------------------------------
# Tests: build_multi_issue_pack
# ---------------------------------------------------------------------------

class TestBuildMultiIssuePack:
    def test_creates_structure(self, tmp_path: Path):
        """Multi-issue pack creates expected directory structure."""
        issues = [
            {"title": "Mesele 1", "description": "First legal issue"},
            {"title": "Mesele 2", "description": "Second legal issue"},
        ]
        result = build_multi_issue_pack(
            matter="Test Matter",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        assert result["ok"] is True
        pack_dir = Path(result["out_dir"])
        assert pack_dir.exists()
        assert (pack_dir / "petition-brief.json").exists()
        assert (pack_dir / "petition-pack.json").exists()
        assert (pack_dir / "draft-skeleton.md").exists()
        assert (pack_dir / "petition-instructions.md").exists()
        # hash-manifest.json only exists when there are source documents

    def test_issues_directory(self, tmp_path: Path):
        """Each issue gets its own subdirectory under issues/."""
        issues = [
            {"title": "Mesele 1", "description": "First"},
            {"title": "Mesele 2", "description": "Second"},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        pack_dir = Path(result["out_dir"])
        assert (pack_dir / "issues" / "issue-1").is_dir()
        assert (pack_dir / "issues" / "issue-2").is_dir()

    def test_per_issue_citation_bank(self, tmp_path: Path):
        """Each issue has its own citation-bank.md."""
        issues = [
            {"title": "Mesele 1", "description": "First"},
            {"title": "Mesele 2", "description": "Second"},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        pack_dir = Path(result["out_dir"])
        assert (pack_dir / "issues" / "issue-1" / "citation-bank.md").exists()
        assert (pack_dir / "issues" / "issue-2" / "citation-bank.md").exists()

    def test_per_issue_argument_map(self, tmp_path: Path):
        """Each issue has its own argument-map.md."""
        issues = [
            {"title": "Mesele 1", "description": "First"},
            {"title": "Mesele 2", "description": "Second"},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        pack_dir = Path(result["out_dir"])
        assert (pack_dir / "issues" / "issue-1" / "argument-map.md").exists()
        assert (pack_dir / "issues" / "issue-2" / "argument-map.md").exists()

    def test_per_issue_instructions(self, tmp_path: Path):
        """Each issue has its own petition-instructions.md with no-invention rule."""
        issues = [
            {"title": "Mesele 1", "description": "First"},
            {"title": "Mesele 2", "description": "Second"},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        pack_dir = Path(result["out_dir"])
        for i in (1, 2):
            inst_path = pack_dir / "issues" / f"issue-{i}" / "petition-instructions.md"
            assert inst_path.exists()
            text = inst_path.read_text(encoding="utf-8")
            assert "uydurma" in text.lower() or "no-invention" in text.lower()

    def test_shared_source_documents(self, tmp_path: Path):
        """Source documents are shared and deduplicated across issues."""
        doc = _make_doc(document_id="shared-001", source="test_source")
        issues = [
            {"title": "Mesele 1", "description": "First", "documents": [doc.model_dump(mode="json")]},
            {"title": "Mesele 2", "description": "Second", "documents": [doc.model_dump(mode="json")]},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        pack_dir = Path(result["out_dir"])
        src_dir = pack_dir / "source-documents"
        assert src_dir.exists()
        src_files = list(src_dir.glob("*.md"))
        # Should be deduplicated: only 1 source file
        assert len(src_files) == 1

    def test_per_issue_documents(self, tmp_path: Path):
        """Per-issue documents are included in that issue's citation bank."""
        doc1 = _make_doc(document_id="doc-issue1", source="test_source")
        doc2 = _make_doc(document_id="doc-issue2", source="test_source")
        issues = [
            {"title": "Mesele 1", "description": "First", "documents": [doc1.model_dump(mode="json")]},
            {"title": "Mesele 2", "description": "Second", "documents": [doc2.model_dump(mode="json")]},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        pack_dir = Path(result["out_dir"])
        bank1 = (pack_dir / "issues" / "issue-1" / "citation-bank.md").read_text(encoding="utf-8")
        bank2 = (pack_dir / "issues" / "issue-2" / "citation-bank.md").read_text(encoding="utf-8")
        assert "doc-issue1" in bank1
        assert "doc-issue2" in bank2

    def test_hash_manifest_covers_all_docs(self, tmp_path: Path):
        """Hash manifest covers all source documents across issues."""
        doc1 = _make_doc(document_id="hdoc-1", source="test_source")
        doc2 = _make_doc(document_id="hdoc-2", source="test_source")
        issues = [
            {"title": "Mesele 1", "description": "First", "documents": [doc1.model_dump(mode="json")]},
            {"title": "Mesele 2", "description": "Second", "documents": [doc2.model_dump(mode="json")]},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        pack_dir = Path(result["out_dir"])
        manifest = json.loads((pack_dir / "hash-manifest.json").read_text(encoding="utf-8"))
        # Both docs should be in the manifest
        assert len(manifest) >= 2

    def test_issue_result_structure(self, tmp_path: Path):
        """Each issue result has expected keys."""
        issues = [
            {"title": "M1", "description": "D1"},
            {"title": "M2", "description": "D2"},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        assert result["issue_count"] == 2
        for ir in result["issues"]:
            assert "issue_index" in ir
            assert "title" in ir
            assert "description" in ir
            assert "dir" in ir
            assert "draft_safe" in ir
            assert "classification_counts" in ir
            assert "authority_count" in ir

    def test_draft_safe_when_any_issue_has_petition_ready(self, tmp_path: Path):
        """Pack is draft_safe if at least one issue has petition_ready docs."""
        issues = [
            {"title": "M1", "description": "D1", "documents": [_make_doc().model_dump(mode="json")]},
            {"title": "M2", "description": "D2", "documents": [_make_metadata_only_doc().model_dump(mode="json")]},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        assert result["draft_safe"] is True

    def test_not_draft_safe_when_no_petition_ready(self, tmp_path: Path):
        """Pack is not draft_safe when no issue has petition_ready docs."""
        issues = [
            {"title": "M1", "description": "D1", "documents": [_make_metadata_only_doc().model_dump(mode="json")]},
            {"title": "M2", "description": "D2", "documents": [_make_pdf_only_doc().model_dump(mode="json")]},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "multi_pack",
        )
        assert result["draft_safe"] is False

    def test_empty_issues_returns_error(self, tmp_path: Path):
        """Empty issues list returns error dict."""
        result = build_multi_issue_pack(
            matter="M",
            issues=[],
            out_dir=tmp_path / "multi_pack",
        )
        assert result["ok"] is False
        assert "errorCode" in result

    def test_single_issue_works(self, tmp_path: Path):
        """Single issue still works (backward compatible structure)."""
        issues = [
            {"title": "Single Issue", "description": "Just one"},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "single_pack",
        )
        assert result["ok"] is True
        assert result["issue_count"] == 1
        pack_dir = Path(result["out_dir"])
        assert (pack_dir / "issues" / "issue-1").is_dir()

    def test_pack_meta_is_multi_issue_type(self, tmp_path: Path):
        """petition-pack.json has type=multi_issue."""
        issues = [{"title": "M1", "description": "D1"}]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        meta = json.loads((pack_dir / "petition-pack.json").read_text(encoding="utf-8"))
        assert meta["type"] == "multi_issue"
        assert meta["version"] == "0.9.0"

    def test_brief_has_issues_list(self, tmp_path: Path):
        """petition-brief.json contains issues list."""
        issues = [
            {"title": "M1", "description": "D1"},
            {"title": "M2", "description": "D2"},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        brief = json.loads((pack_dir / "petition-brief.json").read_text(encoding="utf-8"))
        assert len(brief["issues"]) == 2
        assert brief["issues"][0]["title"] == "M1"
        assert brief["issues"][1]["title"] == "M2"

    def test_cache_logging(self, tmp_path: Path):
        """Cache.log is called when cache is provided."""
        class FakeCache:
            def __init__(self):
                self.logs = []
            def log(self, action, payload):
                self.logs.append((action, payload))

        cache = FakeCache()
        build_multi_issue_pack(
            matter="M",
            issues=[{"title": "M1", "description": "D1"}],
            out_dir=tmp_path / "pack",
            cache=cache,
        )
        assert len(cache.logs) == 1
        assert cache.logs[0][0] == "build_multi_issue_pack"

    def test_skeleton_has_placeholders(self, tmp_path: Path):
        """Draft skeleton has placeholders for each issue."""
        issues = [
            {"title": "Mesele 1", "description": "First"},
            {"title": "Mesele 2", "description": "Second"},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        skeleton = (pack_dir / "draft-skeleton.md").read_text(encoding="utf-8")
        placeholders = __import__("re").findall(r"\{\{[^}]+\}\}", skeleton)
        assert len(placeholders) >= 2  # at least one per issue


# ---------------------------------------------------------------------------
# Tests: inspect_multi_issue_pack
# ---------------------------------------------------------------------------

class TestInspectMultiIssuePack:
    def _build_pack(self, tmp_path: Path, doc=None) -> Path:
        """Helper: build and return pack path."""
        issues_def: list[dict[str, Any]] = [
            {"title": "M1", "description": "D1"},
            {"title": "M2", "description": "D2"},
        ]
        if doc is not None:
            issues_def[0]["documents"] = [doc.model_dump(mode="json")]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues_def,
            out_dir=tmp_path / "multi_pack",
        )
        return Path(result["out_dir"])

    def test_valid_pack_ok(self, tmp_path: Path):
        pack_dir = self._build_pack(tmp_path)
        result = inspect_multi_issue_pack(pack_dir)
        assert result["ok"] is True

    def test_missing_issues_dir(self, tmp_path: Path):
        pack_dir = tmp_path / "empty_pack"
        pack_dir.mkdir()
        # Write minimal required files
        for fname in ["petition-brief.json", "petition-pack.json", "draft-skeleton.md", "petition-instructions.md"]:
            if fname.endswith(".json"):
                (pack_dir / fname).write_text("{}", encoding="utf-8")
            else:
                (pack_dir / fname).write_text("# Content", encoding="utf-8")
        result = inspect_multi_issue_pack(pack_dir)
        assert result["ok"] is False
        assert any("issues/" in e for e in result["errors"])

    def test_missing_issue_files(self, tmp_path: Path):
        pack_dir = tmp_path / "bad_pack"
        pack_dir.mkdir()
        # Create top-level files
        for fname in ["petition-brief.json", "petition-pack.json", "draft-skeleton.md", "petition-instructions.md"]:
            if fname.endswith(".json"):
                (pack_dir / fname).write_text("{}", encoding="utf-8")
            else:
                (pack_dir / fname).write_text("# Content", encoding="utf-8")
        # Create issues dir with empty issue
        issues_dir = pack_dir / "issues" / "issue-1"
        issues_dir.mkdir(parents=True)
        # No citation-bank.md or argument-map.md
        result = inspect_multi_issue_pack(pack_dir)
        assert result["ok"] is False

    def test_no_cross_contamination(self, tmp_path: Path):
        """No cross-issue citation contamination in a clean pack."""
        pack_dir = self._build_pack(tmp_path)
        result = inspect_multi_issue_pack(pack_dir)
        assert result["checks"]["noCrossIssueContamination"]["ok"] is True

    def test_hash_manifest_valid(self, tmp_path: Path):
        pack_dir = self._build_pack(tmp_path, doc=_make_doc())
        result = inspect_multi_issue_pack(pack_dir)
        assert result["checks"]["hashManifestValid"]["ok"] is True

    def test_hash_manifest_tampered(self, tmp_path: Path):
        pack_dir = self._build_pack(tmp_path, doc=_make_doc())
        # Tamper
        src_files = list((pack_dir / "source-documents").glob("*.md"))
        if src_files:
            src_files[0].write_text("TAMPERED", encoding="utf-8")
        result = inspect_multi_issue_pack(pack_dir)
        assert result["checks"]["hashManifestValid"]["ok"] is False

    def test_issue_results_structure(self, tmp_path: Path):
        pack_dir = self._build_pack(tmp_path)
        result = inspect_multi_issue_pack(pack_dir)
        assert len(result["issue_results"]) == 2
        for ir in result["issue_results"]:
            assert "issue_dir" in ir
            assert "ok" in ir
            assert "errors" in ir
            assert "citation_count" in ir

    def test_no_invention_rule_per_issue(self, tmp_path: Path):
        """Each issue directory has instructions with no-invention rule."""
        pack_dir = self._build_pack(tmp_path)
        result = inspect_multi_issue_pack(pack_dir)
        for ir in result["issue_results"]:
            assert ir["ok"] is True

    def test_metadata_only_not_draft_safe(self, tmp_path: Path):
        issues = [
            {"title": "M1", "description": "D1", "documents": [_make_metadata_only_doc().model_dump(mode="json")]},
            {"title": "M2", "description": "D2", "documents": [_make_metadata_only_doc().model_dump(mode="json")]},
        ]
        result = build_multi_issue_pack(
            matter="M",
            issues=issues,
            out_dir=tmp_path / "pack",
        )
        pack_dir = Path(result["out_dir"])
        result = inspect_multi_issue_pack(pack_dir)
        assert result["draft_safe"] is False

    def test_checks_structure(self, tmp_path: Path):
        pack_dir = self._build_pack(tmp_path)
        result = inspect_multi_issue_pack(pack_dir)
        checks = result["checks"]
        assert "noCrossIssueContamination" in checks
        assert "placeholdersInDraftSkeleton" in checks
        assert "petitionInstructionsForbidsInvention" in checks
        assert "hashManifestValid" in checks
        assert "metadataOnlyDraftUsable" in checks

    def test_type_must_be_multi_issue(self, tmp_path: Path):
        """Inspect fails if petition-pack.json type is not multi_issue."""
        pack_dir = tmp_path / "bad_pack"
        pack_dir.mkdir()
        for fname in ["petition-brief.json", "draft-skeleton.md", "petition-instructions.md"]:
            if fname.endswith(".json"):
                (pack_dir / fname).write_text("{}", encoding="utf-8")
            else:
                (pack_dir / fname).write_text("# Content", encoding="utf-8")
        (pack_dir / "petition-pack.json").write_text(
            json.dumps({"type": "single_issue"}), encoding="utf-8"
        )
        issues_dir = pack_dir / "issues" / "issue-1"
        issues_dir.mkdir(parents=True)
        (issues_dir / "citation-bank.md").write_text("# Bank", encoding="utf-8")
        (issues_dir / "argument-map.md").write_text("# Map", encoding="utf-8")
        (issues_dir / "petition-instructions.md").write_text(
            "# Instructions\n\nUydurma yasak.\n", encoding="utf-8"
        )
        result = inspect_multi_issue_pack(pack_dir)
        assert result["ok"] is False
        assert any("multi_issue" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Tests: CLI / MCP integration for multi-issue
# ---------------------------------------------------------------------------

class TestMultiIssueCLIIntegration:
    def test_multi_issue_functions_importable(self):
        from emsal_mcp.petition import (
            build_multi_issue_pack,
            inspect_multi_issue_pack,
        )
        assert callable(build_multi_issue_pack)
        assert callable(inspect_multi_issue_pack)

    def test_cli_app_importable(self):
        from emsal_mcp.cli import app
        assert app is not None
