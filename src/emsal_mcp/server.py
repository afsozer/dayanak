from __future__ import annotations

from .cache import Cache
from .document import controlled_draft, export_bundle as export_bundle_impl
from .models import Document
from .research import refresh_research_bundle, research_quality_dashboard, research_topic
from .safety import build_input_pack as build_input_pack_impl, citation_check
from .sources.registry import capabilities, get_source, smoke_all_sync
from .udf import probe_udf, read_udf as read_udf_impl, write_udf as write_udf_impl
from .release import archive_release, readiness_dashboard, release_notes, release_smoke as release_smoke_result


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise SystemExit("MCP extra kurulu değil. Kurulum: pip install -e .[mcp]") from exc

    mcp = FastMCP("emsal-mcp")

    @mcp.tool()
    async def search_decisions(source: str, query: str, limit: int = 10, page: int = 1) -> list[dict]:
        results = [r.model_dump(mode="json") for r in await get_source(source).search(query, limit=limit, page=page)]
        # Store search results in cache for later local search
        cache = Cache()
        cache.set(f"search:{source}:{query}:{limit}:{page}", results)
        cache.close()
        return results

    @mcp.tool()
    async def get_document(source: str, document_id: str) -> dict:
        doc = await get_source(source).get_document(document_id)
        cache = Cache()
        cache.set(f"doc:{source}:{document_id}", doc.model_dump(mode="json"))
        cache.store_document(doc)
        cache.log("get", {"source": source, "document_id": document_id})
        cache.close()
        return doc.model_dump(mode="json")

    @mcp.tool()
    def source_capabilities() -> list[dict]:
        return capabilities()

    @mcp.tool()
    def source_smoke(online: bool = False) -> dict:
        """Run per-source smoke tests. Offline by default, online opt-in."""
        results = smoke_all_sync(online=online)
        return {
            "ok": all(r.get("offline_ok", False) for r in results),
            "online_requested": online,
            "source_count": len(results),
            "sources": results,
        }

    @mcp.tool()
    def citation_safety(document: dict) -> dict:
        return citation_check(Document.model_validate(document)).model_dump(mode="json")

    @mcp.tool()
    def build_input_pack(matter: str, issue: str, documents: list[dict]) -> dict:
        docs = [Document.model_validate(d) for d in documents]
        return build_input_pack_impl(matter, issue, docs).model_dump(mode="json")

    @mcp.tool()
    def draft_document(title: str, body: str, documents: list[dict]) -> dict:
        docs = [Document.model_validate(d) for d in documents]
        return {"markdown": controlled_draft(title, body, docs)}

    @mcp.tool()
    def export_bundle(out_dir: str, matter: str, issue: str, documents: list[dict]) -> dict:
        return export_bundle_impl(out_dir, matter=matter, issue=issue, docs=[Document.model_validate(d) for d in documents])

    @mcp.tool()
    def read_udf(path: str) -> dict:
        return {"text": read_udf_impl(path), "probe": probe_udf(path)}

    @mcp.tool()
    def write_udf(text: str, out_path: str, title_centered: bool = False) -> dict:
        return {"out_path": str(write_udf_impl(text, out_path, title_centered=title_centered)), "warning": "UYAP Doküman Editörü ile manuel doğrulama gerekir."}

    @mcp.tool()
    def release_smoke() -> dict:
        return release_smoke_result()

    @mcp.tool()
    def release_dashboard() -> dict:
        return readiness_dashboard()

    @mcp.tool()
    def release_notes_tool() -> dict:
        return {"markdown": release_notes()}

    @mcp.tool()
    def release_archive(out_dir: str) -> dict:
        return archive_release(out_dir)

    # ── Cache v2 MCP tools ────────────────────────────────────────────

    @mcp.tool()
    def search_local_cache(
        query: str = "",
        source: str | None = None,
        court: str | None = None,
        chamber: str | None = None,
        date: str | None = None,
        esas_no: str | None = None,
        karar_no: str | None = None,
        document_id: str | None = None,
        content_status: str | None = None,
        draft_usable: bool | None = None,
        quote_usable: bool | None = None,
        sort: str = "relevance",
        limit: int = 20,
    ) -> list[dict]:
        """Search cached documents locally without network access.

        Supports filters: source, court, chamber, date, esas_no, karar_no,
        document_id, content_status, draft_usable, quote_usable.
        Sort options: relevance, decision_date_desc, decision_date_asc,
        fetched_at_desc, fetched_at_asc.
        Returns snippets around matching text.
        """
        cache = Cache()
        try:
            return cache.search_local(
                query=query, source=source, court=court, chamber=chamber,
                date=date, esas_no=esas_no, karar_no=karar_no,
                document_id=document_id, content_status=content_status,
                draft_usable=draft_usable, quote_usable=quote_usable,
                sort=sort, limit=limit,
            )
        finally:
            cache.close()

    @mcp.tool()
    def get_cache_stats() -> dict:
        """Return cache statistics: document counts, sources, DB size."""
        cache = Cache()
        try:
            return cache.cache_stats()
        finally:
            cache.close()

    @mcp.tool()
    def list_cached_documents(
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """List cached documents with optional source filter."""
        cache = Cache()
        try:
            return cache.list_cached_documents(source=source, limit=limit, offset=offset)
        finally:
            cache.close()

    # ── Research v0.5 MCP tools ────────────────────────────────────────

    @mcp.tool()
    def research_topic_tool(
        query: str,
        sources: list[str] | None = None,
        fetch_count: int = 5,
        filters: dict | None = None,
        output_dir: str | None = None,
    ) -> dict:
        """Search sources, fetch documents, and build a research bundle.

        Returns bundle metadata with query, sources, result_count, fetched_count,
        content_status_summary, citation_safe_count, generated_files, warnings,
        and recommended_next_steps.
        """
        return research_topic(
            query=query,
            sources=sources,
            fetch_count=fetch_count,
            filters=filters or {},
            output_dir=output_dir,
        )

    @mcp.tool()
    def refresh_research_bundle_tool(
        bundle_path: str,
        dry_run: bool = False,
    ) -> dict:
        """Re-run research from an existing bundle.json, detecting new/changed docs.

        Returns report with new_documents, changed_documents, hash_changed.
        Preserves manual notes in index.md.
        """
        return refresh_research_bundle(bundle_path, dry_run=dry_run)

    @mcp.tool()
    def research_quality_dashboard_tool(
        bundle_path: str,
    ) -> dict:
        """Compute quality metrics for a research bundle.

        Returns full_text_ratio, citation_safe_ratio, metadata_only_count,
        source_distribution, missing_metadata_count, duplicate_citation_count,
        draft_readiness_score, and recommendations.
        """
        return research_quality_dashboard(bundle_path)

    mcp.run()


if __name__ == "__main__":
    main()
