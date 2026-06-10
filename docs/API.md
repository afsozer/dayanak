# Emsal-mcp API Reference

Auto-generated from module docstrings.

---

## `argument`

### `def build_argument_chain(pack_dir: str | Path, cache: Any | None) -> dict[str, Any]`

Build structured argument chains from a petition pack.

    Reads ``petition-pack.json`` and ``argument-map.md`` from *pack_dir*
        and produces a list of argument chains with:
    
        - ``claim`` — the legal claim/argument derived from the authority map
        - ``supporting_authorities`` — **only** petition_ready docs (citation-safe)
        - ``research_leads`` — research_lead_only docs for further investigation
        - ``counter_argument`` — empty placeholder for attorney to fill
        - ``strength`` — 0.0–1.0 score based on supporting evidence
        - ``warnings`` — non-fatal issues (e.g. no support found)
    
        Safety invariants enforced:
        - **No metadata_only leak**: only petition_ready in supporting_authorities
        - **No fabrication**: missing support → warning, never invent connections
        - **Citation-safe**: all cited docs pass citation_check
    
        Args:
            pack_dir: Path to a petition pack directory (from v0.7+).
            cache: Optional Cache instance for history logging.
    
        Returns:
            Dict with ok, pack_dir, arguments, overall_strength, warnings.

---

### `def score_argument(claim_text: str, authorities: list[dict[str, Any]], cache: Any | None) -> dict[str, Any]`

Score how well an argument is supported by authorities.

    Scoring criteria (0.0–1.0):
        - Count of supporting petition_ready documents (higher = better)
        - Content availability (full_text > metadata_only)
        - Quote usability (quote_usable flag)
        - Keyword overlap between claim and authority text
    
        Args:
            claim_text: The legal claim/argument text.
            authorities: List of authority dicts (must be petition_ready only).
            cache: Optional Cache instance.
    
        Returns:
            Dict with ok, score, factors, supporting_count, warnings.

---

### `def get_argument_strength_report(pack_dir: str | Path, cache: Any | None) -> dict[str, Any]`

Generate an overall argument strength report for a petition pack.

    Calls ``build_argument_chain`` internally and computes aggregate metrics.
    
        Args:
            pack_dir: Path to petition pack directory.
            cache: Optional Cache instance.
    
        Returns:
            Dict with ok, overall_strength, argument_count, classification_distribution,
            strength_distribution, recommendations, warnings.

---

### `def render_arguments_to_markdown(pack_dir: str | Path, out_path: str | Path | None) -> str`

Render argument chains as a readable markdown document.

    Args:
            pack_dir: Path to petition pack directory.
            out_path: Optional output file path.  If None, only returns the
                markdown string without writing to disk.
    
        Returns:
            Markdown string of rendered arguments.

---

## `benchmark`

### `def run_benchmarks() -> dict[str, Any]`

Run the full benchmark suite.

    Args:
            corpus_size: Number of synthetic documents to create.
            repetitions: Number of times to repeat each benchmark (only first run timed).
    
        Returns:
            Dict with ok, benchmarks (per-test timings), summary.

---

## `calibrate`

### `def calibrate_source(source_id: str) -> dict[str, Any]`

Measure safe request rate for a source by issuing test calls.

    Sends sample_requests test calls with delay_between seconds between
        them.  Measures observed latency and suggests a safe rate.
    
        Args:
            source_id: Source identifier (e.g. 'bedesten', 'yargitay').
            sample_requests: Number of test requests to send.
            delay_between: Seconds between requests (be polite).
            online: If True, make actual HTTP calls.  Default False (smoke-only).
    
        Returns:
            Dict with ok, source_id, latencies_ms, avg_ms, recommended_rps,
            suggested_config, warnings.

---

### `def calibrate_all() -> dict[str, Any]`

Run calibration on all registered sources.

    Args:
            online: Whether to make actual HTTP calls.
    
        Returns:
            Dict with ok, results per source, summary.

---

## `chamber`

### `def get_chamber_overview(court: str | None, cache: Cache | None) -> dict[str, Any]`

Overview of all chambers with statistics.

    Args:
            court: Optional court name filter.
            cache: Optional Cache instance for DB injection.
    
        Returns:
            Dict with ok, court_filter, total_chambers, total_documents, chambers list,
            warnings, recommended_next_steps, version.

---

### `def profile_chamber(chamber: str, court: str | None, cache: Cache | None) -> dict[str, Any]`

Detailed profile of a specific chamber.

    Args:
            chamber: Chamber name to profile.
            court: Optional court name filter.
            cache: Optional Cache instance for DB injection.
    
        Returns:
            Dict with ok, chamber, court_filter, metrics, top_keywords, recent_documents,
            warnings, recommended_next_steps, version.

---

### `def chamber_timeline(chamber: str | None, court: str | None, start_year: int | None, end_year: int | None, cache: Cache | None) -> dict[str, Any]`

Decision timeline grouped by year.

    Args:
            chamber: Optional chamber filter.
            court: Optional court filter.
            start_year: Optional start year (inclusive).
            end_year: Optional end year (inclusive).
            cache: Optional Cache instance for DB injection.
    
        Returns:
            Dict with ok, chamber_filter, court_filter, year_range, total_documents,
            timeline, warnings, version.

---

### `def find_similar_chambers(chamber: str, court: str | None, limit: int, cache: Cache | None) -> dict[str, Any]`

Find chambers with similar topic profiles based on keyword overlap.

    Uses Jaccard similarity on top keyword sets extracted from document titles.
    
        Args:
            chamber: Target chamber name.
            court: Optional court filter (applied to target chamber lookup).
            limit: Maximum similar chambers to return.
            cache: Optional Cache instance for DB injection.
    
        Returns:
            Dict with ok, target_chamber, similar_chambers, warnings,
            recommended_next_steps, version.

---

## `circuit`

### `def record_success(source_id: str, cache: Any) -> None`

Record a successful call for *source_id*.

    - Increments success_count.
        - Resets consecutive_failures to 0.
        - If state was HALF_OPEN, transitions to CLOSED.

---

### `def record_failure(source_id: str, cache: Any) -> None`

Record a failed call for *source_id*.

    - Increments failure_count and consecutive_failures.
        - If consecutive_failures >= threshold while CLOSED, transitions to OPEN.
        - If state was HALF_OPEN, transitions back to OPEN.

---

### `def is_circuit_open(source_id: str, cache: Any, threshold: int | None, recovery_timeout: int | None) -> bool`

Check if the circuit breaker for *source_id* is blocking calls.

    - If OPEN and recovery_timeout has elapsed -> transition to HALF_OPEN, return False (allow one try).
        - If OPEN and still within timeout -> return True (block).
        - If CLOSED or HALF_OPEN -> return False (allow).
    
        Args:
            source_id: Source identifier.
            cache: Optional Cache instance (created if None).
            threshold: Override default threshold (for testing).
            recovery_timeout: Override default recovery timeout in seconds (for testing).

---

### `def get_source_health(source_id: str, cache: Any) -> dict[str, Any]`

Return health metrics for a source.

    Returns dict with:
            ok, source_id, state, failure_count, success_count,
            last_failure_at, last_success_at, consecutive_failures,
            uptime_pct, circuit_open.

---

### `def get_all_sources_health(cache: Any) -> dict[str, Any]`

Return health for all registered sources.

    Returns dict with ok=True and sources dict keyed by source_id.

---

### `def reset_circuit(source_id: str, cache: Any) -> dict[str, Any]`

Manually reset a circuit breaker to CLOSED state.

    Returns dict with ok, source_id, state, previous_state.

---

## `citation`

### `def extract_citation_candidates(text: str) -> list[CitationCandidate]`

Extract citation candidates from text using regex patterns.

    Scans the text for Turkish legal citation patterns and returns
        candidates ranked by field completeness.  Never fabricates missing
        metadata; missing fields produce warnings and lower confidence.
    
        Args:
            text: Input text to scan for citations.
            limit: Maximum number of candidates to return.
    
        Returns:
            List of CitationCandidate objects, sorted by confidence (descending).

---

### `def format_legal_citation(source: dict[str, Any] | Document | None) -> dict[str, Any]`

Format a legal citation from document metadata.

    Uses only existing metadata; never fabricates date/chamber/esas/karar.
        Missing fields produce warnings and lower confidence.
    
        Args:
            source: Document dict, Document model, or None (look up by document_id).
            document_id: Document ID to look up if source is None.
            style: Formatting style — 'petition', 'parenthetical', or 'short'.
            refetch: If True, attempt to re-fetch from source.
            cache: Optional Cache instance for lookups.
            source_client: Optional source client for re-fetching.
    
        Returns:
            Dict with formatted_citation, warnings, confidence, quote_usable,
            draft_usable, content_status, source_url, metadata fields.

---

### `def verify_legal_citation(text: str | None) -> dict[str, Any]`

Verify legal citations found in text or file.

    Pipeline: load text → extract candidates → search local cache (unless
        live_only) → live search (unless no_live) → rank by metadata match score →
        optionally fetch docs → return structured result.
    
        Args:
            text: Text content to verify.  Mutually exclusive with file_path.
            file_path: Path to file to read.  Mutually exclusive with text.
            source: Filter cache/live search to a specific source.
            limit: Max candidates to extract.
            fetch: Max documents to fetch for top candidates.
            no_live: Skip live search (cache-only mode).
            live_only: Skip local cache search.
            min_score: Minimum match score threshold.
            strategy_debug: Include extraction/search strategy details.
            cache: Optional Cache instance.
            sources_override: Optional dict mapping source_id to fake client.
    
        Returns:
            Dict with candidates, search_attempts, matched_documents,
            formatted_citations, verification_findings, warnings,
            recommended_next_steps, timing.

