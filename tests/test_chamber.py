"""Tests for v0.12 Chamber Profiling module."""
from __future__ import annotations

from pathlib import Path

from emsal_mcp.chamber import (
    get_chamber_overview,
    profile_chamber,
    chamber_timeline,
    find_similar_chambers,
    CHAMBER_MODULE_VERSION,
)
from emsal_mcp.cache import Cache
from emsal_mcp.models import ContentStatus, Document


def _seed_test_data(cache):
    docs = [
        Document(source="yargitay", document_id="yg-001", title="Sözleşme İhlali Kararı", court="Yargitay", chamber="3. Hukuk Dairesi", decision_date="2023-05-15", full_text="Sözleşme ihlali tazminat borçlar kanunu...", content_status=ContentStatus.FULL_TEXT, quote_usable=True, draft_usable=True),
        Document(source="yargitay", document_id="yg-002", title="Kira Sözleşmesi Fesih Davası", court="Yargitay", chamber="3. Hukuk Dairesi", decision_date="2024-01-20", full_text="Kira sözleşmesi fesih borçlar kanunu...", content_status=ContentStatus.HTML_MARKDOWN, quote_usable=True, draft_usable=False),
        Document(source="yargitay", document_id="yg-003", title="İş Kazası Tazminat Davası", court="Yargitay", chamber="10. Hukuk Dairesi", decision_date="2023-11-10", full_text="İş kazası tazminat iş kanunu sosyal güvenlik...", content_status=ContentStatus.FULL_TEXT, quote_usable=True, draft_usable=True),
        Document(source="yargitay", document_id="yg-004", title="İşçi Alacakları Davası", court="Yargitay", chamber="10. Hukuk Dairesi", decision_date="2024-06-01", full_text="İşçi alacakları kıdem tazminatı iş kanunu...", content_status=ContentStatus.FULL_TEXT, quote_usable=True, draft_usable=True),
        Document(source="danistay", document_id="ds-001", title="İdari Para Cezası İptal Davası", court="Danistay", chamber="6. Daire", decision_date="2023-03-15", full_text="İdari para cezası kabahatler kanunu...", content_status=ContentStatus.METADATA_ONLY, quote_usable=False, draft_usable=False),
        Document(source="yargitay", document_id="yg-005", title="Sigorta Tahkim Davası", court="Yargitay", chamber=None, decision_date=None, full_text="Sigorta tahkim...", content_status=ContentStatus.METADATA_ONLY, quote_usable=False, draft_usable=False),
        Document(source="yargitay", document_id="yg-006", title="Eski Sözleşme Davası", court="Yargitay", chamber="3. Hukuk Dairesi", decision_date="2019-07-01", full_text="Eski sözleşme davası borçlar kanunu...", content_status=ContentStatus.FULL_TEXT, quote_usable=True, draft_usable=True),
        Document(source="yargitay", document_id="yg-turkish", title="Türk Tarih Formatlı Karar", court="Yargitay", chamber="3. Hukuk Dairesi", decision_date="15.06.2022", full_text="Türk tarih formatı testi...", content_status=ContentStatus.FULL_TEXT, quote_usable=True, draft_usable=True),
    ]
    for doc in docs:
        cache.store_document(doc)
    return len(docs)


class TestGetChamberOverview:
    def test_overview_all(self, tmp_path: Path):
        cache = Cache(tmp_path / "overview_all.sqlite3")
        try:
            _seed_test_data(cache)
            result = get_chamber_overview(cache=cache)
            assert result["ok"] is True
            assert result["total_chambers"] >= 3
        finally:
            cache.close()

    def test_overview_filter_by_court(self, tmp_path: Path):
        cache = Cache(tmp_path / "overview_court.sqlite3")
        try:
            _seed_test_data(cache)
            result = get_chamber_overview(court="Yargitay", cache=cache)
            assert result["ok"] is True
            chambers = [ch["court"] for ch in result["chambers"]]
            assert all(c == "Yargitay" for c in chambers)
            assert "Danistay" not in chambers
        finally:
            cache.close()

    def test_overview_empty_db(self, tmp_path: Path):
        cache = Cache(tmp_path / "overview_empty.sqlite3")
        try:
            result = get_chamber_overview(cache=cache)
            assert result["ok"] is False
        finally:
            cache.close()


