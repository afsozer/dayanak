"""Tests for safety module."""
from __future__ import annotations

import pytest

from emsal_mcp.models import ContentStatus, Document, SafetyState
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
