"""Tests for M-11 Petition Template Library.

Covers:
- All 4 templates exist with required fields
- get_template returns correct template / error for invalid name
- list_templates returns 4+ templates with summary fields
- render_template_to_skeleton produces valid markdown with {{PLACEHOLDER}}
- Render output includes DISCLAIMER_HEADER
- Template types are distinct
- CLI and MCP imports
- inspect_petition_pack integration
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

import re

from emsal_mcp.petition import DISCLAIMER_HEADER, PLACEHOLDER_PATTERN
from emsal_mcp.templates import (
    DAVA_DILEKCESI,
    CEVAP_DILEKCESI,
    TEMYIZ_DILEKCESI,
    ISTINAF_DILEKCESI,
    get_all_placeholders,
    get_template,
    get_template_types,
    list_templates,
    render_template_to_skeleton,
)


# ---------------------------------------------------------------------------
# Constants for validation
# ---------------------------------------------------------------------------

REQUIRED_TEMPLATE_FIELDS = {"name", "type", "title", "sections"}
REQUIRED_SECTION_FIELDS = {"heading", "content"}
TEMPLATE_NAMES = ["dava_dilekcesi", "cevap_dilekcesi", "temyiz_dilekcesi", "istinaf_dilekcesi"]
ALL_TEMPLATES = [DAVA_DILEKCESI, CEVAP_DILEKCESI, TEMYIZ_DILEKCESI, ISTINAF_DILEKCESI]


# ---------------------------------------------------------------------------
# Tests: Template Structure
# ---------------------------------------------------------------------------

class TestTemplateStructure:
    def test_all_4_templates_exist(self):
        assert len(ALL_TEMPLATES) == 4

    def test_template_names_match(self):
        names = [t["name"] for t in ALL_TEMPLATES]
        assert set(names) == set(TEMPLATE_NAMES)

    def test_required_fields_present(self):
        for template in ALL_TEMPLATES:
            for field in REQUIRED_TEMPLATE_FIELDS:
                assert field in template, f"Template '{template.get('name')}' missing field '{field}'"

    def test_sections_have_required_fields(self):
        for template in ALL_TEMPLATES:
            assert isinstance(template["sections"], list)
            assert len(template["sections"]) >= 3
            for section in template["sections"]:
                for field in REQUIRED_SECTION_FIELDS:
                    assert field in section, (
                        f"Section in '{template['name']}' missing field '{field}'"
                    )

    def test_all_sections_have_placeholders(self):
        for template in ALL_TEMPLATES:
            for section in template["sections"]:
                placeholders = PLACEHOLDER_PATTERN.findall(section["content"])
                assert len(placeholders) > 0, (
                    f"Section '{section['heading']}' in '{template['name']}' has no placeholders"
                )

    def test_type_is_valid(self):
        valid_types = {"dava", "cevap", "temyiz", "istinaf", "icra_itiraz"}
        for template in ALL_TEMPLATES:
            assert template["type"] in valid_types, (
                f"Template '{template['name']}' has invalid type '{template['type']}'"
            )

    def test_all_templates_have_citations_placeholder(self):
        """Every template should have PETITION_READY_CITATIONS somewhere."""
        for template in ALL_TEMPLATES:
            all_content = " ".join(s["content"] for s in template["sections"])
            assert "PETITION_READY_CITATIONS" in all_content, (
                f"Template '{template['name']}' missing PETITION_READY_CITATIONS"
            )


# ---------------------------------------------------------------------------
# Tests: get_template
# ---------------------------------------------------------------------------

class TestGetTemplate:
    def test_get_existing_template(self):
        result = get_template("dava_dilekcesi")
        assert result["name"] == "dava_dilekcesi"
        assert result["type"] == "dava"
        assert result["title"] == "Dava Dilekçesi"
        assert "sections" in result

    def test_get_all_templates(self):
        for name in TEMPLATE_NAMES:
            result = get_template(name)
            assert "name" in result
            assert result["name"] == name

    def test_get_invalid_name_returns_error(self):
        result = get_template("nonexistent_template")
        assert result.get("ok") is False
        assert "errorCode" in result
        assert result["errorCode"] == "TEMPLATE_NOT_FOUND"

    def test_get_returns_copy(self):
        """Modifying the returned dict should not affect the internal registry."""
        t1 = get_template("dava_dilekcesi")
        t1["name"] = "mutated"
        t2 = get_template("dava_dilekcesi")
        assert t2["name"] == "dava_dilekcesi"


# ---------------------------------------------------------------------------
# Tests: list_templates
# ---------------------------------------------------------------------------

class TestListTemplates:
    def test_returns_all_templates(self):
        templates = list_templates()
        assert len(templates) >= 4

    def test_summary_fields(self):
        templates = list_templates()
        for t in templates:
            assert "name" in t
            assert "type" in t
            assert "title" in t
            assert "section_count" in t
            assert "placeholder_count" in t
            assert t["section_count"] >= 3
            assert t["placeholder_count"] > 0

    def test_names_match(self):
        templates = list_templates()
        names = {t["name"] for t in templates}
        assert set(TEMPLATE_NAMES).issubset(names)


# ---------------------------------------------------------------------------
# Tests: render_template_to_skeleton
# ---------------------------------------------------------------------------

class TestRenderTemplateToSkeleton:
    def test_renders_valid_markdown(self):
        for name in TEMPLATE_NAMES:
            md = render_template_to_skeleton(name)
            assert isinstance(md, str)
            assert len(md) > 100

    def test_includes_disclaimer_header(self):
        for name in TEMPLATE_NAMES:
            md = render_template_to_skeleton(name)
            assert DISCLAIMER_HEADER in md

    def test_preserves_placeholders(self):
        for name in TEMPLATE_NAMES:
            md = render_template_to_skeleton(name)
            placeholders = PLACEHOLDER_PATTERN.findall(md)
            assert len(placeholders) > 0, f"No placeholders found in rendered '{name}'"

    def test_has_section_headings(self):
        for name in TEMPLATE_NAMES:
            template = get_template(name)
            md = render_template_to_skeleton(name)
            for section in template["sections"]:
                assert f"## {section['heading']}" in md, (
                    f"Section heading '{section['heading']}' missing from rendered '{name}'"
                )

    def test_has_title_heading(self):
        for name in TEMPLATE_NAMES:
            template = get_template(name)
            md = render_template_to_skeleton(name)
            assert f"# {template['title']}" in md

    def test_invalid_name_raises_key_error(self):
        try:
            render_template_to_skeleton("nonexistent")
            assert False, "Expected KeyError"
        except KeyError:
            pass

    def test_all_placeholders_from_template_in_render(self):
        """Every placeholder in the template sections should appear in the render."""
        for name in TEMPLATE_NAMES:
            template = get_template(name)
            md = render_template_to_skeleton(name)
            for section in template["sections"]:
                for ph in PLACEHOLDER_PATTERN.findall(section["content"]):
                    assert ph in md, (
                        f"Placeholder {ph} from '{name}' section "
                        f"'{section['heading']}' missing in render"
                    )

    def test_render_contains_all_content(self):
        for name in TEMPLATE_NAMES:
            template = get_template(name)
            md = render_template_to_skeleton(name)
            for section in template["sections"]:
                # First 40 chars of content should be in render
                snippet = section["content"][:40]
                assert snippet in md, (
                    f"Content snippet '{snippet}' from '{name}' missing in render"
                )


# ---------------------------------------------------------------------------
# Tests: get_template_types
# ---------------------------------------------------------------------------

class TestGetTemplateTypes:
    def test_returns_distinct_types(self):
        types = get_template_types()
        assert len(types) == len(set(types))

    def test_includes_expected_types(self):
        types = set(get_template_types())
        expected = {"dava", "cevap", "temyiz", "istinaf"}
        assert expected.issubset(types)

    def test_all_templates_types_present(self):
        types = set(get_template_types())
        for template in ALL_TEMPLATES:
            assert template["type"] in types


# ---------------------------------------------------------------------------
# Tests: get_all_placeholders
# ---------------------------------------------------------------------------

class TestGetAllPlaceholders:
    def test_returns_placeholders(self):
        placeholders = get_all_placeholders("dava_dilekcesi")
        assert len(placeholders) > 0
        for ph in placeholders:
            assert ph.startswith("{{")
            assert ph.endswith("}}")

    def test_invalid_name_returns_empty(self):
        placeholders = get_all_placeholders("nonexistent")
        assert placeholders == []

    def test_count_matches(self):
        for name in TEMPLATE_NAMES:
            placeholders = get_all_placeholders(name)
            templates = list_templates()
            template_info = next(t for t in templates if t["name"] == name)
            assert len(placeholders) == template_info["placeholder_count"]


# ---------------------------------------------------------------------------
# Tests: Placeholder Preservation ({{...}} convention)
# ---------------------------------------------------------------------------

class TestPlaceholderConvention:
    def test_double_brace_pattern(self):
        """All placeholders must use {{DOUBLE_BRACE}} convention."""
        for name in TEMPLATE_NAMES:
            template = get_template(name)
            for section in template["sections"]:
                # All {{...}} patterns should be valid placeholders
                matches = re.findall(r"\{\{[^}]+\}\}", section["content"])
                assert len(matches) > 0, (
                    f"Section '{section['heading']}' in '{name}' "
                    f"has no {{PLACEHOLDER}} patterns"
                )

    def test_no_single_brace_placeholders(self):
        """Ensure no accidental single-brace {PLACEHOLDER} patterns exist."""
        for name in TEMPLATE_NAMES:
            template = get_template(name)
            for section in template["sections"]:
                # Find single-brace patterns (not part of double-brace)
                content = section["content"]
                # Remove all double-brace patterns first
                stripped = re.sub(r"\{\{[^}]+\}\}", "", content)
                # Any remaining { } should not look like a placeholder
                single_braces = re.findall(r"\{[^{}]+\}", stripped)
                for sb in single_braces:
                    # Allow empty braces (structural) but not word-like
                    inner = sb.strip("{}")
                    assert not inner.isalpha(), (
                        f"Single-brace placeholder '{{{inner}}}' found in "
                        f"'{name}' section '{section['heading']}'"
                    )


# ---------------------------------------------------------------------------
# Tests: inspect_petition_pack integration
# ---------------------------------------------------------------------------

class TestInspectIntegration:
    def test_rendered_skeleton_has_placeholders_for_inspect(self):
        """A rendered skeleton should have placeholders that inspect checks for."""
        for name in TEMPLATE_NAMES:
            md = render_template_to_skeleton(name)
            placeholders = PLACEHOLDER_PATTERN.findall(md)
            # inspect_petition_pack checks placeholdersInDraftSkeleton.count > 0
            assert len(placeholders) > 0

    def test_rendered_skeleton_no_hardcoded_law_references(self):
        """Rendered skeletons should not contain hardcoded law references."""
        law_pattern = re.compile(
            r"(?:Kanun|Madde|Hüküm)\s*(?:No|numarası)?\s*[:.]?\s*\d+",
            re.IGNORECASE,
        )
        for name in TEMPLATE_NAMES:
            md = render_template_to_skeleton(name)
            refs = law_pattern.findall(md)
            assert len(refs) == 0, (
                f"Hardcoded law references found in '{name}': {refs}"
            )


# ---------------------------------------------------------------------------
# Tests: CLI / MCP imports
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_cli_import(self):
        from emsal_mcp.cli import app
        assert app is not None

    def test_templates_importable(self):
        from emsal_mcp.templates import (
            get_template,
            get_template_types,
            list_templates,
            render_template_to_skeleton,
        )
        assert callable(get_template)
        assert callable(list_templates)
        assert callable(render_template_to_skeleton)
        assert callable(get_template_types)


class TestMCPServerIntegration:
    def test_server_import(self):
        from emsal_mcp.server import main
        assert callable(main)


# ---------------------------------------------------------------------------
# Tests: Template content completeness
# ---------------------------------------------------------------------------

class TestTemplateCompleteness:
    def test_dava_has_parties(self):
        """Dava template must include both Davacı and Davalı."""
        template = get_template("dava_dilekcesi")
        headings = [s["heading"] for s in template["sections"]]
        assert "DAVACI" in headings
        assert "DAVALI" in headings

    def test_cevap_has_response_sections(self):
        """Cevap template must include response sections."""
        template = get_template("cevap_dilekcesi")
        headings = [s["heading"] for s in template["sections"]]
        assert "CEVAPLARIMIZ" in headings
        assert "SONUÇ" in headings

    def test_temyiz_has_appeal_reasons(self):
        """Temyiz template must include appeal reasons."""
        template = get_template("temyiz_dilekcesi")
        headings = [s["heading"] for s in template["sections"]]
        assert "TEMYİZ NEDENLERİ" in headings

    def test_istinaf_has_appeal_reasons(self):
        """İstinaf template must include regional appeal reasons."""
        template = get_template("istinaf_dilekcesi")
        headings = [s["heading"] for s in template["sections"]]
        assert "İSTİNAF NEDENLERİ" in headings

    def test_all_templates_have_sonuc(self):
        """All templates must have a conclusion section."""
        for name in TEMPLATE_NAMES:
            template = get_template(name)
            headings = [s["heading"] for s in template["sections"]]
            has_sonuc = any("SONUÇ" in h for h in headings)
            assert has_sonuc, f"Template '{name}' missing SONUÇ section"