"""Tests for drafter module — assemble_draft, validate_draft_body."""
from __future__ import annotations

from emsal_mcp.models import ContentStatus, Document, InputPack
from emsal_mcp.drafter import assemble_draft, validate_draft_body


def _make_doc(source="test", doc_id="001", esas_no="2023/123", karar_no="2024/456"):
    return Document(
        source=source,
        document_id=doc_id,
        title="Test Kararı",
        full_text="Test content for validation.",
        content_status=ContentStatus.FULL_TEXT,
        decision_date="2024-01-01",
        esas_no=esas_no,
        karar_no=karar_no,
    )


def _make_pack(docs=None, safe_citations=None, excluded=None, warnings=None):
    if docs is None:
        docs = [_make_doc()]
    if safe_citations is None:
        safe_citations = [f"{d.source}:{d.document_id}" for d in docs]
    if excluded is None:
        excluded = []
    if warnings is None:
        warnings = []
    return InputPack(
        matter="Test Matter",
        issue="Test Issue",
        documents=docs,
        safe_citations=safe_citations,
        excluded=excluded,
        warnings=warnings,
    )


class TestAssembleDraft:
    """Tests for assemble_draft()."""

    def test_basic_assemble(self):
        pack = _make_pack()
        draft = assemble_draft(pack, "dilekce", "# Dilekçe\n\nGövde metni.")
        assert draft.kind == "dilekce"
        assert "Gövde metni" in draft.body_markdown
        assert len(draft.citations) >= 1
        assert draft.pack_id == pack.id

    def test_body_with_citation_pattern_creates_warnings(self):
        """Body containing Yargıtay reference should trigger warning."""
        pack = _make_pack()
        draft = assemble_draft(
            pack, "dilekce",
            "Yargıtay 3. Daire kararına göre..."
        )
        assert len(draft.warnings) > 0
        assert any("Yargıtay" in w for w in draft.warnings)

    def test_body_with_esas_no_pattern(self):
        pack = _make_pack()
        draft = assemble_draft(pack, "dilekce", "Esas No: 2023/456 uyarınca...")
        assert len(draft.warnings) > 0
        assert any("Esas numarası" in w for w in draft.warnings)

    def test_body_with_karar_no_pattern(self):
        pack = _make_pack()
        draft = assemble_draft(pack, "cevap", "Karar No: 2024/789 ile...")
        assert any("Karar numarası" in w for w in draft.warnings)

    def test_body_with_danistay_pattern(self):
        pack = _make_pack()
        draft = assemble_draft(pack, "dilekce", "Danıştay 5. Daire...")
        assert any("Danıştay dairesi" in w for w in draft.warnings)

    def test_body_with_aym_pattern(self):
        pack = _make_pack()
        draft = assemble_draft(pack, "dilekce", "Anayasa Mahkemesi kararı...")
        assert any("AYM referansı" in w for w in draft.warnings)

    def test_body_with_year_number_pattern(self):
        pack = _make_pack()
        draft = assemble_draft(pack, "dilekce", "2023/456 sayılı karar.")
        assert len(draft.warnings) > 0
        assert any("Yıl/sayı formatı" in w for w in draft.warnings)

    def test_clean_body_no_warnings(self):
        pack = _make_pack()
        draft = assemble_draft(
            pack, "dilekce",
            "Dilekçe gövdesi. Herhangi bir atıf kalıbı yok."
        )
        assert len(draft.warnings) == 0

    def test_extra_citations_appended(self):
        pack = _make_pack()
        draft = assemble_draft(
            pack, "dilekce", "Gövde.",
            extra_citations=["Ek atıf 1", "Ek atıf 2"]
        )
        assert "Ek atıf 1" in draft.citations
        assert "Ek atıf 2" in draft.citations

    def test_extra_citations_no_duplicates(self):
        pack = _make_pack(safe_citations=["test:001"])
        draft = assemble_draft(
            pack, "dilekce", "Gövde.",
            extra_citations=["test:001", "Ek atıf"]
        )
        # "test:001" should appear only once
        assert draft.citations.count("test:001") == 1
        assert "Ek atıf" in draft.citations

    def test_multiple_documents(self):
        docs = [
            _make_doc(doc_id="001"),
            _make_doc(doc_id="002", esas_no="2024/100"),
        ]
        pack = _make_pack(docs=docs)
        draft = assemble_draft(pack, "dilekce", "Gövde.")
        assert len(draft.citations) >= 2

    def test_citation_patterns_multiple(self):
        pack = _make_pack()
        draft = assemble_draft(
            pack, "dilekce",
            "Yargıtay 3. Daire, Esas No: 2023/456, Karar No: 2024/789"
        )
        # Should detect multiple patterns
        assert len(draft.warnings) >= 3

    def test_empty_pack_assembly(self):
        pack = _make_pack(docs=[], safe_citations=[])
        draft = assemble_draft(pack, "dilekce", "Basit metin.")
        assert draft.citations == []
        assert draft.pack_id == pack.id

    def test_none_extra_citations(self):
        pack = _make_pack(docs=[], safe_citations=[])
        draft = assemble_draft(pack, "dilekce", "Metin.", extra_citations=None)
        assert draft.citations == []

    def test_body_with_newlines(self):
        pack = _make_pack(docs=[], safe_citations=[])
        body = "Satır 1\nSatır 2\nSatır 3"
        draft = assemble_draft(pack, "dilekce", body)
        assert "Satır 1" in draft.body_markdown

    def test_empty_body(self):
        pack = _make_pack(docs=[], safe_citations=[])
        draft = assemble_draft(pack, "dilekce", "")
        assert draft.body_markdown == ""


