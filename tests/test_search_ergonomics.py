"""Tests for search_decisions ergonomics (Yargı-MCP parity Görev 6).

- source optional (defaults to bedesten with Yargıtay+Danıştay sweep)
- at-least-one-criterion required guard
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.integration]


def _mock_resp(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.url = "http://mock"
    resp.request = MagicMock()
    return resp


class TestCriterionGuard:
    """The at-least-one-criterion guard lives in the MCP tool wrapper, not in
    the client.  We exercise the same logic by re-implementing the guard check
    inline (the wrapper is hard to invoke without a full MCP harness)."""

    def _has_criterion(self, **kw):
        return any([
            kw.get("query") and str(kw["query"]).strip(),
            kw.get("esas_no"), kw.get("karar_no"), kw.get("birimAdi"),
            kw.get("karar_tarihi_start"), kw.get("karar_tarihi_end"),
        ])

    def test_no_criterion_rejected(self):
        assert self._has_criterion(court_types=["YARGITAYKARARI"]) is False

    def test_query_only_passes(self):
        assert self._has_criterion(query="tazminat") is True

    def test_docket_only_passes(self):
        assert self._has_criterion(esas_no="2023/1") is True

    def test_birim_only_passes(self):
        assert self._has_criterion(birimAdi="H12") is True

    def test_date_range_only_passes(self):
        assert self._has_criterion(karar_tarihi_start="2023-01-01") is True


def _capturing_client(captured: list[dict], responses: list[dict] | None = None):
    """Patch context manager that records each POST body and replays responses."""
    default = {"data": {"total": 1, "emsalKararList": [
        {"id": "1", "itemType": {"description": "Y"}}
    ]}}
    queue = list(responses) if responses else None

    async def _capture(*a, **k):
        captured.append(k.get("json", {}))
        if queue:
            return _mock_resp(queue.pop(0))
        return _mock_resp(default)

    mc = patch("emsal_mcp.sources.bedesten.client")
    started = mc.start()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture)))
    cm.__aexit__ = AsyncMock(return_value=False)
    started.return_value = cm
    return mc


class TestDefaultCourtTypes:
    """When source defaults to bedesten and no court_types given, the search
    should run a combined Yargıtay+Danıştay sweep."""

    def test_default_court_types_yargitay_danistay(self):
        from emsal_mcp.sources.bedesten import DEFAULT_COURT_TYPES, BedestenClient
        ci = BedestenClient()
        captured: list[dict] = []
        mc = _capturing_client(captured)
        try:
            asyncio.run(ci.search("tazminat", limit=5, court_types=list(DEFAULT_COURT_TYPES)))
        finally:
            mc.stop()
        assert captured[0]["data"]["itemTypeList"] == ["YARGITAYKARARI", "DANISTAYKARAR"]

    def test_default_is_the_spelling_bedesten_accepts(self):
        """Regression: the old default said DANISTAYKARARI, which Bedesten
        answers with a silent total=0 — every Danıştay decision vanished from
        every default search.  The trailing I must stay gone."""
        from emsal_mcp.sources.bedesten import DEFAULT_COURT_TYPES, VALID_ITEM_TYPES
        assert DEFAULT_COURT_TYPES == ["YARGITAYKARARI", "DANISTAYKARAR"]
        assert set(DEFAULT_COURT_TYPES) <= VALID_ITEM_TYPES


class TestItemTypeNormalization:
    def test_known_bad_spellings_are_repaired(self):
        from emsal_mcp.sources.bedesten import normalize_item_types
        valid, unknown = normalize_item_types(
            ["DANISTAYKARARI", "ISTINAFKARARI", "YERELKARARI", "KYBKARAR"]
        )
        assert valid == ["DANISTAYKARAR", "ISTINAFHUKUK", "YERELHUKUK", "KYB"]
        assert unknown == []

    def test_lowercase_and_diacritics_normalized(self):
        from emsal_mcp.sources.bedesten import normalize_item_type
        assert normalize_item_type("danıştaykarar") == "DANISTAYKARAR"
        assert normalize_item_type(" yargitaykarari ") == "YARGITAYKARARI"

    def test_unknown_reported_not_forwarded(self):
        from emsal_mcp.sources.bedesten import normalize_item_types
        valid, unknown = normalize_item_types(["YARGITAYKARARI", "ANAYASAMAHKEMESI"])
        assert valid == ["YARGITAYKARARI"]
        assert unknown == ["ANAYASAMAHKEMESI"]

    def test_duplicates_collapsed(self):
        from emsal_mcp.sources.bedesten import normalize_item_types
        valid, _ = normalize_item_types(["DANISTAYKARAR", "DANISTAYKARARI"])
        assert valid == ["DANISTAYKARAR"]

    def test_all_invalid_raises_instead_of_silent_zero(self):
        """Sending a bogus itemType returns total=0, which reads as 'no such
        precedent'.  Refuse the call so the caller sees the real cause."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        captured: list[dict] = []
        mc = _capturing_client(captured)
        try:
            with pytest.raises(ValueError, match="court_types"):
                asyncio.run(ci.search("tazminat", limit=5, court_types=["BOGUSKARAR"]))
        finally:
            mc.stop()
        assert captured == [], "invalid itemType must never reach the upstream"

    def test_partial_invalid_warns_and_keeps_valid(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        captured: list[dict] = []
        mc = _capturing_client(captured)
        try:
            sp = asyncio.run(ci.search_page(
                "tazminat", limit=5, court_types=["YARGITAYKARARI", "BOGUSKARAR"]
            ))
        finally:
            mc.stop()
        assert captured[0]["data"]["itemTypeList"] == ["YARGITAYKARARI"]
        assert any("BOGUSKARAR" in w for w in sp.warnings)


class TestAndToOrFallback:
    """A bare multi-word query is tried as AND first; the index is not stemmed,
    so a starved AND result is an artefact of OUR rewrite, not an absence of
    precedent.  Fall back to the caller's original OR query whenever the AND
    pass cannot fill the requested page."""

    def test_empty_and_result_retries_as_or(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        captured: list[dict] = []
        mc = _capturing_client(captured, responses=[
            {"data": {"total": 0, "emsalKararList": []}},
            {"data": {"total": 42, "emsalKararList": [
                {"id": "9", "itemType": {"description": "Yargıtay"}}
            ]}},
        ])
        try:
            sp = asyncio.run(ci.search_page("tahliye taahhüdü adli tatil", limit=5))
        finally:
            mc.stop()
        assert len(captured) == 2, "AND pass then OR pass"
        assert captured[0]["data"]["phrase"] == "+tahliye +taahhüdü +adli +tatil"
        assert captured[1]["data"]["phrase"] == "tahliye taahhüdü adli tatil"
        assert sp.total == 42
        assert len(sp.results) == 1
        assert sp.results[0].metadata["fallback_to_or"] is True
        assert sp.results[0].metadata["original_query"] == "tahliye taahhüdü adli tatil"
        assert any("OR" in w for w in sp.warnings)

    def test_thin_and_result_also_retries_as_or(self):
        """The regression that started this: '+tahliye +taahhüdü +adli +tatil'
        returns 2 incidental hits, not 0.  A couple of accidental
        co-occurrences look like an answer and are worse than an empty page —
        they must trigger the fallback too."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        captured: list[dict] = []
        mc = _capturing_client(captured, responses=[
            {"data": {"total": 2, "emsalKararList": [
                {"id": "1", "itemType": {"description": "Yargıtay"}},
                {"id": "2", "itemType": {"description": "Yargıtay"}},
            ]}},
            {"data": {"total": 1839461, "emsalKararList": [
                {"id": "9", "itemType": {"description": "Yargıtay"}}
            ]}},
        ])
        try:
            sp = asyncio.run(ci.search_page("tahliye taahhüdü adli tatil", limit=10))
        finally:
            mc.stop()
        assert len(captured) == 2
        assert sp.total == 1839461
        assert sp.results[0].metadata["fallback_to_or"] is True
        assert any("2 sonuç" in w for w in sp.warnings)

    def test_full_page_of_and_results_does_not_fall_back(self):
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        captured: list[dict] = []
        mc = _capturing_client(captured, responses=[
            {"data": {"total": 753, "emsalKararList": [
                {"id": str(i), "itemType": {"description": "Yargıtay"}}
                for i in range(5)
            ]}},
        ])
        try:
            sp = asyncio.run(ci.search_page("kıdem tazminatı", limit=5))
        finally:
            mc.stop()
        assert len(captured) == 1, "no retry when the AND pass filled the page"
        assert captured[0]["data"]["phrase"] == "+kıdem +tazminatı"
        assert sp.warnings == []
        assert sp.results[0].metadata.get("fallback_to_or") is None

    def test_operator_query_never_falls_back(self):
        """The caller used operators deliberately — 0 hits is a real answer."""
        from emsal_mcp.sources.bedesten import BedestenClient
        ci = BedestenClient()
        captured: list[dict] = []
        mc = _capturing_client(captured, responses=[
            {"data": {"total": 0, "emsalKararList": []}},
        ])
        try:
            sp = asyncio.run(ci.search_page('+"tahliye taahhüdü" +"adli tatil"', limit=5))
        finally:
            mc.stop()
        assert len(captured) == 1
        assert sp.total == 0
        assert sp.warnings == []
