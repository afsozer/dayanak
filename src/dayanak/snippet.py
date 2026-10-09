"""Snippet extraction for search results (Yargı-MCP parity Görev 4).

Produces a ~300–400 char passage from a document's full text centred on the
first occurrence of any of the query terms.  Mirrors hosted yargı-mcp's
``snippet`` field so the LLM can triage relevance without fetching every
result's full text individually.
"""
from __future__ import annotations

import re
from typing import Iterable

# Default snippet window.  Slightly wider than the cache's local snippet
# (200) so the LLM gets enough context to judge relevance at a glance.
SNIPPET_MAX_LENGTH = 360

# Tokens we never want to centre a snippet on — Solr operators and common
# noise.  Kept small and conservative.
_OPERATOR_TOKENS = {"AND", "OR", "NOT", "ve", "veya", "ile"}


def extract_query_terms(query: str) -> list[str]:
    """Extract searchable term tokens from a (possibly Solr-rewritten) query.

    Strips ``+``/``-`` prefixes, unwraps quoted phrases (kept as a single
    multi-word term), drops boolean operators, and returns the bare lowercase
    terms in encounter order.
    """
    if not query:
        return []
    terms: list[str] = []
    # First pull out quoted phrases as atomic multi-word terms.
    for m in re.finditer(r'"([^"]+)"', query):
        phrase = m.group(1).strip()
        if phrase:
            terms.append(phrase.lower())
    # Then strip quotes and operators and scan the remaining bare tokens.
    cleaned = re.sub(r'"[^"]*"', " ", query)
    cleaned = re.sub(r"[+\-()]", " ", cleaned)
    for tok in cleaned.split():
        t = tok.strip().strip("'")
        if not t:
            continue
        if t.upper() in _OPERATOR_TOKENS:
            continue
        if len(t) < 2:
            continue
        terms.append(t.lower())
    return terms


def make_snippet(text: str, terms: Iterable[str], max_length: int = SNIPPET_MAX_LENGTH) -> str:
    """Return a snippet of *text* centred on the first matched term.

    Falls back to the leading *max_length* chars when no term matches.
    """
    if not text:
        return ""
    terms = [t for t in terms if t]
    if not terms:
        return text[:max_length] + ("..." if len(text) > max_length else "")
    lower = text.lower()
    # Find the earliest occurrence of any term.
    best = -1
    for t in terms:
        idx = lower.find(t)
        if idx != -1 and (best == -1 or idx < best):
            best = idx
    if best == -1:
        return text[:max_length] + ("..." if len(text) > max_length else "")
    start = max(0, best - max_length // 3)
    end = min(len(text), best + max_length - (best - start))
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet
