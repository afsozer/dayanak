"""Tests for the Bedesten Solr query-rewrite safety net (Yargı-MCP parity Görev 1).

Bedesten's default Solr operator is OR.  emsal-mcp transparently rewrites
plain multi-word queries (no operators) so every term is required (`+term`),
preventing the OR-default from returning irrelevant noise.  Operator-bearing
queries pass through untouched.
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

from emsal_mcp.sources.bedesten import rewrite_solr_query


class TestRewriteSolrQuery:
    def test_plain_multiword_gets_plus_prefix(self):
        q, rewritten = rewrite_solr_query("tahliye taahhüdü geçerlilik")
        assert rewritten is True
        assert q == "+tahliye +taahhüdü +geçerlilik"

    def test_single_word_not_rewritten(self):
        q, rewritten = rewrite_solr_query("tazminat")
        assert rewritten is False
        assert q == "tazminat"

    def test_empty_not_rewritten(self):
        q, rewritten = rewrite_solr_query("")
        assert rewritten is False
        assert q == ""

    def test_whitespace_only_not_rewritten(self):
        q, rewritten = rewrite_solr_query("   ")
        assert rewritten is False

    def test_plus_operator_passes_through(self):
        original = '+"tahliye taahhüdü" +geçerlilik'
        q, rewritten = rewrite_solr_query(original)
        assert rewritten is False
        assert q == original

    def test_quotes_pass_through(self):
        original = '"iş kazası" tazminat'
        q, rewritten = rewrite_solr_query(original)
        assert rewritten is False
        assert q == original

    def test_and_operator_passes_through(self):
        original = "kıdem AND ihbar AND tazminat"
        q, rewritten = rewrite_solr_query(original)
        assert rewritten is False
        assert q == original

    def test_or_operator_passes_through(self):
        original = "işçi OR memur"
        q, rewritten = rewrite_solr_query(original)
        assert rewritten is False
        assert q == original

    def test_not_operator_passes_through(self):
        original = "tazminat NOT manevi"
        q, rewritten = rewrite_solr_query(original)
        assert rewritten is False
        assert q == original

    def test_parens_pass_through(self):
        original = "(+işçi OR +memur) +tazminat"
        q, rewritten = rewrite_solr_query(original)
        assert rewritten is False
        assert q == original

    def test_minus_operator_passes_through(self):
        original = "tazminat -manevi"
        q, rewritten = rewrite_solr_query(original)
        assert rewritten is False
        assert q == original

    def test_wildcard_alone_still_rewrites(self):
        # `*` is not an operator for the rewrite, so this multi-token query IS
        # rewritten.  NOTE: Bedesten rejects `*` outright (measured 22 Eyl
        # 2026); search_page strips it via sanitize_bedesten_query BEFORE the
        # rewrite runs — see test_bedesten_query_validation.
        q, rewritten = rewrite_solr_query("boşanma tazminat*")
        assert rewritten is True
        assert q == "+boşanma +tazminat*"

    def test_turkish_diacritics_preserved(self):
        q, rewritten = rewrite_solr_query("çiftçi şartları gücü")
        assert rewritten is True
        # diacritics preserved, each token prefixed
        assert q == "+çiftçi +şartları +gücü"


class TestNoStaleAndAssumptionInDocs:
    """Görev 1 verification: no wrong 'implicit AND' / 'boşanma tazminat*'
    examples remain in source or docs."""

    def _scan(self) -> list[str]:
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        hits: list[str] = []
        # The core false claim is that Solr's default operator is AND.
        # "boşanma tazminat*" appearing as a WRONG example (with a warning) is
        # fine — only its presentation as a correct implicit-AND example is bad.
        patterns = [
            "Solr AND is the default operator",
            "Solr AND is the default operator for bare terms",
        ]
        skip = {"YARGI_MCP_PARITY_TALIMAT.md"}
        for p in root.rglob("*.md"):
            if p.name in skip:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            for pat in patterns:
                if pat in text:
                    hits.append(f"{p}: {pat!r}")
        for py in (root / "src").rglob("*.py"):
            try:
                text = py.read_text(encoding="utf-8")
            except Exception:
                continue
            for pat in patterns:
                if pat in text:
                    hits.append(f"{py}: {pat!r}")
        return hits

    def test_no_wrong_examples_remain(self):
        hits = self._scan()
        assert hits == [], f"Stale wrong AND examples found: {hits}"
