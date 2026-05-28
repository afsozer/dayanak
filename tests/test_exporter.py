"""Tests for exporter module."""
from __future__ import annotations

from emsal_mcp.exporter import create_bundle, export_draft_to_docx, verify_bundle
from emsal_mcp.models import ContentStatus, Document, Draft, InputPack


def make_pack_and_draft():
    doc = Document(
        source="test", document_id="123", title="Test",
        full_text="Test content", content_status=ContentStatus.FULL_TEXT,
        decision_date="2024-01-01", court="Yargıtay", chamber="1. Daire",
        esas_no="2024/1", karar_no="123",
    )
    pack = InputPack(matter="Matter", issue="Issue", documents=[doc],
                     safe_citations=[doc.citation_label()], excluded=[], warnings=[])
    draft = Draft(kind="Dilekçe", body_markdown="Test body text",
                  citations=pack.safe_citations, pack_id=pack.id)
    return pack, draft


class TestExportDOCX:
    def test_export(self, tmp_path):
        pack, draft = make_pack_and_draft()
        output = tmp_path / "test.docx"
        result = export_draft_to_docx(draft, output, pack)
        assert result.exists()
        assert result.stat().st_size > 0


class TestBundle:
    def test_create_and_verify(self, tmp_path):
        pack, draft = make_pack_and_draft()
        bundle = create_bundle(draft, pack, tmp_path)
        assert bundle.exists()

        result = verify_bundle(bundle)
        assert result["valid"] is True
        assert "hashes" in result

    def test_verify_missing(self, tmp_path):
        result = verify_bundle(tmp_path / "missing.zip")
        assert result["valid"] is False

    def test_bundle_content_hash(self, tmp_path):
        pack, draft = make_pack_and_draft()
        bundle = create_bundle(draft, pack, tmp_path)

        import hashlib
        import json
        from zipfile import ZipFile

        with ZipFile(bundle, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
            draft_content = zf.read("draft.json")
            computed = hashlib.sha256(draft_content).hexdigest()
            assert computed == manifest["draft_hash"]
