"""FAZ M — Tool profile infrastructure (M-97).

Defines tool categories, profile membership, and filtering logic so that
``server.py`` can register only the 14-tool core surface by default (or all
50 tools with ``EMSAL_TOOL_PROFILE=full``).

This module is pure data — no business logic, no I/O.  ``tests/test_tool_surface``
asserts it stays in sync with the ``@_tool`` registrations in ``server.py``.
"""

from __future__ import annotations

import os
from typing import Any

# ── M-98 14-tool core profile ─────────────────────────────────────────────
# These are the EXACT tool names that appear in the core profile.
# Order matches ROADMAP.md M-98.

CORE_TOOLS: list[str] = [
    "search_decisions",
    "get_document",
    "search_local_corpus",
    "search_legislation",
    "get_legislation",
    "research_topic",
    "citation_check",
    "prepare_petition",
    "export_document",
    "read_legal_file",
    "list_sources",
    "legal_research_guide",
    "load_extended_tools",
    "health_check",
]

# ── Category → tool name mappings (M-97 table) ───────────────────────────
# All tool names here match the original names in server.py (before M-98
# facades).  The core facade names are NOT in this table — they're in the
# core profile above.

CATEGORY_TOOLS: dict[str, list[str]] = {
    # M-105: cache_admin removed (CLI-only: emsal-mcp cache ...)
    # M-105: routing removed (search_decisions handles routing)
    # M-110: every tool a core facade already covered was deleted outright —
    # see RETIRED_TOOLS below for the old name → replacement mapping.
    "health_admin": [
        "circuit_breaker_status",
        "source_health",
        "source_smoke",
        "check_government_servers_health",
    ],
    "citation_graph": [
        "build_citation_graph",
        "get_citation_graph",
        "find_citing_documents",
        "find_cited_documents",
        "citation_graph_stats",
        "export_citation_graph",
    ],
    # M-105: dedup removed (corpus_builder handles dedup automatically)
    "watch": [
        "watch_add",
        "watch_list",
        "watch_run",
        "watch_remove",
    ],
    "privacy": [
        "privacy_scan",
        "privacy_redact",
        "privacy_audit",
    ],
    "chambers": [
        "chamber_overview",
        "profile_chamber",
        "chamber_timeline",
        "find_similar_chambers",
    ],
    "indexing": [
        "index_status",
    ],
    "drafting_advanced": [
        "inspect_petition_pack",
        "build_multi_issue_pack",
        "inspect_multi_issue_pack",
        "list_petition_templates",
        "get_petition_template",
        "build_argument_chain",
        "score_argument",
        "get_argument_strength_report",
        "draft_document",
        "export_bundle",
    ],
    "udf_admin": [
        "udf_toolkit_status",
        "udf_authoring_instructions",
        "pdf_toolkit_status",
        "promote_pdf_to_full_text",
    ],
}

# ── Extended-only tools (single-source from server.py) ──────────────────
# Every tool that is NOT part of the core 14.  Built from CATEGORY_TOOLS.

EXTENDED_TOOLS: set[str] = set()
for _cat_tools in CATEGORY_TOOLS.values():
    EXTENDED_TOOLS.update(_cat_tools)

# ── Retired tools → replacement call (M-110) ────────────────────────────
# These names were registered as separate MCP tools until M-110.  Each was
# fully covered by a core facade, so they were deleted rather than kept as
# aliases.  The mapping stays here so an agent (or a human) that remembers an
# old name gets pointed at the surviving call instead of a bare KeyError.
# The underlying implementations still live in their modules and are still
# reachable from the CLI — only the duplicate MCP registrations are gone.

