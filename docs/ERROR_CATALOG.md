# Error Catalog — emsal-mcp

> Auto-generated from `build_error()` calls across `src/emsal_mcp/`.
> Source of truth: `server_utils.py::KNOWN_ERROR_CODES` and `server_utils.py::get_error_codes()`.
> Regenerate with: `emsal-mcp error-catalog --json`

## Quick Reference

| Code | Modules | Recommended Action |
|------|---------|-------------------|
| `ANALYTICS_QUERY_FAILED` | search_analytics | Check analytics query parameters and cache state. |
| `ANALYTICS_RECORD_FAILED` | search_analytics | Verify cache DB is writable. |
| `ARGUMENT_MAP_MISSING` | argument | Run petition pack generation first. |
| `BENCHMARK_FAILED` | benchmark | Check corpus configuration and dependencies. |
| `CHAMBER_NOT_FOUND` | chamber | Verify chamber name matches a cached record. |
| `CHECK_FAILED` | exporter, release | Inspect the specific check that failed; may be transient. |
| `CIRCUIT_OPEN` | sources/base | Wait for the circuit to close or reset manually. |
| `CLUSTER_NOT_FOUND` | dedup | Run find_duplicates first to identify clusters. |
| `CONVERSION_FAILED` | exporter, udf | Check toolkit availability (LibreOffice for DOCX/PDF). |
| `DB_OPEN_FAILED` | cache | Verify DB file permissions and path. |
| `DB_QUERY_FAILED` | chamber | Check cache DB integrity; may need rebuild. |
| `DEDUP_FAILED` | dedup | Check cache DB state and dedup parameters. |
| `DEDUP_LOOKUP_FAILED` | dedup | Verify document_id exists in cache. |
| `DEDUP_STATS_FAILED` | dedup | Check cache DB schema integrity. |
| `DOC_NOT_FOUND` | citation_graph | Verify the document exists in the specified source. |
| `DOCUMENT_NOT_FOUND` | pdf_extractor | Check the document ID and source. |
| `DRAFT_DIR_NOT_FOUND` | draft_diff | Verify the draft directory path exists. |
| `DRAFT_NOT_FOUND` | draft_diff | Verify the draft file path exists. |
| `EMBEDDING_BACKEND_UNAVAILABLE` | semantic | Install fastembed or use local-hash-v1 provider. |
| `EMBEDDING_INDEX_FAILED` | semantic | Check embedding provider availability and DB state. |
| `EMBEDDING_SEARCH_FAILED` | semantic | Ensure embedding index is built; check provider. |
| `EMBEDDING_STATUS_FAILED` | semantic | Check DB accessibility and embedding_vectors table. |
| `EMPTY_DB` | chamber, legislation | Populate cache with documents first. |
| `EMPTY_DOCUMENT` | udf | Provide a non-empty UDF file. |
| `EXCEPTION` | udf | Unexpected error; check UDF toolkit installation. |
| `EXPERIMENTAL_REQUIRED` | exporter, udf | Pass --experimental flag to proceed. |
| `FETCH_FAILED` | legislation | Check source availability and document ID. |
| `FILE_NOT_FOUND` | cache, citation, exporter, pdf_extractor, privacy, udf | Verify the file path exists and is readable. |
| `FILE_READ_ERROR` | pdf_extractor | Check file permissions and encoding. |
| `FUZZY_DEDUP_FAILED` | dedup | Ensure embedding index is built for fuzzy matching. |
| `GRAPH_BUILD_FAILED` | citation_graph | Check cache DB has documents with citation metadata. |
| `GRAPH_EXPORT_FAILED` | citation_graph | Check output format support and permissions. |
| `GRAPH_QUERY_FAILED` | citation_graph | Verify document_id and source parameters. |
| `GRAPH_STATS_FAILED` | citation_graph | Check citation_graph DB tables exist. |
| `INCREMENTAL_INDEX_FAILED` | semantic | Check DB state and retry full rebuild. |
| `INDEX_BUILD_FAILED` | semantic | Check DB permissions and schema. |
| `INDEX_QUERY_FAILED` | semantic | Check DB accessibility. |
| `INDEX_SYNC_STATUS_FAILED` | semantic | Check DB state and index tables. |
| `INTEGRITY_CHECK_FAILED` | cache | Check cache DB file integrity. |
| `INVALID_BUMP_FLAGS` | release | Provide exactly one of --major, --minor, --patch. |
| `INVALID_FORMAT` | citation_graph, exporter | Use a supported format (json, dot, mermaid, etc.). |
| `INVALID_HYBRID_WEIGHT` | semantic | Set hybrid_weight to a value in [0.0, 1.0]. |
| `INVALID_INPUT` | citation, exporter, legislation, server_utils | Check input parameters against documented constraints. |
| `INVALID_NAME` | research_watch | Provide a non-empty watch name. |
| `INVALID_QUERY` | research_watch | Provide a non-empty research query. |
| `MERGE_FAILED` | dedup | Check cluster state; may need manual intervention. |
| `NOT_A_DIRECTORY` | draft_diff | Provide a directory path, not a file. |
| `NO_CHAMBERS_AVAILABLE` | chamber | Cache has no chamber data; run a search first. |
| `NO_CHAMBERS_FOUND` | chamber | Check court filter matches cached records. |
| `NO_DOCUMENTS_FOUND` | chamber | Broaden search criteria or populate cache. |
| `NO_ISSUES` | petition | Provide at least one issue for multi-issue pack. |
| `NO_KEYWORDS` | chamber | Provide keywords for chamber profiling. |
| `OCR_FAILED` | pdf_extractor | Check OCR dependencies (pypdf, pillow). |
| `OCR_UNAVAILABLE` | pdf_extractor | Install pypdf and pillow for OCR support. |
| `ORPHAN_CLEANUP_FAILED` | cache | Check DB state; may need manual VACUUM. |
| `PACK_NOT_FOUND` | argument, exporter, petition | Run petition pack generation first. |
| `PARSE_FAILED` | chamber | Check data format of chamber records. |
| `PDF_DOWNLOAD_FAILED` | pdf_extractor | Check network connectivity and URL validity. |
| `PDF_EXTRACTION_FAILED` | pdf_extractor | Check PDF file integrity and toolkit. |
| `PDF_EXTRACTION_UNAVAILABLE` | pdf_extractor | Install pypdf for PDF text extraction. |
| `PDF_TOO_LARGE` | pdf_extractor | Reduce PDF file size or increase limit. |
| `READ_ERROR` | draft_diff | Check file permissions and encoding. |
| `SEARCH_FAILED` | semantic | Check query syntax and index status. |
| `SOURCE_NOT_FOUND` | calibrate | Verify source_id is registered. |
| `TABLE_NOT_FOUND` | cache | Rebuild cache schema. |
| `TEMPLATE_NOT_FOUND` | templates | Use list_templates to see available templates. |
| `TOOLKIT_UNAVAILABLE` | exporter, udf | Install LibreOffice for DOCX/PDF conversion. |
| `VACUUM_FAILED` | cache | Check DB file permissions; try manual VACUUM. |
| `VERSION_DIR_ERROR` | draft_diff | Check output directory permissions. |
| `VERSION_PARSE_FAILED` | release | Verify version format (MAJOR.MINOR.PATCH). |
| `WATCH_ADD_FAILED` | research_watch | Check watch name uniqueness and parameters. |
| `WATCH_EXISTS` | research_watch | Use a different name or remove existing watch. |
| `WATCH_LIST_FAILED` | research_watch | Check watch storage file permissions. |
| `WATCH_NOT_FOUND` | research_watch | Verify watch name; use list to see available watches. |
| `WATCH_REMOVE_FAILED` | research_watch | Check watch storage file permissions. |
| `WATCH_RUN_FAILED` | research_watch | Check source availability and network connectivity. |

