"""Tests for search analytics module (M-10)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from emsal_mcp.cache import Cache
from emsal_mcp.search_analytics import (
    _ensure_search_history,
    get_empty_queries,
    get_search_analytics,
    get_source_coverage,
    get_top_queries,
    record_search,
)


@pytest.fixture
def cache_with_analytics():
    """Create a temporary cache with analytics table."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_analytics.sqlite3"
        c = Cache(path)
        _ensure_search_history(c)
        yield c
        c.close()


@pytest.fixture
def cache_with_documents():
    """Create a temporary cache with some documents and analytics."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_docs_analytics.sqlite3"
        c = Cache(path)
        _ensure_search_history(c)
        # Insert sample documents
        for i, (source, has_ft) in enumerate([
            ("yargitay", True), ("yargitay", True), ("yargitay", False),
            ("danistay", True), ("danistay", False),
            ("mevzuat", True),
        ]):
            c.db.execute(
                """INSERT INTO documents_v2
                   (document_id, source, title, full_text, content_status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f"doc-{i}", source, f"Title {i}", f"Full text {i}" if has_ft else None,
                 "full_text" if has_ft else "metadata_only"),
            )
        c.db.commit()
        yield c
        c.close()


# --- record_search tests ---


def test_record_search_basic(cache_with_analytics):
    result = record_search(query="tazminat", cache=cache_with_analytics)
    assert result["ok"] is True
    assert "id" in result


def test_record_search_empty_result(cache_with_analytics):
    record_search(query="xyznonexistent", result_count=0, empty_result=True, cache=cache_with_analytics)
    row = cache_with_analytics.db.execute(
        "SELECT empty_result FROM search_history WHERE query='xyznonexistent'"
    ).fetchone()
    assert row is not None
    assert row[0] == 1


def test_record_search_cache_hit(cache_with_analytics):
    record_search(query="kira", cache_hit=True, cache=cache_with_analytics)
    row = cache_with_analytics.db.execute(
        "SELECT cache_hit FROM search_history WHERE query='kira'"
    ).fetchone()
    assert row is not None
    assert row[0] == 1


def test_record_search_with_source_filter(cache_with_analytics):
    record_search(query="boşanma", source_filter="yargitay", cache=cache_with_analytics)
    row = cache_with_analytics.db.execute(
        "SELECT source_filter FROM search_history WHERE query='boşanma'"
    ).fetchone()
    assert row is not None
    assert row[0] == "yargitay"


def test_record_search_with_duration(cache_with_analytics):
    record_search(query="velayet", duration_ms=42.5, cache=cache_with_analytics)
    row = cache_with_analytics.db.execute(
        "SELECT duration_ms FROM search_history WHERE query='velayet'"
    ).fetchone()
    assert row is not None
    assert row[0] == 42.5


# --- get_search_analytics tests ---


