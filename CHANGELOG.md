# CHANGELOG.md

All notable changes to emsal-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.6.0] — 2026-05-29

### Added

- **Citation extraction** (`citation.py`): regex-based extraction of Turkish
  legal citation patterns from text. Detects Yargıtay, Danıştay, AYM,
  Sayıştay, Rekabet Kurulu, Ticaret Mahkemesi, and more. Extracts court,
  chamber, date (DD.MM.YYYY / YYYY-MM-DD / Turkish month names), esas_no,
  karar_no, and document_id-like references.
- **Confidence scoring**: high (5+ fields), medium (3-4 fields), low (<3 fields).
  Missing fields produce warnings, never fabricated values.
- **`format_legal_citation()`**: format a citation from Document model or dict.
  Three styles: petition, parenthetical, short. Uses only existing metadata;
  warnings for missing date/chamber/esas/karar/source_url. Includes
  quote_usable/draft_usable/content_status/source_url/confidence.
- **`verify_legal_citation()`**: full verification pipeline — load text/file,
  extract candidates, search local cache (unless live_only), live search
  (unless no_live), rank by metadata match score, optionally fetch docs,
  return structured result with candidates, search_attempts,
  matched_documents, formatted_citations, verification_findings, warnings,
  recommended_next_steps, timing.
- **CLI commands**: `emsal-mcp cite format`, `emsal-mcp cite verify` with
  `--json` output.
- **MCP tools**: `format_legal_citation`, `verify_legal_citation` exposed
  via FastMCP server.
- **Tests**: `tests/test_citation.py` with 45 test cases covering extraction
  (all court types, Turkish chars, dates, confidence, limits, warnings),
  formatting (all styles, missing metadata no fabrication, output contract),
  verification (cache-only, live fake, no_live/live_only, file input,
  strategy debug, timing, output contract).

### Changed

- **Version bumped to 0.6.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.6 citation verification details.

### Backward Compatibility

- All v0.5 tests continue to pass (199+ existing tests unaffected).
- Citation module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.

## [0.5.0] — 2026-05-29

### Added

- **Research workflow** (`research.py`): core v0.5 research pipeline with
  `research_topic()`, `refresh_research_bundle()`, and `research_quality_dashboard()`.
- **`research_topic()`**: searches configured sources, fetches documents up to
  fetch_count, stores in cache, builds output directory with `index.md`,
  `bundle.json`, `results.json`, `documents/*.md`, `manifests/hash-manifest.json`,
  and `warnings.json`. Never fabricates metadata. Returns structured dict with
  query, sources, filters, result_count, fetched_count, content_status_summary,
  citation_safe_count, metadata_only_count, generated_files, warnings,
  recommended_next_steps.
- **`refresh_research_bundle()`**: reads `bundle.json`, re-runs with same
  query/sources, supports `dry_run`, reports new_documents/changed_documents/
  hash_changed, preserves manual notes between `<!-- MANUAL_NOTES_START/END -->`
  markers in `index.md`.
- **`research_quality_dashboard()`**: reads bundle results and computes
  full_text_ratio, citation_safe_ratio, metadata_only_count, pdf_only_count,
  unavailable_count, source_distribution, missing_metadata_count,
  duplicate_citation_count, draft_readiness_score, recommendations.
- **`sources_override` parameter**: all three functions accept optional
  `sources_override` dict for injecting fake source clients in tests (no
  live network required).
- **CLI commands**: `emsal-mcp research topic`, `emsal-mcp research refresh`,
  `emsal-mcp research dashboard` with `--json` output.
- **MCP tools**: `research_topic_tool`, `refresh_research_bundle_tool`,
  `research_quality_dashboard_tool` exposed via FastMCP server.
- **Tests**: `test_research.py` with 30+ test cases covering bundle file
  creation, manifest hash correctness, dashboard metrics, refresh dry_run,
  manual notes preservation, empty source handling, cache storage, CLI/MCP
  imports, and no-network fake source client path.

### Changed

