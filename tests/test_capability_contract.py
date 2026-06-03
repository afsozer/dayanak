"""Tests for v0.2 capability contract.

Covers:
- SourceCapability model round-trip
- Unavailable source behaviour
- CLI ``sources --json`` output shape
- MCP / server import
- Capability matrix completeness
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]

import json
from emsal_mcp.models import SourceCapability, SourceStatus
from emsal_mcp.sources.registry import capabilities, registry


# ── SourceCapability model ──────────────────────────────────────────────

class TestSourceCapabilityModel:
    def test_construct_minimal(self):
        cap = SourceCapability(source_id="x", display_name="X")
        assert cap.source_id == "x"
        assert cap.status == SourceStatus.STABLE
        assert cap.supports_search is True
        assert cap.supports_get_document is True
        assert cap.supports_document is True
        assert cap.live_smoke_recommended is True
        assert cap.known_limitations == []
        assert cap.notes == ""

    def test_construct_unavailable(self):
        cap = SourceCapability(
            source_id="example_unavail",
            display_name="Example Unavailable",
            status=SourceStatus.UNAVAILABLE,
            supports_search=False,
            supports_get_document=True,
            supports_metadata_only=True,
            supports_workflow=False,
            live_smoke_recommended=False,
            known_limitations=["No API"],
            notes="Placeholder",
        )
        assert cap.status == SourceStatus.UNAVAILABLE
        assert cap.supports_search is False
        assert cap.supports_get_document is True
        assert len(cap.known_limitations) == 1

    def test_to_legacy_dict_has_camelcase(self):
        cap = SourceCapability(source_id="t", display_name="T")
        d = cap.to_legacy_dict()
        assert d["citationSafeRule"] == cap.citation_safe_rule
        assert d["noFabrication"] is True
        assert d["tools"] == ["search", "get_document"]
        # Also has snake_case keys
        assert "source_id" in d
        assert "display_name" in d
        # Legacy v0.1 keys
        assert d["source"] == "t"
        assert d["name"] == "T"
        assert d["public"] is True

    def test_model_dump_roundtrip(self):
        cap = SourceCapability(
            source_id="test", display_name="Test",
            known_limitations=["lim1"], notes="n1",
        )
        dumped = cap.model_dump()
        restored = SourceCapability.model_validate(dumped)
        assert restored.source_id == "test"
        assert restored.known_limitations == ["lim1"]
        assert restored.notes == "n1"

    def test_populate_by_name_alias(self):
        """camelCase alias fields accepted via model_validate."""
        data = {
            "source_id": "x", "display_name": "X",
            "citationSafeRule": "custom rule", "noFabrication": False,
        }
        cap = SourceCapability.model_validate(data)
        assert cap.citation_safe_rule == "custom rule"
        assert cap.no_fabrication is False

    def test_status_enum_values(self):
        assert SourceStatus.STABLE.value == "stable"
        assert SourceStatus.PARTIAL.value == "partial"
        assert SourceStatus.EXPERIMENTAL.value == "experimental"
        assert SourceStatus.UNAVAILABLE.value == "unavailable"

    def test_canonical_fields_present(self):
        """All v0.2 canonical fields are present on the model."""
        cap = SourceCapability(source_id="x", display_name="X")
        dumped = cap.model_dump()
        for key in [
            "source_id", "display_name", "status",
            "supports_search", "supports_get_document",
            "supports_full_text", "supports_pdf_link",
            "supports_metadata_only", "supports_article_search",
            "supports_type_filter", "supports_workflow",
            "live_smoke_recommended", "notes", "known_limitations",
        ]:
            assert key in dumped, f"Missing canonical field: {key}"


# ── Registry & capability matrix ────────────────────────────────────────

EXPECTED_SOURCES = [
    "bedesten", "yargitay", "mevzuat", "aym", "danistay",
    "gib", "uyusmazlik", "rekabet", "sayistay",
    "resmigazete", "kvkk",
]


class TestRegistryCompleteness:
    def test_registry_has_all_sources(self):
        reg = registry()
        for sid in EXPECTED_SOURCES:
            assert sid in reg, f"Missing source: {sid}"

    def test_capabilities_count_matches_registry(self):
        caps = capabilities()
        assert len(caps) == len(EXPECTED_SOURCES)

    def test_capability_dict_has_required_keys(self):
        required_keys = {
            "source_id", "display_name", "status",
            "supports_search", "supports_get_document", "supports_document",
            "supports_full_text", "supports_pdf_link", "supports_metadata_only",
            "supports_article_search", "supports_type_filter", "supports_workflow",
            "live_smoke_recommended",
            "known_limitations", "notes",
            "source", "name", "public", "tools",
            "citationSafeRule", "noFabrication",
        }
        for cap in capabilities():
            missing = required_keys - set(cap.keys())
            assert not missing, f"{cap['source_id']}: missing keys {missing}"

    def test_each_capability_has_source_id(self):
        for cap in capabilities():
            assert isinstance(cap["source_id"], str)
            assert len(cap["source_id"]) > 0


# ── CLI sources --json output shape ─────────────────────────────────────

class TestCliSourcesJson:
    def test_sources_json_via_capabilites(self):
        """capabilities() produces valid JSON with correct shape."""
        data = capabilities()
        # Must be JSON-serializable
        json_str = json.dumps(data, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)
        assert len(parsed) == len(EXPECTED_SOURCES)


    def test_active_sources_have_true_capabilities(self):
        data = capabilities()
        active_ids = {"bedesten", "yargitay", "aym", "danistay", "gib"}
        for cap in data:
            if cap["source_id"] in active_ids:
                assert cap["supports_search"] is True
                assert cap["supports_get_document"] is True
                assert cap["status"] == "stable"


# ── MCP / server import ─────────────────────────────────────────────────

class TestMcpServerImport:
    def test_server_main_callable(self):
        from emsal_mcp.server import main
        assert callable(main)

    def test_cli_app_importable(self):
        from emsal_mcp.cli import app
        assert app is not None

    def test_capabilities_callable_from_registry(self):
        from emsal_mcp.sources.registry import capabilities as cap_fn
        assert callable(cap_fn)
        result = cap_fn()
        assert isinstance(result, list)


# ── Document helper contract (search/document) ──────────────────────────

class TestDocumentSearchContract:
    """Verify SearchResult and Document models satisfy the documented contract."""

    def test_search_result_fields(self):
        from emsal_mcp.models import SearchResult, ContentStatus
        sr = SearchResult(
            source="test", document_id="1", title="T",
            court="C", chamber="CH", decision_date="2024-01-01",
            esas_no="E/1", karar_no="K/1",
        )
        assert sr.content_status == ContentStatus.METADATA_ONLY
        d = sr.model_dump()
        assert "source" in d
        assert "content_status" in d

    def test_document_usability(self):
        from emsal_mcp.models import Document, ContentStatus
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="Full text here",
            content_status=ContentStatus.FULL_TEXT,
        )
        assert doc.quote_usable is True
        assert doc.draft_usable is True
        assert doc.text == "Full text here"

    def test_document_unusable_when_metadata_only(self):
        from emsal_mcp.models import Document, ContentStatus
        doc = Document(
            source="test", document_id="1", title="T",
            content_status=ContentStatus.METADATA_ONLY,
        )
        assert doc.quote_usable is False
        assert doc.draft_usable is False

    def test_document_provenance(self):
        from emsal_mcp.models import Document, ContentStatus
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="text", content_status=ContentStatus.FULL_TEXT,
            source_url="https://example.test/1",
        )
        prov = doc.provenance()
        assert prov.source == "test"
        assert prov.document_id == "1"
        assert prov.source_url == "https://example.test/1"

    def test_citation_label(self):
        from emsal_mcp.models import Document, ContentStatus
        doc = Document(
            source="test", document_id="1", title="T",
            full_text="t", content_status=ContentStatus.FULL_TEXT,
            court="Yargitay", chamber="1. Daire",
            decision_date="2024-01-01", esas_no="2024/1", karar_no="100",
        )
        label = doc.citation_label()
        assert "Yargitay" in label
        assert "2024/1" in label
        assert "100" in label