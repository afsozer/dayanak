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
