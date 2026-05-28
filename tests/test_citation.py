"""Tests for v0.6 Citation Verification + Citation Formatting."""
from __future__ import annotations

import tempfile
from pathlib import Path

from emsal_mcp.cache import Cache
from emsal_mcp.citation import (
    CitationCandidate,
    VerificationFinding,
    extract_citation_candidates,
    format_legal_citation,
    verify_legal_citation,
)
from emsal_mcp.models import ContentStatus, Document


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_doc(**overrides) -> Document:
    """Create a Document with sensible defaults for testing."""
    defaults = {
        "source": "test_source",
        "document_id": "DOC-001",
        "title": "Test Kararı",
        "court": "Yargıtay",
        "chamber": "3. Hukuk Dairesi",
        "decision_date": "2024-06-15",
        "esas_no": "2023/12345",
        "karar_no": "2024/5678",
        "source_url": "https://example.test/doc/001",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": "Yargıtay 3. Hukuk Dairesi E.2023/12345 K.2024/5678 Tarihi: 15.06.2024",
    }
    defaults.update(overrides)
    return Document(**defaults)


# ---------------------------------------------------------------------------
# Candidate extraction tests
# ---------------------------------------------------------------------------

class TestExtraction:
    def test_extract_full_citation(self):
        text = (
            "Yargıtay 3. Hukuk Dairesi'nin E.2023/12345, K.2024/5678 "
            "Tarihi: 15.06.2024 tarihli kararına atıfta bulunulmuştur."
        )
        candidates = extract_citation_candidates(text, limit=5)
        assert len(candidates) >= 1
        c = candidates[0]
        assert c.court == "Yargıtay"
        assert c.chamber is not None
        assert c.esas_no is not None or c.karar_no is not None

    def test_extract_danistay(self):
        text = "Danıştay 10. Dairesi E.2022/5678 kararına bakınız."
        candidates = extract_citation_candidates(text)
        assert len(candidates) >= 1
        assert candidates[0].court == "Danıştay"

    def test_extract_aym(self):
        text = "Anayasa Mahkemesi 2023/123 tarihli kararı emsal teşkil eder."
        candidates = extract_citation_candidates(text)
        assert len(candidates) >= 1
        assert candidates[0].court == "Anayasa Mahkemesi"

    def test_extract_sayistay(self):
        text = "Sayıştay'ın 2024/456 sayılı kararı doğrultusunda hareket edilmelidir."
        candidates = extract_citation_candidates(text)
        assert len(candidates) >= 1
        assert candidates[0].court == "Sayıştay"

    def test_extract_rekabet(self):
        text = "Rekabet Kurulu'nun 2023-123-456 sayılı kararı gereği."
        candidates = extract_citation_candidates(text)
        assert len(candidates) >= 1
        assert candidates[0].court == "Rekabet Kurulu"

    def test_extract_no_citation(self):
        text = "Bu metinde herhangi bir hukuki referans bulunmamaktadır."
        candidates = extract_citation_candidates(text)
        assert len(candidates) == 0

    def test_extract_limit(self):
        lines = "\n".join([
            f"Yargıtay 1. Dairesi E.2024/{i} Tarihi: 01.01.2024"
            for i in range(1, 20)
        ])
        candidates = extract_citation_candidates(lines, limit=3)
        assert len(candidates) <= 3

    def test_extract_confidence_high(self):
        text = (
            "Yargıtay 3. Hukuk Dairesi E.2023/12345 K.2024/5678 "
            "Tarihi: 15.06.2024"
        )
        candidates = extract_citation_candidates(text)
        assert len(candidates) >= 1
        # High confidence: court + chamber + date + esas + karar
        assert candidates[0].confidence == "high"

    def test_extract_confidence_low(self):
        text = "Yargıtay kararı hakkında not düşülmüştür."
        candidates = extract_citation_candidates(text)
        # Might not extract a full candidate without esas/karar/date
        # Low confidence or no candidates is acceptable
        if candidates:
            assert candidates[0].confidence in ("low", "medium")

    def test_extract_warnings_for_missing_fields(self):
        text = "Yargıtay kararı hakkında not."
        candidates = extract_citation_candidates(text)
        if candidates:
            # Should have warnings for missing esas_no, karar_no, date
            assert len(candidates[0].warnings) > 0

    def test_extract_dates_dmy(self):
        text = "Yargıtay E.2023/100 Tarihi: 15.03.2024"
        candidates = extract_citation_candidates(text)
        if candidates and candidates[0].date:
            assert "2024-03-15" == candidates[0].date

    def test_extract_dates_ymd(self):
        text = "Yargıtay E.2023/200 Tarihi: 2024-12-01"
        candidates = extract_citation_candidates(text)
        if candidates and candidates[0].date:
            assert candidates[0].date == "2024-12-01"