def test_analytics_empty_db():
    """Analytics on empty DB returns ok=True with zeros."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty.sqlite3"
        c = Cache(path)
        try:
            result = get_search_analytics(cache=c)
            assert result["ok"] is True
            assert result["total_searches"] == 0
            assert result["empty_result_rate"] == 0.0
            assert result["avg_result_count"] == 0.0
            assert result["cache_hit_rate"] == 0.0
            assert result["top_queries"] == []
            assert result["empty_queries"] == []
            assert result["source_distribution"] == {}
            assert result["daily_activity"] == []
        finally:
            c.close()


def test_analytics_with_recorded_searches(cache_with_analytics):
    record_search(query="tazminat", result_count=5, cache=cache_with_analytics)
    record_search(query="tazminat", result_count=3, cache=cache_with_analytics)
    record_search(query="kira", result_count=0, empty_result=True, cache=cache_with_analytics)

    result = get_search_analytics(cache=cache_with_analytics)
    assert result["ok"] is True
    assert result["total_searches"] == 3
    assert result["empty_result_rate"] == pytest.approx(1 / 3, abs=0.01)
    assert result["avg_result_count"] == pytest.approx(8 / 3, abs=0.01)


def test_analytics_cache_hit_rate(cache_with_analytics):
    record_search(query="a", cache_hit=True, cache=cache_with_analytics)
    record_search(query="b", cache_hit=True, cache=cache_with_analytics)
    record_search(query="c", cache_hit=False, cache=cache_with_analytics)

    result = get_search_analytics(cache=cache_with_analytics)
    assert result["ok"] is True
    assert result["cache_hit_rate"] == pytest.approx(2 / 3, abs=0.01)


def test_analytics_top_queries(cache_with_analytics):
    for _ in range(5):
        record_search(query="popular", result_count=2, cache=cache_with_analytics)
    for _ in range(2):
        record_search(query="rare", result_count=1, cache=cache_with_analytics)

    result = get_search_analytics(cache=cache_with_analytics)
    assert result["ok"] is True
    assert len(result["top_queries"]) == 2
    assert result["top_queries"][0]["query"] == "popular"
    assert result["top_queries"][0]["count"] == 5


def test_analytics_empty_queries(cache_with_analytics):
    record_search(query="empty1", result_count=0, empty_result=True, cache=cache_with_analytics)
    record_search(query="empty2", result_count=0, empty_result=True, cache=cache_with_analytics)
    record_search(query="found", result_count=3, cache=cache_with_analytics)

    result = get_search_analytics(cache=cache_with_analytics)
    assert result["ok"] is True
    assert len(result["empty_queries"]) == 2
    empty_q_names = {q["query"] for q in result["empty_queries"]}
    assert "empty1" in empty_q_names
    assert "empty2" in empty_q_names


def test_analytics_source_distribution(cache_with_documents):
    record_search(query="test", cache=cache_with_documents)
    result = get_search_analytics(cache=cache_with_documents)
    assert result["ok"] is True
    assert "yargitay" in result["source_distribution"]
    assert result["source_distribution"]["yargitay"] == 3
    assert result["source_distribution"]["danistay"] == 2
    assert result["source_distribution"]["mevzuat"] == 1


def test_analytics_daily_activity(cache_with_analytics):
    record_search(query="today", cache=cache_with_analytics)
    result = get_search_analytics(cache=cache_with_analytics)
    assert result["ok"] is True
    assert len(result["daily_activity"]) >= 1
    assert result["daily_activity"][0]["count"] >= 1


def test_analytics_days_filter(cache_with_analytics):
    """Older queries are excluded by days filter."""
    record_search(query="recent", cache=cache_with_analytics)
    # Manually backdate a search
    cache_with_analytics.db.execute(
        "UPDATE search_history SET searched_at = datetime('now', '-60 days') WHERE query='recent'"
    )
    cache_with_analytics.db.commit()

    result = get_search_analytics(cache=cache_with_analytics, days=30)
    assert result["ok"] is True
    assert result["total_searches"] == 0

    result_all = get_search_analytics(cache=cache_with_analytics, days=90)
    assert result_all["total_searches"] == 1


# --- get_empty_queries tests ---


def test_get_empty_queries_basic(cache_with_analytics):
    record_search(query="found", result_count=3, cache=cache_with_analytics)
    record_search(query="empty_a", result_count=0, empty_result=True, cache=cache_with_analytics)
    record_search(query="empty_b", result_count=0, empty_result=True, cache=cache_with_analytics)

    result = get_empty_queries(cache=cache_with_analytics)
    assert result["ok"] is True
    assert len(result["empty_queries"]) == 2


def test_get_empty_queries_limit(cache_with_analytics):
    for i in range(5):
        record_search(query=f"empty_{i}", result_count=0, empty_result=True, cache=cache_with_analytics)

    result = get_empty_queries(cache=cache_with_analytics, limit=3)
    assert result["ok"] is True
    assert len(result["empty_queries"]) == 3


def test_get_empty_queries_empty_db():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty_eq.sqlite3"
        c = Cache(path)
        try:
            result = get_empty_queries(cache=c)
            assert result["ok"] is True
            assert result["empty_queries"] == []
        finally:
            c.close()


# --- get_top_queries tests ---


def test_get_top_queries_basic(cache_with_analytics):
    for _ in range(3):
        record_search(query="alpha", result_count=2, cache=cache_with_analytics)
    record_search(query="beta", result_count=5, cache=cache_with_analytics)

    result = get_top_queries(cache=cache_with_analytics)
    assert result["ok"] is True
    assert len(result["top_queries"]) == 2
    assert result["top_queries"][0]["query"] == "alpha"
    assert result["top_queries"][0]["count"] == 3
    assert result["top_queries"][0]["avg_results"] == 2.0
    assert result["top_queries"][1]["query"] == "beta"
    assert result["top_queries"][1]["avg_results"] == 5.0


def test_get_top_queries_limit(cache_with_analytics):
    for i in range(5):
        record_search(query=f"q{i}", cache=cache_with_analytics)

    result = get_top_queries(cache=cache_with_analytics, limit=2)
    assert result["ok"] is True
    assert len(result["top_queries"]) == 2


# --- get_source_coverage tests ---


def test_get_source_coverage_basic(cache_with_documents):
    result = get_source_coverage(cache=cache_with_documents)
    assert result["ok"] is True
    assert len(result["coverage"]) == 3

    yargitay = next(c for c in result["coverage"] if c["source"] == "yargitay")
    assert yargitay["total_docs"] == 3
    assert yargitay["full_text_docs"] == 2
    assert yargitay["coverage_pct"] == pytest.approx(66.7, abs=0.5)

    danistay = next(c for c in result["coverage"] if c["source"] == "danistay")
    assert danistay["total_docs"] == 2
    assert danistay["full_text_docs"] == 1
    assert danistay["coverage_pct"] == 50.0

    mevzuat = next(c for c in result["coverage"] if c["source"] == "mevzuat")
    assert mevzuat["total_docs"] == 1
    assert mevzuat["full_text_docs"] == 1
    assert mevzuat["coverage_pct"] == 100.0


def test_get_source_coverage_empty_db():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty_sc.sqlite3"
        c = Cache(path)
        try:
            result = get_source_coverage(cache=c)
            assert result["ok"] is True
            assert result["coverage"] == []
        finally:
            c.close()


# --- Record → stats consistency ---


def test_record_then_stats_consistency(cache_with_analytics):
    """Record multiple searches and verify stats are consistent."""
    record_search(query="q1", result_count=10, cache_hit=True, cache=cache_with_analytics)
    record_search(query="q1", result_count=8, cache_hit=True, cache=cache_with_analytics)
    record_search(query="q2", result_count=0, empty_result=True, cache_hit=False, cache=cache_with_analytics)
    record_search(query="q3", result_count=5, cache_hit=True, cache=cache_with_analytics)

    result = get_search_analytics(cache=cache_with_analytics)
    assert result["ok"] is True
    assert result["total_searches"] == 4
    # empty rate: 1/4 = 0.25
    assert result["empty_result_rate"] == pytest.approx(0.25, abs=0.01)
    # avg: (10+8+0+5)/4 = 23/4 = 5.75
    assert result["avg_result_count"] == pytest.approx(5.75, abs=0.01)
    # cache hit rate: 3/4 = 0.75
    assert result["cache_hit_rate"] == pytest.approx(0.75, abs=0.01)
    # top query is q1 (2 hits)
    assert result["top_queries"][0]["query"] == "q1"
    assert result["top_queries"][0]["count"] == 2


# --- CLI and MCP imports ---


def test_cli_import():
    """CLI analytics commands can be imported."""
    from emsal_mcp.cli import analytics_app
    assert analytics_app is not None


def test_mcp_tools_import():
    """MCP server module can be imported (analytics tools registered)."""
    from emsal_mcp.server import main
    assert callable(main)


# --- Auto-recording integration test ---


def test_auto_recording_from_search_local(cache_with_documents):
    """search_local auto-records analytics."""
    results = cache_with_documents.search_local(query="Full text", limit=10)
    # Verify a row was recorded
    row = cache_with_documents.db.execute(
        "SELECT query, result_count, empty_result, cache_hit FROM search_history WHERE query='Full text'"
    ).fetchone()
    assert row is not None
    assert row["result_count"] == len(results)
    assert row["cache_hit"] == 1


def test_auto_recording_empty_result(cache_with_documents):
    """search_local auto-records empty results."""
    results = cache_with_documents.search_local(query="nonexistent_xyz_query", limit=10)
    assert len(results) == 0
    row = cache_with_documents.db.execute(
        "SELECT empty_result FROM search_history WHERE query='nonexistent_xyz_query'"
    ).fetchone()
    assert row is not None
    assert row[0] == 1
