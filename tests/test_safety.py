"""Tests for safety module."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]

import pytest

from emsal_mcp.models import ContentStatus, Document, SafetyState, SearchResult, merge_search_metadata
from emsal_mcp.safety import build_input_pack, citation_check, exact_quote, verify_document_hash


def make_doc(**kwargs) -> Document:
    defaults = {
        "source": "test",
        "document_id": "123",
        "title": "Test Document",
        "full_text": "Bu bir test belgesidir.",
        "content_status": ContentStatus.FULL_TEXT,
        "decision_date": "2024-01-01",
    }
    defaults.update(kwargs)
    return Document(**defaults)


class TestMergeSearchMetadata:
    def test_fills_empty_provenance_and_unblocks_citation(self):
        # Document with full text but no provenance (Bedesten getDocumentContent
        # returns content-only) → citation_check fails.
        doc = Document(
            source="bedesten", document_id="1208605300", title="1208605300",
            full_text="8. Hukuk Dairesi ... uzun karar metni " * 5,
            content_status=ContentStatus.HTML_MARKDOWN,
        )
        assert citation_check(doc).quoteUsable is False
        sr = SearchResult(
            source="bedesten", document_id="1208605300", title="8. HD kararı",
            esas_no="2024/271", karar_no="2026/2944", decision_date="28.04.2026",
            court="Yargıtay", chamber="8. Hukuk Dairesi",
        )
        merge_search_metadata(doc, sr)
        assert doc.esas_no == "2024/271"
        assert doc.karar_no == "2026/2944"
        assert doc.decision_date == "28.04.2026"
        assert citation_check(doc).quoteUsable is True

    def test_never_overwrites_existing_values(self):
        doc = Document(
            source="bedesten", document_id="1", title="Gerçek Başlık",
            esas_no="2020/100", decision_date="01.01.2020",
            full_text="metin", content_status=ContentStatus.HTML_MARKDOWN,
        )
        sr = SearchResult(
            source="bedesten", document_id="1", title="Farklı Başlık",
            esas_no="9999/999", karar_no="2021/55", decision_date="02.02.2021",
        )
        merge_search_metadata(doc, sr)
        # Existing values preserved
        assert doc.esas_no == "2020/100"
        assert doc.decision_date == "01.01.2020"
        assert doc.title == "Gerçek Başlık"
        # Only the empty field is filled
        assert doc.karar_no == "2021/55"


class TestCitationCheck:
    def test_safe_document(self):
        doc = make_doc()
        result = citation_check(doc)
        assert result.ok is True
        assert result.quoteUsable is True
        assert result.draftUsable is True
        assert result.safety_state == SafetyState.SAFE
        assert result.reasons == []

    def test_unsafe_no_full_text(self):
        doc = make_doc(content_status=ContentStatus.METADATA_ONLY, full_text=None, markdown=None)
        result = citation_check(doc)
        assert result.ok is False
        assert result.quoteUsable is False
        assert result.safety_state == SafetyState.UNSAFE
        assert any("tam metin yok" in r for r in result.reasons)

    def test_unsafe_empty_text(self):
        doc = make_doc(full_text="", content_status=ContentStatus.FULL_TEXT)
        result = citation_check(doc)
        assert result.ok is False
        assert any("metni boş" in r for r in result.reasons)

    def test_unsafe_no_provenance(self):
        doc = make_doc(decision_date=None, esas_no=None, karar_no=None, source_url=None)
        result = citation_check(doc)
        assert result.ok is False
        assert any("metadata" in r.lower() for r in result.reasons)

    def test_safe_with_markdown(self):
        doc = make_doc(content_status=ContentStatus.HTML_MARKDOWN, markdown="Test markdown", full_text=None)
        result = citation_check(doc)
        assert result.ok is True


class TestExactQuote:
    def test_found(self):
        doc = make_doc(full_text="Bu bir test belgesidir. İçerik burada.")
        quote = exact_quote(doc, "test belgesidir")
        assert "test belgesidir" in quote

    def test_not_found(self):
        doc = make_doc(full_text="Başka bir metin.")
        with pytest.raises(ValueError, match="bulunamadı"):
            exact_quote(doc, "olmayan ibare")

    def test_context(self):
        text = "A" * 100 + "HEDEF" + "B" * 100
        doc = make_doc(full_text=text)
        quote = exact_quote(doc, "HEDEF", context=10)
        assert "HEDEF" in quote
        assert len(quote) < 50


class TestBuildInputPack:
    def test_all_safe(self):
        docs = [make_doc(), make_doc(document_id="456")]
        pack = build_input_pack("Matter", "Issue", docs)
        assert len(pack.documents) == 2
        assert len(pack.excluded) == 0
        assert len(pack.safe_citations) == 2

    def test_mixed_safe_unsafe(self):
        safe = make_doc()
        unsafe = make_doc(document_id="999", content_status=ContentStatus.METADATA_ONLY, full_text=None)
        pack = build_input_pack("Matter", "Issue", [safe, unsafe])
        assert len(pack.documents) == 1
        assert len(pack.excluded) == 1
        assert pack.excluded[0]["document_id"] == "999"

    def test_all_unsafe(self):
        unsafe = make_doc(content_status=ContentStatus.METADATA_ONLY, full_text=None)
        pack = build_input_pack("Matter", "Issue", [unsafe])
        assert len(pack.documents) == 0
        assert len(pack.excluded) == 1


class TestVerifyDocumentHash:
    def test_valid_hash(self):
        from hashlib import sha256
        doc = make_doc(full_text="Test content")
        expected = sha256("Test content".encode("utf-8")).hexdigest()
        doc.content_hash = expected
        assert verify_document_hash(doc) is True

    def test_invalid_hash(self):
        doc = make_doc(full_text="Test content")
        doc.content_hash = "invalid_hash"
        assert verify_document_hash(doc) is False

    def test_no_hash(self):
        doc = make_doc(full_text="Test content")
        doc.content_hash = None
        assert verify_document_hash(doc) is True


class TestSafetyInvariants:
    """Invariant tests for safety.py — these must NEVER break."""

    def test_metadata_only_never_draft_usable(self):
        """Invariant: metadata_only documents are NEVER quote/draft usable."""
        statuses = [
            ContentStatus.METADATA_ONLY,
            ContentStatus.PDF_LINK_ONLY,
            ContentStatus.UNAVAILABLE,
        ]
        for status in statuses:
            doc = make_doc(content_status=status, full_text=None, markdown=None)
            result = citation_check(doc)
            assert result.ok is False, f"{status} should NOT pass citation_check"
            assert result.quoteUsable is False, f"{status} should NOT be quoteUsable"
            assert result.draftUsable is False, f"{status} should NOT be draftUsable"

    def test_full_text_is_usable(self):
        """Invariant: full_text and html_markdown with content ARE usable."""
        doc = make_doc(content_status=ContentStatus.FULL_TEXT, full_text="A" * 100)
        result = citation_check(doc)
        assert result.ok is True
        assert result.quoteUsable is True
        assert result.draftUsable is True

    def test_empty_full_text_not_usable(self):
        """Invariant: empty full_text is NOT usable."""
        doc = make_doc(content_status=ContentStatus.FULL_TEXT, full_text="")
        result = citation_check(doc)
        assert result.ok is False

    def test_no_provenance_not_usable(self):
        """Invariant: missing provenance (date/esas/karar/url) is NOT usable."""
        doc = make_doc(
            decision_date=None, esas_no=None, karar_no=None, source_url=None
        )
        result = citation_check(doc)
        assert result.ok is False
        assert "metadata" in " ".join(result.reasons).lower()

    def test_exact_quote_never_fabricates(self):
        """Invariant: exact_quote never returns text that doesn't contain the phrase."""
        doc = make_doc(full_text="Test metni burada.")
        with pytest.raises(ValueError):
            exact_quote(doc, "olmayan bir ibare")
        # Also test with empty text
        doc2 = make_doc(full_text="")
        with pytest.raises(ValueError):
            exact_quote(doc2, "anything")

    def test_build_input_pack_excludes_unsafe(self):
        """Invariant: build_input_pack excludes all metadata_only documents."""
        safe = make_doc(document_id="safe")
        meta_only = make_doc(
            document_id="meta", content_status=ContentStatus.METADATA_ONLY,
            full_text=None, markdown=None,
        )
        pdf_only = make_doc(
            document_id="pdf", content_status=ContentStatus.PDF_LINK_ONLY,
            full_text=None, markdown=None,
        )
        pack = build_input_pack("m", "i", [safe, meta_only, pdf_only])
        assert len(pack.documents) == 1
        assert pack.documents[0].document_id == "safe"
        assert len(pack.excluded) == 2
        excluded_ids = {e["document_id"] for e in pack.excluded}
        assert excluded_ids == {"meta", "pdf"}

    def test_input_pack_has_no_invention_warning(self):
        """Invariant: build_input_pack always includes the no-invention warning."""
        pack = build_input_pack("m", "i", [make_doc()])
        assert any("eksik metadata uydurulmaz" in w for w in pack.warnings)

    def test_citation_check_markdown_usable(self):
        """Invariant: html_markdown with content IS usable."""
        doc = make_doc(
            content_status=ContentStatus.HTML_MARKDOWN,
            full_text=None, markdown="A" * 100,
        )
        result = citation_check(doc)
        assert result.ok is True
        assert result.draftUsable is True

    def test_verify_document_hash_without_text(self):
        """Invariant: document without text but with hash should fail."""
        doc = make_doc(full_text=None, markdown=None, content_status=ContentStatus.METADATA_ONLY)
        doc.content_hash = "some_hash"
        result = verify_document_hash(doc)
        assert result is False

    def test_verify_document_hash_without_hash(self):
        """Invariant: no hash to verify means OK."""
        doc = make_doc()
        doc.content_hash = None
        assert verify_document_hash(doc) is True