## Detailed Catalog

### ANALYTICS_QUERY_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `search_analytics.py`
- **Action**: Check analytics query parameters and cache state.

### ANALYTICS_RECORD_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `search_analytics.py`
- **Action**: Verify cache DB is writable.

### ARGUMENT_MAP_MISSING
- **Message pattern**: `Argument map not found`
- **Modules**: `argument.py`
- **Action**: Run petition pack generation first.

### BENCHMARK_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `benchmark.py`
- **Action**: Check corpus configuration and dependencies.

### CHAMBER_NOT_FOUND
- **Message pattern**: `Chamber not found`
- **Modules**: `chamber.py`
- **Action**: Verify chamber name matches a cached record.

### CHECK_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `exporter.py`, `release.py`
- **Action**: Inspect the specific check that failed; may be transient.

### CIRCUIT_OPEN
- **Message pattern**: `Circuit breaker open for source`
- **Modules**: `sources/base.py`
- **Action**: Wait for the circuit to close or reset manually.

### CLUSTER_NOT_FOUND
- **Message pattern**: `Cluster {id} not found`
- **Modules**: `dedup.py`
- **Action**: Run find_duplicates first to identify clusters.

### CONVERSION_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `exporter.py`, `udf.py`
- **Action**: Check toolkit availability (LibreOffice for DOCX/PDF).

