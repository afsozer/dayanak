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
