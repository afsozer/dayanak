# docs/MCP_CONTRACTS.md — MCP Tool Contracts

> **emsal-mcp v5.0.0** — 14 core MCP tools (default) · 82 tools in full profile.
> Input parameters use Python type hints; output shapes are documented per tool.
> Source of truth for profiles/categories: `src/emsal_mcp/tool_profile.py`.

## Tool Profiles (FAZ M / FAZ O)

The server exposes two tool profiles to control which MCP tools are registered:

| Profile | Tools | Description |
|---------|-------|-------------|
<!-- drift:core-tools-start -->
| `core` | 14 | Default. `search_decisions`, `get_document`, `search_local_corpus`, `search_legislation`, `get_legislation`, `research_topic`, `citation_check`, `prepare_petition`, `export_document`, `read_legal_file`, `list_sources`, `legal_research_guide`, `load_extended_tools`, `health_check`. |
<!-- drift:core-tools-end -->
| `full` | 82 | Core + all extended categories + legacy (facade-absorbed) tool names. |

Select via the `EMSAL_TOOL_PROFILE` environment variable:

```
EMSAL_TOOL_PROFILE=core   # default — 14 tools
EMSAL_TOOL_PROFILE=full   # all 82 tools
```

### `load_extended_tools`

Dynamically loads extended tool categories into the running server (core profile).

**Input**:
- `categories: list[str]` — Categories to load.

**Valid categories** (M-105 sonrası):
<!-- drift:categories-start -->
| Category | Tools |
|----------|-------|
| `health_admin` | circuit_breaker_status, source_health, source_smoke, check_government_servers_health |
| `citation_graph` | build_citation_graph, get_citation_graph, find_citing_documents, find_cited_documents, citation_graph_stats, export_citation_graph |
| `watch` | watch_add, watch_list, watch_run, watch_remove |
| `privacy` | privacy_scan, privacy_redact, privacy_audit |
| `chambers` | chamber_overview, profile_chamber, chamber_timeline, find_similar_chambers |
| `indexing` | index_status |
| `drafting_advanced` | inspect_petition_pack, build_multi_issue_pack, inspect_multi_issue_pack, list_petition_templates, get_petition_template, build_argument_chain, score_argument, get_argument_strength_report, draft_document, build_input_pack, prepare_drafting_input_pack |
| `udf_admin` | udf_toolkit_status, udf_authoring_instructions, pdf_toolkit_status, promote_pdf_to_full_text |
<!-- drift:categories-end -->

**Output**: `dict` — `ok`, `loaded_tools[]`, `already_loaded[]`, `errors[]`, `categories_requested`, `note`.

**Behavior**: Idempotent — already-loaded categories return `already_loaded`. Invalid category → structured `INVALID_INPUT` error with `valid_categories`. Registration failures land in `errors[]` (never silently reported as loaded).

> **M-105 (v5.0.0):** cache yönetimi, routing, dedup, index kurma ve taslak
> sürümleme araçları MCP yüzeyinden kaldırıldı; CLI'da yaşamaya devam ederler
> (`emsal-mcp cache/router/dedup/semantic ...`).

## Core Tools (v0.1–0.4)

### `source_capabilities`

**Input**: none

**Output**: `list[dict]` — one entry per source, matching the JSON contract in
`docs/JSON_CONTRACTS.md`.

```json
[
  {"source_id": "bedesten", "display_name": "Bedesten/Yargıtay", "status": "stable", ...},
  ...
  {"source_id": "kvkk", "display_name": "KVKK", "status": "experimental", ...}
]
```

### `search_decisions`

**Input**:
- `source: str` — source_id (e.g. `"bedesten"`, `"aym"`)
- `query: str` — search query
- `limit: int = 10`
- `page: int = 1`

**Output**: `list[dict]` — each dict is a `SearchResult` dump (now includes an
optional `snippet` field — a ~360-char passage around the query terms, populated
for free from the local corpus, or for the first 5 results when `include_snippets=true`).

