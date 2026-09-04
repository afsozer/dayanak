"""Tests for v0.10 legislation module.

Uses fake source clients via sources_override; no live network calls.
Covers: search, document fetch, article extraction, article tree building,
gerekce extraction, source health, citation formatting, types list.
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

from typing import Any
from unittest.mock import patch

from emsal_mcp.models import ContentStatus, Document, SearchResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEGISLATION_TEXT_WITH_ARTICLES = """
BİRİNCİ KISIM
Genel Hükümler

BİRİNCİ BÖLÜM
Amaç, Kapsam ve Tanımlar

MADDE 1 - Bu Kanunun amacı, hukuk sisteminde emsal araştırma usullerini düzenlemektir.

MADDE 2 - Bu Kanun, tüm yargı mercilerinde uygulanır.

İKİNCİ BÖLÜM
Temel İlkeler

MADDE 3 - Emsal araştırması yapılırken resmi kaynaklar esas alınır.

MADDE 4 - Alıntı yapılan kararların tam metni kaynakta mevcut olmalıdır.

MADDE 5 - Metadata seviyesindeki belgeler alıntı için kullanılamaz.

İKİNCİ KISIM
Uygulama Esasları

MADDE 6 - Araştırma sürecinde en az iki bağımsız kaynak kullanılır.

MADDE 7 - Elde edilen belgeler SHA-256 hash ile doğrulanır.

GENEL GEREKÇE
Bu kanun teklifi, hukuk sistemimizde emsal araştırmalarının standartlaştırılması
amacıyla hazırlanmıştır. Mevcut durumda emsal araştırmaları dağınık kaynaklardan
yapılmakta olup, güvenilirlik sorunları bulunmaktadır.

MADDE GEREKÇELERİ
Madde 1 - Madde ile kanunun amacı düzenlenmektedir. Emsal araştırma usullerinin
belirli standartlara kavuşturulması hedeflenmiştir.

Madde 2 - Kapsam maddesidir. Kanunun uygulama alanı tüm yargı mercileri olarak
belirlenmiştir.

Madde 3 - Temel ilkelerden ilki düzenlenmektedir. Resmi kaynak zorunluluğu
getirilmektedir.
"""

FLAT_ARTICLES_TEXT = """
MADDE 1 - Birinci maddedir.

MADDE 2 - İkinci maddedir.