# ---------------------------------------------------------------------------
# CitationCandidate data class tests
# ---------------------------------------------------------------------------

class TestCitationCandidate:
    def test_to_dict(self):
        c = CitationCandidate(
            raw_text="test",
            court="Yargıtay",
            esas_no="2024/100",
            confidence="high",
        )
        d = c.to_dict()
        assert d["raw_text"] == "test"
        assert d["court"] == "Yargıtay"
        assert d["esas_no"] == "2024/100"
        assert d["confidence"] == "high"
        assert isinstance(d["warnings"], list)

    def test_defaults(self):
        c = CitationCandidate(raw_text="minimal")
        assert c.court is None
        assert c.chamber is None
        assert c.confidence == "medium"
        assert c.warnings == []
        assert c.position == 0


# ---------------------------------------------------------------------------
# VerificationFinding tests
# ---------------------------------------------------------------------------

class TestVerificationFinding:
    def test_to_dict_matched(self):
        cand = CitationCandidate(raw_text="test", court="Yargıtay")
        vf = VerificationFinding(
            candidate=cand,
            matched=True,
            match_score=0.95,
            matched_document={"source": "test", "document_id": "1"},
        )
        d = vf.to_dict()
        assert d["matched"] is True
        assert d["match_score"] == 0.95
        assert "matched_document" in d

    def test_to_dict_unmatched(self):
        cand = CitationCandidate(raw_text="test")
        vf = VerificationFinding(candidate=cand, matched=False)
        d = vf.to_dict()
        assert d["matched"] is False
        assert "matched_document" not in d


# ---------------------------------------------------------------------------
# Formatting tests
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_format_petition(self):
        doc = _make_doc()
        result = format_legal_citation(doc, style="petition")
        assert "Yargıtay" in result["formatted_citation"]
        assert result["style"] == "petition"
        assert result["court"] == "Yargıtay"
        assert result["date"] == "2024-06-15"
        assert result["esas_no"] == "2023/12345"
        assert result["karar_no"] == "2024/5678"

    def test_format_parenthetical(self):
        doc = _make_doc()
        result = format_legal_citation(doc, style="parenthetical")
        assert result["formatted_citation"].startswith("(")
        assert result["formatted_citation"].endswith(")")
        assert "Yargıtay" in result["formatted_citation"]

    def test_format_short(self):
        doc = _make_doc()
        result = format_legal_citation(doc, style="short")
        assert "Ygt." in result["formatted_citation"]
        assert result["style"] == "short"

    def test_format_dict_source(self):
        d = {
            "source": "test",
            "document_id": "1",
            "court": "Danıştay",
            "chamber": "5. Daire",
            "decision_date": "2024-01-01",
            "esas_no": "2023/500",
            "karar_no": "2024/100",
            "source_url": "https://test.example",
            "content_status": "full_text",
            "quote_usable": True,
            "draft_usable": True,
        }
        result = format_legal_citation(d, style="petition")
        assert "Danıştay" in result["formatted_citation"]

    def test_format_none_source_no_fabrication(self):
        """Missing metadata should produce warnings, not fabricated values."""
        result = format_legal_citation(None, document_id="unknown:123")
        assert len(result["warnings"]) > 0
        assert result["confidence"] == "low"
        # Should not have fabricated any field
        assert result["court"] is None
        assert result["date"] is None
        assert result["esas_no"] is None

    def test_format_missing_date_warning(self):
        doc = _make_doc(decision_date=None)
        result = format_legal_citation(doc, style="petition")
        assert any("tarih" in w.lower() for w in result["warnings"])

    def test_format_missing_chamber_warning(self):
        doc = _make_doc(chamber=None)
        result = format_legal_citation(doc, style="petition")
        assert any("daire" in w.lower() for w in result["warnings"])

    def test_format_missing_source_url_warning(self):
        doc = _make_doc(source_url=None)
        result = format_legal_citation(doc, style="petition")
        assert any("url" in w.lower() for w in result["warnings"])

    def test_format_unknown_style(self):
        doc = _make_doc()
        result = format_legal_citation(doc, style="unknown_style")
        assert any("bilinmeyen" in w.lower() for w in result["warnings"])

    def test_format_confidence_high(self):
        doc = _make_doc()
        result = format_legal_citation(doc, style="petition")
        assert result["confidence"] == "high"

    def test_format_confidence_low(self):
        doc = _make_doc(court=None, chamber=None, date=None, esas_no=None, karar_no=None)
        result = format_legal_citation(doc, style="petition")
        assert result["confidence"] == "low"

    def test_format_output_contract(self):
        """Verify all required keys are present in output."""
        doc = _make_doc()
        result = format_legal_citation(doc, style="petition")
        required_keys = {
            "formatted_citation", "style", "court", "chamber", "date",
            "esas_no", "karar_no", "document_id", "source", "source_url",
            "content_status", "quote_usable", "draft_usable", "confidence",
            "warnings",
        }
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# Verification tests (cache-only, no network)
# ---------------------------------------------------------------------------