### DB_OPEN_FAILED
- **Message pattern**: `Cannot open cache DB`
- **Modules**: `cache.py`
- **Action**: Verify DB file permissions and path.

### DB_QUERY_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `chamber.py`
- **Action**: Check cache DB integrity; may need rebuild.

### DEDUP_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `dedup.py`
- **Action**: Check cache DB state and dedup parameters.

### DEDUP_LOOKUP_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `dedup.py`
- **Action**: Verify document_id exists in cache.

### DEDUP_STATS_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `dedup.py`
- **Action**: Check cache DB schema integrity.

### DOC_NOT_FOUND
- **Message pattern**: `Belge bulunamadi: {source}:{document_id}`
- **Modules**: `citation_graph.py`
- **Action**: Verify the document exists in the specified source.

### DOCUMENT_NOT_FOUND
- **Message pattern**: `Document not found`
- **Modules**: `pdf_extractor.py`
- **Action**: Check the document ID and source.

### DRAFT_DIR_NOT_FOUND
- **Message pattern**: `Draft directory not found`
- **Modules**: `draft_diff.py`
- **Action**: Verify the draft directory path exists.

### DRAFT_NOT_FOUND
- **Message pattern**: `Draft not found`
- **Modules**: `draft_diff.py`
- **Action**: Verify the draft file path exists.

### EMBEDDING_BACKEND_UNAVAILABLE
- **Message pattern**: `Embedding provider unavailable`
- **Modules**: `semantic.py`
- **Action**: Install fastembed or use local-hash-v1 provider.

### EMBEDDING_INDEX_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `semantic.py`
- **Action**: Check embedding provider availability and DB state.

### EMBEDDING_SEARCH_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `semantic.py`
- **Action**: Ensure embedding index is built; check provider.

### EMBEDDING_STATUS_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `semantic.py`
- **Action**: Check DB accessibility and embedding_vectors table.

### EMPTY_DB
- **Message pattern**: `Belge icerigi mevcut degil`
- **Modules**: `chamber.py`, `legislation.py`
- **Action**: Populate cache with documents first.

### EMPTY_DOCUMENT
- **Message pattern**: `UDF document is empty`
- **Modules**: `udf.py`
- **Action**: Provide a non-empty UDF file.

### EXCEPTION
- **Message pattern**: `str(e)`
- **Modules**: `udf.py`
- **Action**: Unexpected error; check UDF toolkit installation.

### EXPERIMENTAL_REQUIRED
- **Message pattern**: `Experimental flag required`
- **Modules**: `exporter.py`, `udf.py`
- **Action**: Pass --experimental flag to proceed.

### FETCH_FAILED
- **Message pattern**: `Belge alinamadi / Kaynak bulunamadi`
- **Modules**: `legislation.py`
- **Action**: Check source availability and document ID.

### FILE_NOT_FOUND
- **Message pattern**: `File not found: {path}`
- **Modules**: `cache.py`, `citation.py`, `exporter.py`, `pdf_extractor.py`, `privacy.py`, `udf.py`
- **Action**: Verify the file path exists and is readable.

### FILE_READ_ERROR
- **Message pattern**: `str(exc)`
- **Modules**: `pdf_extractor.py`
- **Action**: Check file permissions and encoding.

### FUZZY_DEDUP_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `dedup.py`
- **Action**: Ensure embedding index is built for fuzzy matching.

