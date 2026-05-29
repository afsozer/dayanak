"""Search analytics: query success rate, empty-result queries, source coverage, cache hit ratio.

All metrics are deterministic and derived from cache data. Analytics is non-critical:
failures never break search operations.
"""
from __future__ import annotations

import logging
from typing import Any

from .models import build_error

logger = logging.getLogger(__name__)


def _ensure_search_history(cache: Any) -> None:
    """Create search_history table and indexes if they don't exist."""
    cache.db.execute("""
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            source_filter TEXT,
            result_count INTEGER DEFAULT 0,
            empty_result INTEGER DEFAULT 0,
            cache_hit INTEGER DEFAULT 0,
            duration_ms REAL,
            searched_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cache.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_history_query ON search_history(query)"
    )
    cache.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_history_searched_at ON search_history(searched_at)"
    )
    cache.db.commit()


def record_search(
    query: str,
    source_filter: str | None = None,
    result_count: int = 0,
    empty_result: bool = False,
    cache_hit: bool = False,
    duration_ms: float = 0.0,
    cache: Any = None,
) -> dict[str, Any]:
    """Record a search in the analytics table.

    Called by search functions (optional integration). Analytics failure
    never breaks search.

    Args:
        query: The search query string.
        source_filter: Comma-separated source filter, or None.
        result_count: Number of results returned.
        empty_result: True if result_count == 0.
        cache_hit: True if results came from cache.
        duration_ms: Search duration in milliseconds.
        cache: Cache instance. If None, a new one is created.

    Returns:
        Dict with ok=True and the recorded row id, or error dict.
    """
    own_cache = False
    if cache is None:
        from .cache import Cache
        cache = Cache()
        own_cache = True
    try:
        _ensure_search_history(cache)
        cursor = cache.db.execute(
            """INSERT INTO search_history
               (query, source_filter, result_count, empty_result, cache_hit, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                query,
                source_filter,
                result_count,
                1 if empty_result else 0,
                1 if cache_hit else 0,
                duration_ms,
            ),
        )
        cache.db.commit()
        return {"ok": True, "id": cursor.lastrowid}
    except Exception as exc:
        logger.debug("record_search failed: %s", exc)
        return build_error("ANALYTICS_RECORD_FAILED", str(exc))
    finally:
        if own_cache:
            cache.close()


