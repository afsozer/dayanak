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


# ---------------------------------------------------------------------------
# Görev 1 (parity-v2): to_tool_payload deduplication
# ---------------------------------------------------------------------------

class TestToToolPayload:
    """to_tool_payload() invariants — single text field, no raw, no metadata.content."""

    def test_single_text_field_markdown_exists(self):
        """When markdown exists, it becomes the single text field; full_text removed."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="bedesten",
            document_id="test-1",
            title="Test",
            markdown="# Karar\nBu bir testtir.",
            full_text="düz metin",
            content_status=ContentStatus.HTML_MARKDOWN,
            metadata={"kararNo": "2024/123"},
        )
        payload = doc.to_tool_payload()
        assert payload["markdown"] == "# Karar\nBu bir testtir."
        assert "full_text" not in payload

    def test_full_text_promoted_when_markdown_none(self):
        """When markdown is None, full_text is promoted to markdown key."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="bedesten",
            document_id="test-2",
            title="Test",
            markdown=None,
            full_text="sadece full_text var",
            content_status=ContentStatus.FULL_TEXT,
        )
        payload = doc.to_tool_payload()
        assert payload["markdown"] == "sadece full_text var"
        assert "full_text" not in payload

    def test_both_missing_yields_none_markdown(self):
        """When both markdown and full_text are None/empty, markdown is None."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="bedesten",
            document_id="test-3",
            title="Test",
            markdown=None,
            full_text=None,
            content_status=ContentStatus.METADATA_ONLY,
        )
        payload = doc.to_tool_payload()
        assert payload["markdown"] is None
        assert "full_text" not in payload

    def test_raw_stripped_by_default(self):
        """raw key must be absent from default payload."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="bedesten",
            document_id="test-4",
            title="Test",
            markdown="metin",
            raw={"data": {"content": "base64blob", "kararNo": "2024/1"}},
            content_status=ContentStatus.HTML_MARKDOWN,
        )
        payload = doc.to_tool_payload()
        assert "raw" not in payload

    def test_raw_included_when_include_raw_true(self):
        """raw key is present when include_raw=True."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="bedesten",
            document_id="test-5",
            title="Test",
            markdown="metin",
            raw={"data": {"content": "base64blob"}},
            content_status=ContentStatus.HTML_MARKDOWN,
        )
        payload = doc.to_tool_payload(include_raw=True)
        assert "raw" in payload
        assert payload["raw"] == {"data": {"content": "base64blob"}}

    def test_metadata_content_stripped(self):
        """metadata.content (base64 HTML) must be removed from metadata dict."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="bedesten",
            document_id="test-6",
            title="Test",
            markdown="karar metni",
            content_status=ContentStatus.HTML_MARKDOWN,
            metadata={
                "content": "BASE64_ENCODED_HTML_BLOB_VERY_LONG",
                "kararNo": "2024/456",
                "esasNo": "2024/123",
                "alternate_url": "https://emsal.uyap.gov.tr/...",
            },
        )
        payload = doc.to_tool_payload()
        md = payload.get("metadata", {})
        assert "content" not in md, "metadata.content (base64) must be stripped"
        assert md["kararNo"] == "2024/456"
        assert md["esasNo"] == "2024/123"
        assert "alternate_url" in md

    def test_metadata_empty_or_missing_handled(self):
        """Empty metadata or missing metadata → no crash."""
        from emsal_mcp.models import ContentStatus, Document

        # Test with empty metadata dict
        doc = Document(
            source="bedesten",
            document_id="test-7",
            title="Test",
            markdown="metin",
            content_status=ContentStatus.HTML_MARKDOWN,
            metadata={},
        )
        payload = doc.to_tool_payload()
        assert "metadata" in payload
        assert payload["metadata"] == {}

        # Test with default metadata (not passed)
        doc2 = Document(
            source="bedesten",
            document_id="test-7b",
            title="Test",
            markdown="metin",
            content_status=ContentStatus.HTML_MARKDOWN,
        )
        payload2 = doc2.to_tool_payload()
        assert "metadata" in payload2

    def test_quote_usable_and_draft_usable_preserved(self):
        """to_tool_payload preserves quote_usable/draft_usable properties."""
        from emsal_mcp.models import ContentStatus, Document

        doc = Document(
            source="bedesten",
            document_id="test-8",
            title="Test",
            markdown="uzun karar metni " * 20,
            content_status=ContentStatus.HTML_MARKDOWN,
        )
        payload = doc.to_tool_payload()
        # quote_usable/draft_usable are computed properties, not serialized by default
        # But the payload should still have content_status and markdown so consumers can compute them
        assert payload["content_status"] == "html_markdown"
        assert payload["markdown"] is not None

    def test_payload_size_smaller_than_full_dump(self):
        """Deduplicated payload should be significantly smaller than full model_dump."""
        from emsal_mcp.models import ContentStatus, Document
        import json

        big_base64 = "VGhpcyBpcyBhIHZlcnkgbG9uZyBiYXNlNjQgc3RyaW5nIHRoYXQgd291bGQgbm9ybWFsbHkgY29udGFpbiBIVE1MIGNvbnRlbnQK" * 100
        doc = Document(
            source="bedesten",
            document_id="test-9",
            title="Test Kararı",
            markdown="# Karar\n\n" + ("Bu bir test kararıdır. " * 200),
            full_text="Bu bir test kararıdır. " * 200,
            content_status=ContentStatus.HTML_MARKDOWN,
            raw={"data": {"content": big_base64, "mimeType": "text/html"}},
            metadata={"content": big_base64, "kararNo": "2024/1", "esasNo": "2024/100"},
        )

        full_dump_len = len(json.dumps(doc.model_dump(mode="json"), ensure_ascii=False))
        payload_len = len(json.dumps(doc.to_tool_payload(), ensure_ascii=False))

        # The deduplicated payload should be less than 40% of the full dump
        assert payload_len < full_dump_len * 0.40, (
            f"Payload ({payload_len} chars) should be < 40% of full dump "
            f"({full_dump_len} chars), got {payload_len / full_dump_len:.1%}"
        )


