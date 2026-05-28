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