def get_search_analytics(cache: Any = None, days: int = 30) -> dict[str, Any]:
    """Comprehensive search analytics over the given time window.

    Returns:
        Dict with ok, total_searches, empty_result_rate, avg_result_count,
        cache_hit_rate, top_queries, empty_queries, source_distribution,
        daily_activity.
    """
    own_cache = False
    if cache is None:
        from .cache import Cache
        cache = Cache()
        own_cache = True
    try:
        _ensure_search_history(cache)

        # Total searches in window
        row = cache.db.execute(
            "SELECT COUNT(*) FROM search_history WHERE searched_at >= datetime('now', ?)",
            (f"-{days} days",),
        ).fetchone()
        total_searches = row[0] if row else 0

        if total_searches == 0:
            return {
                "ok": True,
                "total_searches": 0,
                "empty_result_rate": 0.0,
                "avg_result_count": 0.0,
                "cache_hit_rate": 0.0,
                "top_queries": [],
                "empty_queries": [],
                "source_distribution": {},
                "daily_activity": [],
            }

        # Empty result rate
        empty_row = cache.db.execute(
            "SELECT COUNT(*) FROM search_history WHERE searched_at >= datetime('now', ?) AND empty_result = 1",
            (f"-{days} days",),
        ).fetchone()
        empty_count = empty_row[0] if empty_row else 0
        empty_result_rate = empty_count / total_searches if total_searches > 0 else 0.0

        # Average result count
        avg_row = cache.db.execute(
            "SELECT AVG(result_count) FROM search_history WHERE searched_at >= datetime('now', ?)",
            (f"-{days} days",),
        ).fetchone()
        avg_result_count = float(avg_row[0]) if avg_row and avg_row[0] is not None else 0.0

        # Cache hit rate
        cache_hit_row = cache.db.execute(
            "SELECT COUNT(*) FROM search_history WHERE searched_at >= datetime('now', ?) AND cache_hit = 1",
            (f"-{days} days",),
        ).fetchone()
        cache_hit_count = cache_hit_row[0] if cache_hit_row else 0
        cache_hit_rate = cache_hit_count / total_searches if total_searches > 0 else 0.0

        # Top queries
        top_rows = cache.db.execute(
            """SELECT query, COUNT(*) as cnt, AVG(result_count) as avg_res
               FROM search_history
               WHERE searched_at >= datetime('now', ?)
               GROUP BY query
               ORDER BY cnt DESC
               LIMIT 20""",
            (f"-{days} days",),
        ).fetchall()
        top_queries = [
            {"query": r["query"], "count": r["cnt"], "avg_results": round(float(r["avg_res"]), 2)}
            for r in top_rows
        ]

        # Empty queries
        empty_rows = cache.db.execute(
            """SELECT query, COUNT(*) as cnt, MAX(searched_at) as last_searched
               FROM search_history
               WHERE searched_at >= datetime('now', ?) AND empty_result = 1
               GROUP BY query
               ORDER BY cnt DESC
               LIMIT 20""",
            (f"-{days} days",),
        ).fetchall()
        empty_queries = [
            {"query": r["query"], "count": r["cnt"], "last_searched": r["last_searched"]}
            for r in empty_rows
        ]

        # Source distribution (from documents_v2)
        source_rows = cache.db.execute(
            "SELECT source, COUNT(*) as cnt FROM documents_v2 GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
        source_distribution = {r["source"]: r["cnt"] for r in source_rows}

        # Daily activity
        daily_rows = cache.db.execute(
            """SELECT DATE(searched_at) as date, COUNT(*) as count
               FROM search_history
               WHERE searched_at >= datetime('now', ?)
               GROUP BY DATE(searched_at)
               ORDER BY date""",
            (f"-{days} days",),
        ).fetchall()
        daily_activity = [{"date": r["date"], "count": r["count"]} for r in daily_rows]

        return {
            "ok": True,
            "total_searches": total_searches,
            "empty_result_rate": round(empty_result_rate, 4),
            "avg_result_count": round(avg_result_count, 2),
            "cache_hit_rate": round(cache_hit_rate, 4),
            "top_queries": top_queries,
            "empty_queries": empty_queries,
            "source_distribution": source_distribution,
            "daily_activity": daily_activity,
        }
    except Exception as exc:
        return build_error("ANALYTICS_QUERY_FAILED", str(exc))
    finally:
        if own_cache:
            cache.close()


def get_empty_queries(cache: Any = None, limit: int = 20) -> dict[str, Any]:
    """List queries that returned 0 results.

    Returns:
        Dict with ok and empty_queries list.
    """
    own_cache = False
    if cache is None:
        from .cache import Cache
        cache = Cache()
        own_cache = True
    try:
        _ensure_search_history(cache)
        rows = cache.db.execute(
            """SELECT query, COUNT(*) as cnt, MAX(searched_at) as last_searched
               FROM search_history
               WHERE empty_result = 1
               GROUP BY query
               ORDER BY cnt DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        empty_queries = [
            {"query": r["query"], "count": r["cnt"], "last_searched": r["last_searched"]}
            for r in rows
        ]
        return {"ok": True, "empty_queries": empty_queries}
    except Exception as exc:
        return build_error("ANALYTICS_QUERY_FAILED", str(exc))
    finally:
        if own_cache:
            cache.close()


def get_top_queries(cache: Any = None, limit: int = 20) -> dict[str, Any]:
    """Most frequent queries.

    Returns:
        Dict with ok and top_queries list.
    """
    own_cache = False
    if cache is None:
        from .cache import Cache
        cache = Cache()
        own_cache = True
    try:
        _ensure_search_history(cache)
        rows = cache.db.execute(
            """SELECT query, COUNT(*) as cnt, AVG(result_count) as avg_res
               FROM search_history
               GROUP BY query
               ORDER BY cnt DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        top_queries = [
            {"query": r["query"], "count": r["cnt"], "avg_results": round(float(r["avg_res"]), 2)}
            for r in rows
        ]
        return {"ok": True, "top_queries": top_queries}
    except Exception as exc:
        return build_error("ANALYTICS_QUERY_FAILED", str(exc))
    finally:
        if own_cache:
            cache.close()


def get_source_coverage(cache: Any = None) -> dict[str, Any]:
    """How many cached documents per source, and what percentage have full_text.

    Returns:
        Dict with ok and coverage list.
    """
    own_cache = False
    if cache is None:
        from .cache import Cache
        cache = Cache()
        own_cache = True
    try:
        rows = cache.db.execute(
            """SELECT source,
                      COUNT(*) as total_docs,
                      SUM(CASE WHEN full_text IS NOT NULL AND full_text != '' THEN 1 ELSE 0 END) as full_text_docs
               FROM documents_v2
               GROUP BY source
               ORDER BY total_docs DESC"""
        ).fetchall()
        coverage = []
        for r in rows:
            total = r["total_docs"]
            full = r["full_text_docs"]
            pct = round((full / total * 100), 1) if total > 0 else 0.0
            coverage.append({
                "source": r["source"],
                "total_docs": total,
                "full_text_docs": full,
                "coverage_pct": pct,
            })
        return {"ok": True, "coverage": coverage}
    except Exception as exc:
        return build_error("ANALYTICS_QUERY_FAILED", str(exc))
    finally:
        if own_cache:
            cache.close()