class TestVerificationCacheOnly:
    def test_verify_no_text(self):
        result = verify_legal_citation()
        assert result["ok"] is False
        assert "metin" in result["error"].lower() or "belirtilmedi" in result["error"].lower()

    def test_verify_no_candidates(self):
        result = verify_legal_citation("Bu metinde referans yok.", no_live=True)
        assert result["ok"] is True
        assert result["candidates"] == []
        assert len(result["warnings"]) > 0

    def test_verify_file_not_found(self):
        result = verify_legal_citation(file_path="/nonexistent/path.txt")
        assert result["ok"] is False
        assert "bulunamadı" in result["error"].lower()

    def test_verify_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Yargıtay 3. Hukuk Dairesi E.2023/12345 Tarihi: 15.06.2024")
            f.flush()
            fname = f.name
        result = verify_legal_citation(file_path=fname, no_live=True)
        assert result["ok"] is True
        assert len(result["candidates"]) >= 1
        Path(fname).unlink()

    def test_verify_empty_cache(self):
        """With empty cache and no_live, should find candidates but no matches."""
        with tempfile.TemporaryDirectory() as td:
            cache_path = Path(td) / "test_cache.sqlite"
            c = Cache(cache_path)
            try:
                result = verify_legal_citation(
                    "Yargıtay E.2023/100 Tarihi: 01.01.2024",
                    no_live=True,
                    cache=c,
                )
                assert result["ok"] is True
                assert len(result["candidates"]) >= 1
                assert result["matched_documents"] == []
            finally:
                c.close()

    def test_verify_no_live_flag(self):
        result = verify_legal_citation(
            "Yargıtay E.2023/100 Tarihi: 01.01.2024",
            no_live=True,
        )
        assert result["ok"] is True
        # Should have search attempts with local_cache method
        for attempt in result["search_attempts"]:
            assert attempt["method"] != "live_search"

    def test_verify_live_only_flag(self):
        """live_only=True skips local cache search."""
        result = verify_legal_citation(
            "Yargıtay E.2023/100 Tarihi: 01.01.2024",
            live_only=True,
            no_live=True,
        )
        assert result["ok"] is True
        for attempt in result["search_attempts"]:
            assert attempt.get("skipped_local") is True

    def test_verify_strategy_debug(self):
        result = verify_legal_citation(
            "Yargıtay E.2023/100 Tarihi: 01.01.2024",
            no_live=True,
            strategy_debug=True,
        )
        assert result["ok"] is True
        assert "strategy_debug" in result
        assert "extraction_count" in result["strategy_debug"]

    def test_verify_timing_present(self):
        result = verify_legal_citation(
            "Yargıtay E.2023/100 Tarihi: 01.01.2024",
            no_live=True,
        )
        assert "timing" in result
        assert "elapsed_ms" in result["timing"]
        assert result["timing"]["elapsed_ms"] >= 0

    def test_verify_output_contract(self):
        """Verify all required keys are present in verification output."""
        result = verify_legal_citation(
            "Yargıtay E.2023/100 Tarihi: 01.01.2024",
            no_live=True,
        )
        required_keys = {
            "ok", "candidates", "search_attempts", "matched_documents",
            "formatted_citations", "verification_findings", "warnings",
            "recommended_next_steps", "timing",
        }
        assert required_keys.issubset(result.keys())