### GRAPH_BUILD_FAILED
- **Message pattern**: `Citation graph olusturulamadi`
- **Modules**: `citation_graph.py`
- **Action**: Check cache DB has documents with citation metadata.

### GRAPH_EXPORT_FAILED
- **Message pattern**: `Graf disa aktarilamadi`
- **Modules**: `citation_graph.py`
- **Action**: Check output format support and permissions.

### GRAPH_QUERY_FAILED
- **Message pattern**: `Sorgu basarisiz`
- **Modules**: `citation_graph.py`
- **Action**: Verify document_id and source parameters.

### GRAPH_STATS_FAILED
- **Message pattern**: `Istatistik alinamadi`
- **Modules**: `citation_graph.py`
- **Action**: Check citation_graph DB tables exist.

### INCREMENTAL_INDEX_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `semantic.py`
- **Action**: Check DB state and retry full rebuild.

### INDEX_BUILD_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `semantic.py`
- **Action**: Check DB permissions and schema.

### INDEX_QUERY_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `semantic.py`
- **Action**: Check DB accessibility.

### INDEX_SYNC_STATUS_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `semantic.py`
- **Action**: Check DB state and index tables.

### INTEGRITY_CHECK_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `cache.py`
- **Action**: Check cache DB file integrity.

### INVALID_BUMP_FLAGS
- **Message pattern**: `Invalid bump flags`
- **Modules**: `release.py`
- **Action**: Provide exactly one of --major, --minor, --patch.

### INVALID_FORMAT
- **Message pattern**: `Unknown format: {format}`
- **Modules**: `citation_graph.py`, `exporter.py`
- **Action**: Use a supported format (json, dot, mermaid, etc.).

### INVALID_HYBRID_WEIGHT
- **Message pattern**: `hybrid_weight must be between 0.0 and 1.0`
- **Modules**: `semantic.py`
- **Action**: Set hybrid_weight to a value in [0.0, 1.0].

### INVALID_INPUT
- **Message pattern**: `param: must not be empty / must be a positive integer`
- **Modules**: `citation.py`, `exporter.py`, `legislation.py`, `server_utils.py`
- **Action**: Check input parameters against documented constraints.

### INVALID_NAME
- **Message pattern**: `Watch name must not be empty`
- **Modules**: `research_watch.py`
- **Action**: Provide a non-empty watch name.

### INVALID_QUERY
- **Message pattern**: `Watch query must not be empty`
- **Modules**: `research_watch.py`
- **Action**: Provide a non-empty research query.

### MERGE_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `dedup.py`
- **Action**: Check cluster state; may need manual intervention.

### NOT_A_DIRECTORY
- **Message pattern**: `Not a directory`
- **Modules**: `draft_diff.py`
- **Action**: Provide a directory path, not a file.

### NO_CHAMBERS_AVAILABLE
- **Message pattern**: `No chambers available`
- **Modules**: `chamber.py`
- **Action**: Cache has no chamber data; run a search first.

### NO_CHAMBERS_FOUND
- **Message pattern**: `No chambers found`
- **Modules**: `chamber.py`
- **Action**: Check court filter matches cached records.

### NO_DOCUMENTS_FOUND
- **Message pattern**: `No documents found`
- **Modules**: `chamber.py`
- **Action**: Broaden search criteria or populate cache.

### NO_ISSUES
- **Message pattern**: `No issues provided`
- **Modules**: `petition.py`
- **Action**: Provide at least one issue for multi-issue pack.

### NO_KEYWORDS
- **Message pattern**: `No keywords`
- **Modules**: `chamber.py`
- **Action**: Provide keywords for chamber profiling.

### OCR_FAILED
- **Message pattern**: `OCR processing failed`
- **Modules**: `pdf_extractor.py`
- **Action**: Check OCR dependencies (pypdf, pillow).

### OCR_UNAVAILABLE
- **Message pattern**: `OCR not available`
- **Modules**: `pdf_extractor.py`
- **Action**: Install pypdf and pillow for OCR support.

### ORPHAN_CLEANUP_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `cache.py`
- **Action**: Check DB state; may need manual VACUUM.