---

## `citation_graph`

### `def build_citation_graph(cache: Cache | None, sources_override: dict[str, Any] | None, limit_docs: int) -> dict[str, Any]`

Build the citation graph by extracting references from cached documents.

    1. Select up to ``limit_docs`` documents with full_text or markdown.
        2. Extract citation candidates from each document.
        3. Search local cache for matching documents.
        4. Insert verified edges into ``citation_edges`` table.
    
        Args:
            cache: Optional Cache instance (creates one if None).
            sources_override: Unused; kept for interface compatibility.
            limit_docs: Maximum documents to process.
    
        Returns:
            Dict with ok, edges_created, docs_processed, citations_found,
            matches_found, confidence_distribution, warnings.

---

### `def get_citation_graph(document_id: str, source: str, cache: Cache | None, direction: str, max_depth: int) -> dict[str, Any]`

Get citation relationships for a document.

    Args:
            document_id: The document ID.
            source: The source identifier.
            cache: Optional Cache instance.
            direction: 'citing' (docs that cite this), 'cited' (docs this cites),
                       or 'both'.
            max_depth: Traversal depth (1 = direct only).
    
        Returns:
            Dict with ok, document, citing, cited_by, total_edges.

---

### `def find_citing_documents(document_id: str, source: str, cache: Cache | None, limit: int) -> dict[str, Any]`

Find documents that cite the given document.

    Args:
            document_id: The cited document ID.
            source: The cited document source.
            cache: Optional Cache instance.
            limit: Maximum results.
    
        Returns:
            Dict with ok, document, citing_documents list.

---

### `def find_cited_documents(document_id: str, source: str, cache: Cache | None, limit: int) -> dict[str, Any]`

Find documents that the given document cites.

    Args:
            document_id: The citing document ID.
            source: The citing document source.
            cache: Optional Cache instance.
            limit: Maximum results.
    
        Returns:
            Dict with ok, document, cited_documents list.

---

### `def get_citation_graph_stats(cache: Cache | None) -> dict[str, Any]`

Get statistics about the citation graph.

    Args:
            cache: Optional Cache instance.
    
        Returns:
            Dict with ok, total_edges, total_docs_with_citations,
            most_cited_docs, avg_citations_per_doc.

---

### `def export_graph(format: str, cache: Cache | None, document_id: str | None, source: str | None, max_depth: int) -> dict[str, Any]`

Export citation graph in various formats.

    Args:
            format: 'json' (node-link), 'dot' (Graphviz), 'mermaid'.
            cache: Optional Cache instance.
            document_id: Optional — if provided, export sub-graph centered on this doc.
            source: Optional source filter for sub-graph.
            max_depth: For sub-graph, how many hops.
    
        Returns:
            Dict with ok, format, export_text, node_count, edge_count.

---

## `cli`

### `def version()`

Print the current emsal-mcp version.

---

### `def doctor(json_out: bool)`

Run environment diagnostics: Python, cache, sources, UDF toolkit.

---

### `def sources(json_out: bool)`

List registered data sources and their capabilities.

---

### `def sources_smoke(offline: bool, online: bool, json_out: bool)`

Run per-source smoke tests (offline by default, online opt-in).

---

### `def search(source: str, query: str, limit: int, page: int, json_out: bool)`

Search court decisions from a given source.

---

### `def get(source: str, document_id: str, json_out: bool)`

Fetch a single document by ID from the given source.

---

### `def citation_check_cmd(source: str, document_id: str, json_out: bool)`

Check citation safety of a document from the given source.

---

### `def build_pack(matter: str, issue: str, docs_json: Path, json_out: bool)`

Build a citation-safe input pack from a JSON document list.

---

### `def draft_document(title: str, body_file: Path, docs_json: Optional[Path], out: Optional[Path])`

Generate a citation-safe markdown draft document.

---

### `def export_docx(markdown_file: Path, out: Path)`

Export a markdown file to DOCX format.

---

### `def bundle(matter: str, issue: str, docs_json: Path, out_dir: Path, json_out: bool)`

Export a citation-safe bundle with input pack and source documents.

---

### `def smoke(offline: bool, json_out: bool)`

Run release smoke tests (offline by default).

---

### `def cache_stats(cache_path: Optional[Path])`

Show cache statistics (document counts, sizes, sources).

---

### `def cache_list(source: Optional[str], limit: int, offset: int, cache_path: Optional[Path])`

List cached documents.

---

### `def cache_search_local(query: str, source: Optional[str], court: Optional[str], chamber: Optional[str], date: Optional[str], esas_no: Optional[str], karar_no: Optional[str], document_id: Optional[str], content_status: Optional[str], draft_usable: Optional[bool], quote_usable: Optional[bool], sort: str, limit: int, cache_path: Optional[Path])`

Search cached documents locally (no network).

---

### `def cache_delete(document_id: str, source: str, cache_path: Optional[Path])`

Delete a cached document (explicit, destructive).

---

### `def cache_prune(max_age_days: int, cache_path: Optional[Path])`

Prune old search cache entries.

---

### `def cache_backup(backup_path: Path, cache_path: Optional[Path])`

Backup the cache database.

---

### `def cache_export(export_path: Path, cache_path: Optional[Path])`

Export cached documents to JSON.

---

### `def cache_import(import_path: Path, cache_path: Optional[Path])`

Import cached documents from JSON.

---

### `def cache_compact(cache_path: Optional[Path], json_out: bool)`

Run VACUUM to reclaim space and defragment the cache database.

---

### `def cache_cleanup_orphans(cache_path: Optional[Path], json_out: bool)`

Remove orphan rows from search_vectors and documents_v2_fts.

---

### `def cache_integrity_check(cache_path: Optional[Path], json_out: bool)`

Run comprehensive integrity checks on the cache database.

---

### `def cache_sync(other_db: Path, cache_path: Optional[Path], json_out: bool)`

Sync documents from another cache database (multi-machine merge).

---

### `def cache_find_duplicates(dry_run: bool, cache_path: Optional[Path], json_out: bool)`

Find duplicate documents across sources (same court+esas_no+karar_no).

---

### `def cache_dedup_cluster(document_id: str, source: str, cache_path: Optional[Path], json_out: bool)`

Find which dedup cluster a document belongs to.

---

### `def cache_dedup_stats(cache_path: Optional[Path], json_out: bool)`

Show deduplication statistics.

---

### `def cache_merge_cluster(cluster_id: str, cache_path: Optional[Path], json_out: bool)`

Merge a dedup cluster: enrich canonical record with alternative source URLs.

---

### `def cache_fuzzy_duplicates(provider: Optional[str], threshold: float, max_date_diff_days: int, cache_path: Optional[Path], json_out: bool)`

Find fuzzy duplicate candidates using dense embeddings.

    Reports suspected_duplicate pairs — NEVER auto-merges.
        Uses embedding vectors (M-24). Requires build_embedding_index() first.

---

### `def cache_fuzzy_dedup_stats(cache_path: Optional[Path], json_out: bool)`

Report fuzzy dedup readiness and embedding availability.

---

### `def release_dashboard(json_out: bool)`

Show release readiness dashboard.

---

### `def release_history(out_dir: Path, json_out: bool)`

Write release history record to output directory.

---

### `def release_compare(left: Path, right: Path, json_out: bool)`

Compare two release history records and report score delta.

---

### `def release_notes_cmd(out: Optional[Path])`

Generate markdown release notes.

---

### `def release_archive(out_dir: Path, json_out: bool)`

Create a release archive with dashboard, notes, and history.

---

### `def release_cmd_center(json_out: bool)`

Comprehensive release verification - all checks.

---

### `def release_version_bump(major: bool, minor: bool, patch: bool, json_out: bool)`

Compute next version (does NOT modify files).

---

### `def release_v1_readiness(json_out: bool)`

Final v1.0.0 readiness gate.

---

### `def release_summary(json_out: bool)`

Human-readable release summary.

---

### `def udf_probe(path: Path, json_out: bool)`

Probe a UDF file for structure and content metadata.

---

### `def udf_read(path: Path)`

Read and print text content from a UDF file.

---

### `def udf_md(path: Path, out: Optional[Path])`

Convert a UDF file to markdown format.

---

### `def udf_write(text_file: Path, out: Path, title_centered: bool)`

Write a UYAP UDF file from a text file.

---

### `def udf_status(json_out: bool)`

Show UDF toolkit availability status.

---

### `def udf_authoring_instructions(format: str, json_out: bool)`

Show UDF authoring instructions and warnings.

---

### `def udf_to_docx_cmd(path: Path, out_path: Optional[Path], json_out: bool)`

Convert UDF to DOCX (requires toolkit).

---

### `def udf_to_pdf_cmd(path: Path, out_path: Optional[Path], json_out: bool)`

Convert UDF to PDF (requires toolkit).

---

### `def udf_docx_to_udf_cmd(path: Path, out_path: Optional[Path], experimental: bool, json_out: bool)`

Convert DOCX to UDF (experimental, requires toolkit).

---

### `def research_topic_cmd(query: str, sources: Optional[str], fetch_count: int, output_dir: Optional[Path], json_out: bool)`

Search sources, fetch documents, build research bundle.

---

### `def research_refresh_cmd(bundle_path: Path, dry_run: bool, json_out: bool)`