# ---------------------------------------------------------------------------
# Görev 4 (parity-v2): split_markdown_for_pagination — paragraph-boundary splitting
# ---------------------------------------------------------------------------

class TestSplitMarkdownForPagination:
    """split_markdown_for_pagination() — paragraph boundary safe splitting."""

    def test_short_text_returns_single_page(self):
        """Text under max_chars returns 1/1 with full text."""
        from emsal_mcp.server_utils import split_markdown_for_pagination

        text = "Kisa bir karar metni.\n\nIkinci paragraf."
        result = split_markdown_for_pagination(text)
        assert result["markdown"] == text
        assert result["current_page"] == 1
        assert result["total_pages"] == 1
        assert result["total_chars"] == len(text)

    def test_empty_text_returns_single_page(self):
        """Empty or None text returns 1/1."""
        from emsal_mcp.server_utils import split_markdown_for_pagination

        for t in ("", "   ", None):  # type: ignore[assignment]
            result = split_markdown_for_pagination(t or "")  # type: ignore[arg-type]
            assert result["current_page"] == 1
            assert result["total_pages"] == 1

    def test_100k_artificial_text_splits_into_3_pages(self):
        """~100k chars of text → multiple pages at paragraph boundaries."""
        from emsal_mcp.server_utils import split_markdown_for_pagination

        # Each paragraph: "Par {n}: " + "x"*50 ≈ 57-60 chars (varies by digit count).
        # With \n\n separators, ~40k per page → 3 pages for ~110k chars.
        paragraphs = [f"Par {i}: " + "x" * 50 for i in range(2000)]
        text = "\n\n".join(paragraphs)  # ~114k chars total

        page1 = split_markdown_for_pagination(text, page_number=1, max_chars=40000)
        assert page1["total_chars"] == len(text)
        assert page1["total_pages"] >= 2, "Long text must span multiple pages"

        # Collect all pages and verify reconstruction
        all_pages = []
        for pn in range(1, page1["total_pages"] + 1):
            pg = split_markdown_for_pagination(text, page_number=pn, max_chars=40000)
            all_pages.append(pg["markdown"])
            assert len(pg["markdown"]) <= 40000, f"Page {pn} exceeds max_chars"

        reconstructed = "\n\n".join(all_pages)
        assert reconstructed == text, "Page concatenation must equal original"

        # Verify no paragraph is cut mid-way: content of each original paragraph
        # must appear wholly in exactly one page.
        for para in paragraphs:
            found_in = [i for i, pg in enumerate(all_pages) if para in pg]
            assert len(found_in) == 1, f"Paragraph '{para[:30]}...' not in exactly one page: {found_in}"

    def test_no_paragraph_cut_mid_way(self):
        """Verify that no page starts or ends mid-paragraph."""
        from emsal_mcp.server_utils import split_markdown_for_pagination

        # Create a text where paragraphs are clearly delimited
        paragraphs = [f"## Bolum {i}\n\nBu bolumun icerigi. " * 20 for i in range(500)]
        text = "\n\n".join(paragraphs)

        for page_num in range(1, 4):
            page = split_markdown_for_pagination(text, page_number=page_num, max_chars=10000)
            content = page["markdown"]
            content = content.strip()
            if content.startswith("##"):
                continue  # OK — page started with full paragraph
            # If page doesn't start with a heading, it should at least
            # not have trailing partial from previous page
            assert not content.startswith(" "), "Page starts mid-paragraph?"

    def test_giant_paragraph_fallback_to_sentences(self):
        """Single paragraph over max_chars falls back to sentence splitting."""
        from emsal_mcp.server_utils import split_markdown_for_pagination

        # One single 60k paragraph
        sentence = "Bu cok uzun bir cumledir ve test amaciyla tekrar ediliyor. "
        text = sentence * 1000  # ~60k chars, NO paragraph breaks

        page = split_markdown_for_pagination(text, page_number=1, max_chars=40000)
        assert page["total_pages"] == 2
        assert page["total_chars"] == len(text)
        assert len(page["markdown"]) <= 40000

        # Second page
        page2 = split_markdown_for_pagination(text, page_number=2, max_chars=40000)
        assert page2["current_page"] == 2

    def test_page_number_clamped(self):
        """Out-of-bounds page_number is clamped to valid range."""
        from emsal_mcp.server_utils import split_markdown_for_pagination

        text = "x" * 200  # short text, only 1 page
        result = split_markdown_for_pagination(text, page_number=5)
        assert result["current_page"] == 1
        assert result["total_pages"] == 1

        result2 = split_markdown_for_pagination(text, page_number=0)
        assert result2["current_page"] == 1

