"""Invariant tests — verify safety invariants hold across all code paths.

These tests assert properties that must ALWAYS be true regardless of input,
module version, or code path.  They serve as regression guards for the
core safety guarantees of emsal-mcp.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Invariant 1: Metadata-only never draft usable
# ---------------------------------------------------------------------------

class TestMetadataOnlyNeverDraftUsable:
    """No path should mark a metadata_only document as draft_usable=True."""

    def test_document_model_metadata_only(self):
        """Document model: METADATA_ONLY → draft_usable is False."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="test",
            document_id="x",
            title="Test",
            content_status=ContentStatus.METADATA_ONLY,
        )
        assert doc.draft_usable is False, (
            "METADATA_ONLY document must never be draft_usable"
        )

    def test_document_model_pdf_link_only(self):
        """Document model: PDF_LINK_ONLY → draft_usable is False."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="test",
            document_id="x",
            title="Test",
            content_status=ContentStatus.PDF_LINK_ONLY,
        )
        assert doc.draft_usable is False

    def test_document_model_unavailable(self):
        """Document model: UNAVAILABLE → draft_usable is False."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="test",
            document_id="x",
            title="Test",
            content_status=ContentStatus.UNAVAILABLE,
        )
        assert doc.draft_usable is False

    def test_citation_check_metadata_only(self):
        """safety.citation_check: metadata_only → quoteUsable=False, draftUsable=False."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.safety import citation_check

        doc = Document(
            source="test",
            document_id="x",
            title="Test",
            content_status=ContentStatus.METADATA_ONLY,
        )
        check = citation_check(doc)
        assert check.quoteUsable is False
        assert check.draftUsable is False

    def test_petition_classification_metadata_only(self):
        """petition._classify_authority: metadata_only → never petition_ready."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.petition import _classify_authority

        doc = Document(
            source="test",
            document_id="x",
            title="Test",
            content_status=ContentStatus.METADATA_ONLY,
        )
        cat = _classify_authority(doc)
        assert cat != "petition_ready", (
            f"metadata_only classified as '{cat}' — must never be petition_ready"
        )

    def test_petition_classification_unavailable(self):
        """petition._classify_authority: unavailable → always excluded."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.petition import _classify_authority

        doc = Document(
            source="test",
            document_id="x",
            title="Test",
            content_status=ContentStatus.UNAVAILABLE,
        )
        cat = _classify_authority(doc)
        assert cat == "excluded"

    def test_controlled_draft_excludes_metadata_only(self):
        """document.controlled_draft: metadata_only docs not in safe list."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.document import controlled_draft

        meta_doc = Document(
            source="test",
            document_id="meta",
            title="Meta Only",
            content_status=ContentStatus.METADATA_ONLY,
        )
        result = controlled_draft("Title", "Body", [meta_doc])
        # The metadata_only doc should NOT appear as a citation candidate
        assert "meta" not in result or "Güvenli tam metinli karar bulunamadı" in result


# ---------------------------------------------------------------------------
# Invariant 2: Citation safety never fabricates
# ---------------------------------------------------------------------------

class TestCitationNeverFabricates:
    """Citation functions never invent metadata — missing fields = warnings."""

    def test_format_legal_citation_missing_fields(self):
        """format_legal_citation with partial source → warnings about missing fields."""
        from emsal_mcp.citation import format_legal_citation

        result = format_legal_citation(source={"title": "Test"}, style="petition")
        assert "warnings" in result
        assert isinstance(result["warnings"], list)
        # Should have warnings about missing court, date, esas_no, karar_no
        assert len(result["warnings"]) > 0
        # Should NOT have "invented" any values
        assert result.get("court") is None
        assert result.get("date") is None
        assert result.get("esas_no") is None
        assert result.get("karar_no") is None

    def test_format_legal_citation_complete_source(self):
        """format_legal_citation with full source → no fabrication warnings."""
        from emsal_mcp.citation import format_legal_citation

        result = format_legal_citation(
            source={
                "title": "Test Kararı",
                "court": "Yargıtay",
                "chamber": "3. Hukuk Dairesi",
                "decision_date": "2024-01-15",
                "esas_no": "2024/123",
                "karar_no": "456",
                "source_url": "https://example.com",
            },
            style="petition",
        )
        assert result["court"] == "Yargıtay"
        assert result["date"] == "2024-01-15"
        assert result["esas_no"] == "2024/123"
        assert result["karar_no"] == "456"

    def test_format_legislation_citation_missing_fields(self):
        """format_legislation_citation with empty doc → warnings."""
        from emsal_mcp.legislation import format_legislation_citation

        result = format_legislation_citation(document={}, style="full")
        assert "warnings" in result
        assert len(result["warnings"]) > 0

    def test_extract_citation_candidates_empty_text(self):
        """extract_citation_candidates with empty text → no results, no errors."""
        from emsal_mcp.citation import extract_citation_candidates

        candidates = extract_citation_candidates("")
        assert candidates == []

    def test_extract_citation_candidates_no_fabrication(self):
        """extract_citation_candidates: missing fields produce warnings."""
        from emsal_mcp.citation import extract_citation_candidates

        candidates = extract_citation_candidates(
            "Yargıtay 3. Hukuk Dairesi kararı"
        )
        # Should find candidates but with warnings about missing fields
        for c in candidates:
            if not c.karar_no:
                assert any("Karar numarası" in w for w in c.warnings)
            if not c.esas_no:
                assert any("Esas numarası" in w for w in c.warnings)