Re-run research from an existing bundle, detect new/changed documents.

---

### `def research_dashboard_cmd(bundle_path: Path, json_out: bool)`

Compute quality metrics for a research bundle.

---

### `def cite_format(document_id: str, source: str, style: str, json_out: bool)`

Format a legal citation from cached document metadata.

---

### `def cite_verify(text: str, file_path: Path, source: str, limit: int, fetch: int, no_live: bool, min_score: float, strategy_debug: bool, json_out: bool)`

Verify legal citations in text or file.

---

### `def petition_pack(matter: str, issue: str, docs_json: Optional[Path], research_bundle: Optional[Path], out_dir: Optional[Path], strict: bool, template: Optional[str], json_out: bool)`

Prepare a petition drafting input pack.

---

### `def petition_inspect(pack_dir: Path, json_out: bool)`

Inspect and validate a petition pack directory.

---

### `def petition_outline(pack_dir: Path, out_dir: Optional[Path], json_out: bool)`

Generate a structured petition outline from a pack.

---

### `def petition_draft(pack_dir: Path, outline_path: Optional[Path], out_dir: Optional[Path], json_out: bool)`

Generate a controlled petition draft from a pack.

---

### `def petition_export_docx(draft_path: Optional[Path], draft_json_path: Optional[Path], out_path: Optional[Path], pack_dir: Optional[Path], json_out: bool)`

Create a validated DOCX export from a controlled draft.

---

### `def petition_export_bundle(pack_dir: Path, draft_dir: Optional[Path], docx_path: Optional[Path], out_dir: Optional[Path], json_out: bool)`

Create a complete export package bundle with verification.

---

### `def petition_multi_pack(matter: str, issues_json: Path, docs_json: Optional[Path], out_dir: Optional[Path], json_out: bool)`

Build a multi-issue petition pack with isolated citation banks.

---

### `def petition_multi_inspect(pack_dir: Path, json_out: bool)`

Inspect and validate a multi-issue petition pack directory.

---

### `def argument_build(pack_dir: Path, json_out: bool)`

Build structured argument chains from a petition pack.

---

### `def argument_score(pack_dir: Path, json_out: bool)`

Score argument strength for a petition pack.

---

### `def argument_render(pack_dir: Path, out_path: Optional[Path], json_out: bool)`

Render argument chains as markdown.

---

### `def legislation_search(query: str, legislation_type: Optional[str], limit: int, json_out: bool)`

Mevzuat ara.

---

### `def legislation_get(document_id: str, source: Optional[str], json_out: bool)`

Mevzuat belgesi getir.

---

### `def legislation_articles(document_id: str, article_number: Optional[str], article_query: Optional[str], source: Optional[str], json_out: bool)`

Belge içinde madde ara.

---

### `def legislation_tree(document_id: str, source: Optional[str], json_out: bool)`

Belgenin kısım/bölüm/madde ağacını çıkar.

---

### `def legislation_gerekce(document_id: str, source: Optional[str], json_out: bool)`

Genel gerekçe ve madde gerekçelerini çıkar.

---

### `def legislation_status(json_out: bool)`

Mevzuat kaynak sağlık durumu.

---

### `def legislation_types(json_out: bool)`

Bilinen mevzuat türlerini listele.

---

### `def legislation_format(title: str, legislation_no: str, gazette_date: str, style: str, json_out: bool)`

Mevzuat atıf formatla.

---

### `def semantic_index(force_rebuild: bool, json_out: bool)`

Build FTS5 + TF-IDF search indices.

---

### `def semantic_search_cmd(query: str, limit: int, source: Optional[str], court: Optional[str], chamber: Optional[str], json_out: bool)`

TF-IDF cosine similarity search. Supports --source, --court, --chamber filters.

---

### `def semantic_hybrid(query: str, limit: int, weight: float, w_dense: float, rerank: bool, source: Optional[str], court: Optional[str], chamber: Optional[str], json_out: bool)`

FTS5 BM25 + TF-IDF cosine hybrid search with optional dense embeddings.

---

### `def semantic_status(json_out: bool)`

Check index health and statistics.

---

### `def semantic_rebuild(json_out: bool)`

Force rebuild all search indices.

---

### `def semantic_embed_index(provider: Optional[str], force_rebuild: bool, json_out: bool)`

Build dense embedding index.

---

### `def semantic_embed_search(query: str, provider: Optional[str], limit: int, json_out: bool)`

Dense embedding similarity search.

---

### `def semantic_providers(json_out: bool)`

List available embedding providers.

---

### `def semantic_embedding_status(json_out: bool)`

Check dense embedding index status.

---

### `def semantic_update_indexes(provider: Optional[str], json_out: bool)`

Incrementally update indexes (new/changed docs only).

---

### `def semantic_sync_status(json_out: bool)`

Check index sync status.

---

### `def chamber_overview(court: Optional[str], json_out: bool)`

Chamber overview with document counts and date ranges.

---

### `def chamber_profile(chamber: str, court: Optional[str], json_out: bool)`

Detailed profile of a specific chamber.

---

### `def chamber_timeline_cmd(chamber: Optional[str], court: Optional[str], start_year: Optional[int], end_year: Optional[int], json_out: bool)`

Decision timeline grouped by year.

---

### `def chamber_similar(chamber: str, court: Optional[str], limit: int, json_out: bool)`

Find chambers with similar topic profiles.

---

### `def graph_build(limit_docs: int, json_out: bool)`

Build citation graph from cached documents.

---

### `def graph_show(document_id: str, source: str, direction: str, json_out: bool)`

Show citation relationships for a document.

---

### `def graph_citing(document_id: str, source: str, limit: int, json_out: bool)`

Find documents that cite the given document.

---

### `def graph_cited(document_id: str, source: str, limit: int, json_out: bool)`

Find documents that the given document cites.

---

### `def graph_stats(json_out: bool)`

Citation graph istatistikleri.

---

### `def graph_export(format: str, document_id: Optional[str], source: Optional[str], max_depth: int, json_out: bool)`

Export citation graph in various formats (json, dot, mermaid).

---

### `def analytics_report(days: int, cache_path: Optional[Path], json_out: bool)`

Comprehensive search analytics report.

---

### `def analytics_empty_queries(limit: int, cache_path: Optional[Path], json_out: bool)`

List queries that returned 0 results.

---

### `def analytics_top_queries(limit: int, cache_path: Optional[Path], json_out: bool)`

Most frequent queries.

---

### `def analytics_source_coverage(cache_path: Optional[Path], json_out: bool)`

Source coverage: doc counts and full_text percentage.

---

### `def template_list(json_out: bool)`

List all available petition templates.

---

### `def template_show(name: str, json_out: bool)`

Show details of a specific petition template.

---

### `def template_render(name: str, out_path: Optional[Path])`

Render a template as a draft-skeleton.md compatible markdown.

---

### `def draft_diff(draft_a: Path, draft_b: Path, json_out: bool)`

Compare two draft files and show changes.

---

### `def draft_placeholders(draft_path: Path, json_out: bool)`

Analyze placeholder fill status in a draft.

---

### `def draft_fill_report(draft_path: Path, pack_dir: Optional[Path], json_out: bool)`

Generate a fill report: what still needs attention.

---

### `def draft_save_version(draft_dir: Path, label: Optional[str], json_out: bool)`

Save a snapshot of current draft state for later diff.

---

### `def export_txt(draft_path: Path, out_path: Optional[Path], json_out: bool)`

Export a draft to plain-text format (always available, no toolkit).

---

### `def export_format_cmd(draft_path: Path, format: str, out_path: Optional[Path], pack_dir: Optional[Path], experimental: bool, json_out: bool)`

Unified export dispatcher: docx, txt, pdf, udf.

---

### `def export_capabilities_cmd(json_out: bool)`

Show which export formats are currently available.

---

### `def circuit_status_cmd(source: Optional[str], json_out: bool)`

Show circuit breaker status for one or all sources.

---

### `def circuit_health_cmd(source: Optional[str], json_out: bool)`

Show source health metrics (uptime, failure counts, circuit state).

---

### `def circuit_reset_cmd(source: str, json_out: bool)`

Manually reset a circuit breaker to CLOSED state.

---

### `def router_capable_sources(capability: str, json_out: bool)`

List source_ids that support a given capability.

---

### `def router_search_cmd(query: str, require: Optional[str], prefer: Optional[str], exclude: Optional[str], json_out: bool)`

Route a search request to capable sources.

---

### `def router_get_document_cmd(document_id: str, require: Optional[str], preferred_source: Optional[str], json_out: bool)`

Route a get_document request to capable sources.

---

### `def pdf_extract(path: Path, ocr: bool, json_out: bool)`

Extract text layer from a PDF file.

---

### `def pdf_toolkit(json_out: bool)`

Check PDF extraction toolkit availability.

---

### `def pdf_promote(document_json: str, ocr: bool, json_out: bool)`

Try to promote a pdf_only Document to full_text.

---

### `def calibrate_source_cmd(source_id: str, online: bool, json_out: bool)`

Measure safe request rate for a source.

---

### `def calibrate_all_cmd(online: bool, json_out: bool)`

Calibrate all registered sources.

---

### `def benchmark_cmd(corpus_size: int, json_out: bool)`

Run micro-benchmark suite (deterministic corpus).

---

### `def watch_add(name: str, query: str, sources: Optional[str], fetch_count: int, interval_hours: int, json_out: bool)`

Register a watch for periodic research.

---

### `def watch_list(json_out: bool)`

