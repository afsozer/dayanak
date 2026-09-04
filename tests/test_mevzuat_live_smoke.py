"""Live smoke tests for legislation full text against the real Mevzuat source.

Opt-in: set ``EMSAL_LIVE_TESTS=1``.  These exist because the failure they
guard was invisible to every mocked test: the adapter fetched İİK (2004 s.k.)
successfully, ``ok`` was ``True``, no warning was raised — but the HTML-to-text
step silently dropped everything past article 193 of 366, so "İİK m. 265"
looked like an article that does not exist.  Only a real fetch of a long,
Word-exported law can catch that.

    EMSAL_LIVE_TESTS=1 pytest tests/test_mevzuat_live_smoke.py -q
"""
from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("EMSAL_LIVE_TESTS") != "1",
        reason="live source test; set EMSAL_LIVE_TESTS=1 to run",
    ),
]

# İcra ve İflas Kanunu — 366 articles, ~1.2 MB of Word-exported HTML.
IIK_DOCUMENT_ID = "102993"


class TestLongLawFullText:
    def test_last_articles_survive_extraction(self):
        from emsal_mcp.legislation import _fetch_doc, _parse_articles

        doc, error = _fetch_doc(IIK_DOCUMENT_ID, None, None)
        assert error is None
        numbers = {a["number"] for a in _parse_articles(doc.text or "")}
        # Anything that truncates the document loses the tail of the law.
        assert "265" in numbers      # ihtiyatî hacze itiraz
        assert "366" in numbers      # son madde
        assert len(numbers) > 400    # 366 + ek/geçici/mükerrer maddeler

    def test_article_lookup_returns_text(self):
        from emsal_mcp.legislation import search_legislation_articles

        result = search_legislation_articles(IIK_DOCUMENT_ID, article_number="265")
        assert result["ok"] is True
        assert len(result["matching_articles"]) == 1
        assert "yedi gün" in result["matching_articles"][0]["text"]

    def test_title_is_not_the_raw_id(self):
        """getDocumentContent answers without metadata; title comes from the text."""
        from emsal_mcp.legislation import _fetch_doc

        doc, error = _fetch_doc(IIK_DOCUMENT_ID, None, None)
        assert error is None
        assert doc.title == "İCRA VE İFLAS KANUNU"
