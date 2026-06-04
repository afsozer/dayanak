"""Corpus builder — M-76.

Batch-fetches documents from all available sources to build a local corpus.
Respects rate limits, applies deduplication, tracks progress.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .cache import Cache
from .models import build_error

CORPUS_BUILDER_VERSION = "1.1.0"


def crawl_full_text(
    source: str = "bedesten",
    *,
    phrase: str = "karar",
    item_type: str = "YARGITAYKARARI",
    sort_direction: str = "desc",
    max_docs: int = 500,
    max_pages: int = 200,
    page_size: int = 100,
    start_page: int = 1,
    cache: Cache | None = None,
) -> dict[str, Any]:
    """Systematically crawl FULL-TEXT decisions into the local cache.

    Paginates a broad search (``phrase`` appears in essentially every decision,
    e.g. "karar"), fetches each hit, and stores ONLY documents whose full text
    is actually available (content_status full_text / html_markdown). Documents
    whose text is not published yet (HTTP 404 → UNAVAILABLE) or metadata-only
    are skipped — never fabricated. Pacing is automatic (the client's built-in
    rate limiter); no manual sleeps needed.

    Resumable: pass ``start_page`` and read ``next_page`` from the result to
    continue a long crawl in batches.

    Args:
        source: Source id. ``bedesten`` (= Yargıtay) is the full-text source.
        phrase: Broad anchor term present in nearly all decisions.
        item_type: Bedesten itemType. ``YARGITAYKARARI`` covers ALL Yargıtay
            chambers in one stream.
        sort_direction: ``desc`` = newest first, ``asc`` = oldest first.
        max_docs: Stop after storing this many full-text documents.
        max_pages: Safety cap on pages scanned.
        page_size: Results per search page (server max 100).
        start_page: Page to start from (for resuming).
        cache: Optional Cache instance.

    Returns:
        Dict with ok, stored, scanned, skipped_unavailable, skipped_metadata,
        pages_scanned, next_page, time_seconds, warnings.
    """
    import asyncio

    from .models import ContentStatus, merge_search_metadata
    from .sources.registry import get_source

    if sort_direction not in {"desc", "asc"}:
        return build_error("INVALID_SORT", "sort_direction must be 'desc' or 'asc'.")

    own_cache = cache is None
    c = cache or Cache()
    start_time = datetime.now(timezone.utc)
    stored = scanned = skipped_unavailable = skipped_metadata = pages_scanned = 0
    warnings: list[str] = []
    page = start_page
    full_text_statuses = {ContentStatus.FULL_TEXT, ContentStatus.HTML_MARKDOWN}

    import httpx

    rl_429 = 0

    async def _retry_429(factory: Any, attempts: int = 6) -> Any:
        """Retry a request on HTTP 429. The client's response hook records the
        server Retry-After as a cooldown, so the next call's acquire() waits it
        out — we just re-issue. Prevents dropping documents/pages on rate limit
        (the cause of ~25 skipped pages in the first overnight run)."""
        nonlocal rl_429
        for i in range(attempts):
            try:
                return await factory()
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response is not None else None
                if code == 429 and i < attempts - 1:
                    rl_429 += 1
                    continue
                raise

    async def _run() -> None:
        nonlocal stored, scanned, skipped_unavailable, skipped_metadata, pages_scanned, page
        client = get_source(source)
        while stored < max_docs and pages_scanned < max_pages:
            try:
                results = await _retry_429(lambda: client.search(
                    phrase, limit=page_size, page=page,
                    item_type=item_type, sort_direction=sort_direction,
                ))
            except Exception as exc:
                warnings.append(f"search page {page} failed: {exc}")
                break
            if not results:
                break  # past the last page
            # Process the WHOLE page (never break mid-page) so resuming from
            # next_page can't skip the unprocessed tail of a page. A batch may
            # store slightly more than max_docs; the outer while stops at the
            # next clean page boundary.
            for sr in results:
                scanned += 1
                try:
                    doc = await _retry_429(lambda sr=sr: client.get_document(sr.document_id))
                except Exception as exc:
                    warnings.append(f"fetch {sr.document_id} failed: {exc}")
                    continue
                merge_search_metadata(doc, sr)
                if doc.content_status in full_text_statuses and (doc.text or "").strip():
                    try:
                        c.store_document(doc)
                        stored += 1
                    except Exception as exc:
                        warnings.append(f"store {sr.document_id} failed: {exc}")
                elif doc.content_status == ContentStatus.UNAVAILABLE:
                    skipped_unavailable += 1
                else:
                    skipped_metadata += 1
            pages_scanned += 1
            page += 1

    try:
        asyncio.run(_run())
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        return {
            "ok": True,
            "source": source,
            "stored": stored,
            "scanned": scanned,
            "skipped_unavailable": skipped_unavailable,  # full text not published yet (404)
            "skipped_metadata": skipped_metadata,
            "pages_scanned": pages_scanned,
            "next_page": page,  # pass as start_page to resume
            "rate_limit_retries": rl_429,  # 429s recovered via wait+retry (not dropped)
            "time_seconds": round(elapsed, 1),
            "warnings": warnings[:50],
            "version": CORPUS_BUILDER_VERSION,
        }
    finally:
        if own_cache:
            c.close()


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
            "total_documents": stats.get("documents_v2", 0),
            "cache_stats": stats,
            "version": CORPUS_BUILDER_VERSION,
        }
        return overview
    finally:
        if own_cache:
            c.close()
