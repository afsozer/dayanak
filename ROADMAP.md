# ROADMAP.md — Emsal-mcp Roadmap

## Vision

Emsal-mcp is a citation-safe MCP legal research and document drafting system.

## v0.1 (shipped)

- Basic source clients: bedesten, yargitay, mevzuat, aym, danistay, gib,
  uyusmazlik, rekabet, sayistay
- Citation safety checks (`citation_check`, `exact_quote`)
- UDF read/write round-trip
- Export bundle (DOCX + ZIP manifest with hashes)
- Offline smoke test
- CLI (`emsal-mcp`) and MCP server (`emsal-mcp-server`)

## v0.2 — Contract Foundation

- `SourceCapability` model with typed capability descriptors
- `SourceStatus` enum: `stable`, `partial`, `experimental`, `unavailable`
- `to_legacy_dict()` for backward compatibility
- KIK unavailable placeholder in capability matrix
- Content-status enrichment fields on search/document models
- Per-source known_limitations
- Documentation: `docs/JSON_CONTRACTS.md`, `docs/MCP_CONTRACTS.md`
- Tests: capability model, KIK graceful degradation, CLI JSON shape

## v0.3 — Cache v2 + Local Search (current)

### Cache v2 Schema (`cache.py`)

Extended `documents_v2` table with rich metadata and access tracking:

| Column | Type | Description |
|---|---|---|
| `document_id` | TEXT | Document identity (part of PK) |
| `source` | TEXT | Source identifier (part of PK) |
| `title` | TEXT | Document title |
| `court` | TEXT | Court name |
| `chamber` | TEXT | Chamber/daire |
| `decision_date` | TEXT | Decision date (ISO or source format) |
| `esas_no` | TEXT | Case number |
| `karar_no` | TEXT | Decision number |
| `source_url` | TEXT | Source URL |
| `content_status` | TEXT | Content availability status |
| `markdown` | TEXT | Markdown content |
| `full_text` | TEXT | Full text content |
| `content_hash` | TEXT | SHA-256 content hash |
| `metadata_json` | TEXT | JSON metadata blob |
| `raw_json` | TEXT | Raw response JSON |
| `retrieved_at` | DATETIME | When document was fetched |
| `last_accessed_at` | DATETIME | Last access time |
| `access_count` | INTEGER | Number of times accessed |
| `quote_usable` | INTEGER | Boolean: safe for quotation |
| `draft_usable` | INTEGER | Boolean: safe for drafting |
| `metadata_confidence` | TEXT | high/medium/low |
| `warnings_json` | TEXT | JSON warnings list |

### `CachedDocument` Model (`models.py`)

Pydantic model with `from_document()` and `to_document()` round-trip.

### Local Search Service

Query cached documents with:
- **Filters**: source, court, chamber, date, esas_no, karar_no, document_id, content_status, draft_usable, quote_usable
- **Sorts**: relevance, decision_date_desc, decision_date_asc, fetched_at_desc, fetched_at_asc
- **Snippets**: text excerpts around query matches
- **No network**: purely local SQLite search

### CLI Cache Subcommands

```
emsal-mcp cache stats           # Cache statistics
emsal-mcp cache list            # List cached documents
emsal-mcp cache search-local    # Local search with filters
emsal-mcp cache delete <id> <src>  # Delete cached document
emsal-mcp cache prune           # Remove old search cache entries
emsal-mcp cache backup <path>   # Backup cache database
emsal-mcp cache export <path>   # Export to JSON
emsal-mcp cache import <path>   # Import from JSON
```

### MCP Cache Tools

- `search_local_cache`: Local search over cached documents
- `get_cache_stats`: Cache statistics
- `list_cached_documents`: List cached documents with optional filters

### CLI Integration

- `emsal-mcp get` now stores documents via `store_document()` in both legacy and v2 tables
- `emsal-mcp search` stores search results in cache

### Backward Compatibility

- Legacy `documents` table preserved alongside `documents_v2`
- All v0.2 tests continue to pass
- `store_document()` writes to both tables

## v0.4 — Adapter Hardening & Source Smoke Contracts

### Source Smoke Layer

- **`SourceSmokeResult` model**: typed per-source smoke result with
  `offline_ok`, `online_ok`, `search_callable`, `get_document_callable`,
  `min_content_length_ok`, `warnings`, `errors`.
- **`SourceClient.smoke()`**: offline-safe default; each source overrides
  for source-specific warnings.
- **`smoke_all()` / `smoke_all_sync()`**: run smoke across all sources.
- **CLI `sources-smoke`**: `--offline` (default) / `--online` opt-in.
- **MCP `source_smoke` tool**: callable from MCP clients.
- **Release integration**: `release_smoke()` includes source smoke summaries.