**Errors**: raises `KeyError` for unknown sources. Registered partial/experimental
sources return structured unavailable/metadata-only payloads instead of MCP
tool errors.

### `get_document`

**Input**:
- `source: str` — source_id
- `document_id: str`

**Output**: `dict` — a `Document` dump.

**Errors**: same as `search_decisions`.

### `citation_safety`

**Input**:
- `document: dict` — a `Document` JSON blob

**Output**: `dict` — `CitationCheck` with keys `ok`, `quoteUsable`, `draftUsable`, `reasons`, `safety_state`.

### `build_input_pack`

**Input**:
- `matter: str`
- `issue: str`
- `documents: list[dict]` — list of `Document` JSON blobs

**Output**: `dict` — `InputPack` dump. Documents failing citation safety are excluded with reasons.

### `draft_document`

**Input**:
- `title: str`
- `body: str` — markdown body
- `documents: list[dict]` — supporting documents

**Output**: `dict` with key `markdown`.

### `export_bundle`

**Input**:
- `out_dir: str`
- `matter: str`
- `issue: str`
- `documents: list[dict]`

**Output**: `dict` with bundle path and manifest.

### `read_udf` / `write_udf`

UDF file operations (read/write round-trip).

> **M-103 (v5.0.0):** `release_smoke`, `release_dashboard`, `release_notes_tool`,
> `release_archive` MCP araçları kaldırıldı. Hazırlık kontrolü:
> CLI `emsal-mcp release v1-readiness --json`.

## Cache v2 Tools (v0.3)

> **M-105 (v5.0.0):** `get_cache_stats` ve `list_cached_documents` MCP'den
> kaldırıldı (CLI: `emsal-mcp cache ...`). `search_local_cache` yalnızca
> `full` profilde kayıtlıdır; core profilde karşılığı `search_local_corpus`
> facade'ıdır.

### `search_local_cache`

**Input**:
- `query: str = ""` — Free-text search (matches title, full_text, markdown)
- `source: str | None = None` — Filter by source
- `court: str | None = None` — Filter by court (partial match)
- `chamber: str | None = None` — Filter by chamber (partial match)
- `date: str | None = None` — Filter by decision_date (partial match)
- `esas_no: str | None = None` — Filter by esas_no (partial match)
- `karar_no: str | None = None` — Filter by karar_no (partial match)
- `document_id: str | None = None` — Filter by document_id (exact match)
- `content_status: str | None = None` — Filter by content_status
- `draft_usable: bool | None = None` — Filter by draft_usable flag
- `quote_usable: bool | None = None` — Filter by quote_usable flag
- `sort: str = "relevance"` — Sort order (see below)
- `limit: int = 20` — Maximum results

**Sort options**:
- `relevance` — Most recently fetched first
- `decision_date_desc` — Decision date newest first
- `decision_date_asc` — Decision date oldest first
- `fetched_at_desc` — Fetched at newest first
- `fetched_at_asc` — Fetched at oldest first

**Output**: `list[dict]` — each dict includes document metadata + `snippet` (text excerpt around match).

**No network**: searches only cached documents. Requires documents to be stored via `get_document` or CLI `get`.

### `get_cache_stats`

**Input**: none

**Output**: `dict` with keys:
- `documents_v2`: count of cached documents
- `documents_legacy`: count of legacy documents
- `cache_entries`: count of key-value cache entries
- `history_entries`: count of history entries
- `packs`: count of stored packs
- `drafts`: count of stored drafts
- `sources`: list of `{source, count}` per source
- `db_path`: path to cache database
- `db_size_bytes`: database file size

### `list_cached_documents`

**Input**:
- `source: str | None = None` — Filter by source
- `limit: int = 50` — Maximum results
- `offset: int = 0` — Offset for pagination

**Output**: `list[dict]` — list of cached document records.

## Capability-based routing

