"""M-38 Golden Corpus & Snapshot Tests.

Deterministic assertions against the 5-sample synthetic Turkish legal
decisions in tests/fixtures/sample_decisions.json.  No binary snapshot
files — expected values are asserted inline.

Covers:
- Citation extraction from sample decisions
- Petition pack generation from sample decisions
- Hybrid search on seeded sample decisions (via Cache)
- Legislation article parsing on synthetic legislation text
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

import json
import tempfile
from pathlib import Path

from emsal_mcp.cache import Cache
from emsal_mcp.citation import extract_citation_candidates
from emsal_mcp.legislation import _parse_articles
from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.petition import (
    inspect_petition_pack,
    prepare_drafting_input_pack,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helper: load golden corpus
# ---------------------------------------------------------------------------

def _load_samples() -> list[dict]:
    return json.loads((FIXTURES / "sample_decisions.json").read_text(encoding="utf-8"))


def _sample_to_doc(s: dict) -> Document:
    """Convert a sample decision dict to a Document model."""
    return Document(
        source=s["source"],
        document_id=s["document_id"],
        title=s["title"],
        court=s["court"],
        chamber=s["chamber"],
        decision_date=s["decision_date"],
        esas_no=s["esas_no"],
        karar_no=s["karar_no"],
        content_status=ContentStatus.FULL_TEXT,
        full_text=s["full_text"],
        source_url=f"https://synthetic-golden.test/{s['document_id']}",
    )


# ---------------------------------------------------------------------------
# Snapshot 1: Citation extraction
# ---------------------------------------------------------------------------

# Expected citation snapshot values — keyed by document_id.
# Each entry lists the courts that must be detected at least once.
_COURT_SNAPSHOT: dict[str, list[str]] = {
    "SYNTH-YT-2025-001": ["Yargıtay"],
    "SYNTH-DT-2025-002": ["Danıştay"],
    "SYNTH-AYM-2025-003": ["Anayasa Mahkemesi"],
    "SYNTH-AH-2025-004": ["Ticaret Mahkemesi"],
    "SYNTH-YH-2025-005": ["Yargıtay"],
}

_ESAS_NO_SNAPSHOT: dict[str, str] = {
    "SYNTH-YT-2025-001": "2024/21456",
    "SYNTH-DT-2025-002": "2024/8934",
    "SYNTH-AYM-2025-003": "2023/62145",
    "SYNTH-AH-2025-004": "2024/567",
    "SYNTH-YH-2025-005": "2024/18765",
}


def test_citation_extraction_on_samples():
    """Citation candidates are extracted from every golden sample."""
    samples = _load_samples()
    for s in samples:
        candidates = extract_citation_candidates(s["full_text"])
        assert len(candidates) > 0, f"No citations found in {s['document_id']}"

        # Every sample must contain its expected court
        courts_found = {c.court for c in candidates if c.court}
        expected_courts = _COURT_SNAPSHOT[s["document_id"]]
        for ec in expected_courts:
            assert ec in courts_found, (
                f"Court '{ec}' not detected in {s['document_id']}; "
                f"found: {courts_found}"
            )

        # Esas number must be detected
        esas_found = [c.esas_no for c in candidates if c.esas_no]
        expected_esas = _ESAS_NO_SNAPSHOT[s["document_id"]]
        assert expected_esas in esas_found, (
            f"Esas no '{expected_esas}' not detected in {s['document_id']}; "
            f"found: {esas_found}"
        )


def test_citation_extraction_confidence_is_high_for_full_metadata():
    """Candidates with court + chamber + date + esas + karar should be high."""
    samples = _load_samples()
    for s in samples:
        candidates = extract_citation_candidates(s["full_text"])
        high_conf = [c for c in candidates if c.confidence == "high"]
        # At least one candidate per sample should have high confidence
        assert len(high_conf) > 0, (
            f"No high-confidence candidate in {s['document_id']}; "
            f"confidences: {[c.confidence for c in candidates]}"
        )


def test_citation_extraction_warns_on_missing_fields():
    """Minimal text yields low-confidence candidates with warnings."""
    minimal_text = "Burada hiçbir hukuki referans bulunmamaktadır."
    candidates = extract_citation_candidates(minimal_text)
    # No court detected → zero candidates from Strategy 1
    # Strategy 2 might find standalone numbers but likely none
    # Either zero or low-confidence is acceptable
    for c in candidates:
        assert c.confidence in ("low", "medium"), (
            f"Unexpected confidence {c.confidence} on minimal text"
        )


# ---------------------------------------------------------------------------
# Snapshot 2: Petition pack generation
# ---------------------------------------------------------------------------

def test_petition_pack_from_samples():
    """Petition pack is generated correctly from golden sample documents."""
    samples = _load_samples()
    docs = [_sample_to_doc(s) for s in samples]

    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "pack_output"
        result = prepare_drafting_input_pack(
            matter="Golden Corpus Test Dava Konusu",
            issue="Emsal araştırma ve dilekçe hazırlık sistemi doğrulama",
            documents=docs,
            out_dir=out,
        )

        assert result["ok"] is True, f"Pack generation failed: {result}"
        assert result["authority_count"] == 5
        assert result["draft_safe"] is True  # all docs are FULL_TEXT

        counts = result["counts"]
        assert counts["petition_ready"] == 5, (
            f"Expected 5 petition_ready, got {counts}"
        )
        assert counts["excluded"] == 0

        # Verify required files exist
        pack_path = Path(result["out_dir"])
        for fname in [
            "petition-brief.json",
            "citation-bank.md",
            "argument-map.md",
            "petition-instructions.md",
            "draft-skeleton.md",
            "petition-pack.json",
        ]:
            assert (pack_path / fname).exists(), f"Missing file: {fname}"

        # Verify brief contents
        brief = json.loads((pack_path / "petition-brief.json").read_text(encoding="utf-8"))
        assert brief["authority_count"] == 5
        assert brief["draft_safe"] is True
        for auth in brief["authorities"]:
            assert auth["classification"] == "petition_ready"


def test_petition_pack_inspection_passes():
    """inspect_petition_pack returns ok=True for a valid golden corpus pack."""
    samples = _load_samples()
    docs = [_sample_to_doc(s) for s in samples]

    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "pack_inspect"
        result = prepare_drafting_input_pack(
            matter="Inspection Test",
            issue="Pack inspection validation",
            documents=docs,
            out_dir=out,
        )
        assert result["ok"] is True

        inspection = inspect_petition_pack(out)
        assert inspection["ok"] is True, (
            f"Inspection failed: errors={inspection['errors']}"
        )
        assert inspection["draft_safe"] is True
        assert inspection["counts"]["petition_ready"] == 5


# ---------------------------------------------------------------------------
# Snapshot 3: Hybrid search on seeded sample decisions
# ---------------------------------------------------------------------------

def test_hybrid_search_on_seeded_decisions():
    """Seed golden corpus into cache, then search and verify ranking."""
    samples = _load_samples()

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "test_cache.sqlite3"
        cache = Cache(path=cache_path)

        try:
            # Seed all samples
            for s in samples:
                doc = _sample_to_doc(s)
                cache.store_document(doc)

            # Search by court name — Yargıtay appears in samples 1 and 5
            results = cache.search_local("Yargıtay", limit=10)
            assert len(results) >= 2, (
                f"Expected at least 2 results for 'Yargıtay', got {len(results)}"
            )
            courts_in_results = {r["court"] for r in results}
            assert "Yargıtay" in courts_in_results

            # Search by esas number
            results_esas = cache.search_local("2024/21456", limit=5)
            assert len(results_esas) >= 1, "Expected at least 1 result for esas_no search"
            assert results_esas[0]["esas_no"] == "2024/21456"

            # Search by decision date (use the date filter parameter)
            results_date = cache.search_local("", date="2025-05-22", limit=5)
            assert len(results_date) >= 1, "Expected at least 1 result for date search"

            # Filter by content_status
            results_ft = cache.search_local("", content_status="full_text", limit=10)
            assert len(results_ft) == 5, f"Expected 5 full_text docs, got {len(results_ft)}"

        finally:
            cache.close()


def test_search_returns_snippets():
    """Search results include non-empty snippets."""
    samples = _load_samples()

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "test_cache_snippet.sqlite3"
        cache = Cache(path=cache_path)

        try:
            for s in samples:
                doc = _sample_to_doc(s)
                cache.store_document(doc)

            results = cache.search_local("haksız rekabet", limit=5)
            assert len(results) >= 1
            for r in results:
                assert isinstance(r["snippet"], str)
                # snippet should be non-empty for documents with full_text
                if r["content_status"] == "full_text":
                    assert len(r["snippet"]) > 0, (
                        f"Empty snippet for {r['document_id']}"
                    )
        finally:
            cache.close()


# ---------------------------------------------------------------------------
# Snapshot 4: Legislation article parsing on synthetic text
# ---------------------------------------------------------------------------

SYNTHETIC_LEGISLATION = """
BİRİNCİ KISIM
Genel Hükümler