MADDE 3 - Üçüncü maddedir.
"""


# ---------------------------------------------------------------------------
# Fake source client
# ---------------------------------------------------------------------------

class FakeMevzuatClient:
    """Deterministic fake source for testing legislation. No network calls."""

    source_id = "mevzuat"
    name = "Test Mevzuat"
    public = True

    def __init__(self) -> None:
        self.search_results: list[SearchResult] = []
        self.doc_to_return: Document | None = None
        self.search_error: Exception | None = None
        self.get_doc_error: Exception | None = None

    async def search(self, query: str, limit: int = 10, **kw: Any) -> list[SearchResult]:
        if self.search_error:
            raise self.search_error
        return self.search_results[:limit]

    async def get_document(self, document_id: str, **kw: Any) -> Document:
        if self.get_doc_error:
            raise self.get_doc_error
        if self.doc_to_return:
            return self.doc_to_return
        return Document(
            source="mevzuat",
            document_id=document_id,
            title=f"Default {document_id}",
            content_status=ContentStatus.METADATA_ONLY,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_result(**overrides) -> SearchResult:
    defaults: dict[str, Any] = {
        "source": "mevzuat",
        "document_id": "test-12345",
        "title": "Test Kanunu",
        "court": "Mevzuat",
        "decision_date": "2024-01-15",
        "karar_no": "1234",
        "content_status": ContentStatus.HTML_MARKDOWN,
        "summary": "Test kanunu özeti",
        "metadata": {"mevzuatTur": "Kanun"},
    }
    defaults.update(overrides)
    return SearchResult(**defaults)


def _make_legislation_doc(**overrides) -> Document:
    defaults: dict[str, Any] = {
        "source": "mevzuat",
        "document_id": "test-12345",
        "title": "Test Kanunu",
        "court": "Mevzuat",
        "content_status": ContentStatus.HTML_MARKDOWN,
        "karar_no": "1234",
        "decision_date": "2024-01-15",
        "full_text": LEGISLATION_TEXT_WITH_ARTICLES,
        "markdown": LEGISLATION_TEXT_WITH_ARTICLES,
        "metadata": {"mevzuatTur": "Kanun"},
    }
    defaults.update(overrides)
    return Document(**defaults)


def _make_fake_sources(client: FakeMevzuatClient | None = None) -> dict[str, Any]:
    return {"mevzuat": client or FakeMevzuatClient()}


# ---------------------------------------------------------------------------
# TestSearchLegislation
# ---------------------------------------------------------------------------

class TestSearchLegislation:
    def test_search_basic(self):
        """Search with fake client returning 3 results."""
        from emsal_mcp.legislation import search_legislation

        client = FakeMevzuatClient()
        client.search_results = [
            _make_search_result(document_id=f"doc-{i}", title=f"Kanun {i}", karar_no=str(i))
            for i in range(1, 4)
        ]
        result = search_legislation(
            "kanun testi", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["query"] == "kanun testi"
        assert result["total_results"] == 3
        assert len(result["results"]) == 3
        assert result["results"][0]["document_id"] == "doc-1"
        assert result["results"][0]["legislation_no"] == "1"

    def test_search_with_type_filter(self):
        """Search with legislation_type='Kanun'."""
        from emsal_mcp.legislation import search_legislation

        client = FakeMevzuatClient()
        client.search_results = [
            _make_search_result(title="Yönetmelik Test", metadata={"mevzuatTur": "Yönetmelik"}),
        ]
        result = search_legislation(
            "test", legislation_type="Yönetmelik", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["legislation_type"] == "Yönetmelik"
        assert result["results"][0]["legislation_type"] == "Yönetmelik"

    def test_search_no_results(self):
        """Empty search results, ok=False."""
        from emsal_mcp.legislation import search_legislation

        client = FakeMevzuatClient()
        client.search_results = []
        result = search_legislation(
            "bulunamayan sey", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False
        assert result["total_results"] == 0
        assert result["results"] == []

    def test_search_source_not_found(self):
        """Invalid source id produces warning."""
        from emsal_mcp.legislation import search_legislation

        result = search_legislation(
            "test", sources=["nonexistent_source"], sources_override={},
        )
        assert result["ok"] is False
        assert any("bulunamadı" in w for w in result["warnings"])

    def test_search_error(self):
        """Source raises exception during search."""
        from emsal_mcp.legislation import search_legislation

        client = FakeMevzuatClient()
        client.search_error = RuntimeError("Network failure")
        result = search_legislation(
            "test", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False
        assert any("başarısız" in w for w in result["warnings"])

    def test_search_sources_override(self):
        """Uses sources_override instead of registry."""
        from emsal_mcp.legislation import search_legislation

        client = FakeMevzuatClient()
        client.search_results = [_make_search_result(document_id="override-doc")]
        result = search_legislation(
            "test", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["results"][0]["document_id"] == "override-doc"

    def test_search_result_structure(self):
        """Validates all returned keys in result dict."""
        from emsal_mcp.legislation import search_legislation

        client = FakeMevzuatClient()
        client.search_results = [_make_search_result()]
        result = search_legislation(
            "test", sources_override={"mevzuat": client},
        )
        required_keys = {
            "ok", "query", "sources", "legislation_type", "total_results",
            "results", "warnings", "recommended_next_steps", "version", "rule",
        }
        assert required_keys.issubset(result.keys())
        # Check result item keys
        item_keys = {
            "document_id", "source", "title", "legislation_no", "gazette_date",
            "legislation_type", "legislation_type_id", "type_confidence",
            "summary", "content_status", "court",
        }
        assert item_keys.issubset(result["results"][0].keys())


# ---------------------------------------------------------------------------
# TestGetLegislationDocument
# ---------------------------------------------------------------------------

class TestGetLegislationDocument:
    def test_get_document_basic(self):
        """Get full document with citation_check."""
        from emsal_mcp.legislation import get_legislation_document

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = get_legislation_document(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["document_id"] == "test-12345"
        assert result["title"] == "Test Kanunu"
        assert result["citation_check"] is not None
        assert "ok" in result["citation_check"]

    def test_get_document_with_articles(self):
        """Counts articles in text."""
        from emsal_mcp.legislation import get_legislation_document

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = get_legislation_document(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["article_count"] == 7

    def test_get_document_source_not_found(self):
        """Invalid source returns ok=False."""
        from emsal_mcp.legislation import get_legislation_document

        result = get_legislation_document(
            "test-12345", source="nonexistent", sources_override={},
        )
        assert result["ok"] is False
        assert "Kaynak bulunamadı" in result["error"]
        assert result["document"] is None

    def test_get_document_error(self):
        """Source raises exception during get_document."""
        from emsal_mcp.legislation import get_legislation_document

        client = FakeMevzuatClient()
        client.get_doc_error = RuntimeError("Fetch failed")
        result = get_legislation_document(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False
        assert "Belge alınamadı" in result["error"]
        assert result["document"] is None

    def test_get_document_sources_override(self):
        """Uses sources_override for document fetch."""
        from emsal_mcp.legislation import get_legislation_document

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc(document_id="override-id")
        result = get_legislation_document(
            "override-id", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["document_id"] == "override-id"

    def test_get_document_metadata_only(self):
        """metadata_only content_status produces warning."""
        from emsal_mcp.legislation import get_legislation_document

        client = FakeMevzuatClient()
        doc = _make_legislation_doc(
            content_status=ContentStatus.METADATA_ONLY,
            full_text=None,
            markdown=None,
        )
        client.doc_to_return = doc
        result = get_legislation_document(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["content_status"] == "metadata_only"


# ---------------------------------------------------------------------------
# TestSearchLegislationArticles
# ---------------------------------------------------------------------------

class TestSearchLegislationArticles:
    def test_search_all_articles(self):
        """Get all articles from document (no filter)."""
        from emsal_mcp.legislation import search_legislation_articles

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = search_legislation_articles(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["total_articles_found"] == 7
        assert len(result["matching_articles"]) == 7

    def test_search_specific_article(self):
        """Filter by article_number='3'."""
        from emsal_mcp.legislation import search_legislation_articles

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = search_legislation_articles(
            "test-12345", article_number="3", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["article_number"] == "3"
        assert len(result["matching_articles"]) == 1
        assert result["matching_articles"][0]["number"] == "3"

    def test_search_article_query(self):
        """Filter by article_query containing keyword."""
        from emsal_mcp.legislation import search_legislation_articles

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = search_legislation_articles(
            "test-12345", article_query="SHA-256", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["article_query"] == "SHA-256"
        assert len(result["matching_articles"]) >= 1
        assert any("SHA-256" in a["text"] for a in result["matching_articles"])

    def test_search_article_number_not_found(self):
        """Invalid article number produces warning."""
        from emsal_mcp.legislation import search_legislation_articles

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = search_legislation_articles(
            "test-12345", article_number="999", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False
        assert len(result["matching_articles"]) == 0
        assert any("999" in w for w in result["warnings"])

    def test_search_no_content(self):
        """Document with empty text returns ok=False."""
        from emsal_mcp.legislation import search_legislation_articles

        client = FakeMevzuatClient()
        doc = _make_legislation_doc(full_text="", markdown="")
        client.doc_to_return = doc
        result = search_legislation_articles(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False
        assert result["total_articles_found"] == 0

    def test_search_metadata_only_warning(self):
        """metadata_only content_status warns about limited search."""
        from emsal_mcp.legislation import search_legislation_articles

        client = FakeMevzuatClient()
        doc = _make_legislation_doc(
            content_status=ContentStatus.METADATA_ONLY,
            full_text=LEGISLATION_TEXT_WITH_ARTICLES,
            markdown=LEGISLATION_TEXT_WITH_ARTICLES,
        )
        client.doc_to_return = doc
        result = search_legislation_articles(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert any("metadata" in w.lower() for w in result["warnings"])

    def test_search_article_structure(self):
        """Validate all returned keys."""
        from emsal_mcp.legislation import search_legislation_articles

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = search_legislation_articles(
            "test-12345", sources_override={"mevzuat": client},
        )
        required_keys = {
            "ok", "document_id", "source", "title", "article_number",
            "article_query", "total_articles_found", "matching_articles",
            "content_status", "warnings", "recommended_next_steps", "version", "rule",
        }
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# TestGetLegislationArticleTree
# ---------------------------------------------------------------------------

class TestGetLegislationArticleTree:
    def test_tree_basic(self):
        """Build tree from document with parts, sections, articles."""
        from emsal_mcp.legislation import get_legislation_article_tree

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = get_legislation_article_tree(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["article_count"] == 7
        assert result["part_count"] >= 2
        assert result["section_count"] >= 2

    def test_tree_no_parts_no_sections(self):
        """Flat articles when no hierarchy."""
        from emsal_mcp.legislation import get_legislation_article_tree

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc(full_text=FLAT_ARTICLES_TEXT, markdown=FLAT_ARTICLES_TEXT)
        result = get_legislation_article_tree(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["article_count"] == 3
        assert result["part_count"] == 0
        assert result["section_count"] == 0

    def test_tree_flat_article_list(self):
        """Check flat_article_list structure."""
        from emsal_mcp.legislation import get_legislation_article_tree

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = get_legislation_article_tree(
            "test-12345", sources_override={"mevzuat": client},
        )
        flat = result["flat_article_list"]
        assert isinstance(flat, list)
        assert len(flat) == 7
        for item in flat:
            assert "number" in item
            assert "preview" in item

    def test_tree_no_content(self):
        """Empty text returns error."""
        from emsal_mcp.legislation import get_legislation_article_tree

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc(full_text="", markdown="")
        result = get_legislation_article_tree(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False
        assert result["article_count"] == 0

    def test_tree_structure_keys(self):
        """Validates all returned keys present."""
        from emsal_mcp.legislation import get_legislation_article_tree

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = get_legislation_article_tree(
            "test-12345", sources_override={"mevzuat": client},
        )
        required_keys = {
            "ok", "document_id", "source", "title", "article_count",
            "section_count", "part_count", "tree", "flat_article_list",
            "warnings", "recommended_next_steps", "version", "rule",
        }
        assert required_keys.issubset(result.keys())

    def test_tree_source_not_found(self):
        """Invalid source returns ok=False."""
        from emsal_mcp.legislation import get_legislation_article_tree

        result = get_legislation_article_tree(
            "test-12345", source="nonexistent", sources_override={},
        )
        assert result["ok"] is False

    def test_tree_error(self):
        """Source raises exception."""
        from emsal_mcp.legislation import get_legislation_article_tree

        client = FakeMevzuatClient()
        client.get_doc_error = RuntimeError("Fetch error")
        result = get_legislation_article_tree(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# TestGetLegislationGerekce
# ---------------------------------------------------------------------------

class TestGetLegislationGerekce:
    def test_gerekce_found(self):
        """Extract gerekce from text with GENEL GEREKCE and MADDE GEREKCELERI."""
        from emsal_mcp.legislation import get_legislation_gerekce

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = get_legislation_gerekce(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["found"] is True
        assert result["genel_gerekce"] is not None
        assert "hukuk sistemimizde" in result["genel_gerekce"]

    def test_genel_gerekce_only(self):
        """Text with only GENEL GEREKCE."""
        from emsal_mcp.legislation import get_legislation_gerekce

        text_only_genel = """
