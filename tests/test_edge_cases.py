"""M-46: Edge-Case & Error-Path Hardening Tests.

Deterministic edge-case tests for critical modules: citation, petition,
legislation, semantic, safety.  Every test verifies the function returns a
dict (or build_error dict) and NEVER crashes / throws exceptions.
"""
from __future__ import annotations

import tempfile

import pytest

pytestmark = [pytest.mark.unit]

from emsal_mcp.citation import (
    extract_citation_candidates,
    format_legal_citation,
    verify_legal_citation,
)
from emsal_mcp.models import ContentStatus, Document, build_error
from emsal_mcp.petition import (
    inspect_petition_pack,
    prepare_controlled_petition_draft,
    prepare_drafting_input_pack,
    prepare_petition_outline,
)
from emsal_mcp.safety import build_input_pack, citation_check
from emsal_mcp.semantic import (
    _build_query_vector,
    _cosine_similarity,
    _expand_query,
    _generate_snippet,
    _tokenize,
)
from emsal_mcp.legislation import (
    format_legislation_citation,
    search_legislation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(**overrides) -> Document:
    defaults = {
        "source": "test",
        "document_id": "EDGE-001",
        "title": "Edge Case Test",
        "court": "Yargitay",
        "chamber": "3. Hukuk Dairesi",
        "decision_date": "2024-01-15",
        "esas_no": "2023/100",
        "karar_no": "2024/50",
        "source_url": "https://example.test/doc/001",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": "Yargitay 3. Hukuk Dairesi E.2023/100 K.2024/50 karari.",
    }
    defaults.update(overrides)
    return Document(**defaults)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Empty Inputs
# ═══════════════════════════════════════════════════════════════════════════

class TestCitationEmptyInputs:
    def test_extract_empty_string(self):
        result = extract_citation_candidates("", limit=5)
        assert isinstance(result, list)

    def test_extract_empty_list_no_crash(self):
        result = extract_citation_candidates("no citations here", limit=0)
        assert isinstance(result, list)
        assert result == []

    def test_format_legal_citation_none_source(self):
        result = format_legal_citation(source=None, document_id=None)
        assert isinstance(result, dict)

    def test_format_legal_citation_empty_dict(self):
        result = format_legal_citation(source={})
        assert isinstance(result, dict)

    def test_verify_citation_none_text(self):
        result = verify_legal_citation(text=None)
        assert isinstance(result, dict)
        assert result.get("errorCode") == "INVALID_INPUT"

    def test_verify_citation_empty_string(self):
        result = verify_legal_citation(text="")
        assert isinstance(result, dict)
        # Empty text should either return ok or an error, never crash
        assert "ok" in result or "errorCode" in result


class TestLegislationEmptyInputs:
    def test_format_legislation_citation_empty_dict(self):
        result = format_legislation_citation(document={})
        assert isinstance(result, dict)
        assert "formatted_citation" in result

    def test_search_legislation_empty_query(self):
        result = search_legislation(query="", sources_override={})
        assert isinstance(result, dict)
        assert "ok" in result

    def test_search_legislation_none_source(self):
        result = search_legislation(query="test", sources_override={})
        assert isinstance(result, dict)
        assert "ok" in result


class TestSafetyEmptyInputs:
    def test_citation_check_empty_document(self):
        doc = _make_doc(
            content_status=ContentStatus.METADATA_ONLY,
            full_text=None,
            markdown=None,
            decision_date=None,
            esas_no=None,
            karar_no=None,
            source_url=None,
        )
        result = citation_check(doc)
        assert result.ok is False

    def test_build_input_pack_empty_list(self):
        result = build_input_pack(matter="", issue="", documents=[])
        # Returns InputPack — should never crash
        assert hasattr(result, "matter")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Very Large Inputs
# ═══════════════════════════════════════════════════════════════════════════

class TestSemanticLargeInputs:
    def test_tokenize_large_text(self):
        large = "word " * 50000  # ~250KB
        result = _tokenize(large)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_expand_query_long_string(self):
        long_query = " ".join(["kelime"] * 500)
        result = _expand_query(long_query)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_build_query_vector_large(self):
        large = " ".join(["test"] * 1000)
        vec = _build_query_vector(large)
        assert isinstance(vec, dict)

    def test_cosine_similarity_identical(self):
        vec = {"a": 1.0, "b": 2.0}
        score = _cosine_similarity(vec, vec)
        assert abs(score - 1.0) < 0.001

    def test_generate_snippet_large_text(self):
        large_text = "Bu bir test cumlesidir. " * 10000
        snippet, hl = _generate_snippet(large_text, "test")
        assert isinstance(snippet, str)
        assert len(snippet) <= 300  # snippet should be truncated


class TestCitationLargeDocumentId:
    def test_format_with_long_doc_id(self):
        long_id = "X" * 500
        result = format_legal_citation(
            source={
                "document_id": long_id,
                "source": "test",
                "court": "Yargitay",
                "content_status": "full_text",
            }
        )
        assert isinstance(result, dict)
        assert result.get("document_id") == long_id


# ═══════════════════════════════════════════════════════════════════════════
# 3. Malformed Inputs
# ═══════════════════════════════════════════════════════════════════════════

class TestCitationMalformed:
    def test_extract_gibberish(self):
        result = extract_citation_candidates("!@#$%^&*()_+ 12345 {}[]", limit=5)
        assert isinstance(result, list)

    def test_format_legal_citation_bad_date(self):
        result = format_legal_citation(
            source={
                "document_id": "TEST-001",
                "source": "test",
                "court": "Yargitay",
                "decision_date": "not-a-date",
                "content_status": "full_text",
            }
        )
        assert isinstance(result, dict)
        assert result.get("date") == "not-a-date"  # preserved as-is

    def test_format_legal_citation_invalid_json_in_metadata(self):
        result = format_legal_citation(
            source={
                "document_id": "TEST-002",
                "source": "test",
                "metadata": "not-a-json-string",
                "content_status": "metadata_only",
            }
        )
        assert isinstance(result, dict)

    def test_verify_citation_bad_file_path(self):
        result = verify_legal_citation(file_path="/nonexistent/path/file.txt")
        assert isinstance(result, dict)
        assert result.get("errorCode") == "FILE_NOT_FOUND"


class TestLegislationMalformed:
    def test_format_legislation_bad_style(self):
        result = format_legislation_citation(
            document={"title": "Test", "legislation_no": "123"},
            style="bogus_style",
        )
        assert isinstance(result, dict)
        assert "formatted_citation" in result
        assert any("Bilinmeyen stil" in w for w in result.get("warnings", []))


# ═══════════════════════════════════════════════════════════════════════════
# 4. Unicode Extremes
# ═══════════════════════════════════════════════════════════════════════════

class TestCitationUnicode:
    def test_extract_emoji_text(self):
        text = "Yargitay mahkemesi \U0001f600 \U0001f525 E.2023/100 karari"
        candidates = extract_citation_candidates(text, limit=5)
        assert isinstance(candidates, list)

    def test_extract_rtl_text(self):
        text = "\u0627\u0644\u062a\u0634\u0643\u064a\u0644 Yargitay 3. Daire E.2023/100"
        candidates = extract_citation_candidates(text, limit=5)
        assert isinstance(candidates, list)

    def test_extract_combining_characters(self):
        # Turkish combining characters
        text = "Ya\u0307rg\u0131tay 3. Hukuk Dairesi E.2023/100"
        candidates = extract_citation_candidates(text, limit=5)
        assert isinstance(candidates, list)

    def test_format_citation_unicode_title(self):
        result = format_legal_citation(
            source={
                "document_id": "UNI-001",
                "source": "test",
                "court": "Yarg\u0131tay",
                "chamber": "3. Hukuk Dairesi",
                "decision_date": "2024-01-15",
                "esas_no": "2023/100",
                "content_status": "full_text",
            }
        )
        assert isinstance(result, dict)
        assert "Yarg" in result.get("formatted_citation", "")

    def test_expand_query_unicode(self):
        result = _expand_query("s\u00f6zle\u015fmelerin t\u00fcrk\u00e7e")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_tokenize_null_bytes(self):
        result = _tokenize("test\x00word\x00another")
        assert isinstance(result, list)

    def test_format_legislation_unicode(self):
        result = format_legislation_citation(
            document={"title": "K\u0131s\u0131m Test \u00d6rnekleri", "legislation_no": "123"},
            style="full",
        )
        assert isinstance(result, dict)
        assert "K\u0131s\u0131m" in result.get("formatted_citation", "")


# ═══════════════════════════════════════════════════════════════════════════
# 5. Bogus / Edge-Case Numeric Inputs
# ═══════════════════════════════════════════════════════════════════════════

class TestSemanticBogusInputs:
    def test_cosine_similarity_empty_vectors(self):
        assert _cosine_similarity({}, {}) == 0.0
        assert _cosine_similarity({"a": 1.0}, {}) == 0.0
        assert _cosine_similarity({}, {"a": 1.0}) == 0.0

    def test_build_query_vector_empty(self):
        vec = _build_query_vector("")
        assert vec == {}

    def test_build_query_vector_whitespace(self):
        vec = _build_query_vector("   ")
        assert isinstance(vec, dict)

    def test_generate_snippet_empty(self):
        snippet, hl = _generate_snippet("", "query")
        assert snippet == ""
        assert hl is False

    def test_generate_snippet_no_query(self):
        snippet, hl = _generate_snippet("some text", "")
        assert isinstance(snippet, str)


class TestCitationBogusLimits:
    def test_extract_negative_limit(self):
        result = extract_citation_candidates("text", limit=-1)
        assert isinstance(result, list)
        assert result == []

    def test_extract_huge_limit(self):
        result = extract_citation_candidates(
            "Yargitay E.2023/100", limit=999999
        )
        assert isinstance(result, list)

    def test_verify_float_limit(self):
        result = verify_legal_citation(
            text="Yargitay E.2023/100",
            limit=1.5,
            no_live=True,
        )
        assert isinstance(result, dict)

    def test_verify_huge_page_number(self):
        result = verify_legal_citation(
            text="Yargitay E.2023/100",
            limit=10,
            no_live=True,
        )
        assert isinstance(result, dict)


class TestPetitionEdgeCases:
    def test_inspect_nonexistent_pack(self):
        result = inspect_petition_pack("/nonexistent/path/pack")
        assert isinstance(result, dict)
        assert result.get("ok") is False

    def test_outline_nonexistent_pack(self):
        result = prepare_petition_outline("/nonexistent/path/pack")
        assert isinstance(result, dict)
        assert result.get("ok") is False

    def test_draft_nonexistent_pack(self):
        result = prepare_controlled_petition_draft("/nonexistent/path/pack")
        assert isinstance(result, dict)
        assert result.get("ok") is False

    def test_pack_with_empty_matter_issue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = prepare_drafting_input_pack(
                matter="",
                issue="",
                documents=[],
                out_dir=tmpdir,
            )
            assert isinstance(result, dict)
            assert result.get("ok") is True

    def test_pack_with_huge_strings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = prepare_drafting_input_pack(
                matter="M" * 100000,
                issue="I" * 100000,
                documents=[],
                out_dir=tmpdir,
            )
            assert isinstance(result, dict)
            assert result.get("ok") is True


# ═══════════════════════════════════════════════════════════════════════════
# 6. Build Error Never Crashes
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildErrorNeverCrashes:
    def test_build_error_minimal(self):
        result = build_error("TEST_CODE", "test message")
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert result["errorCode"] == "TEST_CODE"

    def test_build_error_with_extra_kwargs(self):
        result = build_error(
            "TEST_CODE",
            "msg",
            extra1="val1",
            extra2=42,
            nested={"key": "value"},
        )
        assert isinstance(result, dict)
        assert result["extra1"] == "val1"
        assert result["nested"]["key"] == "value"

    def test_build_error_empty_message(self):
        result = build_error("CODE", "")
        assert isinstance(result, dict)
        assert result["message"] == ""
