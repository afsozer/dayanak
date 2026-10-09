"""Corpus builder — M-76.

Batch-fetches documents from all available sources to build a local corpus.
Respects rate limits, applies deduplication, tracks progress.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .cache import Cache
from .models import build_error

CORPUS_BUILDER_VERSION = "1.2.0"


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
    start_date: str | None = None,
    end_date: str | None = None,
    incremental: bool = False,
    stop_after_seen: int = 200,
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
        incremental: When True (use with ``sort_direction='desc'``), skip the
            expensive full-text fetch for decisions already in the cache and stop
            once ``stop_after_seen`` consecutive already-cached decisions are seen
            (i.e. the crawl has reached the region it covered last time). In this
            mode ``stored`` counts ONLY genuinely new decisions.
        stop_after_seen: Consecutive-already-cached threshold that ends an
            incremental run. Ignored when ``incremental`` is False.
        cache: Optional Cache instance.

    Returns:
        Dict with ok, stored, scanned, skipped_unavailable, skipped_metadata,
        skipped_cached, pages_scanned, next_page, stopped_reason, time_seconds,
        warnings.
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
    skipped_cached = 0
    consecutive_seen = 0
    stopped_reason = "max_docs"
    warnings: list[str] = []
    page = start_page
    full_text_statuses = {ContentStatus.FULL_TEXT, ContentStatus.HTML_MARKDOWN}

    import httpx

    rl_429 = 0

    async def _retry_429(factory: Any, attempts: int = 6) -> Any:
        """Retry a request on HTTP 429 and transient 5xx (e.g. UYAP's Solr
        ``IOException``). On 429 the client's response hook records the server
        Retry-After as a cooldown, so the next call's acquire() waits it out —
        we just re-issue. On 5xx we back off a few seconds. This keeps a long
        crawl alive through rate-limit storms and brief upstream outages instead
        of dying on the first bad page (a single failed *search* ends the run)."""
        nonlocal rl_429
        for i in range(attempts):
            try:
                return await factory()
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response is not None else None
                if i >= attempts - 1:
                    raise
                if code == 429:
                    rl_429 += 1
                    continue
                if code is not None and 500 <= code < 600:
                    await asyncio.sleep(min(5.0 * (i + 1), 30.0))
                    continue
                raise
            except httpx.TransportError:
                # Connection reset / timeout — transient; back off and retry.
                if i >= attempts - 1:
                    raise
                await asyncio.sleep(min(3.0 * (i + 1), 20.0))

    async def _run() -> None:
        nonlocal stored, scanned, skipped_unavailable, skipped_metadata, pages_scanned, page
        nonlocal skipped_cached, consecutive_seen, stopped_reason
        client = get_source(source)
        while stored < max_docs and pages_scanned < max_pages:
            try:
                results = await _retry_429(lambda: client.search(
                    phrase, limit=page_size, page=page,
                    item_type=item_type, sort_direction=sort_direction,
                    start_date=start_date, end_date=end_date,
                ), attempts=30)
            except Exception as exc:
                warnings.append(f"search page {page} failed: {exc}")
                stopped_reason = "search_error"
                break
            if not results:
                stopped_reason = "exhausted"
                break  # past the last page
            # Process the WHOLE page (never break mid-page) so resuming from
            # next_page can't skip the unprocessed tail of a page. A batch may
            # store slightly more than max_docs; the outer while stops at the
            # next clean page boundary.
            for sr in results:
                scanned += 1
                # Incremental mode: skip the expensive full-text fetch for
                # decisions we already hold, and end the run once we've hit a
                # long enough run of already-cached decisions (we've caught up
                # with the previous crawl). Only meaningful with sort=desc.
                if incremental and c.has_document(sr.document_id, source):
                    skipped_cached += 1
                    consecutive_seen += 1
                    if consecutive_seen >= stop_after_seen:
                        stopped_reason = "caught_up"
                        return
                    continue
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
                        consecutive_seen = 0  # a genuinely new full-text doc
                    except Exception as exc:
                        warnings.append(f"store {sr.document_id} failed: {exc}")
                elif doc.content_status == ContentStatus.UNAVAILABLE:
                    skipped_unavailable += 1
                else:
                    skipped_metadata += 1
            pages_scanned += 1
            page += 1
        else:
            # while condition went false (not a break/return)
            if pages_scanned >= max_pages:
                stopped_reason = "max_pages"

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
            "skipped_cached": skipped_cached,  # already in cache (incremental mode)
            "pages_scanned": pages_scanned,
            "next_page": page,  # pass as start_page to resume
            "stopped_reason": stopped_reason,  # caught_up|exhausted|max_docs|max_pages|search_error
            "incremental": incremental,
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