Madde 1 - Birinci madde.

GENEL GEREKÇE
Bu teklifin genel gerekçesidir. Detaylı açıklama burada yer almaktadır.
"""
        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc(full_text=text_only_genel, markdown=text_only_genel)
        result = get_legislation_gerekce(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["found"] is True
        assert result["genel_gerekce"] is not None
        assert "genel gerekçesidir" in result["genel_gerekce"]

    def test_no_gerekce(self):
        """Text without any gerekce section."""
        from emsal_mcp.legislation import get_legislation_gerekce

        text_no_gerekce = """
MADDE 1 - Birinci madde.
MADDE 2 - İkinci madde.
"""
        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc(full_text=text_no_gerekce, markdown=text_no_gerekce)
        result = get_legislation_gerekce(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False
        assert result["found"] is False
        assert result["genel_gerekce"] is None
        assert any("bulunamadı" in w for w in result["warnings"])

    def test_gerekce_no_content(self):
        """Empty text returns error."""
        from emsal_mcp.legislation import get_legislation_gerekce

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc(full_text="", markdown="")
        result = get_legislation_gerekce(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False
        assert result["found"] is False

    def test_gerekce_madde_gerekceleri_parsed(self):
        """Individual article gerekceleri are extracted."""
        from emsal_mcp.legislation import get_legislation_gerekce

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = get_legislation_gerekce(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is True
        assert result["madde_gerekceleri"] is not None
        assert isinstance(result["madde_gerekceleri"], list)
        assert len(result["madde_gerekceleri"]) >= 2
        for item in result["madde_gerekceleri"]:
            assert "article" in item
            assert "gerekce" in item

    def test_gerekce_structure_keys(self):
        """Validates all returned keys."""
        from emsal_mcp.legislation import get_legislation_gerekce

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc()
        result = get_legislation_gerekce(
            "test-12345", sources_override={"mevzuat": client},
        )
        required_keys = {
            "ok", "document_id", "source", "title", "found",
            "genel_gerekce", "madde_gerekceleri", "raw_text",
            "warnings", "recommended_next_steps", "version", "rule",
        }
        assert required_keys.issubset(result.keys())

    def test_gerekce_source_not_found(self):
        """Invalid source returns ok=False."""
        from emsal_mcp.legislation import get_legislation_gerekce

        result = get_legislation_gerekce(
            "test-12345", source="nonexistent", sources_override={},
        )
        assert result["ok"] is False

    def test_gerekce_error(self):
        """Source raises exception."""
        from emsal_mcp.legislation import get_legislation_gerekce

        client = FakeMevzuatClient()
        client.get_doc_error = RuntimeError("Network error")
        result = get_legislation_gerekce(
            "test-12345", sources_override={"mevzuat": client},
        )
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# TestGetLegislationSourceStatus
# ---------------------------------------------------------------------------

class TestGetLegislationSourceStatus:
    def test_status_healthy(self):
        """Source returns offline_ok=True."""
        from emsal_mcp.legislation import get_legislation_source_status

        fake_smoke = [
            {"source_id": "mevzuat", "offline_ok": True, "online_ok": True},
        ]
        fake_caps = [
            {"source_id": "mevzuat", "display_name": "Mevzuat", "status": "stable"},
        ]
        with patch("emsal_mcp.legislation.smoke_all_sync", return_value=fake_smoke), \
             patch("emsal_mcp.legislation.get_capabilities", return_value=fake_caps):
            result = get_legislation_source_status()
        assert result["ok"] is True
        assert result["overall_ok"] is True
        assert "mevzuat" in result["healthy_sources"]

    def test_status_degraded(self):
        """Source returns offline_ok=False."""
        from emsal_mcp.legislation import get_legislation_source_status

        fake_smoke = [
            {"source_id": "mevzuat", "offline_ok": False, "online_ok": False},
        ]
        fake_caps = [
            {"source_id": "mevzuat", "display_name": "Mevzuat", "status": "unavailable"},
        ]
        with patch("emsal_mcp.legislation.smoke_all_sync", return_value=fake_smoke), \
             patch("emsal_mcp.legislation.get_capabilities", return_value=fake_caps):
            result = get_legislation_source_status()
        assert result["ok"] is False
        assert result["overall_ok"] is False
        assert "mevzuat" in result["degraded_sources"]

    def test_status_overall_ok(self):
        """All sources healthy."""
        from emsal_mcp.legislation import get_legislation_source_status

        fake_smoke = [
            {"source_id": "mevzuat", "offline_ok": True, "online_ok": True},
        ]
        fake_caps = [
            {"source_id": "mevzuat", "display_name": "Mevzuat", "status": "stable"},
        ]
        with patch("emsal_mcp.legislation.smoke_all_sync", return_value=fake_smoke), \
             patch("emsal_mcp.legislation.get_capabilities", return_value=fake_caps):
            result = get_legislation_source_status()
        assert result["overall_ok"] is True
        assert result["source_count"] == 1

    def test_status_keys(self):
        """Validates all returned keys."""
        from emsal_mcp.legislation import get_legislation_source_status

        fake_smoke = [
            {"source_id": "mevzuat", "offline_ok": True, "online_ok": True},
        ]
        fake_caps = [
            {"source_id": "mevzuat", "display_name": "Mevzuat", "status": "stable"},
        ]
        with patch("emsal_mcp.legislation.smoke_all_sync", return_value=fake_smoke), \
             patch("emsal_mcp.legislation.get_capabilities", return_value=fake_caps):
            result = get_legislation_source_status()
        required_keys = {
            "ok", "sources", "overall_ok", "source_count", "healthy_sources",
            "degraded_sources", "warnings", "recommended_next_steps", "version", "rule",
        }
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# TestFormatLegislationCitation
# ---------------------------------------------------------------------------

class TestFormatLegislationCitation:
    def test_format_full(self):
        """style='full' produces full citation."""
        from emsal_mcp.legislation import format_legislation_citation

        doc = _make_legislation_doc()
        result = format_legislation_citation(doc, style="full")
        assert "Kanun" in result["formatted_citation"]
        assert "1234" in result["formatted_citation"]
        assert "2024-01-15" in result["formatted_citation"]
        assert "Test Kanunu" in result["formatted_citation"]
        assert result["style"] == "full"

    def test_format_short(self):
        """style='short' produces short citation."""
        from emsal_mcp.legislation import format_legislation_citation

        doc = _make_legislation_doc()
        result = format_legislation_citation(doc, style="short")
        assert "1234" in result["formatted_citation"]
        assert result["style"] == "short"

    def test_format_article(self):
        """style='article' produces citation with MADDE placeholder."""
        from emsal_mcp.legislation import format_legislation_citation

        doc = _make_legislation_doc()
        result = format_legislation_citation(doc, style="article")
        assert "{MADDE}" in result["formatted_citation"]
        assert result["style"] == "article"

    def test_format_missing_fields(self):
        """Missing title generates warnings."""
        from emsal_mcp.legislation import format_legislation_citation

        doc_dict = {"title": "", "legislation_no": "", "gazette_date": ""}
        result = format_legislation_citation(doc_dict, style="full")
        assert len(result["warnings"]) > 0

    def test_format_invalid_input(self):
        """Non-dict/non-Document raises error."""
        from emsal_mcp.legislation import format_legislation_citation

        result = format_legislation_citation(None, style="full")  # type: ignore[arg-type]
        assert "error" in result

    def test_format_from_dict(self):
        """Formatting from dict input."""
        from emsal_mcp.legislation import format_legislation_citation

        doc_dict = {
            "title": "Test Yönetmeliği",
            "legislation_no": "2024/5678",
            "gazette_date": "2024-06-15",
            "metadata": {},
        }
        result = format_legislation_citation(doc_dict, style="full")
        assert "Yönetmelik" in result["formatted_citation"]
        assert "2024/5678" in result["formatted_citation"]

    def test_format_unknown_style(self):
        """Unknown style generates warning."""
        from emsal_mcp.legislation import format_legislation_citation

        doc = _make_legislation_doc()
        result = format_legislation_citation(doc, style="unknown_style")  # type: ignore[arg-type]
        assert any("bilinmeyen" in w.lower() for w in result["warnings"])
        assert "formatted_citation" in result

    def test_format_output_keys(self):
        """Validates output structure."""
        from emsal_mcp.legislation import format_legislation_citation

        doc = _make_legislation_doc()
        result = format_legislation_citation(doc, style="full")
        required_keys = {
            "formatted_citation", "style", "legislation_no", "gazette_date",
            "legislation_type", "title", "warnings",
        }
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# TestGetLegislationTypes
# ---------------------------------------------------------------------------

class TestGetLegislationTypes:
    def test_types_list(self):
        """Returns list of type dicts with type_id and display_name."""
        from emsal_mcp.legislation import get_legislation_types

        types = get_legislation_types()
        assert isinstance(types, list)
        assert len(types) >= 10
        for t in types:
            assert "type_id" in t
            assert "display_name" in t

    def test_types_contains_kanun(self):
        """'kanun' type is in the list."""
        from emsal_mcp.legislation import get_legislation_types

        types = get_legislation_types()
        kanun = [t for t in types if t["type_id"] == "kanun"]
        assert len(kanun) == 1
        assert kanun[0]["display_name"] == "Kanun"


# ---------------------------------------------------------------------------
# TestModuleConstants
# ---------------------------------------------------------------------------

class TestModuleConstants:
    def test_legislation_version(self):
        """LEGISLATION_VERSION equals '0.10.0'."""
        from emsal_mcp.legislation import LEGISLATION_VERSION

        assert LEGISLATION_VERSION == "0.10.0"

    def test_no_fabrication_rule(self):
        """_NO_INVENTION_BLOCK rule is present in responses."""
        from emsal_mcp.legislation import _NO_INVENTION_BLOCK

        assert "uydurma" in _NO_INVENTION_BLOCK.lower() or "uydurmaz" in _NO_INVENTION_BLOCK.lower()
        # Check it appears in search response
        from emsal_mcp.legislation import search_legislation

        client = FakeMevzuatClient()
        client.search_results = [_make_search_result()]
        result = search_legislation(
            "test", sources_override={"mevzuat": client},
        )
        assert "rule" in result
        assert "uydurma" in result["rule"].lower() or "uydurmaz" in result["rule"].lower()


# ---------------------------------------------------------------------------
# TestCLIImports
# ---------------------------------------------------------------------------

class TestCLIImports:
    def test_cli_import(self):
        """Can import from CLI."""
        from emsal_mcp.cli import app
        assert app is not None

    def test_mcp_import(self):
        """Can import from server (just test import succeeds)."""
        from emsal_mcp.server import main
        assert callable(main)


# ---------------------------------------------------------------------------
# TestArticleHeadings — real-world heading shapes on mevzuat.gov.tr
# ---------------------------------------------------------------------------

OLD_STYLE_TEXT = """
İCRA VE İFLAS KANUNU