LLM agents can use `source_capabilities` to discover:
1. Which sources are `stable` / `partial` / `experimental` vs `unavailable`
2. Which sources have `supports_search` / `supports_document`
3. Known limitations before attempting queries
4. `live_smoke_recommended` for health monitoring

Example agent flow:
```
1. Call source_capabilities → get list
2. Filter for status=stable AND supports_search=true
3. For each matching source, call search_decisions
4. Use citation_safety to verify before quoting
5. Store documents via get_document for local cache
6. Use search_local_cache for offline search over cached documents
```

## Backward compatibility

- `source_capabilities` returns dicts with both `source_id` (snake_case) and
  v0.1 keys (`source`, `name`, `public`, `tools`, `citationSafeRule`,
  `noFabrication`) for legacy consumers.
- All document/search models retain their v0.1 field names.
- New fields are additive and optional for clients. Existing tool names must not
  be removed within the 0.x/1.x compatibility window; any rename must be added as
  an alias first.
- Cache v2 tools are additive; existing cache operations continue to work.

## Research v0.5 Tools

### `research_topic_tool`

**Input**:
- `query: str` — Research query string
- `sources: list[str] | None = None` — Source IDs to query (default: all searchable)
- `fetch_count: int = 5` — Max documents to fetch
- `filters: dict | None = None` — Search filters
- `output_dir: str | None = None` — Output directory

**Output**: `dict` — Bundle metadata with query, sources, result_count, fetched_count, content_status_summary, citation_safe_count, metadata_only_count, generated_files, warnings, recommended_next_steps.

### `refresh_research_bundle_tool`

**Input**:
- `bundle_path: str` — Path to bundle.json
- `dry_run: bool = False` — Compute diff without writing

**Output**: `dict` — Report with new_documents, changed_documents, hash_changed, new_count, changed_count.

### `research_quality_dashboard_tool`

**Input**:
- `bundle_path: str` — Path to bundle.json

**Output**: `dict` — Quality metrics: full_text_ratio, citation_safe_ratio, metadata_only_count, pdf_only_count, unavailable_count, source_distribution, missing_metadata_count, duplicate_citation_count, draft_readiness_score, recommendations.

## Citation v0.6 Tools

### `format_legal_citation`

**Input**:
- `document: dict | None = None` — Document dict with title, court, chamber, decision_date, esas_no, karar_no, source_url, content_status
- `style: str = "petition"` — Citation style: `"petition"`, `"parenthetical"`, or `"short"`
- `source: str | None = None` — Optional source for cache lookup
- `document_id: str | None = None` — Optional document ID for cache lookup

**Output**: `dict` — `formatted_citation`, `style`, `court`, `chamber`, `date`, `esas_no`, `karar_no`, `document_id`, `source`, `source_url`, `content_status`, `quote_usable`, `draft_usable`, `confidence`, `warnings`.

**Styles**:
- `petition`: "Yargıtay, 3. Hukuk Dairesi, E.2023/12345, K.2024/5678, Tarihi: 2024-06-15"
- `parenthetical`: "(Yargıtay, 3. Hukuk Dairesi, 2024-06-15, E.2023/12345, K.2024/5678)"
- `short`: "Ygt. 2023/12345"

**No fabrication**: missing metadata fields produce `warnings`, never invented values.

### `verify_legal_citation`

**Input**:
- `text: str | None = None` — Text to extract citations from
- `file_path: str | None = None` — Path to file to read
- `source: str | None = None` — Source filter for live search
- `limit: int = 10` — Max candidates to process
- `fetch: bool = True` — Whether to fetch matching documents
- `no_live: bool = False` — Skip live search (cache only)
- `live_only: bool = False` — Skip cache search (live only)
- `min_score: float = 0.0` — Minimum match score threshold