### Base Utility Hardening

- `decode_b64()`: returns empty bytes on failure (no false `full_text`).
- `check_http_response()`: consistent 4xx/5xx handling.
- `finalize_document()`: min content length sanity (50 chars), auto
  content_hash, structured warnings.
- User-Agent: `EmsalMcp/{version}` with GitHub URL.

### Adapter Correctness (local-yargi patterns)

- **Bedesten/Yargıtay**: `item_type` normalization, `source_id`
  preservation via `_default_item_type`, `decode_b64` failure → UNAVAILABLE.
- **Mevzuat**: `mevzuatAdi` title priority, `decode_b64` failure handling,
  `experimental` status.
- **AYM**: fallback `metadata_only` on short content.
- **Danıştay**: `Accept` header, min content check.
- **GİB**: query normalization dict, HTML-stripped titles.
- **Uyuşmazlık/Rekabet/Sayıştay**: graceful `UNAVAILABLE` on parser
  failures; `finalize_document` applied.

### Tests

- 73 new adapter tests (mocked httpx, contract tests, CLI smoke).
- Total: 199 tests, all passing.

### Backward Compatibility

- All v0.3 tests pass (199/199).
- New models/functions are additive; no breaking changes.

## Future (v0.5+)

- Live smoke tests with configurable rate limits
- Partial sources (`status: "partial"`) for degraded-access scenarios
- Capability-based tool routing in MCP (auto-select sources by capability)
- Source health monitoring and circuit-breaker patterns
- Cache sync between multiple instances
- Full-text search index optimization

## v0.10 — Legislation (Mevzuat) Module (current)

### Legislation Search

- **`search_legislation()`**: search Mevzuat source with optional legislation type
  filter (Kanun, KHK, Yönetmelik, etc.).  Returns structured dict with ok, query,
  results, total_results, legislation_type, warnings, recommended_next_steps.
  Uses heuristic classification on title/metadata for result enrichment.

### Document Fetch

- **`get_legislation_document()`**: fetch full legislation document with
  citation_check integration, article count, and content status.  Returns
  ok, document fields, citation_check (ok, quote_usable, draft_usable),
  article_count, text_length.

### Article Search

- **`search_legislation_articles()`**: search articles within a document by
  article number or keyword query.  Parses MADDE entries from legislation text.
  Returns ok, matching_articles with number/text/preview, total_articles_found.

### Article Tree

- **`get_legislation_article_tree()`**: builds hierarchical part → section →
  article tree from legislation text.  Recognizes KISIM (part) and BÖLÜM
  (section) headers.  Returns tree, flat_article_list, part_count, section_count,
  article_count.  Flat texts without hierarchy markers produce zero counts.

### Gerekçe (Rationale) Extraction

- **`get_legislation_gerekce()`**: extracts GENEL GEREKÇE (general rationale)
  and MADDE GEREKÇELERİ (per-article rationales) from legislation text.  Parses
  individual madde gerekçeleri into structured list.  Returns ok, found,
  genel_gerekce, madde_gerekceleri.

### Source Health

- **`get_legislation_source_status()`**: aggregate Mevzuat source health via
  smoke tests.  Returns overall_ok, healthy_sources, degraded_sources.

### Citation Formatting

- **`format_legislation_citation()`**: format legislation citations with styles
  full, short, article.  Includes legislation_no, gazette_date, title.

### Legislation Types

- **`get_legislation_types()`**: returns list of 11 Turkish legislation types
  with type_id and display_name (Kanun, KHK, CBK, Yönetmelik, Tebliğ, Genelge,
  Yönerge, Tüzük, Uluslararası Anlaşma, Anayasa, Diğer).

### Classification

- **`_classify_type()`**: heuristic regex-based classification of legislation
  documents into types.  Considers title and metadata fields (mevzuatTur,
  documentType).  Returns type_id, display_name, confidence.  Never fabricates.

### CLI Commands

```
emsal-mcp legislation search <query> [--legislation-type] [--limit] [--json]
emsal-mcp legislation get <document_id> [--source] [--json]
emsal-mcp legislation articles <document_id> [--article-number] [--article-query] [--json]
emsal-mcp legislation tree <document_id> [--source] [--json]
emsal-mcp legislation gerekce <document_id> [--source] [--json]
emsal-mcp legislation status [--json]
emsal-mcp legislation types [--json]
emsal-mcp legislation format [--title] [--legislation-no] [--gazette-date] [--style] [--json]
```

### MCP Tools

