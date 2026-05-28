# CHANGELOG.md

All notable changes to emsal-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.3.0] — 2026-05-29

### Added

- **`CachedDocument` model** (`models.py`): extended document model for cache v2
  with rich metadata (`title`, `court`, `chamber`, `decision_date`, `esas_no`,
  `karar_no`, `source_url`, `content_status`, `markdown`, `full_text`,
  `content_hash`, `metadata_json`, `raw_json`, `retrieved_at`,
  `last_accessed_at`, `access_count`, `quote_usable`, `draft_usable`,
  `metadata_confidence`, `warnings_json`). Round-trip via `from_document()` /
  `to_document()`.
- **`documents_v2` table** (`cache.py`): SQLite table with indexed columns for
  local search. Backward-compatible: legacy `documents` table preserved.
- **Local search service** (`cache.py`): `search_local()` with filters (source,
  court, chamber, date, esas_no, karar_no, document_id, content_status,
  draft_usable, quote_usable), sorts (relevance, decision_date_desc/asc,
  fetched_at_desc/asc), snippets, and limit. No network required.
- **CLI `cache` subcommands** (`cli.py`): `stats`, `list`, `search-local`,
  `delete`, `prune`, `backup`, `export`, `import`.
- **MCP cache tools** (`server.py`): `search_local_cache`, `get_cache_stats`,
  `list_cached_documents`.
- **CLI `get` integration**: `emsal-mcp get` now stores documents in both legacy
  and v2 cache tables via `store_document()`.
- **CLI `search` integration**: search results stored in cache for later local
  search.
- **Cache maintenance**: `cache_stats()`, `list_cached_documents()`,
  `delete_cached_document()`, `prune_search_cache()`, `backup_cache()`,
  `export_json()`, `import_json()`.
- **Cache integrity check**: `documents_v2` table included in verification.
- **Tests**: `test_cache_v2.py` (schema, store/read, hash verification, local
  search filters/sorts/snippets, maintenance operations), `test_cli_cache.py`
  (CLI subcommands, MCP imports, CLI get integration).

### Changed

- **Version bumped to 0.3.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.3 Cache v2 + Local Search.
- **`docs/JSON_CONTRACTS.md`** and **`docs/MCP_CONTRACTS.md`** updated with cache
  v2 contracts.

### Backward Compatibility

- All v0.2 tests continue to pass.
- Legacy `documents` table preserved alongside `documents_v2`.
- `store_document()` writes to both tables for seamless migration.

## [0.2.0] — 2026-05-29

### Added

- **`SourceCapability` model** (`models.py`): typed capability descriptor with
  `source_id`, `display_name`, `status` (`SourceStatus` enum), `supports_search`,
  `supports_get_document`, `supports_full_text`, `supports_pdf_link`,
  `supports_metadata_only`, `supports_article_search`, `supports_type_filter`,
  `supports_workflow`, `live_smoke_recommended`, `known_limitations`, `notes`.
- **`SourceStatus` enum**: `stable`, `partial`, `experimental`, `unavailable`.
- **`to_legacy_dict()`**: produces both snake_case and camelCase keys for
  backward compatibility (`citationSafeRule`, `noFabrication`).
- **`SourceClient.capability_model()`**: returns a typed `SourceCapability`
  instance from any source client.
- **KIK unavailable placeholder**: present in capability matrix with
  `status: "unavailable"`; `get_source("kik")` returns a graceful placeholder
  client whose search/get methods return unavailable/metadata-only contract
  payloads instead of crashing MCP calls.
- **Content-status enrichment fields** on search/document models:
  `content_status_label`, `content_available`, `full_text_available`,
  `metadata_confidence`, `metadata_confidence_reason`, `recommended_next_step`.
- **Per-source known_limitations**: each source client now declares explicit,
  non-fabricated limitations (e.g. "base64-encoded HTML", "PDF-only links").
- **Documentation**: `ROADMAP.md`, `CHANGELOG.md`, `docs/JSON_CONTRACTS.md`,
  `docs/MCP_CONTRACTS.md`.
- **Tests**: `tests/test_capability_contract.py` with 30+ test cases covering
  capability model, KIK graceful degradation, CLI JSON shape, MCP import,
  enrichment fields, and document/search contract.

### Changed

- **`sources/registry.py`** refactored: `capabilities()` now returns the full
  capability matrix for all 10 sources; KIK is a structured unavailable
  placeholder.
- **`sources/base.py`**: `SourceClient.capabilities()` now delegates to
  `capability_model().to_legacy_dict()`.

### Backward Compatibility

- All existing tests updated and passing.
- `capabilities()` output retains v0.1 keys (`source`, `name`, `public`,
  `tools`, `citationSafeRule`, `noFabrication`) alongside v0.2 fields.
- `get_source("kik")` now returns a structured client (was raising RuntimeError).

## [0.1.0] — 2026-05-28

Initial release.