RETIRED_TOOLS: dict[str, str] = {
    # → search_local_corpus(mode=...)
    "search_local_cache": 'search_local_corpus(mode="lexical")',
    "semantic_search": 'search_local_corpus(mode="semantic")',
    "hybrid_search": 'search_local_corpus(mode="hybrid")',
    "hybrid_search_rrf": 'search_local_corpus(mode="rrf")',
    "embedding_search": 'search_local_corpus(mode="semantic", provider=...)',
    # → search_legislation / get_legislation
    "search_legislation_articles": 'search_legislation(scope="article")',
    "get_legislation_document": 'get_legislation(part="document")',
    "get_legislation_article_tree": 'get_legislation(part="article_tree")',
    "get_legislation_gerekce": 'get_legislation(part="gerekce")',
    # → citation_check(action=...)
    "verify_legal_citation": 'citation_check(action="verify")',
    "format_legal_citation": 'citation_check(action="format")',
    "format_legislation_citation": 'citation_check(action="format_legislation")',
    "citation_safety": 'citation_check(action="safety")',
    # → prepare_petition(step=...)
    "build_input_pack": 'prepare_petition(step="input_pack")',
    "prepare_drafting_input_pack": 'prepare_petition(step="input_pack")',
    "prepare_petition_outline": 'prepare_petition(step="outline")',
    "prepare_controlled_petition_draft": 'prepare_petition(step="controlled_draft")',
    # → export_document(format=...)
    "get_export_capabilities": 'export_document(format="capabilities")',
    "prepare_docx_export": 'export_document(format="docx")',
    "export_to_format": 'export_document(format="pdf")',
    "export_plain_text": 'export_document(format="plain")',
    "prepare_export_package_bundle": 'export_document(format="bundle")',
    "write_udf": 'export_document(format="udf", text=...)',
    "convert_docx_to_udf": 'export_document(format="udf", docx_path=...)',
    "convert_udf_to_docx_tool": 'export_document(format="docx", udf_path=...)',
    "convert_udf_to_pdf_tool": 'export_document(format="pdf", udf_path=...)',
    # → read_legal_file(path=...)
    "read_udf": "read_legal_file(path=...udf)",
    "extract_pdf_text": "read_legal_file(path=...pdf)",
    # → list_sources
    "source_capabilities": "list_sources()",
    "list_birim_codes": 'list_sources(detail="birim_codes")',
    "get_legislation_types": 'list_sources(detail="legislation_types")',
    # → health_check / research_topic
    "legislation_source_status": "health_check()",
    "research_topic_tool": "research_topic()",
}

# ── Per-tool → category reverse mapping ──────────────────────────────────

TOOL_CATEGORY: dict[str, str] = {}
for _cat, _names in CATEGORY_TOOLS.items():
    for _name in _names:
        TOOL_CATEGORY[_name] = _cat

# Core facade tools don't belong to any extended category.
for _name in CORE_TOOLS:
    if _name not in TOOL_CATEGORY:
        TOOL_CATEGORY[_name] = "core"

# ── Per-tool → profile mapping ───────────────────────────────────────────

TOOL_PROFILE: dict[str, str] = {}
for _name in CORE_TOOLS:
    TOOL_PROFILE[_name] = "core"
for _name in EXTENDED_TOOLS:
    TOOL_PROFILE.setdefault(_name, "extended")


# ── Profile resolution ───────────────────────────────────────────────────


def get_active_profile() -> str:
    """Return the active tool profile name.

    Reads ``EMSAL_TOOL_PROFILE`` environment variable.
    ``"core"`` (default) → only the 14-tool surface (M-98).
    ``"full"`` → all tools (today's 119-tool surface).
    """
    return os.environ.get("EMSAL_TOOL_PROFILE", "core")


def is_tool_active(tool_name: str) -> bool:
    """Return True if *tool_name* should be registered under the active profile.

    In ``full`` profile every tool passes.  In ``core`` profile only the 14
    core tools pass.
    """
    profile = get_active_profile()
    if profile == "full":
        return True
    return tool_name in set(CORE_TOOLS)


def get_category_summary() -> list[dict[str, Any]]:
    """Return a list of category descriptions for ``load_extended_tools``.

    Each entry has ``category``, ``tool_count``, and ``examples`` (first 3
    tool names).
    """
    summaries: list[dict[str, Any]] = []
    for cat, names in sorted(CATEGORY_TOOLS.items()):
        summaries.append({
            "category": cat,
            "tool_count": len(names),
            "examples": names[:3],
        })
    return summaries
