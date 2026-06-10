"""FAZ M — Tool profile infrastructure (M-97).

Defines tool categories, profile membership, and filtering logic so that
``server.py`` can register only the 14-tool core surface by default (or all
119 tools with ``EMSAL_TOOL_PROFILE=full``).

This module is pure data — no business logic, no I/O.
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
    "health_admin": [
        "circuit_breaker_status",
        "source_health",
        "source_smoke",
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
        "build_input_pack",
        "prepare_drafting_input_pack",
    ],
    "udf_admin": [
        "udf_toolkit_status",
        "udf_authoring_instructions",
        "pdf_toolkit_status",
        "promote_pdf_to_full_text",
    ],
}

# ── Extended-only tools (single-source from server.py) ──────────────────
# These are the original server.py tools that are NOT part of the core 14.
# Built automatically from CATEGORY_TOOLS for reverse lookups.

EXTENDED_TOOLS: set[str] = set()
for _cat_tools in CATEGORY_TOOLS.values():
    EXTENDED_TOOLS.update(_cat_tools)

# Also include tools that appear in server.py but aren't in categories
# (search_local_cache, semantic_search, hybrid_search, etc. — absorbed by
# facades in M-98 but still present as legacy names in full profile).
# fmt: off
_LEGACY_ABSORBED: set[str] = {
    "search_local_cache", "semantic_search", "hybrid_search",
    "hybrid_search_rrf", "embedding_search",
    "search_legislation_articles",
    "get_legislation_document", "get_legislation_article_tree",
    "get_legislation_gerekce",
    "research_topic_tool",
    "citation_safety", "format_legal_citation", "verify_legal_citation",
    "format_legislation_citation",
    "prepare_petition_outline", "prepare_controlled_petition_draft",
    "prepare_docx_export", "prepare_export_package_bundle",
    "export_plain_text", "export_to_format",
    "read_udf", "write_udf", "extract_pdf_text",
    "source_capabilities", "list_birim_codes", "get_legislation_types",
    "convert_udf_to_docx_tool", "convert_udf_to_pdf_tool",
    "convert_docx_to_udf_experimental_tool",
    "export_bundle",
    "get_export_capabilities",
    "legislation_source_status",
}
# fmt: on
EXTENDED_TOOLS.update(_LEGACY_ABSORBED)

# ── Legacy absorbed tools → category mapping ─────────────────────────────
# These tools are replaced by facades in core profile but still exist in full
# profile.  They are assigned to the same categories as their facade wrappers.

_LEGACY_CATEGORIES: dict[str, str] = {
    # Absorbed by search_local_corpus
    "search_local_cache": "search",
    "semantic_search": "search",
    "hybrid_search": "search",
    "hybrid_search_rrf": "search",
    "embedding_search": "search",
    # Absorbed by search_legislation (scope="article")
    "search_legislation_articles": "legislation",
    # Absorbed by get_legislation
    "get_legislation_document": "legislation",
    "get_legislation_article_tree": "legislation",
    "get_legislation_gerekce": "legislation",
    "legislation_source_status": "legislation",
    "format_legislation_citation": "legislation",
    "get_legislation_types": "legislation",
    # Absorbed by citation_check
    "citation_safety": "citation",
    "format_legal_citation": "citation",
    "verify_legal_citation": "citation",
    # Absorbed by prepare_petition
    "prepare_petition_outline": "petition",
    "prepare_controlled_petition_draft": "petition",
    # Absorbed by export_document
    "prepare_docx_export": "export",
    "prepare_export_package_bundle": "export",
    "export_plain_text": "export",
    "export_to_format": "export",
    "get_export_capabilities": "export",
    # Absorbed by read_legal_file
    "read_udf": "udf_admin",
    "write_udf": "udf_admin",
    "extract_pdf_text": "udf_admin",
    "convert_udf_to_docx_tool": "udf_admin",
    "convert_udf_to_pdf_tool": "udf_admin",
    "convert_docx_to_udf_experimental_tool": "udf_admin",
    # Absorbed by list_sources
    "source_capabilities": "discovery",
    "list_birim_codes": "discovery",
    # Absorbed by research_topic (renamed from research_topic_tool)
    "research_topic_tool": "research",
    # Renamed / absorbed
    "export_bundle": "drafting_advanced",
}

# ── Per-tool → category reverse mapping ──────────────────────────────────

TOOL_CATEGORY: dict[str, str] = {}
for _cat, _names in CATEGORY_TOOLS.items():
    for _name in _names:
        TOOL_CATEGORY[_name] = _cat

# Add legacy absorbed categories
TOOL_CATEGORY.update(_LEGACY_CATEGORIES)

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
