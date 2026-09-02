"""Regression tests: get_index_status() must never COUNT(*) the FTS5 table.

Root cause guarded here: ``documents_v2_fts`` is an external-content FTS5 table
(``content='documents_v2'``). ``SELECT COUNT(*) FROM documents_v2_fts`` makes
SQLite walk the whole 25 GB content table row by row, which hung the production
MCP server for 15+ minutes and made every client see "unavailable".

The tests assert behaviour, not timing (a duration assertion would be flaky in
CI): the counter must come from the ``documents_v2_fts_docsize`` shadow table,
and the forbidden statement must not be issued at all.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from emsal_mcp.cache import Cache
from emsal_mcp.models import ContentStatus, Document
from emsal_mcp.semantic import build_semantic_index, get_index_status

pytestmark = [pytest.mark.integration]


# ``documents_v2_fts\b`` deliberately does not match ``documents_v2_fts_docsize``
# (``_`` is a word character, so there is no word boundary after ``fts`` there).
_FORBIDDEN_COUNT = re.compile(
    r"count\s*\(\s*\*\s*\)\s+from\s+[\"'`\[]?documents_v2_fts\b", re.IGNORECASE
)

_DOCS = [
    {
        "source": "yargitay",
        "document_id": "yg-fts-1",
        "title": "Sozlesme ihlali karari",
        "court": "Yargitay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": "Taraflar arasindaki sozlesme hukumleri ihlal edilmistir.",
        "markdown": "# Sozlesme ihlali",
    },
    {
        "source": "danistay",
        "document_id": "ds-fts-1",
        "title": "Idari para cezasi iptali",
        "court": "Danistay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": "Idari para cezasinin iptali talebiyle acilan dava.",
        "markdown": "# Idari para cezasi",
    },
    {
        "source": "yargitay",
        "document_id": "yg-fts-2",
        "title": "Is kazasi tazminat davasi",
        "court": "Yargitay",
        "content_status": ContentStatus.FULL_TEXT,
        "full_text": "Is kazasi sonucu olusan maddi zararin tazmini istemiyle acilan dava.",
        "markdown": "# Is kazasi",
    },
]


def _build(cache: Cache) -> None:
    for data in _DOCS:
        cache.store_document(Document(**data))
    result = build_semantic_index(cache=cache)
    assert result["ok"] is True


def _status_with_trace(cache: Cache) -> tuple[dict, list[str]]:
    """Run get_index_status() while recording every SQL statement it executes."""
    statements: list[str] = []
    cache.db.set_trace_callback(statements.append)
    try:
        result = get_index_status(cache=cache)
    finally:
        cache.db.set_trace_callback(None)
    return result, statements


def _assert_no_fts_scan(statements: list[str]) -> None:
    offenders = [s for s in statements if _FORBIDDEN_COUNT.search(s)]
    assert not offenders, (
        "get_index_status() issued COUNT(*) against the external-content FTS5 "
        f"table, which scans the whole content table: {offenders}"
    )
    assert statements, "trace callback captured nothing; the test is not observing anything"


class TestIndexStatusDoesNotScanFts:
    def test_regex_distinguishes_docsize_from_fts_table(self) -> None:
        """Guard the guard: the pattern must not fire on the shadow table."""
        assert _FORBIDDEN_COUNT.search("SELECT COUNT(*) FROM documents_v2_fts")
        assert _FORBIDDEN_COUNT.search("select count( * ) from documents_v2_fts ")
        assert not _FORBIDDEN_COUNT.search("SELECT COUNT(*) FROM documents_v2_fts_docsize")
        assert not _FORBIDDEN_COUNT.search("SELECT COUNT(*) FROM documents_v2")

    def test_count_is_correct_and_taken_from_docsize(self, tmp_path: Path) -> None:
        cache = Cache(tmp_path / "fts_count.sqlite3")
        try:
            _build(cache)
            result, statements = _status_with_trace(cache)

            assert result["ok"] is True
            assert result["fts5_exists"] is True
            assert result["fts5_document_count"] == len(_DOCS)
            assert result["total_cached_documents"] == len(_DOCS)

            _assert_no_fts_scan(statements)
            assert any(
                "documents_v2_fts_docsize" in s for s in statements
            ), f"docsize shadow table was never queried: {statements}"
        finally:
            cache.close()

    def test_no_fts_scan_when_index_missing(self, tmp_path: Path) -> None:
        """Empty DB: no FTS5 table at all, still no forbidden statement."""
        cache = Cache(tmp_path / "fts_empty.sqlite3")
        try:
            result, statements = _status_with_trace(cache)
            assert result["ok"] is True
            assert result["fts5_exists"] is False
            assert result["fts5_document_count"] == 0
            _assert_no_fts_scan(statements)
        finally:
            cache.close()

    def test_falls_back_when_docsize_table_absent(self, tmp_path: Path) -> None:
        """detail='none'/columnsize=0 indexes have no docsize table.

        The fallback must still avoid COUNT(*) on the FTS5 table, return a
        usable number and warn that the number is an estimate.
        """
        cache = Cache(tmp_path / "fts_no_docsize.sqlite3")
        try:
            _build(cache)
            try:
                cache.db.execute("DROP TABLE documents_v2_fts_docsize")
                cache.db.commit()
            except sqlite3.OperationalError as exc:  # pragma: no cover
                pytest.skip(f"cannot drop FTS5 shadow table on this SQLite build: {exc}")

            result, statements = _status_with_trace(cache)

            assert result["ok"] is True
            assert result["fts5_exists"] is True
            assert result["fts5_document_count"] == len(_DOCS)
            assert any(
                "docsize" in w and "estimate" in w for w in result["warnings"]
            ), f"missing estimate warning: {result['warnings']}"
            _assert_no_fts_scan(statements)
        finally:
            cache.close()
