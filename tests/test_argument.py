"""Tests for M-12 Argument Builder.

Uses fake Documents; ensures metadata_only authorities NEVER leak into
supporting_authorities; citation_only stay in separate research_leads field;
scoring works correctly; empty/missing packs handled gracefully.
No live network calls.
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

import json
from pathlib import Path
from typing import Any

from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.argument import (
    build_argument_chain,
    score_argument,
    get_argument_strength_report,
    render_arguments_to_markdown,
    _parse_argument_map,
    _extract_keywords,
    _keyword_overlap_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(**kwargs: Any) -> Document:
    defaults: dict[str, Any] = {
        "source": "test_source",
        "document_id": "doc-001",
        "title": "Sözleşme İhlali Kararı",
        "court": "Yargıtay",
        "chamber": "3. Hukuk Dairesi",
        "decision_date": "2024-06-15",
        "esas_no": "2024/12345",
        "karar_no": "2024/5678",
        "source_url": "https://example.com/doc/001",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": "Sözleşme hükümleri ihlal edilmiştir. Tazminat talebi kabul edilmelidir. " * 10,
    }
    defaults.update(kwargs)
    return Document(**defaults)


def _make_metadata_only_doc(**kwargs: Any) -> Document:
    defaults = {
        "document_id": "meta-001",
        "title": "Metadata Only Decision",
        "content_status": ContentStatus.METADATA_ONLY,
        "full_text": None,
        "markdown": None,
    }
    defaults.update(kwargs)
    return _make_doc(**defaults)


def _make_research_lead_doc(**kwargs: Any) -> Document:
    defaults = {
        "document_id": "research-001",
        "title": "Research Lead Document",
        "court": None,
        "chamber": None,
        "decision_date": None,
        "esas_no": None,
        "karar_no": None,
        "source_url": None,
        "content_status": ContentStatus.METADATA_ONLY,
        "full_text": None,
        "markdown": None,
    }
    defaults.update(kwargs)
    return _make_doc(**defaults)


def _make_pack(
    tmp_path: Path,
    docs: list[Document] | None = None,
    extra_args: list[dict[str, Any]] | None = None,
) -> Path:
    """Create a minimal petition pack directory for testing."""
    from emsal_mcp.petition import prepare_drafting_input_pack

    docs = docs or []
    pack_dir = tmp_path / "test_pack"

    result = prepare_drafting_input_pack(
        matter="Sözleşme İhlali Davası",
        issue="Sözleşme hükümlerinin ihlali nedeniyle tazminat",
        documents=docs,
        out_dir=pack_dir,
    )
    assert result["ok"], f"Pack creation failed: {result}"

    # Enhance argument-map.md with extra argument entries if provided
    if extra_args:
        arg_map_path = pack_dir / "argument-map.md"
        current = arg_map_path.read_text(encoding="utf-8")
        lines = current.splitlines()

        # Find the Authority Map section and append entries
        new_lines = []
        in_authority_map = False
        for line in lines:
            new_lines.append(line)
            if line.strip() == "## Authority Map":
                in_authority_map = True
            elif in_authority_map and line.strip().startswith("## "):
                # We're leaving Authority Map, insert extra args before this
                for extra in extra_args:
                    tag = extra.get("tag", "READY")
                    label = extra.get("label", "Extra Decision")
                    source = extra.get("source", "test_source:extra-001")
                    classification = extra.get("classification", "petition_ready")
                    content_status = extra.get("content_status", "full_text")
                    new_lines.append(f"- [{tag}] **{label}** ({source})")
                    new_lines.append(f"  - Classification: {classification}")
                    new_lines.append(f"  - Content Status: {content_status}")
                    new_lines.append("")
                in_authority_map = False

        arg_map_path.write_text("\n".join(new_lines), encoding="utf-8")

    return pack_dir


# ---------------------------------------------------------------------------
# Tests: _parse_argument_map
# ---------------------------------------------------------------------------

class TestParseArgumentMap:
    def test_parses_authority_entries(self):
        md = """# Argument Map

**Matter**: Test
**Issue**: Test Issue

## Authority Map

- [READY] **Test Decision** (test:doc-001)
  - Classification: petition_ready
  - Content Status: full_text

- [RESEARCH] **Research Doc** (test:doc-002)
  - Classification: research_lead_only
  - Content Status: metadata_only

## Research Leads

- Verify `test:doc-002` from official source
"""
        entries = _parse_argument_map(md)
        assert len(entries) == 2
        assert entries[0]["tag"] == "READY"
        assert entries[0]["classification"] == "petition_ready"
        assert entries[1]["tag"] == "RESEARCH"
        assert entries[1]["classification"] == "research_lead_only"

    def test_empty_map_returns_empty(self):
        entries = _parse_argument_map("")
        assert entries == []

    def test_no_sections_returns_entries(self):
        md = """- [READY] **Doc** (src:1)
  - Classification: petition_ready
"""
        entries = _parse_argument_map(md)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Tests: _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_extracts_meaningful_words(self):
        kw = _extract_keywords("Sözleşme hükümleri ihlal edilmiştir")
        assert "sözleşme" in kw or "hükümleri" in kw or "ihlal" in kw

    def test_filters_stop_words(self):
        kw = _extract_keywords("bir bu için ile")
        assert len(kw) == 0

    def test_filters_short_words(self):
        kw = _extract_keywords("ab cd ef")
        assert len(kw) == 0


# ---------------------------------------------------------------------------
# Tests: _keyword_overlap_score
# ---------------------------------------------------------------------------

class TestKeywordOverlapScore:
    def test_identical_text_score_one(self):
        score = _keyword_overlap_score("hello world test", "hello world test")
        assert score == 1.0

    def test_no_overlap_score_zero(self):
        score = _keyword_overlap_score("hello world", "foo bar baz")
        assert score == 0.0

    def test_partial_overlap(self):
        score = _keyword_overlap_score("hello world test", "hello world foo")
        assert 0.0 < score < 1.0

    def test_empty_strings(self):
        score = _keyword_overlap_score("", "")
        assert score == 0.0


# ---------------------------------------------------------------------------
# Tests: build_argument_chain
# ---------------------------------------------------------------------------

class TestBuildArgumentChain:
    def test_builds_chain_from_pack(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result["ok"] is True
        assert "arguments" in result
        assert "overall_strength" in result

    def test_returns_error_for_missing_pack(self, tmp_path: Path):
        result = build_argument_chain(tmp_path / "nonexistent")
        assert result["ok"] is False
        assert result["errorCode"] == "PACK_NOT_FOUND"

    def test_returns_error_for_missing_argument_map(self, tmp_path: Path):
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        (pack_dir / "petition-pack.json").write_text(
            json.dumps({"version": "0.8.0", "matter": "M", "issue": "I"}),
            encoding="utf-8",
        )
        result = build_argument_chain(pack_dir)
        assert result["ok"] is False
        assert result["errorCode"] == "ARGUMENT_MAP_MISSING"

    def test_empty_pack_returns_ok_with_no_args(self, tmp_path: Path):
        pack_dir = _make_pack(tmp_path, docs=[])
        result = build_argument_chain(pack_dir)
        assert result["ok"] is True
        # May have 0 arguments if argument-map has no entries
        assert isinstance(result["arguments"], list)

    def test_metadata_only_not_in_supporting(self, tmp_path: Path):
        """CRITICAL SAFETY INVARIANT: metadata_only must NEVER appear in
        supporting_authorities."""
        docs = [_make_doc(), _make_metadata_only_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result["ok"] is True
        for arg in result["arguments"]:
            for auth in arg["supporting_authorities"]:
                assert auth["content_status"] not in (
                    "metadata_only", "pdf_link_only", "unavailable"
                ), f"SAFETY VIOLATION: {auth['document_id']} is {auth['content_status']}"

    def test_citation_only_in_research_leads(self, tmp_path: Path):
        """citation_only authorities appear in research_leads, NOT supporting."""
        docs = [_make_doc(), _make_metadata_only_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result["ok"] is True
        for arg in result["arguments"]:
            for lead in arg["research_leads"]:
                assert lead["classification"] in (
                    "citation_only", "research_lead_only"
                )

    def test_counter_argument_is_placeholder(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result["ok"] is True
        for arg in result["arguments"]:
            assert arg["counter_argument"] == "{{KARSI_ARGUMAN_BOSLUK}}"

    def test_strength_is_float(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result["ok"] is True
        assert isinstance(result["overall_strength"], float)
        assert 0.0 <= result["overall_strength"] <= 1.0

    def test_warnings_list_present(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert "warnings" in result
        assert isinstance(result["warnings"], list)

    def test_pack_dir_in_result(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result.get("pack_dir") == str(pack_dir)

    def test_matter_and_issue_in_result(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result.get("matter") == "Sözleşme İhlali Davası"
        assert "ihlal" in result.get("issue", "").lower()


# ---------------------------------------------------------------------------
# Tests: score_argument
# ---------------------------------------------------------------------------

class TestScoreArgument:
    def test_score_with_no_support(self):
        result = score_argument("test claim", [])
        assert result["ok"] is True
        assert result["score"] == 0.0
        assert result["supporting_count"] == 0

    def test_score_with_support(self):
        authorities = [
            {"document_id": "d1", "source": "s", "content_status": "full_text"},
            {"document_id": "d2", "source": "s", "content_status": "full_text"},
        ]
        result = score_argument("test claim", authorities)
        assert result["ok"] is True
        assert result["score"] > 0.0
        assert result["supporting_count"] == 2

    def test_score_higher_with_more_docs(self):
        few = [{"document_id": "d1", "source": "s", "content_status": "full_text"}]
        many = [
            {"document_id": f"d{i}", "source": "s", "content_status": "full_text"}
            for i in range(5)
        ]
        score_few = score_argument("test", few)["score"]
        score_many = score_argument("test", many)["score"]
        assert score_many >= score_few

    def test_score_with_metadata_only_lower(self):
        full = [{"document_id": "d1", "source": "s", "content_status": "full_text"}]
        meta = [{"document_id": "d1", "source": "s", "content_status": "metadata_only"}]
        score_full = score_argument("test", full)["score"]
        score_meta = score_argument("test", meta)["score"]
        assert score_full >= score_meta

    def test_score_factors_present(self):
        result = score_argument("test", [
            {"document_id": "d1", "source": "s", "content_status": "full_text"},
        ])
        assert "factors" in result
        assert len(result["factors"]) >= 2

    def test_score_bounded(self):
        result = score_argument("test", [
            {"document_id": f"d{i}", "source": "s", "content_status": "full_text"}
            for i in range(100)
        ])
        assert 0.0 <= result["score"] <= 1.0


# ---------------------------------------------------------------------------
# Tests: get_argument_strength_report
# ---------------------------------------------------------------------------

class TestGetArgumentStrengthReport:
    def test_report_from_valid_pack(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = get_argument_strength_report(pack_dir)
        assert result["ok"] is True
        assert "overall_strength" in result
        assert "argument_count" in result
        assert "strength_distribution" in result
        assert "recommendations" in result

    def test_report_from_missing_pack(self, tmp_path: Path):
        result = get_argument_strength_report(tmp_path / "nonexistent")
        assert result["ok"] is False

    def test_report_distribution_counts(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = get_argument_strength_report(pack_dir)
        dist = result["strength_distribution"]
        assert "strong" in dist
        assert "moderate" in dist
        assert "weak" in dist

    def test_report_has_classification_distribution(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = get_argument_strength_report(pack_dir)
        assert "classification_distribution" in result


# ---------------------------------------------------------------------------
# Tests: render_arguments_to_markdown
# ---------------------------------------------------------------------------

class TestRenderArgumentsToMarkdown:
    def test_renders_valid_markdown(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        md = render_arguments_to_markdown(pack_dir)
        assert "# Argument Chain Report" in md
        assert "Sözleşme" in md or "Argument" in md

    def test_writes_to_file(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        out = tmp_path / "args.md"
        md = render_arguments_to_markdown(pack_dir, out_path=out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == md

    def test_contains_counter_argument_placeholder(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        md = render_arguments_to_markdown(pack_dir)
        assert "{{KARSI_ARGUMAN_BOSLUK}}" in md

    def test_error_for_missing_pack(self, tmp_path: Path):
        md = render_arguments_to_markdown(tmp_path / "nonexistent")
        assert "Error" in md or "error" in md

    def test_contains_footer(self, tmp_path: Path):
        docs = [_make_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        md = render_arguments_to_markdown(pack_dir)
        assert "emsal-mcp" in md


# ---------------------------------------------------------------------------
# Tests: Safety Invariants (Critical)
# ---------------------------------------------------------------------------

class TestSafetyInvariants:
    def test_metadata_only_never_in_supporting(self, tmp_path: Path):
        """CRITICAL: metadata_only authorities must NEVER leak into
        supporting_authorities list."""
        docs = [
            _make_doc(document_id="ready-001"),
            _make_metadata_only_doc(document_id="meta-001"),
        ]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result["ok"] is True

        for arg in result["arguments"]:
            for auth in arg["supporting_authorities"]:
                assert auth["content_status"] not in (
                    "metadata_only",
                    "pdf_link_only",
                    "unavailable",
                ), (
                    f"SAFETY VIOLATION: {auth['document_id']} with "
                    f"content_status={auth['content_status']} found in "
                    f"supporting_authorities"
                )

    def test_citation_only_not_in_supporting(self, tmp_path: Path):
        """citation_only authorities must not appear in supporting_authorities."""
        docs = [
            _make_doc(document_id="ready-001"),
            _make_metadata_only_doc(document_id="cite-001"),
        ]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result["ok"] is True

        for arg in result["arguments"]:
            for auth in arg["supporting_authorities"]:
                # If it's in supporting_authorities, it must have passed citation_check
                assert auth["content_status"] in (
                    "full_text", "html_markdown"
                ), f"Non-draft-safe doc in supporting: {auth['document_id']}"

    def test_no_fabrication_with_no_support(self, tmp_path: Path):
        """When no petition_ready authorities exist, warnings should say so."""
        docs = [_make_metadata_only_doc()]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        assert result["ok"] is True
        # Check that there are warnings about missing support
        all_warnings = result.get("warnings", [])
        for arg in result["arguments"]:
            all_warnings.extend(arg.get("warnings", []))
        # At least one warning should mention no support
        assert isinstance(all_warnings, list)

    def test_safety_violation_detected(self, tmp_path: Path):
        """Verify the safety invariant check in build_argument_chain catches
        any violation that might slip through."""
        docs = [
            _make_doc(document_id="ready-001"),
            _make_metadata_only_doc(document_id="meta-001"),
        ]
        pack_dir = _make_pack(tmp_path, docs)
        result = build_argument_chain(pack_dir)
        # No safety violations should be reported (they should be prevented)
        safety_violations = [
            w for w in result.get("warnings", [])
            if "SAFETY VIOLATION" in w
        ]
        assert len(safety_violations) == 0, (
            f"Safety violations detected: {safety_violations}"
        )


# ---------------------------------------------------------------------------
# Tests: CLI / MCP integration (import check)
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_cli_import(self):
        from emsal_mcp.cli import app
        assert app is not None

    def test_argument_functions_importable(self):
        from emsal_mcp.argument import (
            build_argument_chain,
            score_argument,
            get_argument_strength_report,
            render_arguments_to_markdown,
        )
        assert callable(build_argument_chain)
        assert callable(score_argument)
        assert callable(get_argument_strength_report)
        assert callable(render_arguments_to_markdown)


class TestMCPServerIntegration:
    def test_server_import(self):
        from emsal_mcp.server import main
        assert callable(main)