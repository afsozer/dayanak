"""Tests for capability-based router (M-19).

Covers:
- get_capable_sources returns correct sources for each capability
- route_search filters by capability
- route_search with preferred_sources
- route_search with exclude_sources
- route_get_document with preferred_source
- route_get_document fallback
- Empty capability list → all sources
- Unknown capability → empty list
- sources_override works for test injection
- Deterministic routing
- CLI and MCP imports
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.router import (
    CAPABILITIES,
    get_capable_sources,
    get_source_by_capability,
    route_get_document,
    route_search,
)


# ---------------------------------------------------------------------------
# Helper: build a fake registry for deterministic tests
# ---------------------------------------------------------------------------


class _FakeClient:
    """Minimal client for capability injection."""

    def __init__(self, source_id: str, **caps: bool) -> None:
        self.source_id = source_id
        self._caps = {
            "supports_search": True,
            "supports_get_document": True,
            "supports_full_text": True,
            "supports_pdf_link": False,
            "supports_metadata_only": True,
            "supports_article_search": False,
            "supports_type_filter": False,
            "supports_workflow": True,
            **caps,
        }

    def capabilities(self) -> dict:
        return self._caps


def _make_registry(**overrides: dict[str, bool]) -> dict[str, _FakeClient]:
    """Build a synthetic registry for testing.

    Keys are source_ids, values are _FakeClient instances.
    ``overrides`` maps source_id → {capability_name: bool} to override.
    """
    defaults: dict[str, dict[str, bool]] = {
        "bedesten": {},
        "yargitay": {},
        "mevzuat": {"supports_article_search": True, "supports_type_filter": True},
        "aym": {},
        "danistay": {},
        "gib": {},
        "uyusmazlik": {"supports_full_text": False, "supports_pdf_link": True},
        "rekabet": {"supports_full_text": False, "supports_pdf_link": True},
        "sayistay": {},
        "kik": {
            "supports_search": False,
            "supports_full_text": False,
            "supports_pdf_link": False,
            "supports_metadata_only": True,
            "supports_workflow": False,
        },
    }
    reg: dict[str, _FakeClient] = {}
    for sid, caps in defaults.items():
        merged = {**caps, **overrides.get(sid, {})}
        reg[sid] = _FakeClient(sid, **merged)
    return reg


# ---------------------------------------------------------------------------
# get_capable_sources
# ---------------------------------------------------------------------------


class TestGetCapableSources:
    def test_full_text(self):
        reg = _make_registry()
        result = get_capable_sources("full_text", sources_override=reg)
        assert "bedesten" in result
        assert "yargitay" in result
        assert "aym" in result
        assert "kik" not in result
        assert "uyusmazlik" not in result
        assert "rekabet" not in result

    def test_article_search(self):
        reg = _make_registry()
        result = get_capable_sources("article_search", sources_override=reg)
        assert result == ["mevzuat"]

    def test_pdf_link(self):
        reg = _make_registry()
        result = get_capable_sources("pdf_link", sources_override=reg)
        assert "rekabet" in result
        assert "uyusmazlik" in result
        assert "bedesten" not in result
        assert "kik" not in result

    def test_search(self):
        reg = _make_registry()
        result = get_capable_sources("search", sources_override=reg)
        assert "kik" not in result  # kik search requires token
        assert "bedesten" in result

    def test_unknown_capability_returns_empty(self):
        reg = _make_registry()
        result = get_capable_sources("nonexistent", sources_override=reg)
        assert result == []

    def test_empty_registry(self):
        result = get_capable_sources("full_text", sources_override={})
        assert result == []

    def test_ordering_is_stable(self):
        reg = _make_registry()
        r1 = get_capable_sources("full_text", sources_override=reg)
        r2 = get_capable_sources("full_text", sources_override=reg)
        assert r1 == r2

    def test_deterministic_across_calls(self):
        """Same input always produces same output."""
        reg = _make_registry()
        results = [get_capable_sources("full_text", sources_override=reg) for _ in range(10)]
        assert all(r == results[0] for r in results)


# ---------------------------------------------------------------------------
# get_source_by_capability
# ---------------------------------------------------------------------------


class TestGetSourceByCapability:
    def test_returns_best_source(self):
        reg = _make_registry()
        result = get_source_by_capability("full_text", sources_override=reg)
        assert result is not None
        assert result in get_capable_sources("full_text", sources_override=reg)

    def test_no_source_for_unknown(self):
        reg = _make_registry()
        result = get_source_by_capability("nonexistent", sources_override=reg)
        assert result is None

    def test_prefer_order_respected(self):
        reg = _make_registry()
        result = get_source_by_capability(
            "full_text",
            prefer_order=["aym", "bedesten"],
            sources_override=reg,
        )
        assert result == "aym"

    def test_prefer_order_skips_incapable(self):
        reg = _make_registry()
        # kik doesn't support full_text, should skip to next
        result = get_source_by_capability(
            "full_text",
            prefer_order=["kik", "bedesten"],
            sources_override=reg,
        )
        assert result == "bedesten"


# ---------------------------------------------------------------------------
# route_search
# ---------------------------------------------------------------------------


class TestRouteSearch:
    def test_basic(self):
        reg = _make_registry()
        result = route_search("test query", sources_override=reg)
        assert result["ok"] is True
        assert result["query"] == "test query"
        assert isinstance(result["routing"]["eligible_sources"], list)
        assert len(result["routing"]["eligible_sources"]) > 0

    def test_required_capabilities_filters(self):
        reg = _make_registry()
        result = route_search(
            "query",
            required_capabilities=["full_text"],
            sources_override=reg,
        )
        eligible = result["routing"]["eligible_sources"]
        assert "bedesten" in eligible
        assert "kik" not in eligible
        assert "uyusmazlik" not in eligible
        assert "rekabet" not in eligible

    def test_preferred_sources_try_first(self):
        reg = _make_registry()
        result = route_search(
            "query",
            preferred_sources=["aym", "bedesten"],
            sources_override=reg,
        )
        eligible = result["routing"]["eligible_sources"]
        assert eligible[0] == "aym"
        assert eligible[1] == "bedesten"

    def test_exclude_sources_skipped(self):
        reg = _make_registry()
        result = route_search(
            "query",
            exclude_sources=["kik"],
            sources_override=reg,
        )
        assert "kik" not in result["routing"]["eligible_sources"]
        assert "kik" in result["routing"]["excluded_sources"]

    def test_exclude_multiple(self):
        reg = _make_registry()
        result = route_search(
            "query",
            exclude_sources=["kik", "bedesten"],
            sources_override=reg,
        )
        assert "kik" not in result["routing"]["eligible_sources"]
        assert "bedesten" not in result["routing"]["eligible_sources"]
        assert set(result["routing"]["excluded_sources"]) == {"kik", "bedesten"}

    def test_no_capabilities_all_sources(self):
        reg = _make_registry()
        result = route_search("query", sources_override=reg)
        eligible = result["routing"]["eligible_sources"]
        # All sources should be eligible (kik is in the registry, just with search=False)
        assert len(eligible) == len(reg)

    def test_per_source_capability_match(self):
        reg = _make_registry()
        result = route_search(
            "query",
            required_capabilities=["full_text"],
            sources_override=reg,
        )
        for sid, info in result["per_source"].items():
            if sid in ("kik", "uyusmazlik", "rekabet"):
                assert info["capability_match"] is False
            else:
                assert info["capability_match"] is True

    def test_results_empty_by_default(self):
        reg = _make_registry()
        result = route_search("query", sources_override=reg)
        assert result["results"] == []

    def test_deterministic(self):
        reg = _make_registry()
        r1 = route_search("q", required_capabilities=["full_text"], sources_override=reg)
        r2 = route_search("q", required_capabilities=["full_text"], sources_override=reg)
        assert r1["routing"]["eligible_sources"] == r2["routing"]["eligible_sources"]

    def test_combined_preferred_exclude(self):
        reg = _make_registry()
        result = route_search(
            "query",
            preferred_sources=["kik", "aym"],
            exclude_sources=["kik"],
            sources_override=reg,
        )
        eligible = result["routing"]["eligible_sources"]
        # kik excluded even though preferred
        assert "kik" not in eligible
        assert eligible[0] == "aym"


# ---------------------------------------------------------------------------
# route_get_document
# ---------------------------------------------------------------------------


class TestRouteGetDocument:
    def test_basic(self):
        reg = _make_registry()
        result = route_get_document("doc:123", sources_override=reg)
        assert result["ok"] is True
        assert result["document_id"] == "doc:123"
        assert isinstance(result["routing"]["eligible_sources"], list)
        assert len(result["routing"]["eligible_sources"]) > 0

    def test_preferred_source_first(self):
        reg = _make_registry()
        result = route_get_document(
            "doc:123",
            preferred_source="aym",
            sources_override=reg,
        )
        assert result["routing"]["preferred_source"] == "aym"
        eligible = result["routing"]["eligible_sources"]
        assert eligible[0] == "aym"

    def test_preferred_not_capable_fallback(self):
        reg = _make_registry()
        result = route_get_document(
            "doc:123",
            required_capabilities=["full_text"],
            preferred_source="kik",
            sources_override=reg,
        )
        eligible = result["routing"]["eligible_sources"]
        # kik doesn't support full_text, so it shouldn't be first
        assert eligible[0] != "kik"
        assert "aym" in eligible or "bedesten" in eligible

    def test_required_capabilities_filters(self):
        reg = _make_registry()
        result = route_get_document(
            "doc:123",
            required_capabilities=["full_text"],
            sources_override=reg,
        )
        eligible = result["routing"]["eligible_sources"]
        assert "kik" not in eligible
        assert "uyusmazlik" not in eligible

    def test_deterministic(self):
        reg = _make_registry()
        r1 = route_get_document("doc:1", preferred_source="aym", sources_override=reg)
        r2 = route_get_document("doc:1", preferred_source="aym", sources_override=reg)
        assert r1["routing"]["eligible_sources"] == r2["routing"]["eligible_sources"]


# ---------------------------------------------------------------------------
# Unknown capability warning (edge cases)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_required_capabilities(self):
        reg = _make_registry()
        result = route_search("q", required_capabilities=[], sources_override=reg)
        # Empty list means no filtering → all sources eligible
        assert len(result["routing"]["eligible_sources"]) == len(reg)

    def test_single_capability(self):
        reg = _make_registry()
        result = route_search(
            "q",
            required_capabilities=["pdf_link"],
            sources_override=reg,
        )
        eligible = result["routing"]["eligible_sources"]
        assert "rekabet" in eligible
        assert "uyusmazlik" in eligible
        assert "bedesten" not in eligible

    def test_all_capabilities_combined(self):
        """A source must support ALL required capabilities."""
        reg = _make_registry()
        result = route_search(
            "q",
            required_capabilities=["full_text", "workflow"],
            sources_override=reg,
        )
        eligible = result["routing"]["eligible_sources"]
        # kik has workflow=False, full_text=False → excluded
        assert "kik" not in eligible


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


class TestImports:
    def test_router_importable(self):
        import emsal_mcp.router  # noqa: F401
        assert callable(get_capable_sources)
        assert callable(route_search)
        assert callable(route_get_document)
        assert callable(get_source_by_capability)

    def test_capabilities_constant(self):
        assert isinstance(CAPABILITIES, list)
        assert "search" in CAPABILITIES
        assert "full_text" in CAPABILITIES
        assert "pdf_link" in CAPABILITIES