**Output**: `dict` — `ok`, `candidates[]` (index, raw_text, parsed, confidence, field_count, warnings), `search_attempts[]`, `matched_documents[]`, `formatted_citations[]`, `verification_findings` (total_candidates, searched, matched, matched_via_cache, matched_via_live, unmatched), `warnings`, `recommended_next_steps`, `timing` (extraction_ms, search_ms, total_ms).

**Pipeline**: extract candidates → local cache search (unless `live_only`) → live search (unless `no_live`) → rank by metadata match score → optionally fetch → format citations.

## Structured error shape

Fatal/domain errors should use this JSON-compatible shape where possible:

```json
{
  "ok": false,
  "errorCode": "SOURCE_UNAVAILABLE",
  "message": "...",
  "source": "rekabet",
  "retryable": false,
  "details": {},
  "recommendedNextStep": "..."
}
```

## Petition v0.7 Tools

### `prepare_drafting_input_pack`

**Input**:
- `matter: str` — Legal matter (e.g. "Konut tahliye davası")
- `issue: str` — Specific issue (e.g. "Kira sözleşmesi feshi")
- `docs_json: str | None = None` — JSON file with document list
- `research_bundle: str | None = None` — Path to research bundle directory
- `out_dir: str | None = None` — Output directory for petition pack
- `strict: bool = False` — Require at least one petition_ready authority

**Output**: `dict` — `ok`, `pack_dir`, `matter`, `issue`, `pack_version`, `classification` (petition_ready_count, citation_only_count, research_lead_only_count, excluded_count, total), `created_at`, `files[]`, `source_documents`, `warnings[]`, `recommended_next_steps[]`.

**Authority classification**:
- `petition_ready`: citation_check passes, full_text/html_markdown, text ≥ 50 chars, provenance present → draft usable
- `citation_only`: metadata-only or PDF link only → reference only, bibliography restricted
- `research_lead_only`: citation_check fails but has some metadata → research direction
- `excluded`: safety check fails, hash mismatch, unavailable → removed

**Invariants**:
- metadata_only and pdf_only documents are NEVER petition_ready
- Hash mismatches cause exclusion
- No-invention enforcement in petition-instructions.md

