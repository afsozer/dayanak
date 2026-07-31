"""Live smoke tests against the real Bedesten endpoint.

Opt-in: set ``EMSAL_LIVE_TESTS=1``.  Everything else in the suite mocks the
HTTP client, which is exactly how the ``DANISTAYKARARI`` typo survived — the
mock happily echoed a bogus itemType while production silently returned
``total=0`` for it, quietly dropping every Danıştay decision from every
default search.  These tests are the only ones that can catch that class of
bug, so they talk to the source for real.

    EMSAL_LIVE_TESTS=1 pytest tests/test_bedesten_live_smoke.py -q
"""
from __future__ import annotations

import asyncio
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

# A common term guaranteed to exist in every court's corpus.
PROBE_QUERY = "tazminat"


def _live_total(item_type: str) -> int:
    from emsal_mcp.sources.bedesten import BedestenClient

    ci = BedestenClient()
    sp = asyncio.run(ci.search_page(PROBE_QUERY, limit=1, court_types=[item_type]))
    return sp.total or 0


class TestItemTypesAreRealUpstream:
    @pytest.mark.parametrize("item_type", [
        "YARGITAYKARARI",
        "DANISTAYKARAR",
        "YERELHUKUK",
        "ISTINAFHUKUK",
        "KYB",
    ])
    def test_every_declared_item_type_returns_records(self, item_type):
        """Each whitelisted itemType must match real records.

        Bedesten does not reject an unknown itemType — it answers total=0.
        A zero here therefore means the constant is misspelled, not that the
        court has no decisions.
        """
        total = _live_total(item_type)
        assert total > 0, (
            f"itemType {item_type!r} returned total=0 for '{PROBE_QUERY}'. "
            "Bedesten answers unknown itemTypes with a silent 0 — the spelling "
            "in VALID_ITEM_TYPES is probably wrong."
        )

    def test_whitelist_matches_the_tested_set(self):
        """Guard against adding a constant without a live probe for it."""
        from emsal_mcp.sources.bedesten import VALID_ITEM_TYPES

        tested = {
            "YARGITAYKARARI", "DANISTAYKARAR", "YERELHUKUK", "ISTINAFHUKUK", "KYB",
        }
        assert set(VALID_ITEM_TYPES) == tested, (
            "VALID_ITEM_TYPES changed; add the new value to this test's "
            "parametrize list so it gets a live probe."
        )

    def test_default_sweep_covers_both_courts(self):
        """The default search must actually reach Danıştay, not just Yargıtay."""
        from emsal_mcp.sources.bedesten import DEFAULT_COURT_TYPES, BedestenClient

        yargitay = _live_total("YARGITAYKARARI")
        sp = asyncio.run(BedestenClient().search_page(
            PROBE_QUERY, limit=1, court_types=list(DEFAULT_COURT_TYPES),
        ))
        combined = sp.total or 0
        assert combined > yargitay, (
            "Combined sweep returned no more than Yargıtay alone — the Danıştay "
            "itemType is being silently dropped."
        )


class TestKnownBadSpellingsAreStillDead:
    """If upstream ever starts accepting these, the alias map should be
    revisited — but today they are the exact trap this whole fix exists for."""

    @pytest.mark.parametrize("bad_type", [
        "DANISTAYKARARI", "YERELKARARI", "ISTINAFKARARI", "KYBKARAR",
    ])
    def test_bad_spelling_would_have_returned_zero(self, bad_type):
        import httpx

        from emsal_mcp.sources.bedesten import BedestenClient

        ci = BedestenClient()
        payload = {
            "data": {
                "pageSize": 1, "pageNumber": 1,
                "itemTypeList": [bad_type], "phrase": PROBE_QUERY,
            },
            "applicationName": "UyapMevzuat",
            "paging": True,
        }
        r = httpx.post(
            f"{ci.base}/emsal-karar/searchDocuments",
            json=payload, headers=ci.headers, timeout=30,
        )
        total = (r.json().get("data") or {}).get("total")
        assert total == 0, (
            f"{bad_type!r} now returns {total} records — upstream vocabulary "
            "changed; re-check _ITEM_TYPE_ALIASES."
        )


class TestUnstemmedIndexAssumption:
    """The AND→OR fallback exists because the index is not Turkish-stemmed.
    If that ever changes, the fallback's rationale should be re-examined."""

    def test_inflected_forms_are_distinct_tokens(self):
        taahhut = _live_total_phrase("+taahhüt")
        taahhudu = _live_total_phrase("+taahhüdü")
        assert taahhut > 0 and taahhudu > 0
        assert taahhut != taahhudu, (
            "'+taahhüt' and '+taahhüdü' now return identical counts — the index "
            "may have gained Turkish stemming; revisit the AND→OR fallback."
        )

    def test_bare_multiword_falls_back_and_finds_precedent(self):
        """The exact query that used to return 2 irrelevant hits."""
        from emsal_mcp.sources.bedesten import BedestenClient

        ci = BedestenClient()
        sp = asyncio.run(ci.search_page("tahliye taahhüdü adli tatil", limit=5))
        assert sp.results, "bare multi-word query returned nothing even after fallback"
        assert any("OR" in w for w in sp.warnings), "expected an AND→OR fallback notice"
        assert sp.results[0].metadata.get("fallback_to_or") is True


def _live_total_phrase(phrase: str) -> int:
    from emsal_mcp.sources.bedesten import BedestenClient

    ci = BedestenClient()
    sp = asyncio.run(ci.search_page(phrase, limit=1, court_types=["YARGITAYKARARI"]))
    return sp.total or 0


class TestResmiGazeteLive:
    """The RG adapter parses a live page, so a layout or encoding change breaks
    it silently. Only a live probe catches that."""

    KNOWN_DAY = "2026-07-31"  # issue 33326: 13 items, 2 of them Kanun

    def _search(self, query: str = "", limit: int = 30):
        from emsal_mcp.sources.resmigazete import ResmiGazeteClient
        return asyncio.run(
            ResmiGazeteClient().search_page(query, limit=limit, date=self.KNOWN_DAY)
        )

    def test_index_parses_into_items(self):
        sp = self._search()
        assert sp.total >= 10, f"only {sp.total} items — index layout may have changed"
        assert all(r.document_id.startswith("20260731") for r in sp.results)

    def test_turkish_characters_survive_decoding(self):
        """The page declares windows-1254 but the server sends no charset."""
        sp = self._search()
        blob = " ".join(r.title for r in sp.results)
        assert "�" not in blob, "mojibake — charset detection regressed"
        assert any(ch in blob for ch in "çğıöşüİ"), "no Turkish characters at all"

    def test_law_number_and_category_extracted(self):
        sp = self._search("7589")
        assert sp.total == 1
        hit = sp.results[0]
        assert hit.document_id == "20260731-1"
        assert hit.karar_no == "7589"
        assert hit.metadata["kategori"] == "KANUNLAR"

    def test_full_text_fetch(self):
        from emsal_mcp.sources.resmigazete import ResmiGazeteClient
        doc = asyncio.run(ResmiGazeteClient().get_document("20260731-1"))
        assert doc.content_status.value == "html_markdown"
        assert len(doc.full_text or "") > 5000
        assert "7589" in (doc.full_text or "")
        assert "mso-style" not in (doc.full_text or ""), "Word boilerplate leaked in"

    def test_pdf_only_item_is_not_claimed_as_text(self):
        from emsal_mcp.sources.resmigazete import ResmiGazeteClient
        doc = asyncio.run(ResmiGazeteClient().get_document("20260731-3"))
        assert doc.content_status.value == "pdf_link_only"
        assert not doc.full_text