List all registered watches.

---

### `def watch_run(name: str, json_out: bool)`

Execute a watch: re-search, detect new/changed docs.

---

### `def watch_remove(name: str, json_out: bool)`

Remove a watch.

---

### `def privacy_scan(text: str, json_out: bool)`

Scan text for potential PII (TCKN, phone, email).

---

### `def privacy_redact(text: str, json_out: bool)`

Redact PII from text. Returns copy — original unchanged.

---

### `def privacy_audit(path: Path, json_out: bool)`

Audit a file or directory for PII presence.

---

## `concurrency`

### `def get_concurrency_status() -> dict[str, Any]`

Report concurrency settings and current state.

    Returns:
            Dict with ok, max_concurrency, available_slots.

---

### `async def run_concurrently(coros: list[Coroutine[Any, Any, T]]) -> list[T | Exception]`

Run multiple coroutines concurrently with a semaphore cap.

    Each coroutine runs under the global semaphore. Exceptions are
        caught per-coroutine and returned as Exception values — this
        allows partial success (some succeed, some fail) without aborting
        the entire batch.
    
        Args:
            coros: List of coroutines to execute.
            max_concurrency: Override the default max concurrency.
    
        Returns:
            List of results. Each element is either the return value
            or an Exception if that coroutine failed.

---

### `async def run_document_fetches(fetch_tasks: list[tuple[Callable[..., Any], str, str]]) -> list[Any]`

Run multiple document fetch operations concurrently.

    Specialized convenience for batch document fetching in research_topic.
        Each task is a tuple of (get_document_fn, source_id, document_id).
    
        Args:
            fetch_tasks: List of (async_get_document_fn, source, doc_id) tuples.
            max_concurrency: Override concurrency limit.
    
        Returns:
            List of fetch results (Document or Exception).

---

### `async def run_source_searches(search_tasks: list[tuple[Callable[..., Any], str, str]]) -> list[Any]`

Run multiple source search operations concurrently.

    Each task is a tuple of (search_fn, source_id, query).
    
        Args:
            search_tasks: List of (async_search_fn, source_id, query) tuples.
            max_concurrency: Override concurrency limit.
    
        Returns:
            List of search results.

---

## `config`

### `def setup_logging() -> logging.Logger`

Configure stdlib logging for emsal-mcp.

    Log level is controlled by EMSAL_LOG_LEVEL (default: WARNING).
        Output goes to stderr only — never pollutes stdout JSON contracts.
    
        Returns the configured logger.

---

## `dedup`

### `def find_duplicates(cache: Any, dry_run: bool) -> dict[str, Any]`

Find duplicate documents across sources.

    Groups documents by (court, esas_no, karar_no).  Documents must have
        non-empty esas_no AND karar_no to be considered.  Only groups with >1
        member create a dedup cluster.
    
        Args:
            cache: Cache instance.  If None, a new one is created.
            dry_run: If True, return plan without modifying DB.
    
        Returns:
            Dict with ok, clusters_found, total_duplicates, clusters list.

---

### `def get_dedup_cluster(document_id: str, source: str, cache: Any) -> dict[str, Any]`

Find which dedup cluster a document belongs to.

    Args:
            document_id: Document ID to look up.
            source: Source identifier.
            cache: Cache instance.  If None, a new one is created.
    
        Returns:
            Dict with ok, in_cluster, cluster_id, canonical, all_members.

---

### `def get_dedup_stats(cache: Any) -> dict[str, Any]`

Compute deduplication statistics.

    Args:
            cache: Cache instance.  If None, a new one is created.
    
        Returns:
            Dict with ok, total_clusters, total_duplicate_docs,
            space_saved_estimate, sources_most_duplicates.

---

### `def merge_cluster(cluster_id: str, cache: Any) -> dict[str, Any]`

Merge a cluster by enriching the canonical record.

    Adds alternative source URLs to the canonical record's metadata
        without overwriting existing fields.  Logs merge in history.
    
        Args:
            cluster_id: The dedup cluster ID to merge.
            cache: Cache instance.  If None, a new one is created.
    
        Returns:
            Dict with ok, cluster_id, canonical, enriched_fields, members_merged.

---

### `def find_fuzzy_duplicates(cache: Any) -> dict[str, Any]`

Find suspected fuzzy duplicates using dense embeddings.

    Only uses embedding_vectors table (requires M-24 dense index).
        Compares document pairs within same court.
    
        CRITICAL INVARIANT: This function ONLY reports candidate pairs. It NEVER
        auto-merges.  All merges require explicit user confirmation.
    
        Args:
            cache: Cache instance. If None, a new one is created.
            provider: Embedding provider to use. Default: from config/env.
            cosine_threshold: Cosine similarity threshold (0.0–1.0). Default 0.85.
            max_date_diff_days: Maximum date difference in days to consider. Default 365.
    
        Returns:
            Dict with ok, suspected_duplicates, total_suspected, warnings.
            Each suspected pair includes doc_a, doc_b, cosine_score, date_diff_days,
            confidence, recommendation.

---

### `def get_fuzzy_dedup_stats(cache: Any) -> dict[str, Any]`

Report fuzzy dedup statistics.

    Checks availability of embedding vectors required for fuzzy matching.
    
        Returns:
            Dict with ok, embedded_document_count, provider, threshold_default.

---

## `document`

### `def controlled_draft(title: str, body: str, docs: Iterable[Document]) -> str`

Build a citation-safe markdown draft with verified authorities.

    Args:
            title: Draft title.
            body: Draft body text.
            docs: Iterable of Document objects to classify for citation safety.
    
        Returns:
            Markdown string with safe citations appended as a bibliography.

---

### `def markdown_to_docx(markdown: str, out_path: str | Path) -> Path`

Convert markdown text to a DOCX file.

    Args:
            markdown: Markdown content string.
            out_path: Output file path for the DOCX.
    
        Returns:
            Path to the created DOCX file.

---

### `def export_bundle(out_dir: str | Path) -> dict`

Export a citation-safe bundle with input pack and source documents.

    Args:
            out_dir: Output directory for the bundle.
            matter: Legal matter description.
            issue: Legal issue description.
            docs: List of Document objects to include.
    
        Returns:
            Dict with out_dir, safe_count, excluded_count.

---

## `draft_diff`

### `def diff_drafts(draft_path_a: str | Path, draft_path_b: str | Path) -> dict[str, Any]`

Compare two draft files (draft.md or draft.json).

    Reads both files, computes a unified line-by-line diff, and analyses
        placeholder changes (filled vs unfilled).
    
        Args:
            draft_path_a: Path to the first (older) draft.
            draft_path_b: Path to the second (newer) draft.
    
        Returns:
            Dict with ok, draft_a, draft_b, diff_lines, changes, unified_diff,
            warnings.

---

### `def track_placeholders(draft_path: str | Path) -> dict[str, Any]`

Analyze a draft for placeholder fill status.

    Finds all ``{{PLACEHOLDER}}`` patterns and reports which are filled
        (no longer present as raw tokens in the text) vs unfilled (still present).
    
        Args:
            draft_path: Path to the draft file.
    
        Returns:
            Dict with ok, total_placeholders, filled, unfilled, fill_ratio,
            placeholders, unfilled_list, ready_for_submission, warnings.

---

### `def get_fill_report(draft_path: str | Path, pack_dir: str | Path | None) -> dict[str, Any]`

Human-readable report of what still needs attention.

    Lists unfilled placeholders with section context, suggests sources
        from the pack (if available), and provides a readiness assessment.
    
        Args:
            draft_path: Path to the draft file.
            pack_dir: Optional petition pack directory for source suggestions.
    
        Returns:
            Dict with ok, total_placeholders, filled, unfilled, fill_ratio,
            readiness, items (per-unfilled-placeholder), suggestions, warnings.

---

### `def save_draft_version(draft_dir: str | Path, version_label: str | None) -> dict[str, Any]`

Save a snapshot of the current draft state for later diff.

    Copies draft files into a versioned subdirectory under
        ``<draft_dir>/.versions/<version_id>/`` and stores metadata.
    
        Args:
            draft_dir: Directory containing draft files.
            version_label: Optional human-readable label for this version.
    
        Returns:
            Dict with ok, version_id, version_label, version_dir, files_copied,
            metadata_path, warnings.

---

## `drafter`

### `def assemble_draft(pack: InputPack, kind: str, body_markdown: str, extra_citations: list[str] | None) -> Draft`

Assemble a controlled draft from safe InputPack only.

    - No invented citations: only uses citations from the pack
        - Includes warnings if body contains citation-like patterns

---

### `def validate_draft_body(body_markdown: str, pack: InputPack) -> list[str]`

Validate draft body doesn't contain fabricated citations.

---

## `embeddings`

### `def get_embedding_provider(provider: str | None) -> EmbeddingProvider | None`

Factory: provider arg > EMSAL_EMBEDDING_PROVIDER env > default local-hash-v1.

    Returns EmbeddingProvider instance.
        Returns None if provider is invalid or unavailable (caller handles graceful).

---

### `def list_embedding_providers() -> list[dict]`

Return metadata for all known providers.

---

### `def pack_vector(vec: list[float]) -> bytes`

Pack float32 vector into BLOB for SQLite storage.

---

### `def unpack_vector(blob: bytes, dim: int) -> list[float]`

Unpack BLOB back to float32 vector.

---

### `def rerank_results(query: str, candidates: list[dict], top_k: int, provider: str | None) -> dict`