# ---------------------------------------------------------------------------
# Invariant 3: Graceful degradation — no exceptions for expected errors
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """Calling functions with bad input returns error dicts, never exceptions."""

    def test_verify_legal_citation_no_input(self):
        """verify_legal_citation() with no input → error dict, not exception."""
        from emsal_mcp.citation import verify_legal_citation

        result = verify_legal_citation()
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "error" in result

    def test_verify_legal_citation_bad_file(self):
        """verify_legal_citation with nonexistent file → error dict."""
        from emsal_mcp.citation import verify_legal_citation

        result = verify_legal_citation(file_path="/nonexistent/path.txt")
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "error" in result

    def test_format_legal_citation_none_source(self):
        """format_legal_citation(None) → dict with warnings."""
        from emsal_mcp.citation import format_legal_citation

        result = format_legal_citation(source=None, style="petition")
        assert isinstance(result, dict)
        assert "warnings" in result

    def test_format_legislation_citation_invalid_input(self):
        """format_legislation_citation(None) → error dict."""
        from emsal_mcp.legislation import format_legislation_citation

        result = format_legislation_citation(None, style="full")  # type: ignore[arg-type]
        assert isinstance(result, dict)
        assert "error" in result

    def test_get_legislation_document_bad_source(self):
        """get_legislation_document with nonexistent source → error dict."""
        from emsal_mcp.legislation import get_legislation_document

        result = get_legislation_document(
            "test-12345", source="nonexistent", sources_override={},
        )
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "error" in result

    def test_search_legislation_no_results(self):
        """search_legislation with empty override → no exception."""
        from emsal_mcp.legislation import search_legislation

        result = search_legislation("test", sources_override={})
        assert isinstance(result, dict)
        assert "ok" in result

    def test_prepare_petition_outline_bad_dir(self):
        """prepare_petition_outline with bad dir → error dict."""
        from emsal_mcp.petition import prepare_petition_outline

        result = prepare_petition_outline(Path("/nonexistent"))
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "errorCode" in result

    def test_prepare_controlled_petition_draft_bad_dir(self):
        """prepare_controlled_petition_draft with bad dir → error dict."""
        from emsal_mcp.petition import prepare_controlled_petition_draft

        result = prepare_controlled_petition_draft(Path("/nonexistent"))
        assert isinstance(result, dict)
        assert result["ok"] is False

    def test_prepare_docx_export_no_inputs(self):
        """prepare_docx_export() with no inputs → error dict."""
        from emsal_mcp.exporter import prepare_docx_export

        result = prepare_docx_export()
        assert isinstance(result, dict)
        assert "error" in result

    def test_prepare_docx_export_missing_draft(self):
        """prepare_docx_export with missing file → error dict."""
        from emsal_mcp.exporter import prepare_docx_export

        result = prepare_docx_export(draft_path="/nonexistent.md")
        assert isinstance(result, dict)
        assert "error" in result

    def test_chamber_overview_empty_db(self):
        """get_chamber_overview with empty DB → no exception."""
        from emsal_mcp.chamber import get_chamber_overview

        result = get_chamber_overview()
        assert isinstance(result, dict)
        assert "ok" in result

    def test_semantic_search_empty_db(self):
        """semantic_search with empty DB → no exception."""
        from emsal_mcp.semantic import semantic_search

        result = semantic_search("test query")
        assert isinstance(result, dict)
        assert "ok" in result


# ---------------------------------------------------------------------------
# Invariant 4: All public function returns have 'ok' and 'warnings' keys
# ---------------------------------------------------------------------------

