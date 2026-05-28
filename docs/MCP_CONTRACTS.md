# docs/MCP_CONTRACTS.md — MCP Tool Contracts

## Tools

### `source_capabilities`

**Input**: none

**Output**: `list[dict]` — one entry per source, matching the JSON contract in
`docs/JSON_CONTRACTS.md`.

```json
[
  {"source_id": "bedesten", "display_name": "Bedesten/Yargıtay", "status": "stable", ...},
  ...
  {"source_id": "kik", "display_name": "Kamu İhale Kurumu / EKAP v2", "status": "unavailable", ...}
]
```

### `search_decisions`

**Input**:
- `source: str` — source_id (e.g. `"bedesten"`, `"aym"`)
- `query: str` — search query
- `limit: int = 10`
- `page: int = 1`

**Output**: `list[dict]` — each dict is a `SearchResult` dump.

**Errors**: raises `KeyError` for unknown sources. Registered unavailable sources
such as KIK return structured unavailable/metadata-only payloads instead of MCP
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

### `release_smoke` / `release_dashboard` / `release_notes_tool` / `release_archive`

Release management tools.

## Cache v2 Tools (v0.3)

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

## Structured error shape

Fatal/domain errors should use this JSON-compatible shape where possible:

```json
{
  "ok": false,
  "errorCode": "SOURCE_UNAVAILABLE",
  "message": "...",
  "source": "kik",
  "retryable": false,
  "details": {},
  "recommendedNextStep": "..."
}
```