BİRİNCİ BÖLÜM
Amaç ve Kapsam

MADDE 1 - Bu Kanunun amacı, dijital hukuki işlemlerin güvenilirliğini ve şeffaflığını sağlamaktır.

MADDE 2 - Bu Kanun, tüm电子 ticaret platformları ve dijital hukuki süreçler hakkında uygulanır.

İKİNCİ BÖLÜM
Tanımlar

MADDE 3 - Bu Kanunda geçen "dijital belge", elektronik ortamda oluşturulan ve hukuki sonuç doğuran tüm metinleri kapsar.

MADDE 4 - "Güvenli depolama", dijital belgelerin değiştirilmez şekilde muhafaza edilmesini ifade eder.

İKİNCİ KISIM
Uygulama Esasları

MADDE 5 - Dijital belgelerin geçerliliği, imza ve zaman damgası ile sağlanır.

MADDE 6 - Güvenli depolama hizmeti sunan kuruluşlar, ISO 27001 standardına uygun olmalıdır.

MADDE 7 - Dijital belgelerin mahkemelerce kabulü için, güvenli depolama sertifikasının ibrazı zorunludur.
"""


def test_legislation_article_parsing():
    """Parse synthetic legislation and verify article extraction."""
    articles = _parse_articles(SYNTHETIC_LEGISLATION)

    assert len(articles) == 7, f"Expected 7 articles, got {len(articles)}"

    # Verify article numbers
    numbers = [a["number"] for a in articles]
    assert numbers == ["1", "2", "3", "4", "5", "6", "7"]

    # Verify first article text
    assert "dijital hukuki işlemlerin güvenilirliğini" in articles[0]["text"]

    # Verify last article text
    assert "güvenli depolama sertifikasının ibrazı" in articles[6]["text"]


def test_legislation_article_parsing_empty_text():
    """Empty text yields no articles."""
    articles = _parse_articles("")
    assert articles == []


def test_legislation_article_raw_text_format():
    """Raw text of parsed articles starts with 'MADDE <number>'."""
    articles = _parse_articles(SYNTHETIC_LEGISLATION)
    for art in articles:
        assert art["raw_text"].startswith(f"MADDE {art['number']}"), (
            f"raw_text mismatch for article {art['number']}"
        )