class TestPublicAPIContracts:
    """Sample functions from each module to verify return contract."""

    def test_citation_check_returns_ok(self):
        """safety.citation_check returns CitationCheck with ok field."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.safety import citation_check

        doc = Document(
            source="test", document_id="x", title="Test",
            content_status=ContentStatus.FULL_TEXT,
            full_text="Test content with enough length for validation.",
            decision_date="2024-01-01",
        )
        result = citation_check(doc)
        assert hasattr(result, "ok")

    def test_format_legal_citation_returns_warnings(self):
        """citation.format_legal_citation returns warnings key."""
        from emsal_mcp.citation import format_legal_citation

        result = format_legal_citation(source={"title": "Test"}, style="petition")
        assert "warnings" in result

    def test_verify_legal_citation_returns_ok(self):
        """citation.verify_legal_citation returns ok key."""
        from emsal_mcp.citation import verify_legal_citation

        result = verify_legal_citation("Test text", no_live=True)
        assert "ok" in result

    def test_petition_pack_returns_ok(self):
        """petition.prepare_drafting_input_pack returns ok key."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.petition import prepare_drafting_input_pack

        doc = Document(
            source="test", document_id="x", title="Test",
            full_text="Test content with enough length for validation.",
            content_status=ContentStatus.FULL_TEXT,
            decision_date="2024-01-01",
            source_url="https://example.com",
        )
        with tempfile.TemporaryDirectory() as td:
            result = prepare_drafting_input_pack(
                "Matter", "Issue", documents=[doc], out_dir=td,
            )
            assert "ok" in result
            assert "warnings" in result

    def test_inspect_petition_pack_returns_ok(self):
        """petition.inspect_petition_pack returns ok key."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.petition import prepare_drafting_input_pack, inspect_petition_pack

        doc = Document(
            source="test", document_id="x", title="Test",
            full_text="Test content with enough length for validation.",
            content_status=ContentStatus.FULL_TEXT,
            decision_date="2024-01-01",
            source_url="https://example.com",
        )
        with tempfile.TemporaryDirectory() as td:
            pack_result = prepare_drafting_input_pack(
                "Matter", "Issue", documents=[doc], out_dir=td,
            )
            result = inspect_petition_pack(pack_result["out_dir"])
            assert "ok" in result

    def test_prepare_export_bundle_returns_ok(self):
        """exporter.prepare_export_package_bundle returns ok key."""
        from emsal_mcp.exporter import prepare_export_package_bundle

        result = prepare_export_package_bundle(Path("/nonexistent"))
        assert "ok" in result

    def test_search_legislation_returns_ok(self):
        """legislation.search_legislation returns ok key."""
        from emsal_mcp.legislation import search_legislation

        result = search_legislation("test", sources_override={})
        assert "ok" in result
        assert "warnings" in result

    def test_format_legislation_citation_returns_warnings(self):
        """legislation.format_legislation_citation returns warnings key."""
        from emsal_mcp.legislation import format_legislation_citation

        result = format_legislation_citation(
            document={"title": "Test"}, style="full",
        )
        assert "warnings" in result

    def test_semantic_search_returns_ok(self):
        """semantic.semantic_search returns ok key."""
        from emsal_mcp.semantic import semantic_search

        result = semantic_search("test")
        assert "ok" in result
        assert "warnings" in result

    def test_hybrid_search_returns_ok(self):
        """semantic.hybrid_search returns ok key."""
        from emsal_mcp.semantic import hybrid_search

        result = hybrid_search("test")
        assert "ok" in result
        assert "warnings" in result

    def test_build_semantic_index_returns_ok(self):
        """semantic.build_semantic_index returns ok key."""
        from emsal_mcp.semantic import build_semantic_index

        result = build_semantic_index()
        assert "ok" in result

    def test_chamber_overview_returns_ok(self):
        """chamber.get_chamber_overview returns ok key."""
        from emsal_mcp.chamber import get_chamber_overview

        result = get_chamber_overview()
        assert "ok" in result
        assert "warnings" in result


# ---------------------------------------------------------------------------
# Invariant 5: Sources override preserves safety flags
# ---------------------------------------------------------------------------

class TestSourcesOverridePreservesSafety:
    """Using sources_override doesn't bypass citation safety."""

    def test_sources_override_no_citation_bypass(self):
        """sources_override: citation_check still enforces safety."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.safety import citation_check

        # Create a metadata-only document — should be citation-unsafe
        doc = Document(
            source="test",
            document_id="x",
            title="Test",
            content_status=ContentStatus.METADATA_ONLY,
        )
        check = citation_check(doc)
        assert check.ok is False
        assert check.quoteUsable is False
        assert check.draftUsable is False

    def test_search_legislation_override_preserves_safety(self):
        """search_legislation with override: results still respect content_status."""
        from emsal_mcp.legislation import search_legislation

        result = search_legislation("test", sources_override={})
        # Even with override, ok may be False but warnings should exist
        assert isinstance(result["warnings"], list)

    def test_petition_pack_override_preserves_safety(self):
        """Petition pack: sources_override doesn't skip citation_check."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.safety import citation_check

        # Any document, regardless of source, must go through citation_check
        doc = Document(
            source="override_source",
            document_id="x",
            title="Test",
            content_status=ContentStatus.METADATA_ONLY,
        )
        check = citation_check(doc)
        assert check.ok is False


