"""M-70 Legal Query Understanding Tests — normalization, expansion, filter extraction.

Covers:
  - normalize_law_ref (abbreviation → full reference)
  - expand_query_terms (synonym dictionary expansion)
  - extract_query_filters (court/chamber pattern matching)
  - Edge cases, empty input, no-fabrication invariants
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]

from emsal_mcp.query_understanding import (
    QUERY_UNDERSTANDING_VERSION,
    expand_query_terms,
    extract_query_filters,
    normalize_law_ref,
)


# ============================================================================
# normalize_law_ref
# ============================================================================


class TestNormalizeLawRef:
    def test_full_article_pattern(self):
        """İYUK 11 → 2577 (İdari Yargılama Usulü Kanunu) 11"""
        result = normalize_law_ref("İYUK 11 uyarınca dava")
        assert result["ok"] is True
        assert "2577" in result["normalized_query"]
        assert "İdari Yargılama Usulü Kanunu" in result["normalized_query"]
        assert len(result["replacements"]) >= 1
        rep = result["replacements"][0]
        assert rep["original"].upper().startswith("İYUK")
        assert "m.11" in rep["normalized"]  # replacement metadata has m. prefix

    def test_hmk_with_article(self):
        """HMK 190 → 6100 (Hukuk Muhakemeleri Kanunu) m.190"""
        result = normalize_law_ref("HMK 190 delil")
        assert result["ok"] is True
        assert "6100" in result["normalized_query"]
        assert "Hukuk Muhakemeleri Kanunu" in result["normalized_query"]

    def test_tck_md_format(self):
        """TCK md 125 → 5237 (Türk Ceza Kanunu) md 125 (md marker preserved)"""
        result = normalize_law_ref("TCK md 125 hakaret")
        assert result["ok"] is True
        assert "5237" in result["normalized_query"]
        # replacement metadata has normalized m.125
        assert any("m.125" in r["normalized"] for r in result["replacements"])

    def test_case_insensitive_abbreviation(self):
        """iyuk (lowercase) should normalize same as İYUK"""
        result = normalize_law_ref("iyuk 20 dava")
        assert result["ok"] is True
        assert "2577" in result["normalized_query"]

    def test_m_fraction_article(self):
        """İİK m.200 → 2004 (İcra ve İflas Kanunu)"""
        result = normalize_law_ref("İİK m.200 takip")
        assert result["ok"] is True
        assert "2004" in result["normalized_query"]
        assert "İcra ve İflas Kanunu" in result["normalized_query"]

    def test_bare_abbreviation_no_article(self):
        """Just 'TTK' without article → still normalized"""
        result = normalize_law_ref("TTK hükümleri")
        # Bare pattern substitution happens after full pattern
        assert "6102" in result["normalized_query"]

    def test_no_abbreviation_found(self):
        """Query with no known law abbreviation → unchanged"""
        result = normalize_law_ref("sözleşme ihlali tazminat")
        assert result["ok"] is True
        assert result["normalized_query"] == "sözleşme ihlali tazminat"
        assert result["replacements"] == []

    def test_empty_query(self):
        """Empty query → no replacements."""
        result = normalize_law_ref("")
        assert result["ok"] is True
        assert result["normalized_query"] == ""
        assert result["replacements"] == []

    def test_deterministic(self):
        """Same input always produces same output."""
        q = "HMK 190 ve İYUK 11"
        r1 = normalize_law_ref(q)
        r2 = normalize_law_ref(q)
        assert r1["normalized_query"] == r2["normalized_query"]
        assert r1["replacements"] == r2["replacements"]

    def test_result_structure(self):
        """Result has all expected keys."""
        result = normalize_law_ref("HMK test")
        expected_keys = {"ok", "original_query", "normalized_query", "replacements", "warnings", "rule"}
        assert expected_keys.issubset(set(result.keys()))
        assert "no fabrication" in result["rule"].lower()

    def test_multiple_laws_in_query(self):
        """Multiple abbreviations should all be normalized."""
        result = normalize_law_ref("HMK 190 ve TCK 125 uygulansın")
        assert result["ok"] is True
        # HMK and TCK both normalized
        assert "6100" in result["normalized_query"]
        assert "5237" in result["normalized_query"]
        # At least 2 article replacements
        article_replacements = [r for r in result["replacements"] if r.get("original")]
        assert len(article_replacements) >= 2


# ============================================================================
# expand_query_terms
# ============================================================================


class TestExpandQueryTerms:
    def test_single_expansion(self):
        """'kira' expands to include synonyms."""
        result = expand_query_terms("kira bedeli")
        assert result["ok"] is True
        assert "kiralayan" in result["expanded_query"] or "kiracı" in result["expanded_query"]
        assert len(result["added_terms"]) > 0

    def test_tazminat_expansion(self):
        """'tazminat' expands to maddi/manevi tazminat, zarar."""
        result = expand_query_terms("tazminat davası")
        assert result["ok"] is True
        assert len(result["added_terms"]) > 0
        assert "zarar" in result["added_terms"] or any("zarar" in t for t in result["added_terms"])

    def test_no_expansion_for_unknown_term(self):
        """Unknown term → no expansion."""
        result = expand_query_terms("zzznotaterm")
        assert result["ok"] is True
        assert result["expanded_query"] == "zzznotaterm"
        assert result["added_terms"] == []

    def test_empty_query(self):
        """Empty query → empty expansion."""
        result = expand_query_terms("")
        assert result["ok"] is True
        assert result["expanded_query"] == ""
        assert result["added_terms"] == []

    def test_deterministic(self):
        """Same input always produces same expansion."""
        r1 = expand_query_terms("kira tahliye")
        r2 = expand_query_terms("kira tahliye")
        assert r1["expanded_query"] == r2["expanded_query"]
        assert r1["added_terms"] == r2["added_terms"]

    def test_multiple_expansions(self):
        """Multiple dictionary terms each expand."""
        result = expand_query_terms("kira sözleşme")
        assert result["ok"] is True
        # Both "kira" and "sözleşme" expand
        assert len(result["added_terms"]) >= 3  # at least a few from both

    def test_no_duplicate_terms(self):
        """Original tokens are not repeated in added_terms."""
        result = expand_query_terms("kira")
        for term in result["added_terms"]:
            assert term != "kira", "'kira' should not be in added_terms"

    def test_result_structure(self):
        """Result has all expected keys."""
        result = expand_query_terms("sözleşme")
        expected_keys = {"ok", "original_query", "expanded_query", "added_terms", "warnings", "rule"}
        assert expected_keys.issubset(set(result.keys()))


# ============================================================================
# extract_query_filters
# ============================================================================


class TestExtractQueryFilters:
    def test_court_yargitay(self):
        """'Yargıtay sözleşme' → court=Yargitay."""
        result = extract_query_filters("Yargıtay sözleşme ihlali")
        assert result["ok"] is True
        assert result["filters"]["court"] == "Yargitay"

    def test_court_danistay(self):
        """'Danıştay karar' → court=Danistay."""
        result = extract_query_filters("Danıştay idari işlem")
        assert result["ok"] is True
        assert result["filters"]["court"] == "Danistay"

    def test_court_aym(self):
        """'Anayasa Mahkemesi' → court=Anayasa Mahkemesi."""
        result = extract_query_filters("Anayasa Mahkemesi ihlal")
        assert result["ok"] is True
        assert result["filters"]["court"] == "Anayasa Mahkemesi"

    def test_court_aym_abbreviation(self):
        """'AYM kararı' → court=Anayasa Mahkemesi."""
        result = extract_query_filters("AYM bireysel başvuru")
        assert result["ok"] is True
        assert result["filters"]["court"] == "Anayasa Mahkemesi"

    def test_chamber_detection(self):
        """'3. Hukuk Dairesi' → chamber=3. Hukuk Dairesi."""
        result = extract_query_filters("Yargıtay 3. Hukuk Dairesi sözleşme")
        assert result["ok"] is True
        assert "chamber" in result["filters"]

    def test_no_court_detected(self):
        """Query with no court → low confidence, no filters."""
        result = extract_query_filters("sözleşme ihlali")
        assert result["ok"] is True
        assert result["filters"] == {}
        assert result["confidence"] == "low"
        assert len(result["warnings"]) >= 1

    def test_partial_detection(self):
        """Court but no chamber → medium confidence."""
        result = extract_query_filters("Yargıtay sözleşme")
        assert result["confidence"] in ("medium", "high")
        assert "court" in result["filters"]

    def test_deterministic(self):
        """Same input produces same filters."""
        r1 = extract_query_filters("Danıştay 10. Hukuk Dairesi iptal")
        r2 = extract_query_filters("Danıştay 10. Hukuk Dairesi iptal")
        assert r1["filters"] == r2["filters"]
        assert r1["confidence"] == r2["confidence"]

    def test_result_structure(self):
        """Result has expected keys."""
        result = extract_query_filters("Yargıtay")
        expected_keys = {"ok", "filters", "extracted", "confidence", "warnings"}
        assert expected_keys.issubset(set(result.keys()))

    def test_empty_query(self):
        """Empty query → no filters."""
        result = extract_query_filters("")
        assert result["ok"] is True
        assert result["filters"] == {}
        assert result["confidence"] == "low"


# ============================================================================
# Version constant
# ============================================================================


def test_version_constant():
    """QUERY_UNDERSTANDING_VERSION is defined and follows semver."""
    assert QUERY_UNDERSTANDING_VERSION == "1.0.0"
    parts = QUERY_UNDERSTANDING_VERSION.split(".")
    assert len(parts) == 3
