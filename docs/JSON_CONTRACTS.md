# docs/JSON_CONTRACTS.md — Canonical JSON Contracts

## Source Capability

Returned by `capabilities()`, CLI `emsal-mcp sources --json`, and MCP
`source_capabilities`. Every entry has this shape:

```json
{
  "source_id": "bedesten",
  "display_name": "Bedesten/Yargıtay",
  "status": "stable",
  "supports_search": true,
  "supports_get_document": true,
  "supports_full_text": true,
  "supports_pdf_link": false,
  "supports_metadata_only": true,
  "supports_article_search": false,
  "supports_type_filter": false,
  "supports_workflow": true,
  "live_smoke_recommended": true,
  "known_limitations": [
    "Content returned as base64-encoded HTML; PDF documents yield only a link."
  ],
  "notes": "Bedesten API is internal to Adalet Bakanlığı; availability depends on upstream.",
  "source": "bedesten",
  "name": "Bedesten/Yargıtay",
  "public": true,
  "tools": ["search", "get_document"],
  "citationSafeRule": "Only documents with content_status full_text/html_markdown and non-empty text are quote/draft usable.",
  "noFabrication": true
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `source_id` | `string` | Machine identifier (snake_case) |
| `display_name` | `string` | Human-readable name |
| `status` | `string` | `"stable"` / `"partial"` / `"experimental"` / `"unavailable"` |
| `supports_search` | `bool` | Whether `search()` works |
| `supports_get_document` | `bool` | Whether `get_document()` works |
| `supports_full_text` | `bool` | Whether full text/Markdown is expected |
| `supports_pdf_link` | `bool` | Whether PDF links are preserved |
| `supports_metadata_only` | `bool` | Whether metadata-only fallback is supported |
| `supports_article_search` | `bool` | Whether article-level search is supported |
| `supports_type_filter` | `bool` | Whether type filtering is supported |
| `supports_workflow` | `bool` | Whether source is workflow-eligible |
| `live_smoke_recommended` | `bool` | Include in live smoke tests |
| `known_limitations` | `string[]` | Explicit, non-fabricated limitations |
| `notes` | `string` | Operational notes |
| `source`, `name`, `public`, `tools` | legacy | v0.1 compatibility keys |
| `citationSafeRule` | `string` | **Legacy alias** — backward compat only |
| `noFabrication` | `bool` | **Legacy alias** — backward compat only |

### Backward compatibility

The `citationSafeRule` and `noFabrication` keys are kept for consumers that
relied on the v0.1 capability shape. New code should use the snake_case keys.

### KIK entry

```json
{
  "source_id": "kik",
  "display_name": "Kamu İhale Kurumu / EKAP v2",
  "status": "unavailable",
  "supports_search": false,
  "supports_get_document": true,
  "supports_full_text": false,
  "supports_pdf_link": false,
  "supports_metadata_only": true,
  "supports_workflow": false,
  "live_smoke_recommended": false,
  "known_limitations": ["Canlı EKAP v2 search önceki QC'de HTTP 401 döndürdü."],
  "notes": "KİK intentionally registered as unavailable placeholder for contract stability.",
  "citationSafeRule": "Only documents with content_status full_text/html_markdown and non-empty text are quote/draft usable.",
  "noFabrication": true
}
```

## SearchResult

```json
{
  "source": "bedesten",
  "document_id": "abc-123",
  "title": "Yargıtay 1. Daire | 2024-01-01 | 2024/1 | 100",
  "summary": null,
  "court": "Yargıtay",
  "chamber": "1. Daire",
  "decision_date": "2024-01-01",
  "esas_no": "2024/1",
  "karar_no": "100",
  "source_url": null,
  "pdf_url": null,
  "content_status": "metadata_only",
  "content_status_label": "Metadata",
  "content_available": false,
  "full_text_available": false,
  "metadata_confidence": "high",
  "metadata_confidence_reason": "Başlık, kaynak ve güçlü karar metadata alanları var.",
  "recommended_next_step": "Bu kayıtta tam metin yok; dilekçede kullanmadan önce resmi kaynaktan doğrulayın.",
  "metadata": {}
}
```

## Document

Extends SearchResult:

```json
{
  "source": "bedesten",
  "document_id": "abc-123",
  "title": "Yargıtay Kararı",
  "full_text": "...",
  "markdown": "...",
  "mime_type": "text/html",
  "content_hash": "sha256...",
  "raw": null,
  "retrieved_at": "2026-05-29T00:30:00+00:00",
  "safety_state": "unknown",
  "content_status": "html_markdown",
  "source_url": "https://...",
  "pdf_url": null,
  "content_status_label": "HTML'den Markdown",
  "content_available": true,
  "full_text_available": true,
  "metadata_confidence": "medium",
  "metadata_confidence_reason": "Başlık ve kaynak var; bazı tarih/numara/daire alanları eksik.",
  "recommended_next_step": null,
  "metadata": {}
}
```

### Usability rules

- `quote_usable` is `true` when `content_status in (full_text, html_markdown)` AND `text` is non-empty.
- `draft_usable` equals `quote_usable`.
- Documents with `content_status: "metadata_only"` or `"pdf_link_only"` are NOT usable for quotation.
- These rules are invariant — no source can bypass them.

## CachedDocument (v0.3)

Extended document model for cache v2 with rich metadata and access tracking.

```json
{
  "document_id": "abc-123",
  "source": "yargitay",
  "title": "Yargıtay Kararı",
  "court": "Yargıtay",
  "chamber": "1. Daire",
  "decision_date": "2024-01-01",
  "esas_no": "2024/1",
  "karar_no": "100",
  "source_url": "https://...",
  "content_status": "full_text",
  "markdown": "...",
  "full_text": "...",
  "content_hash": "sha256...",
  "metadata_json": "{...}",
  "raw_json": "{...}",
  "retrieved_at": "2026-05-29T00:30:00+00:00",
  "last_accessed_at": "2026-05-29T01:00:00+00:00",
  "access_count": 3,
  "quote_usable": true,
  "draft_usable": true,
  "metadata_confidence": "high",
  "warnings_json": null
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `document_id` | `string` | Document identity (primary key part) |
| `source` | `string` | Source identifier (primary key part) |
| `title` | `string?` | Document title |
| `court` | `string?` | Court name |
| `chamber` | `string?` | Chamber/daire |
| `decision_date` | `string?` | Decision date |
| `esas_no` | `string?` | Case number |
| `karar_no` | `string?` | Decision number |
| `source_url` | `string?` | Source URL |
| `content_status` | `string` | Content availability status |
| `markdown` | `string?` | Markdown content |
| `full_text` | `string?` | Full text content |
| `content_hash` | `string?` | SHA-256 content hash |
| `metadata_json` | `string?` | JSON metadata blob |
| `raw_json` | `string?` | Raw response JSON |
| `retrieved_at` | `datetime` | When document was fetched |
| `last_accessed_at` | `datetime` | Last access time |
| `access_count` | `int` | Number of times accessed |
| `quote_usable` | `bool` | Safe for quotation |
| `draft_usable` | `bool` | Safe for drafting |
| `metadata_confidence` | `string?` | high/medium/low |
| `warnings_json` | `string?` | JSON warnings list |

## Local Search Results

Returned by `search_local_cache` MCP tool and CLI `cache search-local`:

```json
{
  "document_id": "abc-123",
  "source": "yargitay",
  "title": "Yargıtay Kararı",
  "court": "Yargıtay",
  "chamber": "1. Daire",
  "decision_date": "2024-01-01",
  "esas_no": "2024/1",
  "karar_no": "100",
  "source_url": "https://...",
  "content_status": "full_text",
  "quote_usable": true,
  "draft_usable": true,
  "metadata_confidence": "high",
  "retrieved_at": "2026-05-29T00:30:00+00:00",
  "last_accessed_at": "2026-05-29T01:00:00+00:00",
  "access_count": 3,
  "snippet": "...text around matching query..."
}
```

## SourceSmokeResult (v0.4)

Returned by `source_smoke` MCP tool, CLI `sources-smoke`, and
`release_smoke` checks. Per-source offline/online smoke test result.

```json
{
  "source_id": "bedesten",
  "offline_ok": true,
  "online_ok": null,
  "search_callable": true,
  "get_document_callable": true,
  "min_content_length_ok": true,
  "content_length_chars": 0,
  "warnings": [],
  "errors": [],
  "tested_at": "2026-05-29T00:30:00+00:00"
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `source_id` | `string` | Source identifier |
| `offline_ok` | `bool` | Offline smoke passed |
| `online_ok` | `bool?` | Online smoke result (null = not tested) |
| `search_callable` | `bool` | search() method available |
| `get_document_callable` | `bool` | get_document() method available |
| `min_content_length_ok` | `bool` | Min content length check passed |
| `content_length_chars` | `int` | Content length tested |
| `warnings` | `string[]` | Non-fatal warnings |
| `errors` | `string[]` | Fatal errors |
| `tested_at` | `datetime` | When smoke was run |

### CLI usage

```
emsal-mcp sources-smoke                # offline only (default)
emsal-mcp sources-smoke --online       # include online checks
emsal-mcp sources-smoke --json         # JSON output
```

### MCP usage

```
source_smoke(online=false)             # offline only (default)
source_smoke(online=true)              # include online checks
```

## Research Bundle (v0.5)

### `bundle.json`

```json
{
  "version": "0.5.0",
  "query": "konut kirası tavan fiyat",
  "sources": ["bedesten", "yargitay"],
  "filters": {},
  "fetch_count": 5,
  "result_count": 10,
  "fetched_count": 5,
  "content_status_summary": {"full_text": 2, "metadata_only": 3},
  "citation_safe_count": 2,
  "metadata_only_count": 3,
  "generated_files": ["bundle.json", "results.json", "index.md", "warnings.json", "manifests/hash-manifest.json", "documents/..."],
  "warnings": [],
  "hash": "sha256...",
  "created_at": "2026-05-29T00:30:00+00:00",
  "recommended_next_steps": ["Bundle is complete with citation-safe documents."]
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `version` | `string` | Bundle schema version |
| `query` | `string` | Research query |
| `sources` | `string[]` | Sources queried |
| `filters` | `object` | Search filters applied |
| `fetch_count` | `int` | Max docs fetched per source |
| `result_count` | `int` | Total search results |
| `fetched_count` | `int` | Documents successfully fetched |
| `content_status_summary` | `object` | Count per content_status |
| `citation_safe_count` | `int` | Documents safe for quotation |
| `metadata_only_count` | `int` | Metadata-only documents |
| `generated_files` | `string[]` | Files written to output dir |
| `warnings` | `string[]` | Search/fetch warnings |
| `hash` | `string` | SHA-256 of bundle content |
| `created_at` | `datetime` | Bundle creation time |
| `recommended_next_steps` | `string[]` | Actionable next steps |

### `manifests/hash-manifest.json`

```json
{
  "source:doc-id": "sha256-content-hash",
  "yargitay:abc-123": "a1b2c3..."
}
```

### Quality Dashboard Output

```json
{
  "total_results": 10,
  "full_text_ratio": 0.4,
  "citation_safe_ratio": 0.3,
  "metadata_only_count": 5,
  "pdf_only_count": 1,
  "unavailable_count": 1,
  "source_distribution": {"bedesten": 6, "yargitay": 4},
  "missing_metadata_count": 2,
  "duplicate_citation_count": 1,
  "draft_readiness_score": 0.52,
  "recommendations": ["Low full-text ratio; fetch more documents with content."]
}
```

## Petition Outline (v0.8)

Returned by `prepare_petition_outline` and CLI `emsal-mcp petition outline --json`.

```json
{
  "version": "0.8.0",
  "created_at": "2026-05-29T12:00:00+00:00",
  "pack_version": "0.8.0",
  "matter": "Konut tahliye davası",
  "issue": "Kira sözleşmesi feshi",
  "petition_ready_count": 2,
  "citation_only_count": 1,
  "citation_only_bibliography_count": 1,
  "placeholder_total": 8,
  "sections": [
    {
      "id": "header",
      "title": "Sorumluluk Reddi",
      "type": "disclaimer",
      "content_source": "generated",
      "placeholders": [],
      "authorities": []
    },
    {
      "id": "bibliography",
      "title": "Kaynakça",
      "type": "bibliography",
      "content_source": "mixed",
      "placeholders": [],
      "authorities": [
        {
          "document_id": "doc-001",
          "source": "test_source",
          "label": "Yargıtay | 3. Hukuk Dairesi | 2024-06-15 | 2024/12345 | 2024/5678",
          "classification": "petition_ready",
          "warning": null
        },
        {
          "document_id": "cite-001",
          "source": "test_source",
          "label": "Test Court | 1. Daire | 2024-01-01 | 2024/1 | 123",
          "classification": "citation_only",
          "warning": "Bibliyografik referans; doğrudan alıntı yapılamaz."
        }
      ],
      "has_citation_only_refs": true,
      "warning": "Bu bölümdeki atıflar yalnızca bibliyografik referans olarak yer almaktadır..."
    }
  ],
  "warnings": []
}
```

## Controlled Draft Metadata (v0.8)

Returned by `prepare_controlled_petition_draft` in `draft.json`.

```json
{
  "version": "0.8.0",
  "created_at": "2026-05-29T12:00:00+00:00",
  "pack_version": "0.8.0",
  "matter": "Konut tahliye davası",
  "issue": "Kira sözleşmesi feshi",
  "paragraph_count": 12,
  "section_count": 6,
  "footnote_count": 2,
  "placeholder_count": 8,
  "blocking_warning_count": 0,
  "readiness_score": 0.67,
  "readiness_level": "medium",
  "finalization_risk_score": 0.33,
  "classification_counts": {
    "petition_ready": 2,
    "citation_only": 1,
    "research_lead_only": 0,
    "excluded": 0
  },
  "citation_only_bibliography_count": 1,
  "has_disclaimer": true,
  "placeholders_in_skeleton": ["{{DILEKCE_BASLIK}}", "{{MAHKEME_ADRES}}"],
  "files": {
    "draft_md": "draft_output/draft.md",
    "draft_json": "draft_output/draft.json",
    "footnotes_json": "draft_output/footnotes.json",
    "warnings_json": "draft_output/warnings.json"
  }
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `paragraph_count` | int | Non-empty paragraphs in draft.md |
| `section_count` | int | `##` heading sections |
| `footnote_count` | int | Footnote references (petition_ready only) |
| `placeholder_count` | int | `{{…}}` patterns in draft.md |
| `blocking_warning_count` | int | Critical warnings (no petition_ready, etc.) |
| `readiness_score` | float | 0.0–1.0: petition_ready / total authorities |
| `readiness_level` | string | `high` (≥0.7), `medium` (≥0.4), `low` (>0), `none` |
| `finalization_risk_score` | float | 0.0–1.0: composite risk of blocking + low readiness |

## Footnotes (v0.8)

Returned by `prepare_controlled_petition_draft` in `footnotes.json`.

```json
{
  "version": "0.8.0",
  "footnote_count": 2,
  "footnotes": [
    {
      "footnote_id": 1,
      "document_id": "doc-001",
      "source": "test_source",
      "citation_label": "Yargıtay | 3. Hukuk Dairesi | 2024-06-15 | 2024/12345 | 2024/5678",
      "classification": "petition_ready",
      "content_status": "full_text",
      "type": "petition_ready",
      "warning": null
    }
  ],
  "citation_only_bibliography": [
    {
      "document_id": "cite-001",
      "source": "test_source",
      "citation_label": "Test Court | 1. Daire | 2024-01-01 | 2024/1 | 123",
      "warning": "Bibliyografik referans; doğrudan alıntı yapılamaz."
    }
  ]
}
```

## DOCX Export Validation (v0.8)

Returned by `prepare_docx_export`.

```json
{
  "ok": true,
  "out_path": "output.docx",
  "checksum_sha256": "a1b2c3...",
  "file_size": 12345,
  "validation": {
    "zip_valid": true,
    "disclaimer_present": true,
    "footnotes_consistent": true,
    "placeholders_preserved": true,
    "validation_warnings": [],
    "export_readiness": true
  }
}
```

## Export Package Bundle v2 (v0.8)

Returned by `prepare_export_package_bundle`.

```json
{
  "ok": true,
  "bundle_dir": "export_bundle/",
  "manifest": {
    "version": "0.8.0",
    "created_at": "2026-05-29T12:00:00+00:00",
    "pack_dir": "petition_pack/",
    "draft_dir": "draft_output/",
    "file_count": 12,
    "files": {
      "petition-pack.json": {"sha256": "...", "size": 1234},
      "draft.md": {"sha256": "...", "size": 5678},
      "manifest.json": {"sha256": "...", "size": 901}
    }
  },
  "hash_manifest": {
    "petition-pack.json": "sha256...",
    "draft.md": "sha256...",
    "manifest.json": "sha256..."
  },
  "files": ["petition-pack.json", "citation-bank.md", "draft.md", "draft.json", "manifest.json", "hash-manifest.json", "verification.txt"],
  "post_verification": {
    "ok": true,
    "errors": [],
    "checks": {
      "hash_manifest_valid": {"ok": true, "mismatches": [], "file_count": 12},
      "required_files_present": {"ok": true, "missing": []},
      "manifest_valid_json": {"ok": true, "file_count": 12}
    }
  }
}
```

## UDF Toolkit Status (v0.9)

Returned by `get_udf_toolkit_status()`, CLI `emsal-mcp udf status`, and MCP
`udf_toolkit_status`.

```json
{
  "ok": false,
  "enabled": false,
  "toolkit_dir": null,
  "libreoffice_path": null,
  "unoconv_path": null,
  "version": "0.9.0",
  "warnings": [
    "UDF toolkit dizini ayarlanmamis. EMSAL_UDF_TOOLKIT_DIR veya UDF_TOOLKIT_DIR ortam degiskeni ile ayarlayin.",
    "LibreOffice (soffice) PATH'te bulunamadi.",
    "unoconv PATH'te bulunamadi."
  ]
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `ok` | `bool` | Toolkit is available and functional |
| `enabled` | `bool` | Toolkit dir configured via env var |
| `toolkit_dir` | `string?` | Configured toolkit directory path |
| `libreoffice_path` | `string?` | Detected LibreOffice path |
| `unoconv_path` | `string?` | Detected unoconv path |
| `version` | `string` | UDF toolkit integration version |
| `warnings` | `string[]` | Non-fatal warnings (missing tools, etc.) |

### Environment variables

| Variable | Description |
|---|---|
| `EMSAL_UDF_TOOLKIT_DIR` | Primary toolkit directory (takes priority) |
| `UDF_TOOLKIT_DIR` | Fallback toolkit directory |

## UDF Authoring Instructions (v0.9)

Returned by `get_udf_authoring_instructions()`, CLI `emsal-mcp udf authoring-instructions`, and MCP
`udf_authoring_instructions`.

### JSON format

```json
{
  "format": "json",
  "steps": [
    "UDF dosyasini dogrudan Python ile olusturabilirsiniz (write_udf).",
    "Olusturulan dosyayi UYAP Doküman Editörü'nde acarak duzeltme yapin.",
    "UYAP Doküman Editörü ile dogrulama zorunludur.",
    "Disclaimer header otomatik olarak eklenir.",
    "Placeholder'lar {{...}} formatinda korunur."
  ],
  "warnings": [
    "UDF yazımı deneysel kabul edilmeli; resmi kullanım öncesi UYAP Doküman Editörü'nde manuel round-trip doğrulama yapılmalıdır.",
    "Dogrudan UDF olusturmak UYAP formatina tam uyumluluk garantisi vermez."
  ],
  "version": "0.9.0",
  "toolkit_status": { "..." }
}
```

### Markdown format

```json
{
  "format": "markdown",
  "instructions": "# UDF Authoring Instructions\n\n## Steps\n1. UDF dosyasini...\n\n## Warnings\n- ...",
  "warnings": ["..."],
  "version": "0.9.0"
}
```

## UDF Safe Wrappers (v0.9)

### `convert_udf_to_docx` / `convert_udf_to_pdf`

Success output:
```json
{
  "ok": true,
  "action": "convert_udf_to_docx",
  "out_path": "output.docx",
  "file_size": 12345,
  "warning": "UDF yazımı deneysel kabul edilmeli; ..."
}
```

Error output (toolkit unavailable):
```json
{
  "ok": false,
  "action": "convert_udf_to_docx",
  "error": "toolkit_unavailable",
  "message": "UDF toolkit is not available. ...",
  "toolkit_status": { "..." }
}
```

### `convert_docx_to_udf_experimental`

Error output (experimental flag required):
```json
{
  "ok": false,
  "action": "convert_docx_to_udf_experimental",
  "error": "experimental_required",
  "message": "DOCX -> UDF conversion requires experimental=True. ...",
  "warning": "DOCX -> UDF dönüşümü deneysel ve geri döndürülemez bir işlemdir. ..."
}
```

Success output:
```json
{
  "ok": true,
  "action": "convert_docx_to_udf_experimental",
  "out_path": "output.udf",
  "file_size": 1234,
  "warning": "DOCX -> UDF dönüşümü deneysel ve geri döndürülemez bir işlemdir. ...",
  "experimental": true,
  "text_length": 5678
}
```
