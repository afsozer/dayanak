"""Capability-based tool routing for MCP.

Read-only module that routes search/document requests to sources that
support the needed capability using the capability matrix from the registry.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Capability mapping: capability name → SourceCapability field name
# ---------------------------------------------------------------------------

CAPABILITIES: list[str] = [
    "search",
    "get_document",
    "full_text",
    "pdf_link",
    "metadata_only",
    "article_search",
    "type_filter",
    "workflow",
]

_CAPABILITY_FIELD: dict[str, str] = {
    "search": "supports_search",
    "get_document": "supports_get_document",
    "full_text": "supports_full_text",
    "pdf_link": "supports_pdf_link",
    "metadata_only": "supports_metadata_only",
    "article_search": "supports_article_search",
    "type_filter": "supports_type_filter",
    "workflow": "supports_workflow",
}

# Stable sources come before experimental/partial for preference ordering.
_STABLE_ORDER: list[str] = [
    "bedesten",
    "yargitay",
    "aym",
    "danistay",
    "gib",
    "mevzuat",
    "sayistay",
    "uyusmazlik",
    "rekabet",
    "kik",
]


def _build_capability_matrix(
    sources_override: dict[str, Any] | None = None,
) -> dict[str, dict[str, bool]]:
    """Build source_id → {capability: bool} from the registry.

    Uses ``sources_override`` for test injection; falls back to the real
    registry when None.
    """
    if sources_override is not None:
        reg = sources_override
    else:
        from emsal_mcp.sources.registry import registry

        reg = registry()

    matrix: dict[str, dict[str, bool]] = {}
    for source_id, client in reg.items():
        caps = client.capabilities()
        row: dict[str, bool] = {}
        for cap_name, field in _CAPABILITY_FIELD.items():
            row[cap_name] = bool(caps.get(field, False))
        matrix[source_id] = row
    return matrix


def get_capable_sources(
    capability: str,
    sources_override: dict[str, Any] | None = None,
) -> list[str]:
    """Get list of source_ids that support a given capability.

    Returns empty list for unknown capabilities (with no exception) so
    callers can degrade gracefully.
    """
    if capability not in _CAPABILITY_FIELD:
        return []

    matrix = _build_capability_matrix(sources_override)
    result = [
        sid
        for sid in _STABLE_ORDER
        if sid in matrix and matrix[sid].get(capability, False)
    ]
    # Include any sources in override that aren't in _STABLE_ORDER
    for sid in matrix:
        if sid not in _STABLE_ORDER and matrix[sid].get(capability, False):
            result.append(sid)
    return result


def get_source_by_capability(
    capability: str,
    prefer_order: list[str] | None = None,
    sources_override: dict[str, Any] | None = None,
) -> str | None:
    """Get the best single source for a capability.

    Preference order: ``prefer_order`` > stable sources > experimental.
    Returns None if no source supports the capability.
    """
    capable = get_capable_sources(capability, sources_override=sources_override)
    if not capable:
        return None

    if prefer_order:
        for sid in prefer_order:
            if sid in capable:
                return sid

    # Default: first in stable order (already sorted stable-first)
    return capable[0]


def route_search(
    query: str,
    required_capabilities: list[str] | None = None,
    preferred_sources: list[str] | None = None,
    exclude_sources: list[str] | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route a search request to capable sources.

    This is READ-ONLY — it only determines which sources *could* serve the
    request based on the capability matrix.  It does not execute searches.
    """
    excluded = set(exclude_sources or [])
    required = list(required_capabilities or [])
    preferred = list(preferred_sources or [])

    matrix = _build_capability_matrix(sources_override)

    # Filter by required capabilities
    eligible: list[str] = []
    for sid in _STABLE_ORDER:
        if sid not in matrix:
            continue
        if sid in excluded:
            continue
        if required:
            if all(matrix[sid].get(cap, False) for cap in required):
                eligible.append(sid)
        else:
            eligible.append(sid)

    # Include any override sources not in _STABLE_ORDER
    for sid in matrix:
        if sid in _STABLE_ORDER or sid in excluded:
            continue
        if required:
            if all(matrix[sid].get(cap, False) for cap in required):
                eligible.append(sid)
        else:
            eligible.append(sid)

    # Order: preferred first (preserving input order), then the rest
    ordered: list[str] = []
    for sid in preferred:
        if sid in eligible and sid not in ordered:
            ordered.append(sid)
    for sid in eligible:
        if sid not in ordered:
            ordered.append(sid)

    per_source: dict[str, dict[str, Any]] = {}
    for sid in ordered:
        if required:
            cap_match = all(matrix[sid].get(cap, False) for cap in required)
        else:
            cap_match = True
        per_source[sid] = {"capability_match": cap_match}

    return {
        "ok": True,
        "query": query,
        "routing": {
            "requested_capabilities": required,
            "eligible_sources": ordered,
            "excluded_sources": sorted(excluded),
            "source_selection_reason": "capability_match",
        },
        "results": [],
        "per_source": per_source,
    }


def route_get_document(
    document_id: str,
    required_capabilities: list[str] | None = None,
    preferred_source: str | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route a get_document request, trying preferred source first then
    falling back to capable alternatives.
    """
    required = list(required_capabilities or [])
    matrix = _build_capability_matrix(sources_override)

    # Determine eligible sources
    eligible: list[str] = []
    for sid in _STABLE_ORDER:
        if sid not in matrix:
            continue
        if required:
            if all(matrix[sid].get(cap, False) for cap in required):
                eligible.append(sid)
        else:
            eligible.append(sid)
    for sid in matrix:
        if sid not in _STABLE_ORDER and sid not in eligible:
            if required:
                if all(matrix[sid].get(cap, False) for cap in required):
                    eligible.append(sid)
            else:
                eligible.append(sid)

    # Build ordered list: preferred first, then rest
    ordered: list[str] = []
    if preferred_source and preferred_source in eligible:
        ordered.append(preferred_source)
    for sid in eligible:
        if sid not in ordered:
            ordered.append(sid)

    return {
        "ok": True,
        "document_id": document_id,
        "routing": {
            "requested_capabilities": required,
            "preferred_source": preferred_source,
            "eligible_sources": ordered,
            "source_selection_reason": "capability_match",
        },
        "results": [],
    }
