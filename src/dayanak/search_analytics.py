"""Search analytics: recording layer.

Kept for cache.py auto-recording (record_search).  All MCP-facing query
functions (get_search_analytics, get_empty_queries, get_top_queries,
get_source_coverage) have been removed in M-104.
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