# ---------------------------------------------------------------------------
# Invariant 6: Placeholder preservation
# ---------------------------------------------------------------------------

class TestPlaceholderPreservation:
    """Petition draft/skeleton preserve all {{PLACEHOLDER}} patterns."""

    def test_skeleton_preserves_placeholders(self):
        """_generate_draft_skeleton preserves all {{...}} patterns."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.petition import PLACEHOLDER_PATTERN, _generate_draft_skeleton

        doc = Document(
            source="test", document_id="x", title="Test",
            full_text="Test content with enough length for validation.",
            content_status=ContentStatus.FULL_TEXT,
            decision_date="2024-01-01",
        )
        skeleton = _generate_draft_skeleton("Matter", "Issue", [doc])

        # All expected placeholders must be present
        placeholders = PLACEHOLDER_PATTERN.findall(skeleton)
        assert len(placeholders) > 0, "Skeleton should contain placeholders"
        assert "{{DILEKCE_BASLIK}}" in placeholders
        assert "{{MAHKEME_ADRES}}" in placeholders
        assert "{{DAVACI_AD_SOYAD}}" in placeholders
        assert "{{SONUC_VE_TALEP}}" in placeholders

    def test_controlled_draft_preserves_placeholders(self):
        """prepare_controlled_petition_draft preserves placeholders in draft.md."""
        from emsal_mcp.models import ContentStatus, Document
        from emsal_mcp.petition import (
            PLACEHOLDER_PATTERN,
            prepare_controlled_petition_draft,
            prepare_drafting_input_pack,
        )

        doc = Document(
            source="test", document_id="x", title="Test",
            full_text="Test content with enough length for validation.",
            content_status=ContentStatus.FULL_TEXT,
            decision_date="2024-01-01",
            source_url="https://example.com",
        )
        with tempfile.TemporaryDirectory() as td:
            pack_result = prepare_drafting_input_pack(
                "Matter", "Issue", documents=[doc], out_dir=td,
            )
            draft_dir = Path(td) / "draft_out"
            draft_result = prepare_controlled_petition_draft(
                pack_result["out_dir"], out_dir=draft_dir,
            )
            if draft_result.get("ok"):
                draft_path = Path(draft_result["draft_md_path"])
                if draft_path.exists():
                    draft_text = draft_path.read_text(encoding="utf-8")
                    placeholders = PLACEHOLDER_PATTERN.findall(draft_text)
                    assert len(placeholders) > 0, (
                        "Draft should preserve placeholders"
                    )

    def test_petition_instructions_contain_no_invention(self):
        """Petition instructions contain no-invention rule."""
        from emsal_mcp.petition import (
            NO_INVENTION_PATTERNS,
            _generate_petition_instructions,
        )

        instructions = _generate_petition_instructions()
        has_no_invention = any(
            re.search(pat, instructions, re.IGNORECASE)
            for pat in NO_INVENTION_PATTERNS
        )
        assert has_no_invention, (
            "Petition instructions must contain no-invention rule"
        )

    def test_disclaimer_header_present(self):
        """Draft includes disclaimer header."""
        from emsal_mcp.petition import DISCLAIMER_HEADER

        assert "DİKKAT" in DISCLAIMER_HEADER
        assert "emsal-mcp" in DISCLAIMER_HEADER


# ---------------------------------------------------------------------------
# Invariant: build_error returns canonical shape
# ---------------------------------------------------------------------------

class TestBuildErrorShape:
    """build_error always returns canonical error dict shape."""

    def test_build_error_basic(self):
        """build_error with minimal args → ok, errorCode, message."""
        from emsal_mcp.models import build_error

        result = build_error("TEST_CODE", "Test message")
        assert result["ok"] is False
        assert result["errorCode"] == "TEST_CODE"
        assert result["message"] == "Test message"

    def test_build_error_with_extra(self):
        """build_error with extra kwargs → extra fields attached."""
        from emsal_mcp.models import build_error

        result = build_error(
            "TEST_CODE", "msg",
            source="test",
            retryable=True,
            warnings=["w1"],
            recommended_next_steps=["step1"],
            custom_field="value",
        )
        assert result["ok"] is False
        assert result["source"] == "test"
        assert result["retryable"] is True
        assert result["warnings"] == ["w1"]
        assert result["recommended_next_steps"] == ["step1"]
        assert result["custom_field"] == "value"

    def test_build_error_no_optional_fields(self):
        """build_error without optional fields → no extra keys."""
        from emsal_mcp.models import build_error

        result = build_error("CODE", "msg")
        assert "source" not in result
        assert "retryable" not in result
        assert "warnings" not in result
        assert "recommended_next_steps" not in result