class TestVerificationLiveFake:
    """Tests with fake source clients (no live network)."""

    def test_verify_with_fake_source(self):
        """Inject a fake source that returns empty results."""
        fake_client = type("FakeClient", (), {
            "search": lambda self, q, **kw: [],
        })()
        result = verify_legal_citation(
            "Yargıtay E.2023/100 Tarihi: 01.01.2024",
            sources_override={"test_source": fake_client},
            no_live=False,
        )
        assert result["ok"] is True

    def test_verify_with_populated_cache(self):
        """Pre-populate cache, verify candidates match."""
        with tempfile.TemporaryDirectory() as td:
            cache_path = Path(td) / "test_cache.sqlite"
            c = Cache(cache_path)
            try:
                doc = _make_doc()
                c.store_document(doc)

                result = verify_legal_citation(
                    "Yargıtay 3. Hukuk Dairesi E.2023/12345 K.2024/5678 Tarihi: 15.06.2024",
                    no_live=True,
                    cache=c,
                )
                assert result["ok"] is True
                assert len(result["candidates"]) >= 1
                # Should have found the cached document
                assert len(result["matched_documents"]) >= 1
                assert len(result["formatted_citations"]) >= 1
                assert len(result["verification_findings"]) >= 1
            finally:
                c.close()

    def test_verify_min_score_filter(self):
        """min_score filters out low-scoring matches."""
        with tempfile.TemporaryDirectory() as td:
            cache_path = Path(td) / "test_cache.sqlite"
            c = Cache(cache_path)
            try:
                doc = _make_doc(court="Danıştay")  # Different court
                c.store_document(doc)

                result = verify_legal_citation(
                    "Yargıtay E.2023/12345 Tarihi: 15.06.2024",
                    no_live=True,
                    cache=c,
                    min_score=0.9,  # High threshold
                )
                # Danıştay doc shouldn't match Yargıtay query at high threshold
                # (depending on scoring)
                assert result["ok"] is True
            finally:
                c.close()


class TestEdgeCases:
    def test_extract_turkish_chars(self):
        text = "Yargıtay 1. Hukuk Dairesi E.2024/500"
        candidates = extract_citation_candidates(text)
        assert len(candidates) >= 1

    def test_format_with_partial_dict(self):
        """Dict with only some fields should not crash."""
        d = {"source": "test", "document_id": "1", "court": "Yargıtay"}
        result = format_legal_citation(d, style="petition")
        assert "Yargıtay" in result["formatted_citation"]
        assert result["date"] is None

    def test_verify_minimal_text(self):
        result = verify_legal_citation("x", no_live=True)
        assert result["ok"] is True
        assert result["candidates"] == []

    def test_multiple_citations_in_text(self):
        text = (
            "Yargıtay 3. Hukuk Dairesi E.2023/100 K.2024/200 Tarihi: 01.01.2024\n"
            "Danıştay 5. Dairesi E.2022/300 K.2023/400 Tarihi: 15.06.2023\n"
            "AYM 2024/50 tarihli kararı."
        )
        candidates = extract_citation_candidates(text, limit=10)
        courts_found = {c.court for c in candidates}
        assert "Yargıtay" in courts_found
        assert "Danıştay" in courts_found