class TestValidateDraftBody:
    """Tests for validate_draft_body()."""

    def test_no_refs_in_clean_body(self):
        pack = _make_pack()
        issues = validate_draft_body("Temiz metin, referans yok.", pack)
        assert len(issues) == 0

    def test_ref_in_body_matches_pack(self):
        doc = _make_doc(esas_no="2023/456")
        pack = _make_pack(docs=[doc])
        issues = validate_draft_body("2023/456 sayılı karar.", pack)
        # The ref matches pack -> no issue
        assert len(issues) == 0

    def test_ref_in_body_not_in_pack(self):
        doc = _make_doc(esas_no="2023/999")
        pack = _make_pack(docs=[doc])
        issues = validate_draft_body("2023/456 sayılı karar.", pack)
        # 2023/456 is NOT in pack -> issue
        assert len(issues) > 0
        assert "2023/456" in issues[0]

    def test_ref_matches_karar_no(self):
        doc = _make_doc(esas_no="2023/100", karar_no="2024/456")
        pack = _make_pack(docs=[doc])
        issues = validate_draft_body("2024/456 sayılı karar.", pack)
        # Matches karar_no -> no issue
        assert len(issues) == 0

    def test_empty_pack_no_refs(self):
        """Empty pack with no doc_refs in body -> no issues."""
        pack = _make_pack(docs=[], safe_citations=[])
        issues = validate_draft_body("Temiz metin.", pack)
        assert len(issues) == 0

    def test_multiple_refs_partial_match(self):
        docs = [
            _make_doc(doc_id="001", esas_no="2023/100"),
            _make_doc(doc_id="002", karar_no="2024/200"),
        ]
        pack = _make_pack(docs=docs)
        issues = validate_draft_body("2023/100 ve 2023/999 kararları.", pack)
        # 2023/100 matches, 2023/999 does not
        assert len(issues) == 1
        assert "2023/999" in issues[0]

    def test_empty_body(self):
        pack = _make_pack()
        issues = validate_draft_body("", pack)
        assert len(issues) == 0

    def test_both_esas_and_karar_not_in_pack(self):
        doc = _make_doc(esas_no="2023/100", karar_no="2024/200")
        pack = _make_pack(docs=[doc])
        issues = validate_draft_body("2023/999 ve 2024/888 kararları.", pack)
        assert len(issues) == 2


class TestDraftModelIntegration:
    """Integration tests with Draft model."""

    def test_draft_has_citation_patterns_method(self):
        from emsal_mcp.models import Draft as DraftModel
        draft = DraftModel(
            kind="dilekce",
            body_markdown="Yargıtay 2023/456 Esas No 2023 kararı.",
            citations=["ref1"],
        )
        patterns = draft.has_citation_patterns()
        assert len(patterns) > 0

    def test_draft_clean_body_no_patterns(self):
        from emsal_mcp.models import Draft as DraftModel
        draft = DraftModel(
            kind="dilekce",
            body_markdown="Temiz metin.",
            citations=["ref1"],
        )
        patterns = draft.has_citation_patterns()
        assert len(patterns) == 0