**Output files**: petition-brief.json, citation-bank.md, argument-map.md, petition-instructions.md, draft-skeleton.md, petition-pack.json, hash-manifest.json, source-documents/*.md

### `inspect_petition_pack`

**Input**:
- `pack_dir: str` — Path to petition pack directory

**Output**: `dict` — `ok`, `pack_dir`, `draft_safe`, `pack_version`, `errors[]`, `warnings[]`, `counts` (total_documents, petition_ready, citation_only, research_lead_only, excluded), `checks` (8 validation checks), `recommended_next_steps[]`.

**8 inspection checks**:
1. `required_files_present` — All 7 required files exist
2. `draft_safe_flag_correct` — draft_safe flag matches authority classification
3. `placeholders_in_draft_skeleton` — Placeholder count preserved
4. `legislation_verified_placeholder` — No hardcoded unverified law refs
5. `petition_instructions_forbids_invention` — No-invention rule present
6. `citation_bank_only_safe_docs` — No excluded docs in citation bank
7. `hash_manifest_valid` — Content hashes match source documents
8. `metadata_only_draft_usable` — metadata_only never marked draft usable

## Petition v0.8 Tools

### `prepare_petition_outline`

**Input**:
- `pack_dir: str` — Path to petition pack directory
- `out_dir: str | None = None` — Output directory for outline.json

**Output**: `dict` with keys:
- `ok: bool`
- `outline_path: str` — Path to generated outline.json
- `sections: list[dict]` — Section descriptors with id, title, type, placeholders, authorities
- `placeholder_total: int` — Total placeholder count across all sections
- `citation_only_bibliography_count: int` — citation_only authorities in bibliography
- `petition_ready_count: int` — petition_ready authorities

**Invariants**:
- Only `petition_ready` authorities appear in `decisions` and `explanations` sections
- `citation_only` authorities appear only in `bibliography` section with warning flags
- Disclaimer section is always first

### `prepare_controlled_petition_draft`

**Input**:
- `pack_dir: str` — Path to petition pack directory
- `outline_path: str | None = None` — Pre-computed outline.json path
- `out_dir: str | None = None` — Output directory for draft files

**Output**: `dict` with keys:
- `ok: bool`
- `out_dir: str` — Output directory path
- `draft_md_path: str` — Path to draft.md
- `draft_json_path: str` — Path to draft.json
- `footnotes_path: str` — Path to footnotes.json
- `warnings_path: str` — Path to warnings.json
- `draft_metadata: dict` — Full draft.json content (paragraph_count, section_count, etc.)

**Output files**:
- `draft.md`: Markdown with disclaimer, sections, footnotes, placeholders
- `draft.json`: Metadata with counts and readiness scoring
- `footnotes.json`: petition_ready footnotes + citation_only bibliography
- `warnings.json`: blocking/warning/info level warnings

**Invariants**:
- `citation_only` authorities never appear in direct quotes or footnotes
- All `{{…}}` placeholders preserved verbatim
- Disclaimer header always present

### `prepare_docx_export`

**Input**:
- `draft_path: str | None = None` — Path to draft.md
- `draft_json: dict | None = None` — Draft metadata dict
- `out_path: str | None = None` — Output DOCX path
- `pack_dir: str | None = None` — Pack directory for footnotes

**Output**: `dict` with keys:
- `ok: bool`
- `out_path: str` — Path to generated DOCX
- `checksum_sha256: str` — SHA-256 of DOCX file
- `file_size: int` — File size in bytes
- `validation: dict` — Validation results:
  - `zip_valid: bool` — DOCX is valid ZIP
  - `disclaimer_present: bool` — Disclaimer text in body
  - `footnotes_consistent: bool` — Footnote count matches petition_ready
  - `placeholders_preserved: bool` — All `{{…}}` patterns present
  - `validation_warnings: list[str]` — Non-fatal warnings
  - `export_readiness: bool` — All checks pass

### `prepare_export_package_bundle`

**Input**:
- `pack_dir: str` — Path to petition pack directory
- `draft_dir: str | None = None` — Draft output directory
- `docx_path: str | None = None` — Path to draft.docx
- `out_dir: str | None = None` — Output bundle directory

**Output**: `dict` with keys:
- `ok: bool`
- `bundle_dir: str` — Bundle directory path
- `manifest: dict` — Manifest with version, file_count, files (sha256+size per file)
- `hash_manifest: dict` — Flat SHA-256 map of all files
- `verification: list[str]` — Verification.txt content lines
- `files: list[str]` — List of files written
- `warnings: list[str]` — Any warnings during creation
- `post_verification: dict` — Integrity check results:
  - `ok: bool`
  - `errors: list[str]`
  - `checks: dict` — hash_manifest_valid, required_files_present, manifest_valid_json, docx_zip_valid

**Bundle contents**:
- petition-pack.json, citation-bank.md, argument-map.md, petition-instructions.md, draft-skeleton.md
- source-documents/*.md
- draft.md, draft.json, footnotes.json, warnings.json (if draft_dir exists)
- draft.docx (if docx_path provided)
- manifest.json, hash-manifest.json, verification.txt

## UDF Toolkit v0.9 Tools

### `udf_toolkit_status`

**Input**: none

**Output**: `dict` — toolkit availability status with `ok`, `enabled`, `toolkit_dir`, `libreoffice_path`, `unoconv_path`, `version`, `warnings`.

### `udf_authoring_instructions`

**Input**:
- `format: str = "json"` — `"json"` or `"markdown"`

**Output**: `dict` — authoring steps, warnings, version. JSON format includes `toolkit_status`.

### `convert_udf_to_docx_tool`

**Input**:
- `file_path: str` — UDF file to convert
- `out_path: str | None = None` — Output DOCX path

**Output**: `dict` — `ok`, `out_path`, `file_size`, `warning` on success; `error`, `message`, `toolkit_status` on failure.

### `convert_udf_to_pdf_tool`

**Input**:
- `file_path: str` — UDF file to convert
- `out_path: str | None = None` — Output PDF path

**Output**: `dict` — same contract as `convert_udf_to_docx_tool`.

### `convert_docx_to_udf_experimental_tool`

**Input**:
- `file_path: str` — DOCX file to convert
- `out_path: str | None = None` — Output UDF path
- `experimental: bool = False` — Must be `True` to proceed

**Output**: `dict` — `ok`, `out_path`, `file_size`, `warning`, `experimental`, `text_length` on success; `error`, `message` on failure.

## Legislation v0.10 Tools

### `search_legislation`

**Input**:
- `query: str` — Search phrase
- `sources: list[str] | None = None` — Source IDs (default: `["mevzuat"]`)
- `legislation_type: str | None = None` — Filter by type (e.g. "Kanun", "Yönetmelik")
- `limit: int = 10` — Max results

**Output**: `dict` — `ok`, `query`, `sources`, `legislation_type`, `total_results`, `results[]` (document_id, source, title, legislation_no, gazette_date, legislation_type, legislation_type_id, type_confidence, summary, content_status, court), `warnings`, `recommended_next_steps`, `version`, `rule`.

### `get_legislation_document`

**Input**:
- `document_id: str` — Mevzuat document ID
- `source: str | None = None` — Source ID (default: `"mevzuat"`)

**Output**: `dict` — `ok`, `document_id`, `source`, `title`, `legislation_no`, `gazette_date`, `legislation_type`, `content_status`, `content_hash`, `citation_check` (ok, quote_usable, draft_usable, warnings), `article_count`, `text_length`, `warnings`, `recommended_next_steps`, `version`, `rule`.

### `search_legislation_articles`

**Input**:
- `document_id: str` — Mevzuat document ID
- `article_number: str | None = None` — Specific article number
- `article_query: str | None = None` — Keyword search in article text
- `source: str | None = None` — Source ID (default: `"mevzuat"`)

**Output**: `dict` — `ok`, `document_id`, `source`, `title`, `article_number`, `article_query`, `total_articles_found`, `matching_articles[]` (number, text, preview), `content_status`, `warnings`, `recommended_next_steps`, `version`, `rule`.

### `get_legislation_article_tree`

**Input**:
- `document_id: str` — Mevzuat document ID
- `source: str | None = None` — Source ID (default: `"mevzuat"`)

**Output**: `dict` — `ok`, `document_id`, `source`, `title`, `article_count`, `section_count`, `part_count`, `tree` (parts → sections → articles), `flat_article_list[]`, `warnings`, `recommended_next_steps`, `version`, `rule`.

### `get_legislation_gerekce`

**Input**:
- `document_id: str` — Mevzuat document ID
- `source: str | None = None` — Source ID (default: `"mevzuat"`)

**Output**: `dict` — `ok`, `document_id`, `source`, `title`, `found`, `genel_gerekce`, `madde_gerekceleri[]` (article, gerekce), `raw_text`, `warnings`, `recommended_next_steps`, `version`, `rule`.

### `legislation_source_status`

**Input**: none

**Output**: `dict` — `ok`, `sources[]`, `overall_ok`, `source_count`, `healthy_sources`, `degraded_sources`, `warnings`, `recommended_next_steps`, `version`, `rule`.

### `format_legislation_citation`

**Input**:
- `document: dict | None = None` — Document dict with title, legislation_no, gazette_date
- `style: str = "full"` — `"full"`, `"short"`, or `"article"`

**Output**: `dict` — `formatted_citation`, `style`, `legislation_no`, `gazette_date`, `legislation_type`, `title`, `warnings`.

### `get_legislation_types`

**Input**: none

**Output**: `list[dict]` — each `{type_id, display_name}` for 11 Turkish legislation types.

## Semantic Search v0.11 Tools

### `build_semantic_index`

**Input**:
- `force_rebuild: bool = False` — Drop and recreate all indices

**Output**: `dict` — `ok`, `fts5_exists`, `fts5_row_count`, `vectors_count`, `documents_total`, `warnings`, `recommended_next_steps`, `version`.

### `semantic_search`

**Input**:
- `query: str` — Search query string
- `limit: int = 10` — Max results
- `filters: dict | None = None` — Metadata filters (source, court, chamber, content_status, quote_usable, draft_usable)

**Output**: `dict` — `ok`, `query`, `results[]` (document_id, source, title, court, chamber, decision_date, score, snippet, content_status, quote_usable, draft_usable), `total_matches`, `method` (`"tfidf_cosine"`), `warnings`, `version`.

### `hybrid_search`

**Input**:
- `query: str` — Search query string
- `limit: int = 10` — Max results
- `filters: dict | None = None` — Metadata filters
- `hybrid_weight: float = 0.6` — Balance 0.0–1.0 (0.0 = pure semantic, 1.0 = pure BM25)

**Output**: `dict` — `ok`, `query`, `results[]` (document_id, source, title, court, chamber, decision_date, bm25_score, cosine_score, hybrid_score, snippet, content_status, quote_usable, draft_usable), `total_matches`, `method` (`"hybrid"`), `hybrid_weight`, `warnings`, `recommended_next_steps`, `version`.

### `index_status`

**Input**: none

**Output**: `dict` — `ok`, `fts5_exists`, `fts5_document_count`, `vectors_table_exists`, `vectors_count`, `total_cached_documents`, `unindexed_documents`, `warnings`, `recommended_next_steps`, `version`.

### `rebuild_search_index`

**Input**: none

**Output**: `dict` — Same as `build_semantic_index` with `force_rebuild=True`. Drops and recreates all FTS5 and TF-IDF indices.

## Chamber Profiling v0.12 Tools

### `chamber_overview`

**Input**:
- `court: str | None = None` — Optional court name filter

**Output**: `dict` — `ok`, `court_filter`, `total_chambers`, `total_documents`, `chambers[]` (court, chamber, document_count, content_available_count, earliest_date, latest_date, recent_count), `warnings`, `recommended_next_steps`, `version`.

### `profile_chamber`

**Input**:
- `chamber: str` — Chamber name (e.g. "3. Hukuk Dairesi")
- `court: str | None = None` — Optional court name filter

**Output**: `dict` — `ok`, `chamber`, `court_filter`, `metrics` (total_documents, content_available_count, content_status_distribution, quote_usable_count, draft_usable_count, earliest_date, latest_date, date_range_years), `top_keywords[]` (word, count), `recent_documents[]` (document_id, title, decision_date), `warnings`, `recommended_next_steps`, `version`.

### `chamber_timeline`

**Input**:
- `chamber: str | None = None` — Optional chamber filter
- `court: str | None = None` — Optional court filter
- `start_year: int | None = None` — Start year (inclusive)
- `end_year: int | None = None` — End year (inclusive)

**Output**: `dict` — `ok`, `chamber_filter`, `court_filter`, `year_range` (start, end), `total_documents`, `timeline[]` (year, count), `warnings`, `version`.

### `find_similar_chambers`

**Input**:
- `chamber: str` — Target chamber name
- `court: str | None = None` — Optional court filter
- `limit: int = 5` — Max results

**Output**: `dict` — `ok`, `target_chamber`, `similar_chambers[]` (chamber, court, similarity_score, shared_keywords, document_count), `warnings`, `recommended_next_steps`, `version`.

## Release Tools

> **M-103 (v5.0.0):** Release yönetimi araçları MCP yüzeyinden kaldırıldı.
> Hazırlık kontrolü CLI'dadır: `emsal-mcp release v1-readiness --json`.
