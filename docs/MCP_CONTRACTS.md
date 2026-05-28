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