class TestProfileChamber:
    def test_profile_existing(self, tmp_path: Path):
        cache = Cache(tmp_path / "profile_existing.sqlite3")
        try:
            _seed_test_data(cache)
            result = profile_chamber("3. Hukuk Dairesi", cache=cache)
            assert result["ok"] is True
            assert result["metrics"]["total_documents"] == 4
        finally:
            cache.close()

    def test_profile_keywords(self, tmp_path: Path):
        cache = Cache(tmp_path / "profile_keywords.sqlite3")
        try:
            _seed_test_data(cache)
            result = profile_chamber("3. Hukuk Dairesi", cache=cache)
            keywords = [k["word"] for k in result.get("top_keywords", [])]
            assert any("sözleşme" in kw for kw in keywords) or any("davası" in kw for kw in keywords)
        finally:
            cache.close()

    def test_profile_nonexistent(self, tmp_path: Path):
        cache = Cache(tmp_path / "profile_nonexistent.sqlite3")
        try:
            _seed_test_data(cache)
            result = profile_chamber("999. Daire", cache=cache)
            assert result["ok"] is False
        finally:
            cache.close()

    def test_profile_empty_db(self, tmp_path: Path):
        cache = Cache(tmp_path / "profile_empty.sqlite3")
        try:
            result = profile_chamber("3. Hukuk Dairesi", cache=cache)
            assert result["ok"] is False
        finally:
            cache.close()


class TestChamberTimeline:
    def test_timeline_all(self, tmp_path: Path):
        cache = Cache(tmp_path / "timeline_all.sqlite3")
        try:
            _seed_test_data(cache)
            result = chamber_timeline(cache=cache)
            assert result["ok"] is True
            assert len(result["timeline"]) >= 2
        finally:
            cache.close()

    def test_timeline_specific_chamber(self, tmp_path: Path):
        cache = Cache(tmp_path / "timeline_chamber.sqlite3")
        try:
            _seed_test_data(cache)
            result = chamber_timeline(chamber="3. Hukuk Dairesi", cache=cache)
            assert result["ok"] is True
        finally:
            cache.close()

    def test_timeline_year_range(self, tmp_path: Path):
        cache = Cache(tmp_path / "timeline_range.sqlite3")
        try:
            _seed_test_data(cache)
            result = chamber_timeline(start_year=2023, end_year=2024, cache=cache)
            assert result["ok"] is True
            years = [t["year"] for t in result["timeline"]]
            assert all(2023 <= y <= 2024 for y in years)
        finally:
            cache.close()

    def test_timeline_empty_db(self, tmp_path: Path):
        cache = Cache(tmp_path / "timeline_empty.sqlite3")
        try:
            result = chamber_timeline(cache=cache)
            assert result["ok"] is False
        finally:
            cache.close()


class TestFindSimilarChambers:
    def test_similar_basic(self, tmp_path: Path):
        cache = Cache(tmp_path / "similar_basic.sqlite3")
        try:
            _seed_test_data(cache)
            result = find_similar_chambers("3. Hukuk Dairesi", cache=cache)
            assert result["ok"] is True
            assert "similar_chambers" in result
            assert "target_chamber" in result
            assert result["target_chamber"] == "3. Hukuk Dairesi"
        finally:
            cache.close()

    def test_similar_empty_db(self, tmp_path: Path):
        cache = Cache(tmp_path / "similar_empty.sqlite3")
        try:
            result = find_similar_chambers("3. Hukuk Dairesi", cache=cache)
            assert result["ok"] is False
        finally:
            cache.close()


class TestModuleConstants:
    def test_version(self):
        assert CHAMBER_MODULE_VERSION == "0.12.0"