Re-rank candidates using cross-encoder if available.

    If cross-encoder is not available, returns original candidates as-is
        with a warning.  Never raises an exception.
    
        Args:
            query: Original search query.
            candidates: List of {document_id, source, title, score, text_preview...}.
            top_k: Number of top results to return after reranking.
            provider: Embedding provider (unused, kept for interface consistency).
    
        Returns:
            dict with ok, results (reranked), was_reranked: bool, method, warnings.

---

## `exporter`

### `def export_draft_to_docx(draft: Draft, output_path: str | Path, pack: InputPack | None) -> Path`

Export a draft to DOCX format.

---

### `def create_bundle(draft: Draft, pack: InputPack, output_dir: str | Path, docx_content: bytes | None) -> Path`

Create a ZIP bundle with manifest hashes and verification.txt.

---

### `def verify_bundle(bundle_path: str | Path) -> dict[str, Any]`

Verify integrity of a ZIP bundle.

---

### `def prepare_docx_export(draft_path: str | Path | None, draft_json: dict[str, Any] | None, out_path: str | Path | None, pack_dir: str | Path | None) -> dict[str, Any]`

Create a validated DOCX export from a controlled draft.

    Accepts either a ``draft.md`` path or a ``draft.json`` dict.  When
        *pack_dir* is provided, footnotes are appended from the pack's
        ``petition-brief.json``.
    
        The DOCX includes:
        - A disclaimer header paragraph
        - Draft body content
        - Footnotes / citation references
        - Placeholder preservation (``{{…}}``)
    
        Returns a dict with:
        - ``checksum_sha256``: SHA-256 of the DOCX file
        - ``file_size``: file size in bytes
        - ``validation``: dict with zip_valid, disclaimer_present,
          footnotes_consistent, placeholders_preserved,
          validation_warnings, export_readiness

---

### `def prepare_export_package_bundle(pack_dir: str | Path, draft_dir: str | Path | None, docx_path: str | Path | None, out_dir: str | Path | None) -> dict[str, Any]`

Create a complete export package bundle (v2) with verification.

    Bundles together:
        - draft.md, draft.json, footnotes.json, warnings.json (from draft_dir)
        - petition-pack.json, citation-bank.md, source-documents/ (from pack_dir)
        - manifest.json, hash-manifest.json, verification.txt, warnings.json
    
        After creation the bundle is verified; any integrity failures are
        reported in the return dict.
    
        Returns:
            Dict with ok, bundle_dir, manifest, hash_manifest, verification,
            files, post_verification.

---

### `def export_plain_text(draft_path: str | Path, out_path: str | Path | None) -> dict[str, Any]`

Export a draft.md to plain text format.

    Converts markdown to plain text by stripping formatting while preserving
        the disclaimer header and ``{{PLACEHOLDER}}`` tokens.
    
        Returns:
            Dict with ok, out_path, text_length, disclaimer_present,
            placeholders_preserved.

---

### `def export_to_format(draft_path: str | Path, format: str, out_path: str | Path | None, pack_dir: str | Path | None, experimental: bool) -> dict[str, Any]`

Unified export dispatcher supporting multiple formats.

    Formats:
            - ``docx``: validated DOCX export (always available via python-docx)
            - ``txt``: plain-text export (always available, stdlib only)
            - ``pdf``: PDF export via LibreOffice (requires toolkit)
            - ``udf``: UYAP UDF format (requires toolkit + experimental=True)
    
        When the toolkit is absent for formats that require it, returns a
        structured error dict (``TOOLKIT_UNAVAILABLE``) — never raises.
    
        Returns:
            Format-specific result dict or structured error.

---

### `def get_export_capabilities() -> dict[str, Any]`

Report which export formats are currently available.

    Returns:
            Dict with formats list, each indicating availability and requirements.

---

## `legislation`

### `def search_legislation(query: str, sources: list[str] | None, legislation_type: str | None, limit: int, sources_override: dict[str, Any] | None) -> dict[str, Any]`

Search legislation via the Mevzuat source.

    Args:
            query: Search phrase.
            sources: Source IDs to search (default: ["mevzuat"]).
            legislation_type: Optional filter (e.g. "Kanun", "Yönetmelik").
            limit: Max results.
            sources_override: Dict mapping source_id -> fake client for tests.
    
        Returns:
            Dict with ok, query, sources, legislation_type, total_results,
            results, warnings, recommended_next_steps, version, rule.

---

### `def get_legislation_document(document_id: str, source: str | None, sources_override: dict[str, Any] | None) -> dict[str, Any]`

Get a full legislation document from the Mevzuat source.

    Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").
            sources_override: Dict mapping source_id -> fake client for tests.
    
        Returns:
            Dict with ok, document_id, title, citation_check, article_count,
            legislation_type, content_status, etc.

---

### `def search_legislation_articles(document_id: str, article_number: str | None, article_query: str | None, source: str | None, sources_override: dict[str, Any] | None) -> dict[str, Any]`

Search articles within a legislation document.

    Args:
            document_id: Mevzuat document ID.
            article_number: Optional specific article number to retrieve.
            article_query: Optional keyword/phrase to search in article text.
            source: Source ID (default: "mevzuat").
            sources_override: Dict mapping source_id -> fake client for tests.
    
        Returns:
            Dict with ok, matching_articles, total_articles_found, etc.

---

### `def get_legislation_article_tree(document_id: str, source: str | None, sources_override: dict[str, Any] | None) -> dict[str, Any]`

Build a hierarchical part/section/article tree from legislation text.

    Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").
            sources_override: Dict mapping source_id -> fake client for tests.
    
        Returns:
            Dict with ok, article_count, section_count, part_count, tree,
            flat_article_list, etc.

---

### `def get_legislation_gerekce(document_id: str, source: str | None, sources_override: dict[str, Any] | None) -> dict[str, Any]`

Extract GENEL GEREKCE and MADDE GEREKCELERI from legislation text.

    Args:
            document_id: Mevzuat document ID.
            source: Source ID (default: "mevzuat").
            sources_override: Dict mapping source_id -> fake client for tests.
    
        Returns:
            Dict with ok, found, genel_gerekce, madde_gerekceleri, raw_text, etc.

---

### `def get_legislation_source_status(sources_override: dict[str, Any] | None) -> dict[str, Any]`

Check Mevzuat source health via smoke tests.

    Args:
            sources_override: Unused (kept for interface consistency).
    
        Returns:
            Dict with ok, overall_ok, healthy_sources, degraded_sources, etc.

---

### `def format_legislation_citation(document: dict[str, Any] | Document, style: Literal['full', 'short', 'article']) -> dict[str, Any]`

Format a legislation citation from document metadata.

    Args:
            document: Document dict or Document model.
            style: 'full', 'short', or 'article'.
    
        Returns:
            Dict with formatted_citation, style, warnings, etc.

---

### `def get_legislation_types() -> list[dict[str, str]]`

Return the list of known Turkish legislation types with IDs.

---

## `models`

### `def build_content_status_fields(item: Any) -> dict[str, Any]`

Build local-yargi style content status helper fields.

    This is intentionally deterministic and citation-safe: it never upgrades a
        document to quote/draft usable; it only labels the existing content status
        and exposes next-step hints for agents.

---

### `def finalize_document(doc: Document, warnings: list[str] | None) -> Document`

Finalize a Document after source-specific parsing.

    - Applies min content length sanity: if content is too short for a
          full_text/html_markdown doc, downgrades to metadata_only with a warning.
        - Enriches content_status fields via build_content_status_fields.
        - Never fabricates metadata; warnings list is appended to, not replaced.
        - Returns the document (mutated in-place and returned for convenience).

---

### `def build_error(error_code: str, message: str) -> dict[str, Any]`

Build a canonical error dict for consistent error shapes.

    All modules should use this helper for structured error responses
        instead of ad-hoc dicts.  This ensures every error response has
        `ok`, `errorCode`, `message`, and optional context fields.
    
        Args:
            error_code: Machine-readable error code (e.g. "TOOLKIT_UNAVAILABLE").
            message: Human-readable error description.
            ok: Always False for errors (kept as kwarg for clarity).
            source: Optional source identifier that produced the error.
            retryable: Whether the operation can be retried.
            warnings: Optional list of non-fatal warning strings.
            recommended_next_steps: Optional actionable next steps.
            **extra: Additional fields attached to the error dict.
    
        Returns:
            Dict with canonical keys: ok, errorCode, message, and any extra fields.

---

## `pdf_extractor`

### `def is_pdf_extraction_available() -> bool`

Check if pypdf is installed for text-layer extraction.

---

### `def is_ocr_available() -> bool`

Check if pytesseract and Pillow are installed for OCR.

---

### `def extract_pdf_text_from_bytes(pdf_content: bytes) -> dict[str, Any]`

Extract text from PDF bytes using text-layer extraction.

    Uses pypdf to extract text from the PDF's text layer.
        This works on born-digital PDFs, not scanned images.
    
        Args:
            pdf_content: Raw PDF file bytes.
    
        Returns:
            Dict with ok, text, page_count, method, warnings.
            On failure, returns structured error dict.

---

### `def extract_pdf_text_ocr(pdf_content: bytes, language: str) -> dict[str, Any]`

Extract text from PDF using OCR (pytesseract).

    Converts each PDF page to an image and runs OCR.
        This works on scanned/image-only PDFs where the text layer is empty.
    
        Args:
            pdf_content: Raw PDF file bytes.
            language: Tesseract language code (default: 'tur' for Turkish).
    
        Returns:
            Dict with ok, text, page_count, method, warnings.
            On failure, returns structured error dict.