### PACK_NOT_FOUND
- **Message pattern**: `petition-pack.json not found`
- **Modules**: `argument.py`, `exporter.py`, `petition.py`
- **Action**: Run petition pack generation first.

### PARSE_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `chamber.py`
- **Action**: Check data format of chamber records.

### PDF_DOWNLOAD_FAILED
- **Message pattern**: `PDF download failed`
- **Modules**: `pdf_extractor.py`
- **Action**: Check network connectivity and URL validity.

### PDF_EXTRACTION_FAILED
- **Message pattern**: `PDF extraction failed`
- **Modules**: `pdf_extractor.py`
- **Action**: Check PDF file integrity and toolkit.

### PDF_EXTRACTION_UNAVAILABLE
- **Message pattern**: `PDF extraction unavailable`
- **Modules**: `pdf_extractor.py`
- **Action**: Install pypdf for PDF text extraction.

### PDF_TOO_LARGE
- **Message pattern**: `PDF too large`
- **Modules**: `pdf_extractor.py`
- **Action**: Reduce PDF file size or increase limit.

### READ_ERROR
- **Message pattern**: `Cannot read {path}`
- **Modules**: `draft_diff.py`
- **Action**: Check file permissions and encoding.

### SEARCH_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `semantic.py`
- **Action**: Check query syntax and index status.

### SOURCE_NOT_FOUND
- **Message pattern**: `Source not found`
- **Modules**: `calibrate.py`
- **Action**: Verify source_id is registered.

### TABLE_NOT_FOUND
- **Message pattern**: `Table not found`
- **Modules**: `cache.py`
- **Action**: Rebuild cache schema.

### TEMPLATE_NOT_FOUND
- **Message pattern**: `Template not found`
- **Modules**: `templates.py`
- **Action**: Use list_templates to see available templates.

### TOOLKIT_UNAVAILABLE
- **Message pattern**: `Toolkit not available`
- **Modules**: `exporter.py`, `udf.py`
- **Action**: Install LibreOffice for DOCX/PDF conversion.

### VACUUM_FAILED
- **Message pattern**: `str(exc)`
- **Modules**: `cache.py`
- **Action**: Check DB file permissions; try manual VACUUM.

### VERSION_DIR_ERROR
- **Message pattern**: `Version directory error`
- **Modules**: `draft_diff.py`
- **Action**: Check output directory permissions.

### VERSION_PARSE_FAILED
- **Message pattern**: `Version parse failed`
- **Modules**: `release.py`
- **Action**: Verify version format (MAJOR.MINOR.PATCH).

### WATCH_ADD_FAILED
- **Message pattern**: `Failed to add watch`
- **Modules**: `research_watch.py`
- **Action**: Check watch name uniqueness and parameters.

### WATCH_EXISTS
- **Message pattern**: `Watch already exists`
- **Modules**: `research_watch.py`
- **Action**: Use a different name or remove existing watch.

### WATCH_LIST_FAILED
- **Message pattern**: `Failed to list watches`
- **Modules**: `research_watch.py`
- **Action**: Check watch storage file permissions.

### WATCH_NOT_FOUND
- **Message pattern**: `Watch not found`
- **Modules**: `research_watch.py`
- **Action**: Verify watch name; use list to see available watches.

### WATCH_REMOVE_FAILED
- **Message pattern**: `Failed to remove watch`
- **Modules**: `research_watch.py`
- **Action**: Check watch storage file permissions.

### WATCH_RUN_FAILED
- **Message pattern**: `Failed to run watch`
- **Modules**: `research_watch.py`
- **Action**: Check source availability and network connectivity.

## Error Response Shape

All `build_error()` calls produce a dict with this canonical shape:

```json
{
  "ok": false,
  "errorCode": "ERROR_CODE",
  "message": "Human-readable description",
  "source": "optional-source-id",
  "retryable": false,
  "warnings": [],
  "recommended_next_steps": [],
  ...additional context fields
}
```

## Adding New Error Codes

1. Use `build_error("NEW_CODE", message)` in the source module.
2. Add `"NEW_CODE"` to `KNOWN_ERROR_CODES` in `server_utils.py`.
3. Add the entry to `get_error_codes()` catalog dict.
4. Update this document.
5. Run `python -m ruff check .` to verify.
