"""Scheduled research watchlist — v2.4

Store named watches in the cache database. Each watch records a query,
source list, fetch count, and optional filters. Calling ``run_watch()``
re-executes the search and produces a diff report comparing new/changed
documents against the previous run.

No built-in cron/scheduler — ``run_watch()`` is called manually or by
an external scheduler.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cache import Cache
from .models import build_error


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_WATCH_DDL = """
CREATE TABLE IF NOT EXISTS watch_configs (
    name TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    last_run_at TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def _ensure_watch_table(cache: Cache) -> None:
    """Create the watch_configs table if it does not exist."""
    cache.db.execute(_WATCH_DDL)
    cache.db.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def add_watch(
    name: str,
    query: str,
    sources: list[str] | None = None,
    fetch_count: int = 5,
    filters: dict[str, Any] | None = None,
    interval_hours: int = 24,
    cache: Cache | None = None,
) -> dict[str, Any]:
    """Register a watch for periodic research.

    Args:
        name: Unique watch name (used as key).
        query: Research query string.
        sources: Optional list of source_ids to search.
        fetch_count: Max documents per search (default 5).
        filters: Optional search filters.
        interval_hours: Suggested interval in hours (default 24).
        cache: Optional Cache instance (created if None).

    Returns:
        Dict with ok, name, config.
    """
    if not name or not name.strip():
        return build_error("INVALID_NAME", "Watch name must not be empty.")

    if not query or not query.strip():
        return build_error("INVALID_QUERY", "Watch query must not be empty.")

    own_cache = cache is None
    if own_cache:
        cache = Cache()
    assert cache is not None  # type narrowed by own_cache branch

    try:
        _ensure_watch_table(cache)

        now = datetime.now(timezone.utc).isoformat()
        config: dict[str, Any] = {
            "query": query.strip(),
            "sources": sources,
            "fetch_count": fetch_count,
            "filters": filters or {},
            "interval_hours": interval_hours,
            "last_run_at": None,
            "created_at": now,
        }

        cache.db.execute(
            "INSERT INTO watch_configs(name, config_json, created_at) VALUES(?, ?, ?)",
            (name.strip(), json.dumps(config, ensure_ascii=False, default=str), now),
        )
        cache.db.commit()

        return {"ok": True, "name": name.strip(), "config": config}
    except sqlite3.IntegrityError:
        return build_error(
            "WATCH_EXISTS",
            f"Watch '{name.strip()}' already exists. Use a different name or remove first.",
        )
    except Exception as exc:
        return build_error("WATCH_ADD_FAILED", f"Failed to add watch: {exc}")
    finally:
        if own_cache:
            cache.close()


def list_watches(cache: Cache | None = None) -> dict[str, Any]:
    """List all registered watches.

    Returns:
        Dict with ok, watches list (each with name, config, last_run_at, created_at).
    """
    own_cache = cache is None
    if own_cache:
        cache = Cache()
    assert cache is not None  # type narrowed by own_cache branch

    try:
        _ensure_watch_table(cache)
        rows = cache.db.execute(
            "SELECT name, config_json, last_run_at, created_at FROM watch_configs ORDER BY name"
        ).fetchall()

        watches = []
        for row in rows:
            config = json.loads(row["config_json"])
            watches.append({
                "name": row["name"],
                "config": config,
                "last_run_at": row["last_run_at"],
                "created_at": row["created_at"],
            })

        return {"ok": True, "watches": watches, "total": len(watches)}
    except Exception as exc:
        return build_error("WATCH_LIST_FAILED", f"Failed to list watches: {exc}")
    finally:
        if own_cache:
            cache.close()


def run_watch(
    name: str,
    cache: Cache | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a watch: re-search, detect new/changed docs, produce diff report.

    Args:
        name: Watch name to execute.
        cache: Optional Cache instance.
        sources_override: Optional source client mapping (for testing).

    Returns:
        Dict with ok, name, result, new_documents, changed_documents, diff_report.
    """
    own_cache = cache is None
    if own_cache:
        cache = Cache()
    assert cache is not None  # type narrowed by own_cache branch

    try:
        _ensure_watch_table(cache)

        row = cache.db.execute(
            "SELECT name, config_json, last_run_at FROM watch_configs WHERE name=?",
            (name,),
        ).fetchone()

        if not row:
            return build_error("WATCH_NOT_FOUND", f"Watch '{name}' not found.")

        config = json.loads(row["config_json"])
        previous_run_at = row["last_run_at"]

        # Execute the research
        from .research import research_topic

        result = research_topic(
            query=config["query"],
            sources=config.get("sources"),
            fetch_count=config.get("fetch_count", 5),
            filters=config.get("filters") or {},
            sources_override=sources_override,
        )

        # Build diff report using bundle metadata
        total_results = result.get("result_count", 0)
        fetched_count = result.get("fetched_count", 0)

        # Read results.json from generated output for document ID tracking
        seen_key = f"watch_seen:{name}"
        previous_ids: set[str] = set(cache.get(seen_key) or [])

        current_ids: set[str] = set()
        generated_files = result.get("generated_files", [])
        # The output dir is computed as .emsal_research/<query_hash>
        # Try to find results.json from the generated files list
        for gf in generated_files:
            if gf == "results.json":
                # Compute the output dir path (same logic as research_topic)
                import hashlib
                qhash = hashlib.sha256(
                    config["query"].encode("utf-8", errors="ignore")
                ).hexdigest()[:12]
                out_dir = Path(".emsal_research") / qhash
                results_path = out_dir / "results.json"
                if results_path.exists():
                    try:
                        results_data = json.loads(results_path.read_text(encoding="utf-8"))
                        for item in results_data:
                            doc_id = item.get("document_id", "")
                            src = item.get("source", "")
                            if doc_id:
                                current_ids.add(f"{src}:{doc_id}")
                    except Exception:
                        pass
                break

        # Fallback: if no results.json found, use count-based tracking
        if not current_ids:
            current_ids = {f"run:{total_results}:{fetched_count}"}

        new_ids = current_ids - previous_ids

        # Update seen set
        cache.set(seen_key, list(current_ids))

        # Update last_run_at
        now = datetime.now(timezone.utc).isoformat()
        cache.db.execute(
            "UPDATE watch_configs SET last_run_at=?, config_json=? WHERE name=?",
            (
                now,
                json.dumps({**config, "last_run_at": now}, ensure_ascii=False, default=str),
                name,
            ),
        )
        cache.db.commit()

        diff_report = {
            "watch_name": name,
            "query": config["query"],
            "run_at": now,
            "previous_run_at": previous_run_at,
            "total_results": total_results,
            "new_document_count": len(new_ids),
            "new_document_ids": list(new_ids),
            "fetched_count": fetched_count,
        }

        # M-67: citation-safe signal — track content recovery
        status_summary = result.get("content_status_summary", {})
        cs_count = status_summary.get("full_text", 0) + status_summary.get("html_markdown", 0)
        prev_cs_key = f"watch_cs:{name}"
        prev_cs_count = cache.get(prev_cs_key) or 0
        cs_delta = cs_count - prev_cs_count
        cache.set(prev_cs_key, cs_count)

        diff_report["citation_safe_count"] = cs_count
        diff_report["citation_safe_delta"] = cs_delta
        if prev_cs_count == 0 and cs_count > 0:
            diff_report["content_recovery_signal"] = True
            diff_report["content_recovery_note"] = (
                f"Kaynak içeriği geri geldi: {cs_count} alıntılanabilir belge mevcut "
                f"(önceki çalıştırmada 0 idi)."
            )
        else:
            diff_report["content_recovery_signal"] = False

        return {
            "ok": True,
            "name": name,
            "result": result,
            "diff_report": diff_report,
        }
    except Exception as exc:
        return build_error("WATCH_RUN_FAILED", f"Failed to run watch: {exc}")
    finally:
        if own_cache:
            cache.close()


def remove_watch(name: str, cache: Cache | None = None) -> dict[str, Any]:
    """Remove a watch.

    Args:
        name: Watch name to remove.
        cache: Optional Cache instance.

    Returns:
        Dict with ok, name, removed.
    """
    if not name or not name.strip():
        return build_error("INVALID_NAME", "Watch name must not be empty.")

    own_cache = cache is None
    if own_cache:
        cache = Cache()
    assert cache is not None  # type narrowed by own_cache branch

    try:
        _ensure_watch_table(cache)

        row = cache.db.execute(
            "SELECT name FROM watch_configs WHERE name=?", (name.strip(),)
        ).fetchone()

        if not row:
            return build_error("WATCH_NOT_FOUND", f"Watch '{name}' not found.")

        # Clean up the seen set too
        seen_key = f"watch_seen:{name.strip()}"
        cache.db.execute("DELETE FROM watch_configs WHERE name=?", (name.strip(),))
        cache.db.commit()

        # Also clean legacy cache entry if present
        cache.db.execute("DELETE FROM cache WHERE key=?", (seen_key,))
        cache.db.commit()

        return {"ok": True, "name": name.strip(), "removed": True}
    except Exception as exc:
        return build_error("WATCH_REMOVE_FAILED", f"Failed to remove watch: {exc}")
    finally:
        if own_cache:
            cache.close()
