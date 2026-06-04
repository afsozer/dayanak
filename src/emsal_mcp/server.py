from __future__ import annotations

import json

# M-52: All domain imports moved inside main() for faster cold-start.
# Only stdlib (json) is imported at module level.


def main() -> None:
    """Launch the MCP server with all registered tools.

    Imports FastMCP from the mcp package and registers all tool functions.
    Exits with an error message if the MCP extra is not installed.

    This is a stdio JSON-RPC MCP server, not a CLI. When started by an MCP
    client (stdin is a pipe), it enters the protocol loop. When a human runs
    it interactively (stdin is a TTY) or passes --help/--version, it prints a
    short usage note and exits instead of emitting confusing JSON parse errors.
    """
    import sys

    from . import __version__

    argv = sys.argv[1:]
    if argv and argv[0] in {"--version", "-V", "version"}:
        print(f"emsal-mcp-server {__version__}")
        return
    if (argv and argv[0] in {"--help", "-h", "help"}) or sys.stdin.isatty():
        print(
            f"emsal-mcp-server {__version__} - stdio MCP (JSON-RPC) sunucusu\n"
            "\n"
            "Bu bir CLI degil; bir MCP istemcisi (orn. Claude Desktop) tarafindan\n"
            "stdio uzerinden baslatilmak uzere tasarlanmistir. Elle/interaktif\n"
            "calistirip Enter'a basmak JSON-RPC parse hatasi uretir (beklenen).\n"
            "\n"
            "Komut satiri arac/komutlari icin:  emsal-mcp --help\n"
            "MCP istemci yapilandirmasi icin komut:  emsal-mcp-server\n",
            file=sys.stderr,
        )
        return

    from .cache import Cache
    from .server_utils import (
        get_active_requests,
        get_error_codes,
        validate_is_dict_with_keys,
        validate_non_empty,
        validate_positive_int,
        validate_range,
        validate_tool_input,
    )
    from .citation import format_legal_citation as format_legal_citation_impl, verify_legal_citation as verify_legal_citation_impl
    from .document import controlled_draft, export_bundle as export_bundle_impl
    from .legislation import (
        format_legislation_citation as format_legislation_citation_impl,
        get_legislation_article_tree as get_legislation_article_tree_impl,
        get_legislation_document as get_legislation_document_impl,
        get_legislation_gerekce as get_legislation_gerekce_impl,
        get_legislation_source_status as get_legislation_source_status_impl,
        get_legislation_types as get_legislation_types_impl,
        search_legislation as search_legislation_impl,
        search_legislation_articles as search_legislation_articles_impl,
    )
    from .chamber import (
        chamber_timeline as chamber_timeline_impl,
        find_similar_chambers as find_similar_chambers_impl,
        get_chamber_overview as get_chamber_overview_impl,
        profile_chamber as profile_chamber_impl,
    )
    from .citation_graph import (
        build_citation_graph as build_citation_graph_impl,
        export_graph as export_graph_impl,
        find_cited_documents as find_cited_documents_impl,
        find_citing_documents as find_citing_documents_impl,
        get_citation_graph as get_citation_graph_impl,
        get_citation_graph_stats as get_citation_graph_stats_impl,
    )
    from .privacy import (
        scan_pii as scan_pii_impl,
        redact_pii as redact_pii_impl,
        audit_privacy as audit_privacy_impl,
    )
    from .pdf_extractor import (
        extract_pdf_text_from_file as extract_pdf_text_impl,
        get_pdf_toolkit_status as get_pdf_toolkit_status_impl,
        promote_pdf_to_full_text as promote_pdf_to_full_text_impl,
    )
    from .semantic import (
        build_semantic_index as build_semantic_index_impl,
        get_index_status as get_index_status_impl,
        hybrid_search as hybrid_search_impl,
        rebuild_index as rebuild_index_impl,
        semantic_search as semantic_search_impl,
        update_indexes as update_indexes_impl,
        get_index_sync_status as get_index_sync_status_impl,
    )
    from .models import Document
    from .petition import (
        build_multi_issue_pack as build_multi_issue_pack_impl,
        inspect_multi_issue_pack as inspect_multi_issue_pack_impl,
        inspect_petition_pack as inspect_petition_pack_impl,
        prepare_controlled_petition_draft as prepare_controlled_petition_draft_impl,
        prepare_drafting_input_pack as prepare_drafting_input_pack_impl,
        prepare_petition_outline as prepare_petition_outline_impl,
    )
    from .templates import (
        get_template as get_template_impl,
        list_templates as list_templates_impl,
        render_template_to_skeleton as render_template_impl,
    )
    from .draft_diff import (
        diff_drafts as diff_drafts_impl,
        get_fill_report as get_fill_report_impl,
        save_draft_version as save_draft_version_impl,
        track_placeholders as track_placeholders_impl,
    )
    from .argument import (
        build_argument_chain as build_argument_chain_impl,
        score_argument as score_argument_impl,
        get_argument_strength_report as get_argument_strength_report_impl,
    )
    from .exporter import (
        export_plain_text as export_plain_text_impl,
        export_to_format as export_to_format_impl,
        get_export_capabilities as get_export_capabilities_impl,
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
    from .release import (
        final_v1_readiness as final_v1_readiness_impl,
        generate_release_summary as generate_release_summary_impl,
        release_command_center as release_command_center_impl,
        version_bump as version_bump_impl,
    )
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise SystemExit("MCP extra kurulu değil. Kurulum: pip install -e .[mcp]") from exc

    mcp = FastMCP("emsal-mcp")

    def _attach_corpus_hint(result: dict) -> dict:
        """Runtime safety net: steer the model back to live search_decisions.

        Local search tools only search already-fetched documents. When they
        return nothing, or when the local cache is tiny, inject an explicit
        ``hint`` (and ``cache_document_count``) telling the caller to use the
        live `search_decisions` tool instead of trusting these results or
        falling back to web search.
        """
        if not isinstance(result, dict):
            return result
        try:
            c = Cache()
            try:
                corpus = c.db.execute("SELECT COUNT(*) FROM documents_v2").fetchone()[0]
            finally:
                c.close()
        except Exception:
            corpus = None
        total = result.get("total_matches", len(result.get("results") or []))
        hint = None
        if total == 0:
            hint = (
                "0 eşleşme. Bu araç YALNIZCA daha önce çekilmiş belgelerde arar, "
                "canlı kaynakta DEĞİL. Karar bulmak için search_decisions (canlı) "
                "aracını çağır; web aramasına başvurma."
            )
        elif corpus is not None and corpus < 200:
            hint = (
                f"Yerel cache yalnızca {corpus} belge içeriyor (crawler/tam derlem "
                "DEĞİL). Eksiksiz ve güncel sonuç için önce search_decisions (canlı) "
                "ile getir; bu sonuçlar yalnızca çekilmiş belgelerin yeniden sıralamasıdır."
            )
        if hint:
            result["hint"] = hint
            if corpus is not None:
                result["cache_document_count"] = corpus
        return result

    @mcp.tool()
    @validate_tool_input(query=validate_non_empty, limit=validate_positive_int)
    async def search_decisions(source: str, query: str, limit: int = 10, page: int = 1) -> list[dict]:
        """✅ PRIMARY, MANDATORY TOOL FOR ALL CASE-LAW / DECISION / MEVZUAT RESEARCH.

        For ANY question about court decisions, precedents, case law, or
        legislation you MUST call THIS tool first. It is the ONLY tool that
        retrieves real, current documents LIVE from the official source
        (online — e.g. Bedesten/Yargıtay, Mevzuat).

        HARD RULES — no exceptions, no interpretation:
        - Do NOT answer case-law questions from memory, training data, or web search.
        - Do NOT use hybrid_search / semantic_search / embedding_search /
          search_local_cache to FIND decisions — those search ONLY the small
          local cache and only RE-RANK what THIS tool has already fetched.
          They cannot discover any decision that was not fetched here first.
        - Every esas/karar number, date, and chamber you cite MUST come from a
          document returned by THIS tool and verified via get_document full text.
        - If you have not called this tool yet, you have NO case law to cite.

        Fetched results are cached so the local re-ranking tools can operate on
        them afterward within the same session.

        --- QUERY HYGIENE (CRITICAL) ---
        - Do NOT paste the user's full question into the query string. The Bedesten
          Solr engine matches tokens, not natural language. Reduce the question to
          2–5 precise legal keywords.  Good: "işçi alacağı zamanaşımı" (3 terms).
          Bad: "işçinin fazla mesai ve kıdem tazminatı konusunda zamanaşımı süresi"
          (verbatim user question, too many noise tokens).
        - Preserve Turkish diacritics exactly. The Solr index is Turkish-aware;
          stripping diacritics silently drops matches. Use "kararı" ✓ not "karari" ✗,
          "geçici iş göremezlik" ✓ not "gecici is goremezlik" ✗.

        --- BEDESTEN SOLR OPERATOR COOKBOOK ---
        The Bedesten backend runs Apache Solr with StandardQueryParser.
        You can use these operators inside the `query` string:

        +required    Prefix + forces the term to appear (MUST match).  +tazminat
        -excluded    Prefix - excludes documents containing the term.  -bölge
        "exact"      Double quotes for phrase/exact match.  "iş kazası"
        AND / OR     UPPERCASE boolean operators (lowercase and/or are treated
                     as plain terms).  tazminat AND zamanaşımı
        NOT          UPPERCASE exclusion.  tazminat NOT manevi
        (grouping)   Parentheses for sub-expressions.  (+işçi OR +memur) +tazminat
        * wildcard   Suffix wildcard (use sparingly).  tazmin*

        Worked examples (query string → what it does):
          +işçi +tazminat                    → docs with BOTH "işçi" AND "tazminat"
          "iş kazası" tazminat               → exact phrase "iş kazası" AND term "tazminat"
          (+işçi OR +memur) +tazminat -manevi → (işçi OR memur) AND tazminat, exclude "manevi"
          boşanma tazminat*                  → "boşanma" AND any word starting "tazminat"
          kıdem AND ihbar AND tazminat       → all three terms required

        Notes:
        - Solr AND is the default operator for bare terms (tazminat zamanaşımı means
          tazminat AND zamanaşımı). OR must be explicit.
        - Overly broad queries (single common term like "karar") return noise; add
          at least one specific legal-term constraint.

        Args:
            source: Source identifier (e.g. 'bedesten', 'mevzuat').
            query: Search query string (must not be empty). For best results,
                craft a short 2–5 term keyword query using the operators above.
            limit: Max results (default 10, must be positive).
            page: Page number for pagination (default 1).

        Returns:
            List of matching document dicts.
        """
        results = [r.model_dump(mode="json") for r in await get_source(source).search(query, limit=limit, page=page)]
        # Store search results in cache for later local search
        cache = Cache()
        cache.set(f"search:{source}:{query}:{limit}:{page}", results)
        cache.close()
        return results

    @mcp.tool()
    @validate_tool_input(document_id=validate_non_empty)
    async def get_document(source: str, document_id: str) -> dict:
        """Fetch a single document by ID from the given source.

        Args:
            source: Source identifier.
            document_id: Document ID (must not be empty).

        Returns:
            Document dict with all metadata and content fields.
        """
        doc = await get_source(source).get_document(document_id)
        cache = Cache()
        # M-65: merge cached provenance so standalone get has metadata
        _cached = cache.get_document(document_id, source)
        if _cached and _cached.esas_no:
            from .models import merge_search_metadata
            merge_search_metadata(doc, _cached)
        cache.set(f"doc:{source}:{document_id}", doc.model_dump(mode="json"))
        cache.store_document(doc)
        cache.log("get", {"source": source, "document_id": document_id})
        cache.close()
        return doc.model_dump(mode="json")

    @mcp.tool()
    def source_capabilities() -> list[dict]:
        """Return capability matrix for all registered sources."""
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
    @validate_tool_input(document=validate_is_dict_with_keys("document_id", "source"))
    def citation_safety(document: dict) -> dict:
        """Check citation safety of a document.

        Verifies full text availability, content status, and minimum provenance
        metadata. Returns ok=True only if the document is safe for quoting.

        Args:
            document: Document dict with document_id, source, and metadata fields.

        Returns:
            Dict with ok, quoteUsable, draftUsable, reasons, safety_state.
        """
        return citation_check(Document.model_validate(document)).model_dump(mode="json")

    @mcp.tool()
    @validate_tool_input(matter=validate_non_empty, issue=validate_non_empty)
    def build_input_pack(matter: str, issue: str, documents: list[dict]) -> dict:
        """Build a citation-safe input pack for petition drafting.

        Filters unsafe documents and builds an InputPack with stable pack_id.

        Args:
            matter: Legal matter description (must not be empty).
            issue: Legal issue description (must not be empty).
            documents: List of Document dicts to classify.

        Returns:
            Dict with matter, issue, documents, safe_citations, excluded, warnings.
        """
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
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        Filters/looks up documents ALREADY fetched via `search_decisions`. It
        cannot find any decision that was not fetched first; the cache is small
        by design (not a crawler, not a full corpus).

        HARD RULE: To find case law on ANY topic you MUST call `search_decisions`
        (live, online) first — it is the primary, mandatory entry point. Use
        this tool only to filter/inspect already-fetched results. Never
        web-search, never cite esas/karar numbers not from a fetched full-text
        document.

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

    @mcp.tool()
    def cache_vacuum() -> dict:
        """Run VACUUM to reclaim space and defragment the cache database.

        Returns dict with ok, size_before, size_after, freed_bytes.
        """
        cache = Cache()
        try:
            return cache.vacuum_cache()
        finally:
            cache.close()

    @mcp.tool()
    def cache_cleanup_orphans() -> dict:
        """Remove orphan rows from search_vectors and documents_v2_fts.

        An orphan is a row whose (document_id, source) pair doesn't exist
        in documents_v2.

        Returns dict with ok, orphans_removed, details.
        """
        cache = Cache()
        try:
            return cache.cleanup_orphans()
        finally:
            cache.close()

    @mcp.tool()
    def cache_integrity_check() -> dict:
        """Run comprehensive integrity checks on the cache database.

        Checks: SQLite PRAGMA integrity_check, orphan counts, schema version,
        content hash consistency, and table row counts.

        Returns dict with ok, checks (per-check results), warnings.
        """
        cache = Cache()
        try:
            return cache.check_integrity_full()
        finally:
            cache.close()

    @mcp.tool()
    def sync_cache(other_db_path: str) -> dict:
        """Sync documents from another cache database (multi-machine merge).

        Merges documents_v2 rows from the other database into this one.
        Conflict resolution: newest retrieved_at wins for same
        (document_id, source). If same retrieved_at, existing is kept.
        Content hashes compared — mismatches produce warnings.

        Args:
            other_db_path: Path to the other cache database file.

        Returns:
            Dict with ok, synced, skipped, conflicts, total_in_other, warnings.
        """
        cache = Cache()
        try:
            return cache.sync_cache(other_db_path)
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
        template_name: str | None = None,
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
            template_name: Optional template name for the draft skeleton.

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
            template_name=template_name,
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

    # ── Multi-Issue Petition Pack MCP tools (M-13) ──────────────────────

    @mcp.tool()
    def build_multi_issue_pack(
        matter: str,
        issues_json: str,
        documents_json: str | None = None,
        out_dir: str | None = None,
    ) -> dict:
        """Build a multi-issue petition pack with isolated citation banks.

        Each issue gets its own citation-bank.md and argument-map.md.
        Source documents are shared and deduplicated across issues.
        Hash manifest covers all documents across all issues.

        Args:
            matter: Legal matter description.
            issues_json: JSON string of issues list. Each issue has:
                - title: Issue title (required)
                - description: Issue description (optional)
                - documents: List of Document dicts (optional)
            documents_json: Optional JSON string of shared Document list.
            out_dir: Output directory for the multi-issue pack.

        Returns:
            Dict with ok, out_dir, issue_count, issues, combined counts,
            draft_safe, files, warnings, hash_manifest.
        """
        issues = json.loads(issues_json)
        docs = [Document.model_validate(d) for d in json.loads(documents_json)] if documents_json else []
        return build_multi_issue_pack_impl(
            matter=matter,
            issues=issues,
            documents=docs,
            out_dir=out_dir,
        )

    @mcp.tool()
    def inspect_multi_issue_pack(pack_dir: str) -> dict:
        """Inspect and validate a multi-issue petition pack directory.

        Checks per-issue citation banks, cross-issue citation contamination,
        hash manifest consistency, no-invention rules, and placeholder
        preservation.

        Args:
            pack_dir: Path to multi-issue petition pack directory.

        Returns:
            Dict with ok, draft_safe, errors, warnings, checks, issue_results.
        """
        return inspect_multi_issue_pack_impl(pack_dir)

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

    # ── Export Format Expansion MCP tools (M-15) ─────────────────────────

    @mcp.tool()
    def export_plain_text(draft_path: str, out_path: str | None = None) -> dict:
        """Export a draft.md to plain-text format.

        Strips markdown formatting (headers → uppercase, bold/italic → plain,
        links → text).  Preserves disclaimer header and {{PLACEHOLDER}} tokens.
        Always available — no toolkit required.

        Args:
            draft_path: Path to the draft.md file.
            out_path: Optional output .txt file path.

        Returns:
            Dict with ok, out_path, text_length, disclaimer_present,
            placeholders_preserved.
        """
        return export_plain_text_impl(draft_path=draft_path, out_path=out_path)

    @mcp.tool()
    def export_to_format(
        draft_path: str,
        format: str = "docx",
        out_path: str | None = None,
        pack_dir: str | None = None,
        experimental: bool = False,
    ) -> dict:
        """Unified export dispatcher supporting multiple formats.

        Formats:
            - docx: validated DOCX export (always available)
            - txt: plain-text export (always available)
            - pdf: PDF via LibreOffice (requires toolkit)
            - udf: UYAP UDF (requires toolkit + experimental=True)

        Returns structured error dict if toolkit is unavailable or format
        is invalid.

        Args:
            draft_path: Path to the draft.md file.
            format: Export format (docx, txt, pdf, udf).
            out_path: Optional output file path.
            pack_dir: Optional pack directory for footnotes.
            experimental: Required True for UDF format.

        Returns:
            Format-specific result dict or structured error.
        """
        return export_to_format_impl(
            draft_path=draft_path,
            format=format,
            out_path=out_path,
            pack_dir=pack_dir,
            experimental=experimental,
        )

    @mcp.tool()
    def get_export_capabilities() -> dict:
        """Report which export formats are currently available.

        Shows availability of docx, txt, pdf, udf formats based on
        toolkit presence (LibreOffice).

        Returns:
            Dict with ok, formats list, toolkit_available, toolkit_status.
        """
        return get_export_capabilities_impl()

    # ── Petition Template Library MCP tools (M-11) ─────────────────────────

    @mcp.tool()
    def list_petition_templates() -> list[dict]:
        """List all available petition templates.

        Returns a list of template summaries with name, type, title,
        section_count, and placeholder_count.
        """
        return list_templates_impl()

    @mcp.tool()
    def get_petition_template(name: str) -> dict:
        """Get a specific petition template by name.

        Returns the full template dict with name, type, title, and sections.
        Returns error dict if template not found.

        Args:
            name: Template identifier (e.g. 'dava_dilekcesi').
        """
        return get_template_impl(name)

    @mcp.tool()
    def render_template_skeleton(name: str) -> dict:
        """Render a petition template as a draft-skeleton.md compatible markdown.

        Output includes DISCLAIMER_HEADER and uses the {{PLACEHOLDER}} convention.
        Placeholders are preserved for manual filling.

        Args:
            name: Template identifier (e.g. 'dava_dilekcesi').
        """
        try:
            md = render_template_impl(name)
            return {"ok": True, "name": name, "markdown": md}
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}

    # ── Draft Diff & Versioning MCP tools (M-14) ──────────────────────────

    @mcp.tool()
    def diff_drafts(draft_a: str, draft_b: str) -> dict:
        """Compare two draft files and report changes.

        Computes unified diff, identifies added/removed/modified sections,
        and reports placeholder fill status changes.

        Args:
            draft_a: Path to the first (older) draft file.
            draft_b: Path to the second (newer) draft file.

        Returns:
            Dict with ok, draft_a, draft_b, diff_lines, changes, unified_diff,
            sections_added, sections_removed, placeholders_filled, warnings.
        """
        return diff_drafts_impl(draft_a, draft_b)

    @mcp.tool()
    def track_placeholders(draft_path: str) -> dict:
        """Analyze a draft for placeholder fill status.

        Finds all {{PLACEHOLDER}} patterns and reports which are filled
        (no longer present as raw tokens) vs unfilled.

        Args:
            draft_path: Path to the draft file.

        Returns:
            Dict with ok, total_placeholders, filled, unfused, fill_ratio,
            placeholders, unfilled_list, ready_for_submission, warnings.
        """
        return track_placeholders_impl(draft_path)

    @mcp.tool()
    def get_fill_report(draft_path: str, pack_dir: str | None = None) -> dict:
        """Generate a fill report for a draft.

        Lists unfilled placeholders with section context, suggests
        citation-safe sources from the pack, and provides readiness assessment.

        Args:
            draft_path: Path to the draft file.
            pack_dir: Optional petition pack directory for source suggestions.

        Returns:
            Dict with ok, total_placeholders, filled, unfilled, fill_ratio,
            readiness, items, suggestions, warnings.
        """
        return get_fill_report_impl(draft_path, pack_dir=pack_dir)

    @mcp.tool()
    def save_draft_version(draft_dir: str, version_label: str | None = None) -> dict:
        """Save a snapshot of current draft state for later diff.

        Copies draft files to a versioned subdirectory with metadata.

        Args:
            draft_dir: Directory containing draft files.
            version_label: Optional human-readable label for this version.

        Returns:
            Dict with ok, version_id, version_label, version_dir,
            files_copied, metadata_path, warnings.
        """
        return save_draft_version_impl(draft_dir, version_label=version_label)

    # ── Argument Builder v0.12 MCP tools ──────────────────────────────────

    @mcp.tool()
    def build_argument_chain(pack_dir: str) -> dict:
        """Build structured argument chains from a petition pack.

        Reads argument-map.md and petition-pack.json, produces claim ->
        supporting authority -> counter-argument chains.  Only petition_ready
        authorities appear in supporting_authorities (citation-safe).

        Safety invariants enforced:
        - No metadata_only leak into supporting_authorities
        - No fabrication: missing support produces warning
        - All cited documents pass citation_check

        Args:
            pack_dir: Path to petition pack directory.

        Returns:
            Dict with ok, pack_dir, arguments, overall_strength, warnings.
        """
        return build_argument_chain_impl(pack_dir=pack_dir)

    @mcp.tool()
    def score_argument(
        claim_text: str,
        document_json: dict | None = None,
    ) -> dict:
        """Score how well an argument is supported by authorities.

        Computes a 0.0-1.0 score based on: count of supporting documents,
        content availability, citation safety.

        Args:
            claim_text: The legal claim/argument text.
            document_json: Optional authority dict with document_id, source,
                title, content_status fields.

        Returns:
            Dict with ok, score, factors, supporting_count, warnings.
        """
        authorities = []
        if document_json:
            authorities = [document_json]
        return score_argument_impl(
            claim_text=claim_text,
            authorities=authorities,
        )

    @mcp.tool()
    def get_argument_strength_report(pack_dir: str) -> dict:
        """Generate overall argument strength report for a petition pack.

        Aggregates individual argument scores into a comprehensive report
        with strength distribution and recommendations.

        Args:
            pack_dir: Path to petition pack directory.

        Returns:
            Dict with ok, overall_strength, argument_count,
            classification_distribution, strength_distribution,
            recommendations, warnings.
        """
        return get_argument_strength_report_impl(pack_dir=pack_dir)

    # ── Legislation v0.10 MCP tools ──────────────────────────────────────

    @mcp.tool()
    def search_legislation(
        query: str,
        sources: list[str] | None = None,
        legislation_type: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Search legislation via the Mevzuat source.

        Args:
            query: Search phrase.
            sources: Source IDs (default: ["mevzuat"]).
            legislation_type: Filter by type (e.g. "Kanun", "Yönetmelik").
            limit: Max results.

        Returns:
            Dict with ok, query, results, total_results, warnings, etc.
        """
        return search_legislation_impl(
            query=query,
            sources=sources,
            legislation_type=legislation_type,
            limit=limit,
        )

    @mcp.tool()
    def get_legislation_document(
        document_id: str,
        source: str | None = None,
    ) -> dict:
        """Get a full legislation document from the Mevzuat source.

        Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").

        Returns:
            Dict with ok, title, citation_check, article_count, etc.
        """
        return get_legislation_document_impl(
            document_id=document_id,
            source=source,
        )

    @mcp.tool()
    def search_legislation_articles(
        document_id: str,
        article_number: str | None = None,
        article_query: str | None = None,
        source: str | None = None,
    ) -> dict:
        """Search articles within a legislation document.

        Args:
            document_id: Mevzuat document ID.
            article_number: Optional specific article number.
            article_query: Optional keyword search in article text.
            source: Source ID (default: "mevzuat").

        Returns:
            Dict with ok, matching_articles, total_articles_found, etc.
        """
        return search_legislation_articles_impl(
            document_id=document_id,
            article_number=article_number,
            article_query=article_query,
            source=source,
        )

    @mcp.tool()
    def get_legislation_article_tree(
        document_id: str,
        source: str | None = None,
    ) -> dict:
        """Build part/section/article hierarchy from legislation document.

        Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").

        Returns:
            Dict with ok, article_count, part_count, section_count, tree, etc.
        """
        return get_legislation_article_tree_impl(
            document_id=document_id,
            source=source,
        )

    @mcp.tool()
    def get_legislation_gerekce(
        document_id: str,
        source: str | None = None,
    ) -> dict:
        """Extract GENEL GEREKCE and MADDE GEREKCELERI from legislation.

        Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").

        Returns:
            Dict with ok, found, genel_gerekce, madde_gerekceleri, etc.
        """
        return get_legislation_gerekce_impl(
            document_id=document_id,
            source=source,
        )

    @mcp.tool()
    def legislation_source_status() -> dict:
        """Check Mevzuat source health via smoke tests.

        Returns:
            Dict with ok, overall_ok, healthy_sources, degraded_sources, etc.
        """
        return get_legislation_source_status_impl()

    @mcp.tool()
    def format_legislation_citation(
        document: dict | None = None,
        style: str = "full",
    ) -> dict:
        """Format a legislation citation from document metadata.

        Args:
            document: Document dict with title, legislation_no, gazette_date.
            style: 'full', 'short', or 'article'.

        Returns:
            Dict with formatted_citation, style, warnings, etc.
        """
        return format_legislation_citation_impl(
            document=document or {},
            style=style,  # type: ignore[arg-type]
        )

    @mcp.tool()
    def get_legislation_types() -> list[dict]:
        """Return known Turkish legislation types.

        Returns:
            List of {type_id, display_name} dicts.
        """
        return get_legislation_types_impl()

    # ── Semantic v0.11 MCP tools ──────────────────────────────────────────

    @mcp.tool()
    def build_semantic_index(
        force_rebuild: bool = False,
    ) -> dict:
        """Build FTS5 + TF-IDF search indices on cached documents.

        Creates SQLite FTS5 virtual table and TF-IDF vectors for hybrid search.
        Run this after importing or caching documents.

        Args:
            force_rebuild: If True, drop and recreate all indices.

        Returns:
            Dict with ok, fts5_row_count, vectors_count, documents_total, warnings.
        """
        return build_semantic_index_impl(force_rebuild=force_rebuild)

    @mcp.tool()
    def semantic_search(
        query: str,
        limit: int = 10,
        filters: dict | None = None,
    ) -> dict:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        This ONLY re-ranks documents ALREADY fetched via `search_decisions`.
        It cannot find any decision that was not fetched first; the local cache
        is small by design (not a crawler, not a full corpus).

        HARD RULE: To find case law on ANY topic you MUST call `search_decisions`
        (live, online) first — it is the primary, mandatory entry point. Use
        this tool only to re-rank already-fetched results. Never web-search,
        never cite esas/karar numbers not from a fetched full-text document.

        Pure term-frequency (TF-IDF cosine) search over the cache.
        Works best with documents that share vocabulary.
        Uses Turkish suffix stripping for query expansion — stemmed
        variants of query terms are generated automatically.

        Snippets include **highlighted** matching terms.

        Args:
            query: Search query string.
            limit: Max results (default 10).
            filters: Optional dict with source, court, chamber, content_status,
                     quote_usable, draft_usable.

        Returns:
            Dict with ok, query, results (score + snippet), total_matches, method,
            expanded_query_terms, snippet_highlighted.
        """
        return _attach_corpus_hint(semantic_search_impl(
            query=query, limit=limit, filters=filters,
        ))

    @mcp.tool()
    @validate_tool_input(limit=validate_positive_int, hybrid_weight=validate_range(0.0, 1.0))
    def hybrid_search(
        query: str,
        limit: int = 10,
        filters: dict | None = None,
        hybrid_weight: float = 0.6,
        rerank: bool = False,
    ) -> dict:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        This ONLY re-ranks documents ALREADY fetched via `search_decisions`.
        It is a re-ranker over an existing local result set, NOT a way to find
        case law. It CANNOT discover any decision that was not fetched first,
        and the local cache is small by design (this is NOT a crawler and NOT a
        corpus of all decisions — it holds only what you fetched this session).

        HARD RULES — no exceptions, no interpretation:
        - To find decisions on ANY topic you MUST call `search_decisions`
          (live, online). That is THE primary, mandatory entry point.
        - Use this tool ONLY to refine/re-rank results AFTER `search_decisions`
          has fetched documents in the same session.
        - "Empty/limited results here" means "you have not fetched yet" — go
          call `search_decisions`. It does NOT mean no case law exists.
        - NEVER substitute web search for `search_decisions`. NEVER cite an
          esas/karar number, date, or chamber not coming from a fetched
          full-text document.

        Balances exact keyword matching (FTS5 BM25) with semantic similarity
        (TF-IDF cosine).  hybrid_weight controls the balance: higher = more
        keyword-oriented, lower = more semantic.

        Uses Turkish suffix stripping for query expansion — stemmed
        variants of query terms are generated automatically for FTS5.
        Snippets include **highlighted** matching terms.

        hybrid_weight must be between 0.0 and 1.0.

        Args:
            query: Search query string.
            limit: Max results (default 10).
            filters: Optional dict with source, court, chamber, content_status,
                     quote_usable, draft_usable.
            hybrid_weight: Balance 0.0-1.0 (0.0 = pure semantic, 1.0 = pure BM25).
            rerank: Cross-encoder reranking of top results (optional, requires fastembed).

        Returns:
            Dict with ok, query, results (bm25/cosine/hybrid scores + snippet),
            total_matches, method, hybrid_weight, reranked, expanded_query_terms,
            snippet_highlighted.
        """
        return _attach_corpus_hint(hybrid_search_impl(
            query=query, limit=limit, filters=filters,
            hybrid_weight=hybrid_weight,
            rerank=rerank,
        ))

    @mcp.tool()
    def index_status() -> dict:
        """Check FTS5 + TF-IDF index health and statistics.

        Returns:
            Dict with ok, fts5_exists, fts5_document_count, vectors_count,
            total_cached_documents, unindexed_documents, warnings.
        """
        return get_index_status_impl()

    @mcp.tool()
    def rebuild_search_index() -> dict:
        """Force rebuild of FTS5 and TF-IDF search indices.

        Drops and recreates all search indices from cached documents.

        Returns:
            Dict with ok, fts5_row_count, vectors_count, documents_total.
        """
        return rebuild_index_impl()

    # ── Dense Embedding v2.1 MCP tools (M-24) ──────────────────────────

    @mcp.tool()
    def build_embedding_index(
        provider: str | None = None,
        force_rebuild: bool = False,
    ) -> dict:
        """Build dense embedding index from cached documents.

        Uses the configured embedding provider (default: local-hash-v1).
        Skips documents whose content_hash hasn't changed unless
        force_rebuild=True.

        Args:
            provider: Optional provider ID (local-hash-v1, fastembed-minilm-l6-v2).
            force_rebuild: If True, re-embed all documents.

        Returns:
            Dict with ok, documents_indexed, skipped, provider, dimensions.
        """
        from .semantic import build_embedding_index as _build_emb

        return _build_emb(provider=provider, force_rebuild=force_rebuild)

    @mcp.tool()
    def embedding_search(
        query: str,
        limit: int = 10,
        provider: str | None = None,
    ) -> dict:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        Dense-embedding re-ranking over documents ALREADY fetched via
        `search_decisions`. Cannot find decisions that were not fetched first;
        the local index is small by design (not a crawler, not a full corpus).

        HARD RULE: To find case law on ANY topic you MUST call `search_decisions`
        (live, online) first — it is the primary, mandatory entry point. Use
        this tool only to re-rank already-fetched results. Never web-search,
        never cite esas/karar numbers not from a fetched full-text document.

        Uses brute-force cosine similarity over indexed embeddings.
        No approximate nearest-neighbor (ANN) — exact but slower for large
        corpora.

        Args:
            query: Search query string.
            limit: Max results (default 10).
            provider: Optional provider ID.

        Returns:
            Dict with ok, results (scored), total_matches, method, provider.
        """
        from .semantic import embedding_search as _emb_search

        return _attach_corpus_hint(_emb_search(query=query, limit=limit, provider=provider))

    @mcp.tool()
    def embedding_index_status() -> dict:
        """Check dense embedding index status.

        Returns per-provider vector counts and dimensions.

        Returns:
            Dict with ok, providers list, version.
        """
        from .semantic import get_embedding_index_status as _emb_status

        return _emb_status()

    @mcp.tool()
    def list_embedding_providers() -> list[dict]:
        """List available embedding providers and their status.

        Returns:
            List of provider metadata dicts with id, dimensions, label,
            status, is_default, needs_download.
        """
        from .embeddings import list_embedding_providers as _list_emb

        return _list_emb()

    @mcp.tool()
    def update_indexes(provider: str | None = None) -> dict:
        """Incrementally update both TF-IDF and dense indexes.

        Only processes documents that are new or have changed content.
        Uses content_hash comparison to skip unchanged documents.
        After update, cleans orphan vectors.

        Args:
            provider: Optional embedding provider for dense index updates.

        Returns:
            Dict with ok, tfidf_updated, dense_updated, skipped, warnings.
        """
        return update_indexes_impl(provider=provider)

    @mcp.tool()
    def index_sync_status() -> dict:
        """Report how many documents are out of sync with indexes.

        Compares total documents with text content against indexed
        counts in TF-IDF and dense embedding stores.

        Returns:
            Dict with ok, total_documents, tfidf_indexed, dense_indexed,
            tfidf_out_of_sync, dense_out_of_sync.
        """
        return get_index_sync_status_impl()

    # ── Chamber Profiling v0.12 MCP tools ──────────────────────────────────

    @mcp.tool()
    def chamber_overview(
        court: str | None = None,
    ) -> dict:
        """Overview of all chambers with document counts and date ranges.

        Reads from cached documents.  GROUP BY court + chamber.

        Args:
            court: Optional court name filter (e.g. 'Yargitay').

        Returns:
            Dict with ok, total_chambers, total_documents, chambers list
            (each with document_count, content_available_count, date range).
        """
        return get_chamber_overview_impl(court=court)

    @mcp.tool()
    def profile_chamber(
        chamber: str,
        court: str | None = None,
    ) -> dict:
        """Detailed profile of a specific court chamber.

        Computes document counts, content status distribution, top keywords,
        usability flags, and recent documents.

        Args:
            chamber: Chamber name (e.g. '3. Hukuk Dairesi').
            court: Optional court name filter.

        Returns:
            Dict with ok, metrics, top_keywords, recent_documents.
        """
        return profile_chamber_impl(chamber=chamber, court=court)

    @mcp.tool()
    def chamber_timeline(
        chamber: str | None = None,
        court: str | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict:
        """Decision timeline grouped by year for a chamber.

        Args:
            chamber: Optional chamber name filter.
            court: Optional court name filter.
            start_year: Optional start year (inclusive).
            end_year: Optional end year (inclusive).

        Returns:
            Dict with ok, timeline (list of {year, count}), year_range.
        """
        return chamber_timeline_impl(
            chamber=chamber, court=court,
            start_year=start_year, end_year=end_year,
        )

    @mcp.tool()
    def find_similar_chambers(
        chamber: str,
        court: str | None = None,
        limit: int = 5,
    ) -> dict:
        """Find chambers with similar topic profiles via keyword overlap.

        Uses Jaccard similarity on top keywords extracted from decision titles.

        Args:
            chamber: Target chamber name.
            court: Optional court filter.
            limit: Max results (default 5).

        Returns:
            Dict with ok, similar_chambers (each with similarity_score,
            shared_keywords, document_count).
        """
        return find_similar_chambers_impl(
            chamber=chamber, court=court, limit=limit,
        )

    # ── Citation Graph v0.14 MCP tools ────────────────────────────────────

    @mcp.tool()
    def build_citation_graph(limit_docs: int = 100) -> dict:
        """Build citation graph from cached documents.

        Extracts court decision references, matches against cached documents,
        and stores verified edges.  Never fabricates — only detectable,
        verifiable references are graphed.

        Args:
            limit_docs: Maximum documents to process.

        Returns:
            Dict with ok, edges_created, docs_processed, citations_found,
            matches_found, confidence_distribution, warnings.
        """
        return build_citation_graph_impl(limit_docs=limit_docs)

    @mcp.tool()
    def get_citation_graph(
        document_id: str,
        source: str,
        direction: str = "both",
        max_depth: int = 1,
    ) -> dict:
        """Get citation relationships for a document.

        Args:
            document_id: The document ID.
            source: The source identifier.
            direction: 'citing' (docs that cite this), 'cited' (docs this cites),
                       or 'both'.
            max_depth: Traversal depth (1 = direct only).

        Returns:
            Dict with ok, document, citing, cited_by, total_edges.
        """
        return get_citation_graph_impl(
            document_id=document_id,
            source=source,
            direction=direction,
            max_depth=max_depth,
        )

    @mcp.tool()
    def find_citing_documents(
        document_id: str,
        source: str,
        limit: int = 20,
    ) -> dict:
        """Find documents that cite the given document.

        Args:
            document_id: The cited document ID.
            source: The cited document source.
            limit: Maximum results.

        Returns:
            Dict with ok, document, citing_documents list.
        """
        return find_citing_documents_impl(
            document_id=document_id,
            source=source,
            limit=limit,
        )

    @mcp.tool()
    def find_cited_documents(
        document_id: str,
        source: str,
        limit: int = 20,
    ) -> dict:
        """Find documents that the given document cites.

        Args:
            document_id: The citing document ID.
            source: The citing document source.
            limit: Maximum results.

        Returns:
            Dict with ok, document, cited_documents list.
        """
        return find_cited_documents_impl(
            document_id=document_id,
            source=source,
            limit=limit,
        )

    @mcp.tool()
    def citation_graph_stats() -> dict:
        """Get citation graph statistics.

        Returns:
            Dict with ok, total_edges, total_docs_with_citations,
            most_cited_docs, avg_citations_per_doc, confidence_distribution.
        """
        return get_citation_graph_stats_impl()

    @mcp.tool()
    def export_citation_graph(
        format: str = "json",
        document_id: str | None = None,
        source: str | None = None,
        max_depth: int = 2,
    ) -> dict:
        """Export citation graph in various formats.

        Args:
            format: Export format — 'json' (node-link), 'dot' (Graphviz),
                    or 'mermaid' (Mermaid diagram).
            document_id: Optional document_id to export sub-graph centered on this doc.
            source: Optional source filter for sub-graph.
            max_depth: For sub-graph, max traversal hops (default 2).

        Returns:
            Dict with ok, format, export_text, node_count, edge_count.
        """
        return export_graph_impl(
            format=format,
            document_id=document_id,
            source=source,
            max_depth=max_depth,
        )

    # ── Dedup v0.15 MCP tools ─────────────────────────────────────────────

    @mcp.tool()
    def find_duplicates(dry_run: bool = False) -> dict:
        """Find duplicate documents across sources (same court+esas_no+karar_no).

        Groups documents by matching court, esas_no, and karar_no.
        Only documents with non-empty esas_no AND karar_no are considered.
        Never false-merges: strict matching only.

        Args:
            dry_run: If True, compute plan without modifying DB.

        Returns:
            Dict with ok, clusters_found, total_duplicates, dry_run, clusters.
        """
        from .dedup import find_duplicates as find_duplicates_impl
        cache = Cache()
        try:
            return find_duplicates_impl(cache=cache, dry_run=dry_run)
        finally:
            cache.close()

    @mcp.tool()
    def get_dedup_cluster(document_id: str, source: str) -> dict:
        """Find which dedup cluster a document belongs to.

        Args:
            document_id: Document ID to look up.
            source: Source identifier.

        Returns:
            Dict with ok, in_cluster, cluster_id, canonical, all_members.
        """
        from .dedup import get_dedup_cluster as get_dedup_cluster_impl
        cache = Cache()
        try:
            return get_dedup_cluster_impl(document_id=document_id, source=source, cache=cache)
        finally:
            cache.close()

    @mcp.tool()
    def dedup_stats() -> dict:
        """Get deduplication statistics.

        Returns:
            Dict with ok, total_clusters, total_duplicate_docs,
            space_saved_estimate, sources_most_duplicates.
        """
        from .dedup import get_dedup_stats as get_dedup_stats_impl
        cache = Cache()
        try:
            return get_dedup_stats_impl(cache=cache)
        finally:
            cache.close()

    @mcp.tool()
    def merge_dedup_cluster(cluster_id: str) -> dict:
        """Merge a dedup cluster: enrich canonical record with alt source URLs.

        Adds alternative source URLs from non-canonical members to the
        canonical document's metadata without overwriting existing fields.

        Args:
            cluster_id: The dedup cluster ID to merge.

        Returns:
            Dict with ok, cluster_id, canonical, enriched_fields, members_merged.
        """
        from .dedup import merge_cluster as merge_cluster_impl
        cache = Cache()
        try:
            return merge_cluster_impl(cluster_id=cluster_id, cache=cache)
        finally:
            cache.close()

    @mcp.tool()
    def find_fuzzy_duplicates(
        provider: str | None = None,
        threshold: float = 0.85,
        max_date_diff_days: int = 365,
    ) -> dict:
        """Find near-duplicate documents using dense embedding similarity.

        Reports suspected_duplicate pairs based on embedding cosine similarity
        within the same court. Never auto-merges — all merges require explicit
        confirmation. Requires embedding vectors from build_embedding_index().

        Args:
            provider: Embedding provider (default: from config).
            threshold: Cosine similarity threshold (0.0-1.0, default 0.85).
            max_date_diff_days: Max date difference in days (default 365).

        Returns:
            Dict with ok, suspected_duplicates, total_suspected, warnings.
        """
        from .dedup import find_fuzzy_duplicates as find_fuzzy_duplicates_impl
        cache = Cache()
        try:
            return find_fuzzy_duplicates_impl(
                cache=cache, provider=provider,
                cosine_threshold=threshold, max_date_diff_days=max_date_diff_days,
            )
        finally:
            cache.close()

    @mcp.tool()
    def fuzzy_dedup_stats() -> dict:
        """Report fuzzy dedup readiness.

        Shows embedding availability for near-duplicate detection.

        Returns:
            Dict with ok, embedded_documents, providers, ready flag.
        """
        from .dedup import get_fuzzy_dedup_stats as get_fuzzy_dedup_stats_impl
        cache = Cache()
        try:
            return get_fuzzy_dedup_stats_impl(cache=cache)
        finally:
            cache.close()

    # ── Release v0.13 MCP tools ──────────────────────────────────────────

    @mcp.tool()
    def release_command_center() -> dict:
        """Comprehensive release verification running ALL checks.

        Runs source smoke, cache integrity, module imports, FTS5 index status,
        chamber overview, and UDF toolkit status.  Aggregates into a single
        readiness report.

        Returns:
            Dict with ok, overall_readiness (0-100), checks detail, warnings,
            recommended_actions.
        """
        return release_command_center_impl()

    @mcp.tool()
    def version_bump(
        major: bool = False,
        minor: bool = False,
        patch: bool = True,
    ) -> dict:
        """Compute a bumped version string (does NOT modify files).

        Args:
            major: Bump major version.
            minor: Bump minor version.
            patch: Bump patch version (default).

        Returns:
            Dict with current_version, next_version, bump_type.
        """
        return version_bump_impl(major=major, minor=minor, patch=patch)

    @mcp.tool()
    def final_v1_readiness() -> dict:
        """Final v1.0.0 readiness gate.

        Checks all criteria needed for v1 release: module imports, stable
        sources, smoke tests, and no blocking issues.

        Returns:
            Dict with ok, ready, criteria, blocking_issues, recommendation.
        """
        return final_v1_readiness_impl()

    @mcp.tool()
    def generate_release_summary() -> dict:
        """Generate a human-readable release summary.

        Includes version, module inventory, source status, document counts,
        and readiness assessment.  Returns both markdown and JSON formats.

        Returns:
            Dict with ok, markdown_summary, json_summary, version.
        """
        return generate_release_summary_impl()

    # ── Search Analytics v0.16 MCP tools ────────────────────────────────

    @mcp.tool()
    def search_analytics(days: int = 30) -> dict:
        """Comprehensive search analytics: success rate, empty queries, source distribution, cache hit ratio.

        All metrics are deterministic and derived from cache data.

        Args:
            days: Number of days to include (default 30).

        Returns:
            Dict with ok, total_searches, empty_result_rate, avg_result_count,
            cache_hit_rate, top_queries, empty_queries, source_distribution,
            daily_activity.
        """
        from .search_analytics import get_search_analytics

        cache = Cache()
        try:
            return get_search_analytics(cache=cache, days=days)
        finally:
            cache.close()

    @mcp.tool()
    def get_empty_queries(limit: int = 20) -> dict:
        """List queries that returned 0 results.

        Args:
            limit: Max results (default 20).

        Returns:
            Dict with ok and empty_queries list.
        """
        from .search_analytics import get_empty_queries as get_empty_queries_impl

        cache = Cache()
        try:
            return get_empty_queries_impl(cache=cache, limit=limit)
        finally:
            cache.close()

    @mcp.tool()
    def get_top_queries(limit: int = 20) -> dict:
        """Most frequent queries.

        Args:
            limit: Max results (default 20).

        Returns:
            Dict with ok and top_queries list.
        """
        from .search_analytics import get_top_queries as get_top_queries_impl

        cache = Cache()
        try:
            return get_top_queries_impl(cache=cache, limit=limit)
        finally:
            cache.close()

    @mcp.tool()
    def get_source_coverage() -> dict:
        """Source coverage: doc counts and full_text percentage.

        Returns:
            Dict with ok and coverage list.
        """
        from .search_analytics import get_source_coverage as get_source_coverage_impl

        cache = Cache()
        try:
            return get_source_coverage_impl(cache=cache)
        finally:
            cache.close()

    # ── Capability Router MCP tools (M-19) ──────────────────────────────

    @mcp.tool()
    def get_capable_sources(capability: str) -> list[str]:
        """Get list of source_ids that support a given capability.

        Args:
            capability: Capability name (e.g. 'full_text', 'search', 'pdf_link',
                       'article_search', 'type_filter', 'workflow').

        Returns:
            List of source_ids sorted by preference (stable sources first).
        """
        from .router import get_capable_sources as get_capable_sources_impl

        return get_capable_sources_impl(capability)

    @mcp.tool()
    def route_search(
        query: str,
        required_capabilities: list[str] | None = None,
        preferred_sources: list[str] | None = None,
        exclude_sources: list[str] | None = None,
    ) -> dict:
        """Route a search request to capable sources based on capability matrix.

        Returns routing metadata with eligible sources, exclusions, and
        per-source capability match info. Does NOT execute searches.

        Args:
            query: Search query string.
            required_capabilities: List of capabilities needed (e.g. ['full_text']).
            preferred_sources: Try these sources first.
            exclude_sources: Skip these sources (e.g. ['rekabet']).

        Returns:
            Dict with ok, query, routing (eligible_sources, excluded_sources),
            results (empty), per_source capability match info.
        """
        from .router import route_search as route_search_impl

        return route_search_impl(
            query=query,
            required_capabilities=required_capabilities,
            preferred_sources=preferred_sources,
            exclude_sources=exclude_sources,
        )

    @mcp.tool()
    def route_get_document(
        document_id: str,
        required_capabilities: list[str] | None = None,
        preferred_source: str | None = None,
    ) -> dict:
        """Route a get_document request to capable sources.

        Tries preferred source first, then falls back to other capable sources.

        Args:
            document_id: Document ID to look up.
            required_capabilities: List of capabilities needed.
            preferred_source: Try this source first.

        Returns:
            Dict with ok, document_id, routing (eligible_sources), results (empty).
        """
        from .router import route_get_document as route_get_document_impl

        return route_get_document_impl(
            document_id=document_id,
            required_capabilities=required_capabilities,
            preferred_source=preferred_source,
        )

    # ── Circuit Breaker MCP tools (M-17) ──────────────────────────────

    @mcp.tool()
    def circuit_breaker_status(source: str | None = None) -> dict:
        """Check circuit breaker status for one or all sources.

        Args:
            source: Optional source_id filter.

        Returns:
            Dict with ok, state, failure_count, consecutive_failures,
            circuit_open, uptime_pct (per source).
        """
        from .circuit import get_source_health as get_source_health_impl, get_all_sources_health as get_all_sources_health_impl

        if source:
            return get_source_health_impl(source)
        return get_all_sources_health_impl()

    @mcp.tool()
    def source_health(source: str | None = None) -> dict:
        """Get source health metrics (uptime, failure counts, circuit state).

        Args:
            source: Optional source_id filter.

        Returns:
            Dict with ok, source_id, state, success_count, failure_count,
            uptime_pct, circuit_open.
        """
        from .circuit import get_source_health as get_source_health_impl, get_all_sources_health as get_all_sources_health_impl

        if source:
            return get_source_health_impl(source)
        return get_all_sources_health_impl()

    @mcp.tool()
    def reset_circuit(source: str) -> dict:
        """Manually reset a circuit breaker to CLOSED state.

        Args:
            source: Source identifier to reset.

        Returns:
            Dict with ok, source_id, state, previous_state.
        """
        from .circuit import reset_circuit as reset_circuit_impl

        return reset_circuit_impl(source)

    # ── Server Hardening MCP tools (M-22) ───────────────────────────

    @mcp.tool()
    def error_catalog() -> dict:
        """Return all known error codes used in build_error() calls.

        Useful for integration tests and error-code validation.

        Returns:
            Dict with ok, known_codes list, total count.
        """
        catalog = get_error_codes()
        return {"ok": True, **catalog}

    @mcp.tool()
    def active_requests_count() -> dict:
        """Return the number of currently active MCP tool requests.

        Informational counter — single-user design assumption preserved.

        Returns:
            Dict with ok, active_requests, note.
        """
        return {
            "ok": True,
            "active_requests": get_active_requests(),
            "note": "Informational counter. Single-user design: no concurrency locks.",
        }

    # ── PDF Extraction MCP tools (M-27) ──────────────────────────────────

    @mcp.tool()
    def extract_pdf_text(file_path: str, ocr_enabled: bool = False) -> dict:
        """Extract text layer from a PDF file.

        Uses pypdf for text-layer extraction. OCR is opt-in only.
        Never modifies the original file.

        Args:
            file_path: Path to the PDF file.
            ocr_enabled: Enable OCR extraction (opt-in, produces low confidence warning).

        Returns:
            Dict with ok, text, text_length, method, warnings.
        """
        return extract_pdf_text_impl(file_path, ocr_enabled=ocr_enabled)

    @mcp.tool()
    def pdf_toolkit_status() -> dict:
        """Check PDF extraction toolkit availability.

        Reports which PDF tools (pypdf, pytesseract, pdf2image, pillow)
        are installed and available.

        Returns:
            Dict with ok, available_tools, unavailable_tools.
        """
        return get_pdf_toolkit_status_impl()

    @mcp.tool()
    def promote_pdf_to_full_text(
        document: dict,
        ocr_enabled: bool = False,
    ) -> dict:
        """Try to promote a pdf_only Document to full_text.

        For local files, use extract_pdf_text directly. This tool
        handles the promotion workflow for documents with source_url.

        Args:
            document: Document dict with content_status, source_url, etc.
            ocr_enabled: Enable OCR extraction (opt-in).

        Returns:
            Dict with ok, promoted, method, warnings, document.
        """
        return promote_pdf_to_full_text_impl(document, ocr_enabled=ocr_enabled)

    # ── Research Watchlist v2.4 MCP tools (M-36) ─────────────────────

    @mcp.tool()
    def watch_add(
        name: str,
        query: str,
        sources: list[str] | None = None,
        fetch_count: int = 5,
        interval_hours: int = 24,
    ) -> dict:
        """Register a watch for periodic research.

        Args:
            name: Unique watch name (used as key).
            query: Research query string.
            sources: Optional list of source_ids to search.
            fetch_count: Max documents per search (default 5).
            interval_hours: Suggested interval in hours (default 24).

        Returns:
            Dict with ok, name, config.
        """
        from .research_watch import add_watch as add_watch_impl
        return add_watch_impl(
            name=name, query=query, sources=sources,
            fetch_count=fetch_count, interval_hours=interval_hours,
        )

    @mcp.tool()
    def watch_list() -> dict:
        """List all registered watches.

        Returns:
            Dict with ok, watches list, total.
        """
        from .research_watch import list_watches as list_watches_impl
        return list_watches_impl()

    @mcp.tool()
    def watch_run(name: str) -> dict:
        """Execute a watch: re-search, detect new/changed docs, produce diff report.

        Args:
            name: Watch name to execute.

        Returns:
            Dict with ok, name, result, diff_report.
        """
        from .research_watch import run_watch as run_watch_impl
        return run_watch_impl(name)

    @mcp.tool()
    def watch_remove(name: str) -> dict:
        """Remove a watch.

        Args:
            name: Watch name to remove.

        Returns:
            Dict with ok, name, removed.
        """
        from .research_watch import remove_watch as remove_watch_impl
        return remove_watch_impl(name)

    # ── Privacy / PII MCP tools (M-37) ────────────────────────────────

    @mcp.tool()
    def privacy_scan(text: str) -> dict:
        """Scan text for potential PII (TCKN, phone, email).

        Detects Turkish national ID numbers (TCKN), phone numbers, and
        email addresses. Returns findings with confidence levels.

        Args:
            text: Input text to scan for PII.

        Returns:
            Dict with ok, findings_count, findings list, risk_level.
        """
        return scan_pii_impl(text)

    @mcp.tool()
    def privacy_redact(text: str) -> dict:
        """Redact PII from text. Returns a copy — original is unchanged.

        Replaces detected TCKN, phone, and email patterns with
        [TCKN_REDACTED], [PHONE_REDACTED], [EMAIL_REDACTED] tokens.

        Args:
            text: Input text to redact PII from.

        Returns:
            Dict with ok, redacted_text, original_length, redactions_applied.
        """
        return redact_pii_impl(text)

    @mcp.tool()
    def privacy_audit(path: str) -> dict:
        """Audit a file or directory for PII presence.

        Scans .md, .txt, .json, .docx files for potential PII.
        Returns per-file findings and overall risk assessment.

        Args:
            path: File or directory path to audit.

        Returns:
            Dict with ok, files_scanned, files_with_pii, findings, warning.
        """
        return audit_privacy_impl(path)

    # ── Eval v4.0 M-71 tool ──────────────────────────────────────────────

    @mcp.tool()
    def run_evaluation(golden_path: str | None = None, k: int = 5) -> dict:
        """Run retrieval evaluation harness against golden query set.

        Uses recall@k and nDCG@k metrics.  Returns per-query scores and
        aggregate metrics.

        Args:
            golden_path: Optional path to golden_queries.json (default: eval/golden_queries.json).
            k: Cutoff rank (default 5).

        Returns:
            Dict with ok, query_count, metrics (recall_at_k, ndcg_at_k, pass_rate),
            per_query details.
        """
        from .eval_metrics import evaluate_search
        from .semantic import hybrid_search
        return evaluate_search(search_fn=hybrid_search, golden_path=golden_path, k_default=k)

    # ── RRF M-69 tool ────────────────────────────────────────────────────

    @mcp.tool()
    def hybrid_search_rrf(
        query: str,
        limit: int = 10,
        filters: dict | None = None,
        include_dense: bool = False,
    ) -> dict:
        """⛔ NOT A RESEARCH TOOL. LOCAL CACHE ONLY — NEVER QUERIES ANY SOURCE.

        Re-ranks documents ALREADY fetched via `search_decisions` using
        Reciprocal Rank Fusion. Cannot find decisions that were not fetched
        first; the local cache is small by design (not a crawler, not a full
        corpus).

        HARD RULE: To find case law on ANY topic you MUST call `search_decisions`
        (live, online) first — it is the primary, mandatory entry point. Use
        this tool only to re-rank already-fetched results. Never web-search,
        never cite esas/karar numbers not from a fetched full-text document.

        RRF merges BM25, TF-IDF, and optionally dense embedding results
        by rank position only — no score normalization required.

        Args:
            query: Search query.
            limit: Max results (default 10).
            filters: Optional dict with source, court, chamber, content_status.
            include_dense: Whether to include dense embeddings (needs built index).

        Returns:
            Dict with ok, results (with rrf_score), method="rrf".
        """
        from .semantic import hybrid_search_rrf as _hybrid_search_rrf
        return _attach_corpus_hint(_hybrid_search_rrf(
            query=query, limit=limit, filters=filters, include_dense=include_dense,
        ))

    # ── Query understanding M-70 tools ────────────────────────────────────

    @mcp.tool()
    def normalize_law_ref(query: str) -> dict:
        """Normalize law abbreviations to full references.

        Example: 'İYUK 11' → '2577 (İdari Yargılama Usulü Kanunu) m.11'
        Uses deterministic hardcoded mappings — no fabrication.

        Args:
            query: Text containing law abbreviation references.

        Returns:
            Dict with normalized_query and replacements list.
        """
        from .query_understanding import normalize_law_ref as _norm_law
        return _norm_law(query)

    @mcp.tool()
    def expand_query_terms(query: str) -> dict:
        """Expand query with legal synonyms from curated dictionary.

        Args:
            query: Query text to expand.

        Returns:
            Dict with expanded_query and added_terms.
        """
        from .query_understanding import expand_query_terms as _expand
        return _expand(query)

    @mcp.tool()
    def extract_query_filters(query: str) -> dict:
        """Extract court/chamber filters from query text.

        Args:
            query: Query text to analyze.

        Returns:
            Dict with filters dict and confidence level.
        """
        from .query_understanding import extract_query_filters as _extract
        return _extract(query)

    mcp.run()


if __name__ == "__main__":
    main()