---

### `def extract_pdf_text(pdf_content: bytes, ocr_enabled: bool, ocr_language: str) -> dict[str, Any]`

Smart PDF text extraction.

    Tries text-layer extraction first (pypdf).
        If that yields no text and OCR is enabled, falls back to OCR.
    
        Args:
            pdf_content: Raw PDF file bytes.
            ocr_enabled: If True, fall back to OCR when text layer is empty.
            ocr_language: Tesseract language code for OCR.
    
        Returns:
            Dict with ok, text, page_count, method, warnings.

---

### `def try_upgrade_pdf_document(document_id: str, source: str, cache: Any) -> dict[str, Any]`

Attempt to extract text from a PDF document and upgrade its content status.

    Only processes documents with content_status='pdf_link_only' and a source_url
        ending in .pdf. Downloads the PDF, extracts text, and if successful, updates
        the document's content_status to FULL_TEXT.
    
        Citation-safety invariant: if extraction fails, content_status is preserved.
    
        Args:
            document_id: Document ID to upgrade.
            source: Source identifier.
            cache: Optional Cache instance.
            ocr_enabled: Whether to attempt OCR fallback.
    
        Returns:
            Dict with ok, upgraded, method, text_length, warnings.

---

### `def upgrade_all_pdf_documents(cache: Any) -> dict[str, Any]`

Try to upgrade all pdf_link_only documents in the cache.

    Iterates through pdf_link_only documents, downloads each PDF, extracts
        text, and upgrades successful ones to full_text.
    
        Args:
            cache: Optional Cache instance.
            source: Optional filter by source.
            limit: Maximum documents to process.
            ocr_enabled: Whether to attempt OCR fallback.
    
        Returns:
            Dict with ok, processed, upgraded, failed, warnings.

---

### `def get_pdf_stats(cache: Any) -> dict[str, Any]`

Report PDF document statistics from the cache.

    Returns counts of pdf_link_only documents and their upgrade potential.
    
        Args:
            cache: Optional Cache instance.
    
        Returns:
            Dict with ok, pdf_link_only_count, source_distribution, version.

---

### `def extract_pdf_text_from_file(file_path: str, ocr_enabled: bool) -> dict[str, Any]`

Extract text from a PDF file on disk.

    Convenience wrapper for CLI usage — reads file, delegates to extract_pdf_text.
    
        Args:
            file_path: Path to PDF file.
            ocr_enabled: Whether to fall back to OCR.
    
        Returns:
            Dict with ok, text, page_count, method, warnings.

---

### `def get_pdf_toolkit_status() -> dict[str, Any]`

Report PDF extraction toolkit availability.

    Returns:
            Dict with ok, pypdf_available, ocr_available, version.

---

### `def promote_pdf_to_full_text(document: dict[str, Any], ocr_enabled: bool) -> dict[str, Any]`

Promote a pdf_only Document dict to full_text if possible.

    Extracts text from the document's pdf_url and returns the enriched dict.
        Does NOT modify the cache — caller must store if desired.
    
        Args:
            document: Document dict with document_id, source, pdf_url/source_url fields.
            ocr_enabled: Whether to attempt OCR.
    
        Returns:
            Dict with ok, document (enriched), upgraded, warnings.

---

## `petition`

### `def prepare_drafting_input_pack(matter: str, issue: str, documents: list[Document] | None, research_bundle_dir: str | Path | None, out_dir: str | Path | None, strict: bool, cache: Any | None, template_name: str | None) -> dict[str, Any]`

Prepare a petition drafting input pack.

    Classifies authorities as petition_ready, citation_only,
        research_lead_only, or excluded using citation safety, content_status,
        metadata/provenance, and content_hash.  Generates a structured pack
        directory with all required files.
    
        Args:
            matter: Legal matter description.
            issue: Legal issue description.
            documents: List of Document objects to classify.  If None and
                research_bundle_dir is provided, documents are loaded from the
                research bundle.
            research_bundle_dir: Optional path to a v0.5 research bundle
                directory.  Documents are loaded from results.json if documents
                is None.
            out_dir: Output directory for the pack.  If None, a default
                directory is created.
            strict: If True, exclude any document that fails hash verification.
            cache: Optional Cache instance for history logging.
            template_name: Optional template name from the template library.
                If provided, the draft-skeleton.md will be rendered from the
                specified template instead of the default skeleton generator.
    
        Returns:
            Dict with pack metadata: ok, out_dir, draft_safe, counts,
            classifications, files, warnings, hash_manifest.

---

### `def inspect_petition_pack(pack_dir: str | Path) -> dict[str, Any]`

Validate a petition pack directory.

    Checks:
        - Required files exist
        - draft_safe flag from petition-pack.json
        - Classification counts
        - placeholdersInDraftSkeleton: placeholder count in draft-skeleton.md
        - legislationVerified placeholder: no unverified legislation references
        - petitionInstructionsForbidsInvention: instructions contain no-invention rule
        - citationBankOnlySafeDocs: citation bank only references safe docs
        - hashManifestValid: if hash-manifest.json exists, verify hashes
    
        Returns:
            Dict with ok, draft_safe, errors, warnings, counts, checks.

---

### `def prepare_petition_outline(pack_dir: str | Path, out_dir: str | Path | None) -> dict[str, Any]`

Generate a structured petition outline from a petition pack.

    Reads petition-pack.json and petition-brief.json from *pack_dir* and
        produces an ``outline.json`` that describes every section, its
        placeholders, and which authorities contribute to it.
    
        Only ``petition_ready`` authorities may supply direct content;
        ``citation_only`` authorities appear only in the bibliography section
        with a warning flag.
    
        Args:
            pack_dir: Path to a petition pack directory (from v0.7).
            out_dir: Where to write ``outline.json``.  Defaults to *pack_dir*.
    
        Returns:
            Dict with ok, outline_path, sections, placeholder_total,
            citation_only_bibliography_count, petition_ready_count.

---

### `def prepare_controlled_petition_draft(pack_dir: str | Path, outline_path: str | Path | None, out_dir: str | Path | None) -> dict[str, Any]`

Generate a controlled petition draft from a petition pack.

    Produces four output files:
    
        * ``draft.md`` — Markdown draft with disclaimer header, placeholder
          sections, and footnotes.  Only ``petition_ready`` authorities may
          supply direct quotes; ``citation_only`` authorities appear only as
          bibliographic references with a warning.
        * ``draft.json`` — Structured metadata with paragraph/section/footnote
          counts, placeholder counts, blocking warning count, readiness
          score/level, and finalization risk score.
        * ``footnotes.json`` — Footnote references extracted from
          ``petition_ready`` authorities.
        * ``warnings.json`` — List of warnings (blocking and non-blocking).
    
        Placeholders (``{{…}}``) are always preserved verbatim.
    
        Args:
            pack_dir: Path to a petition pack directory.
            outline_path: Optional pre-computed outline.json.  If ``None``
                the outline is generated on the fly.
            out_dir: Output directory.  Defaults to ``<pack_dir>/draft_output``.
    
        Returns:
            Dict with ok, out_dir, draft_md_path, draft_json_path,
            footnotes_path, warnings_path, draft_metadata.

---

### `def build_multi_issue_pack(matter: str, issues: list[dict[str, Any]], documents: list[Document] | None, out_dir: str | Path | None, cache: Any | None) -> dict[str, Any]`

Build a petition pack supporting multiple isolated legal issues.

    Each issue gets its own citation-bank.md and argument-map.md inside an
        ``issues/issue-N/`` subdirectory.  Source documents are shared across all
        issues but deduplicated.  The top-level hash-manifest covers every source
        document across all issues.
    
        Args:
            matter: Legal matter description (shared across issues).
            issues: List of issue dicts, each with keys:
                - ``title`` (str): Issue title (required).
                - ``description`` (str): Issue description (optional).
                - ``documents`` (list[Document] or list[dict]): Documents
                  specific to this issue (optional).  These are merged with the
                  shared *documents* list (deduplicated by document_id).
            documents: Shared documents applied to every issue unless overridden
                by per-issue documents.
            out_dir: Root output directory for the multi-issue pack.
            cache: Optional Cache instance for history logging.
    
        Returns:
            Dict with ok, out_dir, issue_count, issues (per-issue results),
            combined_classification_counts, draft_safe, files, warnings.

---

### `def inspect_multi_issue_pack(pack_dir: str | Path) -> dict[str, Any]`

Validate a multi-issue petition pack directory.

    Checks:
        - Top-level required files exist
        - Each issue has its own citation-bank.md and argument-map.md
        - No cross-issue citation contamination
        - Hash manifest covers all source documents
        - petition-instructions.md contains no-invention rule
        - Placeholders preserved in draft-skeleton.md
    
        Returns:
            Dict with ok, draft_safe, errors, warnings, checks, issue_results.

---

## `privacy`

### `def scan_pii(text: str) -> dict[str, Any]`

Scan text for potential PII. Returns findings without modifying text.

    Args:
            text: Input text to scan.
    
        Returns:
            Dict with ok, findings_count, findings list, risk_level.

---

### `def redact_pii(text: str) -> dict[str, Any]`

Redact PII from text. Returns redacted text (original unchanged).

    Args:
            text: Input text to redact.
    
        Returns:
            Dict with ok, redacted_text, original_length, redactions_applied, warning.

---

### `def audit_privacy(path: str | Path) -> dict[str, Any]`