Madde
264 – Dava açma müddeti bu maddede düzenlenir.

Madde
265 – Borçlu, ihtiyatî haczin dayandığı sebeplere yedi gün içinde itiraz edebilir.

Madde
266 – Borçlu parayı depo ederse haciz kalkar.

Ek
Madde 1- (Ek: 17/7/2003-4949/102 md.) Bu Kanunun ek maddesidir.

Geçici
Madde 1 – Bu kanunun yürürlüğe girdiği tarihte derdest takipler hakkında uygulanır.
"""


class TestArticleHeadings:
    def test_lowercase_madde_is_parsed(self):
        """Pre-2000 laws head articles "Madde 265 –", not "MADDE 265 -"."""
        from emsal_mcp.legislation import _parse_articles

        numbers = [a["number"] for a in _parse_articles(OLD_STYLE_TEXT)]
        assert "265" in numbers
        assert numbers[:3] == ["264", "265", "266"]

    def test_qualified_articles_keep_their_prefix(self):
        """"Ek madde 1" must not collide with article 1 of the law."""
        from emsal_mcp.legislation import _parse_articles

        numbers = [a["number"] for a in _parse_articles(OLD_STYLE_TEXT)]
        assert "Ek 1" in numbers
        assert "Geçici 1" in numbers
        assert "1" not in numbers

    def test_gerekce_articles_are_not_counted(self):
        """Rationale sections repeat every article as "Madde N -"."""
        from emsal_mcp.legislation import _parse_articles

        text = OLD_STYLE_TEXT + (
            "\nMADDE GEREKÇELERİ\n"
            "Madde 264 - Madde ile dava açma süresi düzenlenmektedir.\n"
            "Madde 265 - Madde ile itiraz usulü düzenlenmektedir.\n"
        )
        numbers = [a["number"] for a in _parse_articles(text)]
        assert numbers.count("265") == 1
        assert len(numbers) == 5

    def test_article_number_lookup_is_case_and_space_tolerant(self):
        from emsal_mcp.legislation import search_legislation_articles

        client = FakeMevzuatClient()
        client.doc_to_return = _make_legislation_doc(
            full_text=OLD_STYLE_TEXT, markdown=OLD_STYLE_TEXT,
        )
        for wanted in ("265", " 265 "):
            result = search_legislation_articles(
                "test-12345", article_number=wanted,
                sources_override={"mevzuat": client},
            )
            assert result["ok"] is True, wanted
            assert len(result["matching_articles"]) == 1
            assert "yedi gün" in result["matching_articles"][0]["text"]

        result = search_legislation_articles(
            "test-12345", article_number="geçici 1",
            sources_override={"mevzuat": client},
        )
        assert [a["number"] for a in result["matching_articles"]] == ["Geçici 1"]