"""Bedesten phrase validation: query sanitising + error classification.

Also covers ADALET_EMPTY_EXCEPTION wrapping a payload parse fault (8 Eki 2026).

Olay (22 Eyl 2026): `+"83/a" +muvafakat +maaş +"takipten sonra"` →
ADALET_PARAMETER_VALIDATION_EXCEPTION ("Sadece harf ve rakam içeren aramalar
yapılabilir").  The tool reported it as SOURCE_UPSTREAM_ERROR / retryable,
i.e. "geçici hata, tekrar dene" — wrong: the same query fails every time.
Live measurement showed `+`, `-`, quotes, parens and AND/OR/NOT are accepted;
the culprit was `/`.  `*`, `?`, `.`, `,`, `'`, `:` etc. are rejected too.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dayanak.sources.base import BedestenUpstreamError
from dayanak.sources.bedesten import (
    BedestenClient,
    rewrite_solr_query,
    sanitize_bedesten_query,
)

pytestmark = [pytest.mark.unit]

_VALIDATION = {
    "data": None,
    "metadata": {
        "FMTY": "ERROR",
        "FMC": "ADALET_PARAMETER_VALIDATION_EXCEPTION",
        "FMTE": "Parameter validation exception:Lütfen Arama Kriterlerini Kontrol "
                "Ediniz! Sadece harf ve rakam içeren aramalar yapılabilir.",
    },
}
_RUNTIME = {"data": None, "metadata": {"FMTY": "ERROR", "FMC": "ADALET_RUNTIME_EXCEPTION"}}
# Olay (8 Eki 2026): kararTarihiStart="2026-01-01" → Jackson parse fault wrapped
# as ADALET_EMPTY_EXCEPTION; the tool called it "geçici hata, tekrar dene".
_DATE_PARSE_FMTE = (
    "Cannot deserialize value of type `java.time.LocalDateTime` from String "
    "\"2026-01-01\": Failed to deserialize java.time.LocalDateTime: "
    "(java.time.format.DateTimeParseException) Text '2026-01-01' could not be "
    "parsed at index 10\n at [Source: REDACTED (`StreamReadFeature."
    "INCLUDE_SOURCE_IN_LOCATION` disabled); line: 1, column: 108] (through "
    "reference chain: tr.gov.adalet.core.model.request.AdaletRequestDto[\"data\"]"
    "->tr.gov.adalet.service.yuksekyargi.emsal.karar.dto.EmsalKararSearchDto"
    "[\"kararTarihiStart\"])"
)
_EMPTY_PARSE = {"data": None, "metadata": {
    "FMTY": "ERROR", "FMC": "ADALET_EMPTY_EXCEPTION", "FMTE": _DATE_PARSE_FMTE}}
_EMPTY_PLAIN = {"data": None, "metadata": {"FMTY": "ERROR", "FMC": "ADALET_EMPTY_EXCEPTION"}}
_OK = {"data": {"total": 50, "emsalKararList": [
    {"id": str(i), "itemType": {"description": "Y"}} for i in range(10)
]}}


def _mock_resp(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.url = "http://mock"
    resp.request = MagicMock()
    return resp


def _patched_client(captured: list[dict], responses: list[dict]):
    queue = list(responses)

    async def _post(*a, **k):
        captured.append(k.get("json", {}))
        return _mock_resp(queue.pop(0) if len(queue) > 1 else queue[0])

    mc = patch("dayanak.sources.bedesten.client")
    started = mc.start()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_post)))
    cm.__aexit__ = AsyncMock(return_value=False)
    started.return_value = cm
    return mc


# ── Sanitising ───────────────────────────────────────────────────────────────

class TestSanitize:
    def test_clean_query_untouched(self):
        for q in ('+"iş kazası" +tazminat', "(+işçi OR +memur) +tazminat -manevi",
                  "kıdem AND ihbar", "maaş haczi muvafakat", ""):
            assert sanitize_bedesten_query(q) == (q, [])

    def test_incident_query(self):
        q, removed = sanitize_bedesten_query('+"83/a" +muvafakat +maaş +"takipten sonra"')
        assert q == '+"83 a" +muvafakat +maaş +"takipten sonra"'
        assert removed == ["/"]

    def test_article_number_becomes_phrase(self):
        assert sanitize_bedesten_query("83/a")[0] == '"83 a"'
        assert sanitize_bedesten_query("+83/a")[0] == '+"83 a"'
        assert sanitize_bedesten_query("-83/a")[0] == '-"83 a"'

    def test_trailing_punctuation_dropped(self):
        assert sanitize_bedesten_query("maaş. haczi,")[0] == "maaş haczi"

    def test_wildcards_dropped(self):
        q, removed = sanitize_bedesten_query("boşanma tazmin*")
        assert q == "boşanma tazmin"
        assert removed == ["*"]
        assert sanitize_bedesten_query("ma?ş")[0] == '"ma ş"'

    def test_apostrophe_inside_word(self):
        assert sanitize_bedesten_query("Yargıtay'ın kararı")[0] == '"Yargıtay ın" kararı'

    def test_smart_quotes_normalised(self):
        q, removed = sanitize_bedesten_query("“maaş haczi” +muvafakat")
        assert q == '"maaş haczi" +muvafakat'
        assert "“" in removed and "”" in removed

    def test_unmatched_quote_dropped(self):
        assert sanitize_bedesten_query('"maaş haczi')[0] == "maaş haczi"

    def test_parens_kept_balanced(self):
        assert sanitize_bedesten_query("(maaş/ücret) AND muvafakat")[0] == '("maaş ücret") AND muvafakat'
        assert sanitize_bedesten_query("(* OR maaş)")[0] == "( OR maaş)"

    def test_nothing_searchable_left(self):
        assert sanitize_bedesten_query("*")[0] == ""
        assert sanitize_bedesten_query("/ .")[0] == ""

    def test_output_only_contains_accepted_chars(self):
        bad = "/*?.,':_~%;§[]\\^@#=<{…–“”"
        q, _ = sanitize_bedesten_query(f"a{bad}b +c{bad} {bad}d")
        assert all(ch.isalnum() or ch.isspace() or ch in '+-"()&|!' for ch in q), q


class TestRewriteAfterSanitize:
    def test_sanitised_phrase_still_gets_and_rewrite(self):
        # The caller wrote no operators; the quotes come from sanitising, so
        # the AND rewrite must still apply, treating the phrase as one token.
        q, _ = sanitize_bedesten_query("83/a muvafakat maaş")
        assert rewrite_solr_query(q, has_operators=False) == ('+"83 a" +muvafakat +maaş', True)

    def test_operator_queries_still_pass_through(self):
        q, _ = sanitize_bedesten_query('+"83/a" +maaş')
        assert rewrite_solr_query(q, has_operators=True) == (q, False)


# ── Error classification ─────────────────────────────────────────────────────

class TestClassification:
    def test_validation_is_request_error(self):
        exc = BedestenUpstreamError("ADALET_PARAMETER_VALIDATION_EXCEPTION")
        assert exc.is_request_error is True
        assert exc.retryable is False

    def test_any_validation_code_is_request_error(self):
        assert BedestenUpstreamError("SOME_NEW_VALIDATION_FAULT").retryable is False

    def test_runtime_is_retryable(self):
        exc = BedestenUpstreamError("ADALET_RUNTIME_EXCEPTION")
        assert exc.is_request_error is False
        assert exc.retryable is True

    def test_empty_exception_with_parse_fault_is_request_error(self):
        exc = BedestenUpstreamError("ADALET_EMPTY_EXCEPTION", fmte=_DATE_PARSE_FMTE)
        assert exc.is_parameter_format_error is True
        assert exc.is_request_error is True
        assert exc.retryable is False
        assert exc.rejected_field == "kararTarihiStart"

    @pytest.mark.parametrize("fmte", [
        "JSON parse error: Unrecognized field \"foo\"",
        "java.lang.NumberFormatException: For input string: \"abc\"",
        "MismatchedInputException: Cannot construct instance",
    ])
    def test_other_parse_faults_are_request_errors(self, fmte):
        exc = BedestenUpstreamError("ADALET_EMPTY_EXCEPTION", fmte=fmte)
        assert exc.retryable is False
        assert exc.rejected_field is None

    def test_plain_empty_exception_stays_retryable(self):
        exc = BedestenUpstreamError("ADALET_EMPTY_EXCEPTION", fmte="beklenmeyen hata")
        assert exc.is_parameter_format_error is False
        assert exc.retryable is True

    def test_parse_markers_only_reclassify_empty_wrapper(self):
        exc = BedestenUpstreamError("ADALET_RUNTIME_EXCEPTION", fmte=_DATE_PARSE_FMTE)
        assert exc.retryable is True


class TestClientBehaviour:
    def test_sanitised_phrase_is_sent(self):
        captured: list[dict] = []
        mc = _patched_client(captured, [_OK])
        try:
            sp = asyncio.run(BedestenClient().search_page(
                '+"83/a" +muvafakat +maaş +"takipten sonra"', limit=10))
        finally:
            mc.stop()
        assert captured[0]["data"]["phrase"] == '+"83 a" +muvafakat +maaş +"takipten sonra"'
        assert any("temizlendi" in w for w in sp.warnings)
        assert sp.results[0].metadata["query_sanitized"] is True

    def test_or_fallback_uses_sanitised_query(self):
        captured: list[dict] = []
        few = {"data": {"total": 1, "emsalKararList": [{"id": "1", "itemType": {}}]}}
        mc = _patched_client(captured, [few, _OK])
        try:
            asyncio.run(BedestenClient().search_page("83/a maaş", limit=10))
        finally:
            mc.stop()
        assert captured[0]["data"]["phrase"] == '+"83 a" +maaş'
        assert captured[1]["data"]["phrase"] == '"83 a" maaş'

    def test_validation_error_not_retried(self):
        captured: list[dict] = []
        ci = BedestenClient()
        ci._upstream_retry_delay = 0.0
        mc = _patched_client(captured, [_VALIDATION])
        try:
            with pytest.raises(Exception) as ei:
                asyncio.run(ci.search_page("maaş", limit=10))
        finally:
            mc.stop()
        assert type(ei.value).__name__ == "BedestenUpstreamError"
        assert len(captured) == 1

    def test_parse_fault_not_retried(self):
        captured: list[dict] = []
        ci = BedestenClient()
        ci._upstream_retry_delay = 0.0
        mc = _patched_client(captured, [_EMPTY_PARSE])
        try:
            with pytest.raises(BedestenUpstreamError) as ei:
                asyncio.run(ci.search_page("maaş", limit=10))
        finally:
            mc.stop()
        assert ei.value.retryable is False
        assert len(captured) == 1

    def test_runtime_error_retried_once(self):
        captured: list[dict] = []
        ci = BedestenClient()
        ci._upstream_retry_delay = 0.0
        mc = _patched_client(captured, [_RUNTIME])
        try:
            with pytest.raises(Exception):
                asyncio.run(ci.search_page("maaş", limit=10))
        finally:
            mc.stop()
        assert len(captured) == 2


# ── Tool layer ───────────────────────────────────────────────────────────────

def _search_decisions():
    from tests.conftest import capture_registered_tools
    return capture_registered_tools("full")["search_decisions"]


class TestToolErrors:
    def test_validation_error_is_invalid_query(self):
        tool = _search_decisions()
        captured: list[dict] = []
        mc = _patched_client(captured, [_VALIDATION])
        try:
            res = asyncio.run(tool(query="maaş haczi"))
        finally:
            mc.stop()
        assert res["ok"] is False
        assert res["errorCode"] == "INVALID_QUERY"
        assert res["retryable"] is False
        assert res["upstream_error_code"] == "ADALET_PARAMETER_VALIDATION_EXCEPTION"
        assert "düz kelimelerle" in res["message"]
        assert "geçici" not in res["message"]

    def test_runtime_error_stays_upstream_retryable(self):
        tool = _search_decisions()
        captured: list[dict] = []
        mc = _patched_client(captured, [_RUNTIME])
        try:
            with patch.object(BedestenClient, "_upstream_retry_delay", 0.0):
                res = asyncio.run(tool(query="maaş haczi"))
        finally:
            mc.stop()
        assert res["errorCode"] == "SOURCE_UPSTREAM_ERROR"
        assert res["retryable"] is True

    def test_parse_fault_is_invalid_input_not_transient(self):
        tool = _search_decisions()
        captured: list[dict] = []
        mc = _patched_client(captured, [_EMPTY_PARSE])
        try:
            res = asyncio.run(tool(query="maaş haczi"))
        finally:
            mc.stop()
        assert res["ok"] is False
        assert res["errorCode"] == "INVALID_INPUT"
        assert res["retryable"] is False
        assert res["upstream_error_code"] == "ADALET_EMPTY_EXCEPTION"
        assert res["rejected_field"] == "kararTarihiStart"
        assert "kararTarihiStart" in res["message"]
        assert "geçici" not in res["message"]
        assert len(captured) == 1

    def test_plain_empty_exception_stays_upstream_retryable(self):
        tool = _search_decisions()
        captured: list[dict] = []
        mc = _patched_client(captured, [_EMPTY_PLAIN])
        try:
            with patch.object(BedestenClient, "_upstream_retry_delay", 0.0):
                res = asyncio.run(tool(query="maaş haczi"))
        finally:
            mc.stop()
        assert res["errorCode"] == "SOURCE_UPSTREAM_ERROR"
        assert res["retryable"] is True

    def test_unsearchable_query_rejected_without_request(self):
        tool = _search_decisions()
        captured: list[dict] = []
        mc = _patched_client(captured, [_OK])
        try:
            res = asyncio.run(tool(query="*"))
        finally:
            mc.stop()
        assert res["errorCode"] == "INVALID_QUERY"
        assert res["retryable"] is False
        assert captured == []