- `search_legislation`: search Mevzuat source with type filter
- `get_legislation_document`: fetch full legislation document
- `search_legislation_articles`: search articles within document
- `get_legislation_article_tree`: build part/section/article hierarchy
- `get_legislation_gerekce`: extract rationale sections
- `legislation_source_status`: check source health
- `format_legislation_citation`: format legislation citations
- `get_legislation_types`: list known legislation types

### Backward Compatibility

- All v0.9 tests pass (442 total tests).
- New module is additive; no breaking changes.
- New CLI commands and MCP tools are additive.

## v0.5 — Research Workflow Bundles (current)

### Research Pipeline

- **`research_topic()`**: search sources, fetch documents, build output directory
  with `bundle.json`, `results.json`, `documents/*.md`, `manifests/hash-manifest.json`,
  `warnings.json`, and `index.md`. Structured output with query, sources, filters,
  result_count, fetched_count, content_status_summary, citation_safe_count,
  metadata_only_count, generated_files, warnings, recommended_next_steps.
- **`refresh_research_bundle()`**: re-run research from existing bundle, detect
  new/changed documents via hash comparison, support `dry_run`, preserve manual
  notes in `index.md` between markers.
- **`research_quality_dashboard()`**: compute full_text_ratio, citation_safe_ratio,
  metadata_only_count, pdf_only_count, unavailable_count, source_distribution,
  missing_metadata_count, duplicate_citation_count, draft_readiness_score,
  recommendations.

### Testability

- All research functions accept `sources_override` dict for injecting fake source
  clients. Tests use deterministic fake clients with zero network calls.

### CLI Commands

```
emsal-mcp research topic <query> [--sources s1,s2] [--fetch-count 5] [--json]
emsal-mcp research refresh <bundle.json> [--dry-run] [--json]
emsal-mcp research dashboard <bundle.json> [--json]
```

### MCP Tools

- `research_topic_tool`: search + fetch + bundle creation
- `refresh_research_bundle_tool`: re-run + diff detection
- `research_quality_dashboard_tool`: quality metrics

### Bundle Structure

```
research_output/
├── index.md
├── bundle.json
├── results.json
├── warnings.json
├── documents/
│   ├── source_docid.md
│   └── ...
└── manifests/
    └── hash-manifest.json
```

### Backward Compatibility

- All v0.4 tests pass.
- New module is additive; no breaking changes.

## v0.6 — Citation Verification + Citation Formatting

### Citation Extraction

- **`extract_citation_candidates()`**: regex-based extraction of Turkish legal
  citation patterns from text.  Detects Yargıtay, Danıştay, AYM, Sayıştay,
  Rekabet Kurulu, Ticaret Mahkemesi, and more.  Extracts court, chamber,
  date (DD.MM.YYYY / YYYY-MM-DD / Turkish month names), esas_no, karar_no,
  and document_id-like references.
- **Confidence scoring**: high (5+ fields), medium (3-4 fields), low (<3 fields).
  Missing fields produce warnings, never fabricated values.

### Citation Formatting

- **`format_legal_citation()`**: format a citation from Document model or dict.
  Three styles:
  - `petition`: "Yargıtay, 3. Hukuk Dairesi, E.2023/12345, K.2024/5678, Tarihi: 2024-06-15"
  - `parenthetical`: "(Yargıtay, 3. Hukuk Dairesi, 2024-06-15, E.2023/12345, K.2024/5678)"
  - `short`: "Ygt. 2023/12345"
- **Output contract**: formatted_citation, style, court, chamber, date, esas_no,
  karar_no, document_id, source, source_url, content_status, quote_usable,
  draft_usable, confidence, warnings.
- **No fabrication**: missing metadata fields produce warnings, never invented
  values.

### Verification Pipeline

- **`verify_legal_citation()`**: full pipeline — load text/file, extract
  candidates, search local cache (unless `live_only`), live search (unless
  `no_live`), rank by metadata match score, optionally fetch docs, return
  structured result.
- **Output contract**: ok, candidates, search_attempts, matched_documents,
  formatted_citations, verification_findings, warnings, recommended_next_steps,
  timing.
- **Testability**: `no_live` and `live_only` flags; `cache` and `sources_override`
  parameters for injecting fakes.  No live network in tests.

### CLI Commands

```
emsal-mcp cite format <document_id> [--source bedesten] [--style petition] [--json]
emsal-mcp cite verify [--text "..."] [--file-path path.txt] [--no-live] [--json]
```

### MCP Tools

- `format_legal_citation`: format citation from document metadata
- `verify_legal_citation`: verify citations in text/file

### Backward Compatibility

