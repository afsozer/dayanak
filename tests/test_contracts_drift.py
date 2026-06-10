"""M-107: MCP_CONTRACTS.md drift test.

Compares ``docs/MCP_CONTRACTS.md`` against ``src/emsal_mcp/tool_profile.py``
(the single source of truth for profiles and categories).  Fails if the
document is out of sync with the code — catching the same class of drift
that M-58 catches for README.md.

Hermetic — zero network, pure file system read.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "docs" / "MCP_CONTRACTS.md"


def _read_section(start_marker: str, end_marker: str) -> str:
    """Extract text between two HTML comment markers from MCP_CONTRACTS.md."""
    text = CONTRACTS.read_text(encoding="utf-8")
    m = re.search(
        re.escape(start_marker) + r"(.*?)" + re.escape(end_marker),
        text,
        re.DOTALL,
    )
    if m is None:
        return ""
    return m.group(1).strip()


# ── Core tool list check ───────────────────────────────────────────────


def test_core_tools_match_profile() -> None:
    """The 14 core tool names in MCP_CONTRACTS.md match CORE_TOOLS."""
    from emsal_mcp.tool_profile import CORE_TOOLS

    section = _read_section(
        "<!-- drift:core-tools-start -->",
        "<!-- drift:core-tools-end -->",
    )
    # Parse: "| `core` | 14 | Default. `tool1`, `tool2`, ..., `tool14`. |"
    tools_match = re.findall(r"`([a-z_]+)`", section)
    doc_tools = sorted(t for t in tools_match if t != "core")
    expected = sorted(CORE_TOOLS)

    assert doc_tools == expected, (
        f"MCP_CONTRACTS core tools out of sync.\n"
        f"  Document: {doc_tools}\n"
        f"  Code:     {expected}\n"
        f"  Missing from doc: {set(expected) - set(doc_tools)}\n"
        f"  Missing from code: {set(doc_tools) - set(expected)}"
    )


# ── Category name check ────────────────────────────────────────────────


def test_category_names_match_profile() -> None:
    """Category names in MCP_CONTRACTS.md table match CATEGORY_TOOLS keys."""
    from emsal_mcp.tool_profile import CATEGORY_TOOLS

    section = _read_section(
        "<!-- drift:categories-start -->",
        "<!-- drift:categories-end -->",
    )
    # Parse: | `category_name` | tool1, tool2, ... |
    doc_cats = set(re.findall(r"\|\s*`([a-z_]+)`\s*\|", section))
    code_cats = set(CATEGORY_TOOLS.keys())

    assert doc_cats == code_cats, (
        f"MCP_CONTRACTS categories out of sync.\n"
        f"  Document: {sorted(doc_cats)}\n"
        f"  Code:     {sorted(code_cats)}\n"
        f"  Missing from doc: {sorted(code_cats - doc_cats)}\n"
        f"  Missing from code: {sorted(doc_cats - code_cats)}"
    )


# ── Category contents check ────────────────────────────────────────────


def test_category_contents_match_profile() -> None:
    """Each category row's tool list matches CATEGORY_TOOLS[cat]."""
    from emsal_mcp.tool_profile import CATEGORY_TOOLS

    section = _read_section(
        "<!-- drift:categories-start -->",
        "<!-- drift:categories-end -->",
    )
    # Parse rows: | `cat` | tool1, tool2, ... |
    doc_categories: dict[str, list[str]] = {}
    for line in section.split("\n"):
        # Skip header/separator lines
        if "---" in line or "Category" in line:
            continue
        m = re.match(r"\|\s*`([a-z_]+)`\s*\|\s*(.+?)\s*\|", line)
        if m:
            cat = m.group(1)
            tools_str = m.group(2)
            tools = [t.strip().strip("`") for t in tools_str.split(",")]
            doc_categories[cat] = sorted(tools)

    for cat, code_tools in sorted(CATEGORY_TOOLS.items()):
        doc_tools = doc_categories.get(cat, [])
        assert doc_tools == sorted(code_tools), (
            f"Category '{cat}' out of sync.\n"
            f"  Document: {doc_tools}\n"
            f"  Code:     {sorted(code_tools)}"
        )


# ── Tool count check ───────────────────────────────────────────────────


def test_core_count_is_14() -> None:
    """Document says 14 core tools, code agrees."""
    from emsal_mcp.tool_profile import CORE_TOOLS

    section = _read_section(
        "<!-- drift:core-tools-start -->",
        "<!-- drift:core-tools-end -->",
    )
    # Parse "| `core` | 14 | ..."
    count_match = re.search(r"\|\s*`core`\s*\|\s*(\d+)\s*\|", section)
    assert count_match is not None, "Could not find core count in document"
    doc_count = int(count_match.group(1))
    assert doc_count == len(CORE_TOOLS), (
        f"Core count mismatch: doc={doc_count}, code={len(CORE_TOOLS)}"
    )


def test_full_count_matches_snapshot() -> None:
    """Document says 82 full-profile tools, matches test_tool_surface snapshot."""
    from tests.test_tool_surface import TestFullProfile

    text = CONTRACTS.read_text(encoding="utf-8")
    count_match = re.search(r"\|\s*`full`\s*\|\s*(\d+)\s*\|", text)
    assert count_match is not None, "Could not find full count in document"
    doc_count = int(count_match.group(1))
    assert doc_count == TestFullProfile.FULL_TOOL_COUNT_SNAPSHOT, (
        f"Full count mismatch: doc={doc_count}, snapshot={TestFullProfile.FULL_TOOL_COUNT_SNAPSHOT}"
    )
