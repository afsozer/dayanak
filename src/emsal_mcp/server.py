from __future__ import annotations

from .cache import Cache
from .citation import format_legal_citation as format_legal_citation_impl, verify_legal_citation as verify_legal_citation_impl
from .document import controlled_draft, export_bundle as export_bundle_impl
from .models import Document
from .petition import (
    inspect_petition_pack as inspect_petition_pack_impl,
    prepare_controlled_petition_draft as prepare_controlled_petition_draft_impl,
    prepare_drafting_input_pack as prepare_drafting_input_pack_impl,
    prepare_petition_outline as prepare_petition_outline_impl,
)
from .exporter import (
    prepare_docx_export as prepare_docx_export_impl,
    prepare_export_package_bundle as prepare_export_package_bundle_impl,
)
from .research import refresh_research_bundle, research_quality_dashboard, research_topic
from .safety import build_input_pack as build_input_pack_impl, citation_check
from .sources.registry import capabilities, get_source, smoke_all_sync
from .udf import (
    convert_docx_to_udf_experimental,
    convert_udf_to_docx,
    convert_udf_to_pdf,
    get_udf_authoring_instructions,
    get_udf_toolkit_status,
    probe_udf,
    read_udf as read_udf_impl,
    write_udf as write_udf_impl,
)
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
    def udf_toolkit_status() -> dict:
        """Check UDF toolkit (LibreOffice/unoconv) availability."""
        return get_udf_toolkit_status()

    @mcp.tool()
    def udf_authoring_instructions(format: str = "json") -> dict:
        """Return UDF authoring instructions and warnings.

        Args:
            format: 'json' for structured dict, 'markdown' for human-readable text.
        """
        return get_udf_authoring_instructions(format=format)

    @mcp.tool()
    def convert_udf_to_docx_tool(file_path: str, out_path: str | None = None) -> dict:
        """Convert UDF to DOCX using LibreOffice (requires toolkit).

        Returns structured error dict if toolkit is unavailable.
        """
        return convert_udf_to_docx(file_path, out_path)

    @mcp.tool()
    def convert_udf_to_pdf_tool(file_path: str, out_path: str | None = None) -> dict:
        """Convert UDF to PDF using LibreOffice (requires toolkit).

        Returns structured error dict if toolkit is unavailable.
        """
        return convert_udf_to_pdf(file_path, out_path)

    @mcp.tool()
    def convert_docx_to_udf_experimental_tool(
        file_path: str, out_path: str | None = None, experimental: bool = False,
    ) -> dict:
        """Convert DOCX to UDF (experimental, requires toolkit).

        Must set experimental=True. Always returns UYAP manual round-trip warning.
        """
        return convert_docx_to_udf_experimental(file_path, out_path, experimental=experimental)

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

    # ── Citation v0.6 MCP tools ──────────────────────────────────────────

    @mcp.tool()
    def format_legal_citation(
        source: dict | None = None,
        document_id: str | None = None,
        style: str = "petition",
    ) -> dict:
        """Format a legal citation from document metadata.

        Args:
            source: Document dict with metadata fields.
            document_id: Document ID to look up from cache.
            style: 'petition', 'parenthetical', or 'short'.

        Returns:
            Dict with formatted_citation, warnings, confidence, usability flags.
        """
        return format_legal_citation_impl(
            source=source,
            document_id=document_id,
            style=style,  # type: ignore[arg-type]
        )

    @mcp.tool()
    def verify_legal_citation(
        text: str | None = None,
        file_path: str | None = None,
        source: str | None = None,
        limit: int = 5,
        fetch: int = 3,
        no_live: bool = True,
        live_only: bool = False,
        min_score: float = 1.0,
    ) -> dict:
        """Verify legal citations in text or file.

        Pipeline: extract candidates → search local cache → live search →
        rank by metadata match score → return structured result.

        Args:
            text: Text content to verify.
            file_path: Path to file to read.
            source: Filter to specific source.
            limit: Max candidates to extract.
            fetch: Max docs to fetch.
            no_live: Skip live search.
            live_only: Skip local cache search.
            min_score: Minimum match score threshold.

        Returns:
            Dict with candidates, matched_documents, formatted_citations,
            verification_findings, warnings, recommended_next_steps.
        """
        return verify_legal_citation_impl(
            text=text,
            file_path=file_path,
            source=source,
            limit=limit,
            fetch=fetch,
            no_live=no_live,
            live_only=live_only,
            min_score=min_score,
        )

    # ── Petition Pack v0.7 MCP tools ────────────────────────────────────────

    @mcp.tool()
    def prepare_drafting_input_pack(
        matter: str,
        issue: str,
        documents: list[dict] | None = None,
        research_bundle_dir: str | None = None,
        out_dir: str | None = None,
        strict: bool = True,
    ) -> dict:
        """Prepare a petition drafting input pack.

        Classifies authorities as petition_ready, citation_only,
        research_lead_only, or excluded.  Generates a structured pack
        directory with petition-brief.json, citation-bank.md, argument-map.md,
        petition-instructions.md, draft-skeleton.md, petition-pack.json,
        and source-documents/*.md.

        Args:
            matter: Legal matter description.
            issue: Legal issue description.
            documents: Optional list of Document dicts to classify.
            research_bundle_dir: Optional research bundle directory path.
            out_dir: Output directory for the pack.
            strict: If True, exclude hash-mismatch docs.

        Returns:
            Dict with ok, out_dir, draft_safe, counts, classifications,
            files, warnings, hash_manifest.
        """
        docs = [Document.model_validate(d) for d in (documents or [])]
        return prepare_drafting_input_pack_impl(
            matter=matter,
            issue=issue,
            documents=docs,
            research_bundle_dir=research_bundle_dir,
            out_dir=out_dir,
            strict=strict,
        )

    @mcp.tool()
    def inspect_petition_pack(pack_dir: str) -> dict:
        """Inspect and validate a petition pack directory.

        Checks required files, draft_safe flag, classification counts,
        placeholder presence, no-invention rule, citation bank safety,
        and hash manifest validity.

        Args:
            pack_dir: Path to petition pack directory.

        Returns:
            Dict with ok, draft_safe, errors, warnings, counts, checks.
        """
        return inspect_petition_pack_impl(pack_dir)

    # ── Petition v0.8 MCP tools ──────────────────────────────────────────

    @mcp.tool()
    def prepare_petition_outline(
        pack_dir: str,
        out_dir: str | None = None,
    ) -> dict:
        """Generate a structured petition outline from a petition pack.

        Reads petition-pack.json and produces an outline.json with sections,
        placeholders, and authority classification for each section.
        Only petition_ready authorities may supply direct content;
        citation_only appear only in bibliography with warning.

        Args:
            pack_dir: Path to petition pack directory.
            out_dir: Output directory for outline.json.

        Returns:
            Dict with ok, outline_path, sections, placeholder_total,
            citation_only_bibliography_count, petition_ready_count.
        """
        return prepare_petition_outline_impl(pack_dir=pack_dir, out_dir=out_dir)

    @mcp.tool()
    def prepare_controlled_petition_draft(
        pack_dir: str,
        outline_path: str | None = None,
        out_dir: str | None = None,
    ) -> dict:
        """Generate a controlled petition draft from a petition pack.

        Produces draft.md, draft.json, footnotes.json, and warnings.json.
        Only petition_ready authorities supply direct quotes; citation_only
        appear in bibliography warnings only.  Placeholders are preserved.

        Args:
            pack_dir: Path to petition pack directory.
            outline_path: Optional pre-computed outline.json.
            out_dir: Output directory for draft files.

        Returns:
            Dict with ok, out_dir, draft_md_path, draft_json_path,
            footnotes_path, warnings_path, draft_metadata.
        """
        return prepare_controlled_petition_draft_impl(
            pack_dir=pack_dir, outline_path=outline_path, out_dir=out_dir,
        )

    @mcp.tool()
    def prepare_docx_export(
        draft_path: str | None = None,
        draft_json: dict | None = None,
        out_path: str | None = None,
        pack_dir: str | None = None,
    ) -> dict:
        """Create a validated DOCX export from a controlled draft.

        Accepts draft.md path or draft.json dict.  Creates DOCX with
        disclaimer, footnotes, and placeholder preservation.

        Args:
            draft_path: Path to draft.md.
            draft_json: Draft metadata dict (with files.draft_md reference).
            out_path: Output DOCX path.
            pack_dir: Pack directory for footnotes.

        Returns:
            Dict with checksum_sha256, file_size, validation dict.
        """
        return prepare_docx_export_impl(
            draft_path=draft_path,
            draft_json=draft_json,
            out_path=out_path,
            pack_dir=pack_dir,
        )

    @mcp.tool()
    def prepare_export_package_bundle(
        pack_dir: str,
        draft_dir: str | None = None,
        docx_path: str | None = None,
        out_dir: str | None = None,
    ) -> dict:
        """Create a complete export package bundle with verification.

        Bundles draft files, petition pack, source documents, manifest,
        hash-manifest, and verification.txt.  Verifies integrity after
        creation.

        Args:
            pack_dir: Path to petition pack directory.
            draft_dir: Draft output directory.
            docx_path: Path to draft.docx.
            out_dir: Output bundle directory.

        Returns:
            Dict with ok, bundle_dir, manifest, hash_manifest,
            verification, files, post_verification.
        """
        return prepare_export_package_bundle_impl(
            pack_dir=pack_dir, draft_dir=draft_dir,
            docx_path=docx_path, out_dir=out_dir,
        )

    mcp.run()


if __name__ == "__main__":
    main()