Audit a file or directory for PII.

    Args:
            path: File or directory path to audit.
    
        Returns:
            Dict with ok, files_scanned, files_with_pii, findings, warning.

---

## `release`

### `def release_smoke() -> dict[str, Any]`

Run release smoke tests combining offline, cache, and source checks.

    Performs offline smoke tests, cache integrity verification, and per-source
        smoke tests. Returns aggregated pass/fail status.
    
        Returns:
            Dict with ok, version, generated_at, checks (offline, cache, source status).

---

### `def readiness_dashboard() -> dict[str, Any]`

Compute release readiness score from smoke tests and source capabilities.

    Aggregates risk factors (e.g. unavailable sources) and produces a
        ship/review decision based on the readiness score.
    
        Returns:
            Dict with ok, version, readiness_score, release_decision, smoke, risks.

---

### `def write_history(out_dir: str | Path, dashboard: dict[str, Any] | None) -> dict[str, Any]`

Write a release history record with SHA256 integrity hash.

    Args:
            out_dir: Output directory for the history JSON file.
            dashboard: Optional pre-computed dashboard dict (runs readiness_dashboard if None).
    
        Returns:
            Dict with path to the written record and the record content.

---

### `def compare_history(left: str | Path, right: str | Path) -> dict[str, Any]`

Compare two release history records and report score delta.

    Args:
            left: Path to the older (left) history JSON file.
            right: Path to the newer (right) history JSON file.
    
        Returns:
            Dict with ok, score_delta, regression flag, left_score, right_score.

---

### `def release_notes() -> str`

Generate markdown release notes from the current readiness dashboard.

    Returns:
            Markdown string with version, readiness, scope, and risk summary.

---

### `def archive_release(out_dir: str | Path) -> dict[str, Any]`

Create a release archive with dashboard, notes, and history.

    Args:
            out_dir: Output directory for the release archive.
    
        Returns:
            Dict with ok, out_dir, manifest (version, files list).

---

### `def release_command_center(cache: Any | None) -> dict[str, Any]`

Comprehensive release verification running all checks.

    Runs source smoke, cache integrity, module imports, FTS5 index status,
        chamber overview, and UDF toolkit status.  Aggregates into a single
        readiness report for release decision-making.
    
        Args:
            cache: Optional Cache instance for index/chamber checks.
    
        Returns:
            Dict with ok, overall_readiness, checks, warnings, recommended_actions.

---

### `def version_bump(major: bool, minor: bool, patch: bool) -> dict[str, Any]`

Compute a bumped version string without modifying files.

    Reads current version from __version__ and returns the next version.
    
        Args:
            major: Bump major version.
            minor: Bump minor version.
            patch: Bump patch version (default).
    
        Returns:
            Dict with current_version, next_version, bump_type, warnings.

---

### `def final_v1_readiness(cache: Any | None) -> dict[str, Any]`

Final v1.0.0 readiness gate.

    Combines release command center checks with additional v1 criteria:
        - All core modules importable
        - At least 1 stable source
        - Cache integrity passes
        - No blocking warnings
    
        Returns a go/no-go recommendation.
    
        Args:
            cache: Optional Cache instance.
    
        Returns:
            Dict with ok, ready, criteria, blocking_issues, recommendation.

---

### `def generate_release_summary(cache: Any | None) -> dict[str, Any]`

Generate a human-readable release summary for the current version.

    Includes version, module inventory, source status, document counts,
        and readiness assessment.
    
        Args:
            cache: Optional Cache instance.
    
        Returns:
            Dict with ok, markdown_summary, json_summary, version.

---

## `research`

### `def research_topic(query: str, sources: list[str] | None) -> dict[str, Any]`

Search sources, fetch documents, build output directory bundle.

    Args:
            query: Research query string.
            sources: List of source_ids to query.  Defaults to all registered
                sources with ``supports_search=True``.
            fetch_count: Max documents to fetch per search result.
            filters: Optional search filters forwarded to source.search().
            output_dir: Directory to write the bundle into.  If None a temp-like
                dir is derived from the query hash.
            sources_override: Optional dict mapping source_id to a source client
                instance.  When provided these are used *instead* of the real
                registry, enabling tests to inject fakes.
    
        Returns:
            Bundle metadata dict (also written as bundle.json).

---

### `def refresh_research_bundle(bundle_path: str | Path) -> dict[str, Any]`

Re-run research from an existing bundle.json, detecting new/changed docs.

    Reads bundle.json, re-executes research_topic with same query/sources,
        compares hashes, and reports new_documents, changed_documents, hash_changed.
        Preserves manual notes between markers in index.md.
    
        Args:
            bundle_path: Path to the bundle.json to refresh.
            dry_run: If True, compute diff without writing files.
            sources_override: Optional fake source clients for testing.
    
        Returns:
            Refresh report dict.

---

### `def research_quality_dashboard(bundle_path: str | Path) -> dict[str, Any]`

Read a research bundle and compute quality metrics.

    Returns:
            Dict with full_text_ratio, citation_safe_ratio, metadata_only_count,
            pdf_only_count, unavailable_count, source_distribution,
            missing_metadata_count, duplicate_citation_count, draft_readiness_score,
            recommendations.

---

## `research_watch`

### `def add_watch(name: str, query: str, sources: list[str] | None, fetch_count: int, filters: dict[str, Any] | None, interval_hours: int, cache: Cache | None) -> dict[str, Any]`

Register a watch for periodic research.

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

---

### `def list_watches(cache: Cache | None) -> dict[str, Any]`

List all registered watches.

    Returns:
            Dict with ok, watches list (each with name, config, last_run_at, created_at).

---

### `def run_watch(name: str, cache: Cache | None, sources_override: dict[str, Any] | None) -> dict[str, Any]`

Execute a watch: re-search, detect new/changed docs, produce diff report.

    Args:
            name: Watch name to execute.
            cache: Optional Cache instance.
            sources_override: Optional source client mapping (for testing).
    
        Returns:
            Dict with ok, name, result, new_documents, changed_documents, diff_report.

---

### `def remove_watch(name: str, cache: Cache | None) -> dict[str, Any]`

Remove a watch.

    Args:
            name: Watch name to remove.
            cache: Optional Cache instance.
    
        Returns:
            Dict with ok, name, removed.

---

## `router`

### `def get_capable_sources(capability: str, sources_override: dict[str, Any] | None) -> list[str]`

Get list of source_ids that support a given capability.

    Returns empty list for unknown capabilities (with no exception) so
        callers can degrade gracefully.

---

### `def get_source_by_capability(capability: str, prefer_order: list[str] | None, sources_override: dict[str, Any] | None) -> str | None`

Get the best single source for a capability.

    Preference order: ``prefer_order`` > stable sources > experimental.
        Returns None if no source supports the capability.

---

### `def route_search(query: str, required_capabilities: list[str] | None, preferred_sources: list[str] | None, exclude_sources: list[str] | None, sources_override: dict[str, Any] | None) -> dict[str, Any]`

Route a search request to capable sources.

    This is READ-ONLY — it only determines which sources *could* serve the
        request based on the capability matrix.  It does not execute searches.

---

### `def route_get_document(document_id: str, required_capabilities: list[str] | None, preferred_source: str | None, sources_override: dict[str, Any] | None) -> dict[str, Any]`

Route a get_document request, trying preferred source first then

    falling back to capable alternatives.

---

## `safety`

### `def citation_check(doc: Document) -> CitationCheck`

Enforce citation safety: full_text/html_markdown + nonempty text + minimum provenance.

---

### `def exact_quote(doc: Document, phrase: str, context: int) -> str`

Only returns text if phrase exists verbatim; no paraphrase/no invention.

---

### `def build_input_pack(matter: str, issue: str, documents: list[Document]) -> InputPack`

Filter unsafe docs and build InputPack with stable pack_id.

---

### `def verify_document_hash(doc: Document) -> bool`

Verify document content hash matches stored hash.

---

## `search_analytics`

### `def record_search(query: str, source_filter: str | None, result_count: int, empty_result: bool, cache_hit: bool, duration_ms: float, cache: Any) -> dict[str, Any]`

Record a search in the analytics table.

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

---

### `def get_search_analytics(cache: Any, days: int) -> dict[str, Any]`

Comprehensive search analytics over the given time window.

    Returns:
            Dict with ok, total_searches, empty_result_rate, avg_result_count,
            cache_hit_rate, top_queries, empty_queries, source_distribution,
            daily_activity.

---

### `def get_empty_queries(cache: Any, limit: int) -> dict[str, Any]`

List queries that returned 0 results.

    Returns:
            Dict with ok and empty_queries list.

---

### `def get_top_queries(cache: Any, limit: int) -> dict[str, Any]`

Most frequent queries.

    Returns:
            Dict with ok and top_queries list.

---

### `def get_source_coverage(cache: Any) -> dict[str, Any]`

How many cached documents per source, and what percentage have full_text.

    Returns:
            Dict with ok and coverage list.

---

## `semantic`

### `def build_semantic_index(cache: Cache | None, force_rebuild: bool) -> dict[str, Any]`

Build FTS5 and TF-IDF indices.

    Args:
            cache: Optional Cache instance for DB injection.  If None a fresh Cache
                   is created.
            force_rebuild: If True, drop and recreate all index tables first.
    
        Returns:
            Status dict with ok, fts5_exists, fts5_row_count, vectors_count, etc.

---

### `def semantic_search(query: str, limit: int, cache: Cache | None, filters: dict[str, Any] | None) -> dict[str, Any]`