- All v0.5 tests pass.
- New module is additive; no breaking changes.

## v0.7 — Petition Pack v2 + Inspect

### Petition Pack Workflow

- **`prepare_drafting_input_pack()`**: classifies authorities as
  `petition_ready`, `citation_only`, `research_lead_only`, or `excluded`
  using citation safety, content_status, metadata/provenance, and
  content_hash.  Generates structured pack directory.

### Authority Classification

| Category | Criteria | Draft Usable |
|---|---|---|
| `petition_ready` | citation_check passes, full_text/html_markdown, text >= 50 chars, provenance present | Yes |
| `citation_only` | citation_check passes on metadata, or PDF link only | No (reference only) |
| `research_lead_only` | citation_check fails but has some metadata | No (research direction) |
| `excluded` | safety check fails, hash mismatch, or unavailable | No |

### Pack Directory Structure

```
petition_pack/
├── petition-brief.json       # Authority classification metadata
├── citation-bank.md          # Citation-safe reference list
├── argument-map.md           # Authority classification map
├── petition-instructions.md  # No-invention rules
├── draft-skeleton.md         # Petition template with {{PLACEHOLDER}}
├── petition-pack.json        # Pack metadata
├── hash-manifest.json        # Content hashes for source documents
└── source-documents/
    ├── source_docid.md       # Full-text docs for safe authorities
    └── ...
```

### Inspection (`inspect_petition_pack`)

Validates pack directory with checks:
- Required files present
- `draft_safe` flag correctness
- `placeholdersInDraftSkeleton`: placeholder count preserved
- `legislationVerifiedPlaceholder`: no hardcoded unverified law refs
- `petitionInstructionsForbidsInvention`: no-invention rule present
- `citationBankOnlySafeDocs`: no excluded docs in citation bank
- `hashManifestValid`: content hashes match source documents
- `metadataOnlyDraftUsable`: metadata_only never marked draft usable

### CLI Commands

```
emsal-mcp petition pack <matter> <issue> [--docs-json path] [--research-bundle dir] [--out-dir dir] [--json]
emsal-mcp petition inspect <pack_dir> [--json]
```

### MCP Tools

- `prepare_drafting_input_pack`: classify authorities and generate pack
- `inspect_petition_pack`: validate pack directory

### Backward Compatibility

- All v0.6 tests pass.
- New module is additive; no breaking changes.

## v0.8 — Controlled Draft + DOCX/Export Validation

### Controlled Draft Pipeline

- **`prepare_petition_outline(pack_dir, out_dir=None)`**: generates a
  structured outline from a petition pack with sections, placeholders,
  and authority classification per section.  Only `petition_ready`
  authorities may supply direct content; `citation_only` authorities
  appear only in the bibliography section with a warning flag.

- **`prepare_controlled_petition_draft(pack_dir, outline_path=None,
  out_dir=None)`**: produces a controlled petition draft with:

#### Draft Output Files

| File | Description |
|---|---|
| `draft.md` | Markdown draft with disclaimer, sections, footnotes |
| `draft.json` | Metadata: paragraph/section/footnote/placeholder counts, readiness scoring |
| `footnotes.json` | Footnote references (petition_ready only) + citation_only bibliography |
| `warnings.json` | Warnings with blocking/warning/info levels |

#### Draft Metadata (`draft.json`)

| Field | Type | Description |
|---|---|---|
| `paragraph_count` | int | Number of non-empty paragraphs |
| `section_count` | int | Number of `##` sections |
| `footnote_count` | int | Number of footnote references |
| `placeholder_count` | int | Number of `{{…}}` patterns |
| `blocking_warning_count` | int | Critical warnings preventing use |
| `readiness_score` | float | 0.0–1.0 based on petition_ready ratio |
| `readiness_level` | string | `high`/`medium`/`low`/`none` |
| `finalization_risk_score` | float | 0.0–1.0 risk of issues |

### Safety Invariants

- **No metadata-only leak**: `citation_only` authorities never appear in
  direct quotes or footnotes; restricted to bibliography only.
- **Placeholder preservation**: all `{{…}}` patterns from draft-skeleton.md
  are preserved verbatim in draft output.
- **Disclaimer header**: automatic warning that document requires attorney
  review and placeholders must be filled with verified information only.

### DOCX Export Validation

- **`prepare_docx_export(draft_path or draft_json, out_path, pack_dir=None)`**:
  creates validated DOCX with:
  - Disclaimer header paragraph
  - Body content from draft.md
  - Footnotes/citations section from pack
  - Placeholder preservation
  - Returns validation dict:

