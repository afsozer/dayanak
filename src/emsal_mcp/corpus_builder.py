"""Corpus builder — M-76.

Batch-fetches documents from all available sources to build a local corpus.
Respects rate limits, applies deduplication, tracks progress.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .cache import Cache
from .models import build_error

CORPUS_BUILDER_VERSION = "1.0.0"


def build_corpus(
    queries: list[str] | None = None,
    *,
    sources: list[str] | None = None,
    fetch_count: int = 5,
    max_total: int = 100,
    cache: Cache | None = None,
    sources_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a local corpus by searching multiple topics across all sources.

    Args:
        queries: List of search queries. Defaults to a set of common legal terms.
        sources: Source IDs to search. Defaults to all stable sources.
        fetch_count: Docs to fetch per query per source.
        max_total: Stop after this many total documents.
        cache: Optional Cache instance.
        sources_override: For test injection.

    Returns:
        Dict with ok, total_documents, queries_processed, time_taken, warnings.
    """
    if queries is None:
        queries = [
            "sözleşme ihlali tazminat",
            "iş kazası işveren sorumluluğu",
            "kira sözleşmesi tahliye",
            "idari para cezası iptal",
            "icra takibi itiraz",
            "boşanma nafaka velayet",
            "tapu iptal tescil",
            "tazminat hukuku",
        ]

    from .sources.registry import capabilities as get_caps

    if sources is None:
        caps = get_caps()
        sources = [
            c.get("source") or c.get("source_id", "")
            for c in caps
            if c.get("status") == "stable"
        ]
        sources = [s for s in sources if s]

    if not sources:
        return build_error("NO_SOURCES", "No stable sources available for corpus building.")

    own_cache = cache is None
    c = cache or Cache()
    start_time = datetime.now(timezone.utc)

    total_docs = 0
    processed = 0
    warnings: list[str] = []

    try:
        from .research import research_topic

        for query in queries:
            if total_docs >= max_total:
                break

            try:
                result = research_topic(
                    query=query,
                    sources=sources,
                    fetch_count=fetch_count,
                    sources_override=sources_override,
                )
                fetched = result.get("fetched_count", 0)
                total_docs += fetched
                processed += 1
            except Exception as exc:
                warnings.append(f"Query '{query}' failed: {exc}")
                continue

        # Apply dedup after building
        from .dedup import find_duplicates
        try:
            dedup = find_duplicates(cache=c, dry_run=False)
            if dedup.get("ok"):
                warnings.append(f"Dedup: {dedup.get('clusters_found', 0)} clusters found.")
        except Exception:
            pass

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        return {
            "ok": True,
            "total_documents": total_docs,
            "queries_processed": processed,
            "queries_total": len(queries),
            "time_seconds": round(elapsed, 1),
            "sources_used": sources,
            "warnings": warnings,
            "version": CORPUS_BUILDER_VERSION,
        }
    finally:
        if own_cache:
            c.close()


def corpus_status(cache: Cache | None = None) -> dict[str, Any]:
    """Report corpus size and composition.

    Args:
        cache: Optional Cache instance.

    Returns:
        Dict with total_docs, per_source, per_court, content_status_distribution.
    """
    own_cache = cache is None
    c = cache or Cache()
    try:
        stats = c.cache_stats()
        overview = {
            "ok": True,
            "total_documents": stats.get("document_count", 0),
            "cache_stats": stats,
            "version": CORPUS_BUILDER_VERSION,
        }
        return overview
    finally:
        if own_cache:
            c.close()
