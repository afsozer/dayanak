"""Tests for snippet extraction (Yargı-MCP parity Görev 4)."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.snippet import extract_query_terms, make_snippet


class TestExtractQueryTerms:
    def test_plain_terms(self):
        assert extract_query_terms("tazminat zamanaşımı") == ["tazminat", "zamanaşımı"]

    def test_plus_prefixed(self):
        assert extract_query_terms("+tazminat +zamanaşımı") == ["tazminat", "zamanaşımı"]

    def test_quoted_phrase(self):
        terms = extract_query_terms('+"iş kazası" +tazminat')
        assert "iş kazası" in terms
        assert "tazminat" in terms

    def test_minus_excluded_kept_as_term(self):
        # We don't try to honour exclusion semantics for snippet centring; the
        # - term is just stripped of its prefix.  Snippet centring on an
        # excluded term is harmless (worst case: a less-centred snippet).
        terms = extract_query_terms("tazminat -manevi")
        assert "tazminat" in terms

    def test_boolean_operators_dropped(self):
        terms = extract_query_terms("kıdem AND ihbar AND tazminat")
        assert terms == ["kıdem", "ihbar", "tazminat"]

    def test_empty(self):
        assert extract_query_terms("") == []
        assert extract_query_terms("   ") == []

    def test_short_tokens_dropped(self):
        # single-char tokens dropped
        terms = extract_query_terms("+a +tazminat")
        assert terms == ["tazminat"]


class TestMakeSnippet:
    def test_centres_on_first_term(self):
        text = "x " * 200 + "tazminat " + "y " * 200
        snip = make_snippet(text, ["tazminat"])
        assert "tazminat" in snip
        assert snip.startswith("...")
        assert snip.endswith("...")

    def test_picks_earliest_term(self):
        text = "aaa tazminat bbb zamanaşımı ccc"
        snip = make_snippet(text, ["zamanaşımı", "tazminat"])
        # tazminat occurs first → should be in the snippet window
        assert "tazminat" in snip

    def test_no_match_returns_leading(self):
        text = "abc " * 50
        snip = make_snippet(text, ["zzz"])
        assert "abc" in snip

    def test_no_terms_returns_leading(self):
        text = "hello world " * 10
        snip = make_snippet(text, [])
        assert snip.startswith("hello")

    def test_empty_text(self):
        assert make_snippet("", ["x"]) == ""

    def test_length_bounded(self):
        text = "word " * 500 + "tazminat " + "word " * 500
        snip = make_snippet(text, ["tazminat"], max_length=100)
        assert len(snip) <= 106  # 100 + ellipses

    def test_no_ellipsis_when_short(self):
        snip = make_snippet("kısa metin", ["kısa"])
        assert "..." not in snip