Search using TF-IDF cosine similarity only.

    Args:
            query: Free-text search query.
            limit: Maximum results to return.
            cache: Optional Cache instance for DB injection.
            filters: Optional metadata filters applied after scoring.
    
        Returns:
            Dict with ok, results, total_matches, method, warnings, version.

---

### `def hybrid_search(query: str, limit: int, cache: Cache | None, filters: dict[str, Any] | None, hybrid_weight: float, dense_weight: float | None, rerank: bool) -> dict[str, Any]`

Combined FTS5 BM25 + TF-IDF cosine hybrid search (v3 with optional dense).

    When dense_weight is None or 0.0, behaviour is identical to v2 (regression safe).
        When dense_weight > 0, a third dense-embedding signal is merged into the score.
    
        Args:
            query: Free-text search query.
            limit: Maximum results to return.
            cache: Optional Cache instance for DB injection.
            filters: Optional metadata filters applied after scoring.
                Supported keys: source, court, chamber, content_status,
                quote_usable, draft_usable.
            hybrid_weight: Weight for BM25 component (1-hybrid_weight for cosine).
                Must be between 0.0 and 1.0.  Default 0.6 means 60% BM25, 40%
                cosine.
            dense_weight: Optional weight for dense embedding component.
                When None, defaults to config value.  Set to 0.0 to disable.
            rerank: Optional cross-encoder reranking of top results.
                When True, re-scores top candidates with a cross-encoder model
                if available.  Gracefully passes through when unavailable.
    
        Returns:
            Dict with ok, results, total_matches, method, hybrid_weight,
            dense_weight, expanded_query_terms, snippet_highlighted, warnings, version.

---

### `def get_index_status(cache: Cache | None) -> dict[str, Any]`

Check index health and statistics.

    Returns:
            Dict with fts5_exists, fts5_document_count, vectors_table_exists,
            vectors_count, total_cached_documents, unindexed_documents, warnings,
            recommended_next_steps, version.

---

### `def rebuild_index(cache: Cache | None) -> dict[str, Any]`

Force rebuild of both FTS5 and TF-IDF indices.

    Convenience wrapper around build_semantic_index(force_rebuild=True).
    
        Returns:
            Status dict from build_semantic_index.

---

### `def build_embedding_index(cache: Cache | None, provider: str | None, force_rebuild: bool) -> dict[str, Any]`

Build dense embedding index from cached documents.

    Args:
            cache: Optional Cache instance for DB injection.
            provider: Provider ID (default from config/env).
            force_rebuild: If True, re-embed all documents.
    
        Returns:
            Status dict with ok, documents_indexed, provider, dimensions, etc.

---

### `def embedding_search(query: str, limit: int, provider: str | None, cache: Cache | None, filters: dict[str, Any] | None) -> dict[str, Any]`

Search using dense embeddings with brute-force cosine similarity.

    Args:
            query: Free-text search query.
            limit: Maximum results to return.
            provider: Provider ID (default from config/env).
            cache: Optional Cache instance for DB injection.
            filters: Optional metadata filters applied after scoring.
    
        Returns:
            Dict with ok, results, total_matches, method, provider, version.

---

### `def get_embedding_index_status(cache: Cache | None) -> dict[str, Any]`

Check dense embedding index status.

    Returns per-provider vector counts and dimensions.
    
        Returns:
            Dict with ok, providers list, version.

---

### `def update_indexes(cache: Cache | None, since: str | None, provider: str | None) -> dict[str, Any]`

Incrementally update both TF-IDF and dense indexes.

    Only processes documents that are:
        - New (not in search_vectors/embedding_vectors)
        - Changed (content_hash differs from indexed hash, dense only)
    
        After incremental update, cleans orphan vectors.
    
        Args:
            cache: Optional Cache instance for DB injection.
            since: Optional ISO timestamp — only process docs fetched after this time.
            provider: Optional embedding provider for dense index updates.
    
        Returns:
            Dict with ok, tfidf_updated, dense_updated, skipped, warnings.

---

### `def get_index_sync_status(cache: Cache | None) -> dict[str, Any]`

Report how many documents are out of sync with indexes.

    Compares total documents with text content against the number
        of documents indexed in TF-IDF (search_vectors) and dense
        (embedding_vectors) stores.
    
        Args:
            cache: Optional Cache instance for DB injection.
    
        Returns:
            Dict with ok, total_documents, tfidf_indexed, dense_indexed,
            tfidf_out_of_sync, dense_out_of_sync.

---

## `server`

### `def main() -> None`

Launch the MCP server with all registered tools.

    Imports FastMCP from the mcp package and registers all tool functions.
        Exits with an error message if the MCP extra is not installed.

---

## `server_utils`

### `def validate_non_empty(value: Any) -> tuple[bool, str | None]`

Check that a string value is not empty or whitespace-only.

---

### `def validate_positive_int(value: Any) -> tuple[bool, str | None]`

Check that a value is a positive integer (>= 1).

---

### `def validate_range(min_val: float, max_val: float) -> Callable[[Any], tuple[bool, str | None]]`

Return a validator that checks value is within [min_val, max_val].

---

### `def validate_is_dict_with_keys() -> Callable[[Any], tuple[bool, str | None]]`

Check that a value is a dict containing all required keys.

---

### `def validate_tool_input() -> Callable`

Decorator that validates MCP tool input parameters.

    ``validators`` maps parameter names to validator functions.
        Each validator returns ``(is_valid: bool, error_msg: str | None)``.
    
        Usage::
    
            @mcp.tool()
            @validate_tool_input(query=validate_non_empty, limit=validate_positive_int)
            async def search_decisions(source: str, query: str, limit: int = 10):
                ...

---

### `def get_active_requests() -> int`

Return the current number of active requests (informational).

---

### `def get_error_codes() -> dict[str, Any]`

Return the full error code catalog used in the project.

---

## `templates`

### `def get_template(name: str) -> dict[str, Any]`

Return a template by name.

    Returns a template dict on success, or a ``build_error()`` dict if the
        template name is not found.

---

### `def list_templates() -> list[dict[str, Any]]`

Return a list of all available templates with summary fields.

    Each entry contains ``name``, ``type``, and ``title``.

---

### `def render_template_to_skeleton(name: str) -> str`

Render a template as a draft-skeleton.md compatible markdown string.

    The output includes the ``DISCLAIMER_HEADER`` and follows the section
        heading / content format expected by the petition pack workflow.
    
        Returns the rendered markdown string, or raises ``KeyError`` if the
        template name is invalid.

---

### `def get_template_types() -> list[str]`

Return distinct template types across all templates.

---

### `def get_all_placeholders(name: str) -> list[str]`

Return all placeholder strings found in a template.

---

## `udf`

### `def get_udf_toolkit_status() -> dict`

Check whether the external UDF toolkit (libreoffice/unoconv etc.) is available.

    Returns a structured status dict regardless of toolkit presence.

---

### `def get_udf_authoring_instructions(format: str) -> dict`

Return UDF authoring instructions in the requested format.

    Args:
            format: 'json' for structured dict, 'markdown' for human-readable text.
    
        Returns:
            dict with format, instructions, and key warnings.

---

### `def read_udf(path: str | Path) -> str`

Read and extract text content from a UYAP UDF file.

    Args:
            path: Path to the UDF file (ZIP archive with content.xml).
    
        Returns:
            Extracted text content from the UDF.
    
        Raises:
            UdfError: If the file is missing, not a valid ZIP, or lacks content.xml.

---

### `def udf_to_markdown(path: str | Path) -> str`

Convert a UDF file content to formatted markdown with paragraph breaks.

    Args:
            path: Path to the UDF file.
    
        Returns:
            Markdown string with paragraphs separated by double newlines.

---

### `def write_udf(text: str, out_path: str | Path) -> Path`

Write a simple UYAP UDF (format_id=1.8). Caller must verify in UYAP editor.

---

### `def probe_udf(path: str | Path) -> dict`

Probe a UDF file for structure, format, and content metadata.

---

### `def convert_udf_to_docx(file_path: str | Path, out_path: str | Path | None) -> dict`

Convert a UDF file to DOCX using external toolkit (LibreOffice).

    If toolkit is disabled or missing, returns a structured error dict
        instead of raising.

---

### `def convert_udf_to_pdf(file_path: str | Path, out_path: str | Path | None) -> dict`

Convert a UDF file to PDF using external toolkit (LibreOffice).

    If toolkit is disabled or missing, returns a structured error dict.

---

### `def convert_docx_to_udf_experimental(file_path: str | Path, out_path: str | Path | None, experimental: bool) -> dict`

Convert a DOCX file to UDF format (experimental).

    Requires experimental=True. Always includes UYAP manual round-trip warning.
        If toolkit is disabled or missing, returns a structured error dict.

---

## `verification`

### `def smoke_test_offline() -> dict[str, Any]`

Offline smoke test: basic import and model validation.

---

### `def smoke_test_online(source: str) -> dict[str, Any]`

Online smoke test: basic source connectivity.

---

### `def check_cache_integrity(cache_path: str | Path | None) -> dict[str, Any]`

Check cache database integrity.

---

### `def verify_document_hash_in_cache(doc: Document, cache_path: str | Path | None) -> dict[str, Any]`

Verify document hash matches cache.

---

### `def verify_bundle_archive_integrity(bundle_path: str | Path) -> dict[str, Any]`

Verify ZIP bundle archive integrity.

---

## Coverage Summary

- **Total public functions:** 285
- **With docstrings:** 285
- **Coverage:** 100.0%