| Validation Field | Type | Description |
|---|---|---|
| `zip_valid` | bool | DOCX opens as valid ZIP |
| `disclaimer_present` | bool | Disclaimer text found in body |
| `footnotes_consistent` | bool | Footnote count matches petition_ready |
| `placeholders_preserved` | bool | All `{{…}}` patterns present |
| `validation_warnings` | list | Non-fatal warnings |
| `export_readiness` | bool | All checks pass |

### Export Package Bundle v2

- **`prepare_export_package_bundle(pack_dir, draft_dir/docx, out_dir)`**:
  creates complete bundle with:
  - Draft files: draft.md, draft.json, footnotes.json, warnings.json
  - Pack files: petition-pack.json, citation-bank.md, source-documents/
  - Verification: manifest.json, hash-manifest.json, verification.txt
  - Post-creation verification of hash integrity and file presence

### CLI Commands

```
emsal-mcp petition outline <pack_dir> [--out-dir] [--json]
emsal-mcp petition draft <pack_dir> [--outline-path] [--out-dir] [--json]
emsal-mcp petition export-docx [--draft-path] [--draft-json-path] [--out-path] [--pack-dir] [--json]
emsal-mcp petition export-bundle <pack_dir> [--draft-dir] [--docx-path] [--out-dir] [--json]
```

### MCP Tools

- `prepare_petition_outline`: generate structured outline from pack
- `prepare_controlled_petition_draft`: generate controlled draft with scoring
- `prepare_docx_export`: create validated DOCX export
- `prepare_export_package_bundle`: create complete export bundle

### Backward Compatibility

- All v0.7 tests pass.
- New module is additive; no breaking changes.
- Existing pack files remain readable by new functions.

## v0.9 — UDF Toolkit Integration

### UDF Toolkit Status

- **`get_udf_toolkit_status()`**: checks external UDF toolkit (LibreOffice/
  unoconv) availability. Reads from `EMSAL_UDF_TOOLKIT_DIR` or `UDF_TOOLKIT_DIR`
  environment variables. Returns `ok`, `enabled`, `toolkit_dir`, `libreoffice_path`,
  `unoconv_path`, `version`, `warnings`. Never raises.

- **`get_udf_authoring_instructions(format='json|markdown')`**: returns structured
  authoring steps and warnings in JSON or markdown format. Includes toolkit status
  in JSON mode.

### Safe Wrappers

| Function | Description | Toolkit Required |
|---|---|---|
| `convert_udf_to_docx(file_path, out_path)` | UDF → DOCX via LibreOffice | Yes |
| `convert_udf_to_pdf(file_path, out_path)` | UDF → PDF via LibreOffice | Yes |
| `convert_docx_to_udf_experimental(file_path, out_path, experimental)` | DOCX → UDF (experimental) | Yes |

All wrappers return structured error dicts when toolkit is unavailable or files
are missing. No exceptions are raised for expected error conditions.

### DOCX → UDF Experimental

- Requires `experimental=True` flag — refuses to run without it.
- Always includes UYAP manual round-trip warning.
- Text extraction from DOCX via `word/document.xml` parse.
- Returns `ok`, `out_path`, `file_size`, `warning`, `experimental`, `text_length`.

### Improved `probe_udf()`

Extended output fields:
- `format_id`: UDF template format (e.g. "1.8")
- `content_xml_preview`: truncated content.xml preview (max 500 chars)
- `text_length`: extracted text length
- `warnings`: list of any warnings encountered

### CLI Commands

```
emsal-mcp udf status [--json]
emsal-mcp udf authoring-instructions [--format json|markdown] [--json]
emsal-mcp udf to-docx <path> [--out-path] [--json]
emsal-mcp udf to-pdf <path> [--out-path] [--json]
emsal-mcp udf docx-to-udf-experimental <path> [--out-path] [--experimental] [--json]
```

### MCP Tools

- `udf_toolkit_status`: check toolkit availability
- `udf_authoring_instructions`: authoring steps and warnings
- `convert_udf_to_docx_tool`: UDF → DOCX conversion
- `convert_udf_to_pdf_tool`: UDF → PDF conversion
- `convert_docx_to_udf_experimental_tool`: DOCX → UDF (experimental)

### Tests

35 test cases covering:
- Toolkit status disabled by default, env config, env priority
- Authoring instructions JSON/markdown format
- Safe wrappers: missing toolkit, file not found, structured dict
- Experimental flag enforcement
- Native UDF round-trip unchanged

### Backward Compatibility

- All v0.8 tests pass.
- New functions are additive; no breaking changes.
- Existing UDF read/write/probe/to-md behavior preserved.