- **Version bumped to 0.5.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.5 research workflow details.
- **`docs/JSON_CONTRACTS.md`** updated with research bundle contracts.
- **`docs/MCP_CONTRACTS.md`** updated with research MCP tool contracts.

### Backward Compatibility

- All v0.4 tests continue to pass (199+ existing tests unaffected).
- Research module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.

## [0.4.0] — 2026-05-29

### Added

- **`SourceSmokeResult` model** (`models.py`): per-source smoke test result
  with `offline_ok`, `online_ok`, `search_callable`, `get_document_callable`,
  `min_content_length_ok`, `warnings`, `errors`, `tested_at`.
- **`SourceClient.smoke()` method** (`base.py`): offline-safe default smoke
  test for all sources. Override for online-specific checks.
- **`smoke_all()` / `smoke_all_sync()`** (`registry.py`): run smoke tests
  for all registered sources (async and sync wrappers).
- **`finalize_document()` helper** (`models.py`): min content length sanity
  (downgrades full_text/html_markdown to metadata_only if < 50 chars),
  content_hash auto-computation, structured warnings via metadata.
- **`check_http_response()` helper** (`base.py`): consistent HTTP status
  handling across all adapters; raises `HTTPStatusError` on 4xx/5xx.
- **CLI `sources-smoke` command** (`cli.py`): `emsal-mcp sources-smoke
  --offline/--online --json` for per-source smoke summaries.
- **MCP `source_smoke` tool** (`server.py`): `source_smoke(online=False)`
  returns per-source smoke results.
- **Source smoke summaries in `release_smoke()`** (`release.py`):
  `release_smoke` now includes `source_smoke` and `source_smoke_ok` in
  its `checks` dict.
- **Tests**: `tests/test_adapters.py` with 73 test cases covering
  SourceSmokeResult model, decode_b64 error handling, finalize_document,
  mocked adapter search/get_document for all 10 sources, CLI smoke
  command, document status sanity, KIK graceful contract, no-error-HTML
  citation-safe invariant.

### Changed

- **`decode_b64()`** (`base.py`): now returns empty bytes on failure
  instead of raising; prevents false `full_text` from corrupt base64.
- **`client()` User-Agent** (`base.py`): updated to `EmsalMcp/{version}`
  with GitHub URL; consistent across all adapters.
- **Bedesten/Yargıtay** (`bedesten.py`): item_type normalization accepts
  lowercase/Turkish-char variants; source_id preserved through
  `_default_item_type` class attribute; `decode_b64` failures result in
  `UNAVAILABLE` not false `full_text`.
- **Mevzuat** (`mevzuat.py`): source_id/title fixed (`mevzuatAdi` prioritized);
  `decode_b64` failures properly surface as `UNAVAILABLE`; capability
  status set to `experimental`.
- **AYM** (`simple_public.py`): fallback to `metadata_only` when parsed
  content is too short; `finalize_document` applied.
- **Danıştay** (`simple_public.py`): `Accept` header added for AJAX
  endpoint; min content length check; `finalize_document` applied.
- **GİB** (`simple_public.py`): query normalization via dict; HTML
  stripped from titles; structured field-based text construction;
  `finalize_document` applied.
- **Uyuşmazlık** (`simple_public.py`): graceful `UNAVAILABLE` on parser
  failures (search and get_document); `finalize_document` applied.
- **Rekabet** (`simple_public.py`): graceful `UNAVAILABLE` on parser
  failures; `finalize_document` applied.
- **Sayıştay** (`simple_public.py`): graceful `UNAVAILABLE` on parser
  failures; `finalize_document` applied.
- **Registry** (`registry.py`): `smoke_all()` / `smoke_all_sync()` added;
  `YargitayClient` now has `_default_item_type`; KIK has `smoke()`.
- **Version bumped to 0.4.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.4 details.

### Backward Compatibility

- All v0.3 tests continue to pass (199/199).
- `SourceSmokeResult` is a new additive model; no breaking changes.
- `smoke()` is opt-in on `SourceClient`; existing subclasses inherit
  the offline-safe default.
- `finalize_document()` is additive; existing code paths unaffected.

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
