# docs/JSON_CONTRACTS.md — Canonical JSON Contracts

> **emsal-mcp v5.0.0** — 14 core MCP tools (82 in full profile), 11 sources.
> All JSON contracts below are the canonical shapes returned by CLI `--json`
> output and MCP tool responses.

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
  "snippet": null,
  "metadata": {}
}
```

## Document

Extends SearchResult.  The MCP tool output is deduplicated via
``to_tool_payload()`` — the canonical shape below reflects that:

```json
{
  "source": "bedesten",
  "document_id": "abc-123",
  "title": "Yargıtay Kararı",
  "markdown": "... (tek metin alanı — full_text buraya birleştirilir) ...",
  "mime_type": "text/html",
  "content_hash": "sha256...",
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

> **Görev 1 (parity-v2):** ``raw``, ``full_text`` (ayrı alan), ve
> ``metadata.content`` (base64 HTML) artık varsayılan çıktıda **yoktur**.
> ``include_raw=True`` ile ham yanıt istenebilir.
> Tek metin alanı ``markdown``'dır; ``full_text`` yalnızca ``markdown``
> boşsa ``markdown`` adıyla sunulur — ikisi birden asla verilmez.
> Önbellek (cache) tam ``Document`` ile çalışmaya devam eder; budama
> yalnızca araç çıktısı içindir.

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

## Citation Verification & Formatting (v0.6)

### `verify_legal_citation`

Returned by `verify_legal_citation()` and CLI `emsal-mcp cite verify --json`.
Full pipeline: text/file → extract candidates → local cache search → live search → rank → fetch → format.

```json
{
  "ok": true,
  "candidates": [
    {
      "index": 1,
      "raw_text": "Yargıtay 3. Hukuk Dairesi 2024-06-15 E.2023/12345 K.2024/5678",
      "parsed": {
        "court": "Yargıtay",
        "chamber": "3. Hukuk Dairesi",
        "date": "2024-06-15",
        "esas_no": "2023/12345",
        "karar_no": "2024/5678"
      },
      "confidence": "high",
      "field_count": 5,
      "warnings": []
    }
  ],
  "search_attempts": [
    {
      "candidate_index": 1,
      "source": "bedesten",
      "query_method": "cache",
      "matches_found": 2
    }
  ],
  "matched_documents": [
    {
      "document_id": "abc-123",
      "source": "bedesten",
      "title": "Yargıtay 3. Hukuk Dairesi Kararı",
      "match_score": 1.0
    }
  ],
  "formatted_citations": [
    {
      "formatted_citation": "Yargıtay, 3. Hukuk Dairesi, E.2023/12345, K.2024/5678, Tarihi: 2024-06-15",
      "style": "petition",
      "court": "Yargıtay",
      "chamber": "3. Hukuk Dairesi",
      "date": "2024-06-15",
      "esas_no": "2023/12345",
      "karar_no": "2024/5678",
      "document_id": "abc-123",
      "source": "bedesten",
      "source_url": "https://...",
      "content_status": "full_text",
      "quote_usable": true,
      "draft_usable": true,
      "confidence": "high",
      "warnings": []
    }
  ],
  "verification_findings": {
    "total_candidates": 3,
    "searched": 3,
    "matched": 2,
    "matched_via_cache": 2,
    "matched_via_live": 0,
    "unmatched": 1
  },
  "warnings": [],
  "recommended_next_steps": ["2/3 citations verified with supporting documents."],
  "timing": {"extraction_ms": 5, "search_ms": 120, "total_ms": 125}
}
```

### `format_legal_citation`

Returned by `format_legal_citation()` and CLI `emsal-mcp cite format --json`.
Formats a citation from a Document model or dict using one of three styles:
`petition`, `parenthetical`, or `short`.

**Styles:**

| Style | Example |
|---|---|
| `petition` | "Yargıtay, 3. Hukuk Dairesi, E.2023/12345, K.2024/5678, Tarihi: 2024-06-15" |
| `parenthetical` | "(Yargıtay, 3. Hukuk Dairesi, 2024-06-15, E.2023/12345, K.2024/5678)" |
| `short` | "Ygt. 2023/12345" |

**No fabrication:** missing metadata fields produce warnings, never invented values.

### Citation Extraction

`extract_citation_candidates()` detects Turkish legal citation patterns:
Yargıtay, Danıştay, AYM, Sayıştay, Rekabet Kurulu, Ticaret Mahkemesi, and more.
Extracts court, chamber, date (DD.MM.YYYY / YYYY-MM-DD / Turkish month names),
esas_no, karar_no, and document_id-like references.

**Confidence scoring:** high (5+ fields), medium (3–4), low (<3).
Missing fields produce warnings, never fabricated values.

## Petition Pack v2 (v0.7)

### `prepare_drafting_input_pack`

Returned by `prepare_drafting_input_pack()` and CLI `emsal-mcp petition pack --json`.
Classifies authorities and generates structured pack directory.

```json
{
  "ok": true,
  "pack_dir": "petition_pack/",
  "matter": "Konut tahliye davası",
  "issue": "Kira sözleşmesi feshi",
  "pack_version": "0.8.0",
  "classification": {
    "petition_ready_count": 2,
    "citation_only_count": 1,
    "research_lead_only_count": 0,
    "excluded_count": 1,
    "total": 4
  },
  "created_at": "2026-05-29T12:00:00+00:00",
  "files": [
    "petition-brief.json",
    "citation-bank.md",
    "argument-map.md",
    "petition-instructions.md",
    "draft-skeleton.md",
    "petition-pack.json",
    "hash-manifest.json"
  ],
  "source_documents": 2,
  "warnings": [],
  "recommended_next_steps": [
    "Pack ready for inspection: emsal-mcp petition inspect petition_pack/",
    "Pack ready for draft: emsal-mcp petition draft petition_pack/"
  ]
}
```

**Authority Classification:**

| Category | Criteria | Draft Usable |
|---|---|---|
| `petition_ready` | citation_check passes, full_text/html_markdown, text ≥ 50 chars, provenance present | Yes |
| `citation_only` | citation_check passes on metadata, or PDF link only | No (reference only) |
| `research_lead_only` | citation_check fails but has some metadata | No (research direction) |
| `excluded` | safety check fails, hash mismatch, or unavailable | No |

**Pack Directory Structure:**

```
petition_pack/
├── petition-brief.json
├── citation-bank.md
├── argument-map.md
├── petition-instructions.md
├── draft-skeleton.md
├── petition-pack.json
├── hash-manifest.json
└── source-documents/
    ├── bedesten_docid.md
    └── ...
```

### `inspect_petition_pack`

Returned by `inspect_petition_pack()` and CLI `emsal-mcp petition inspect --json`.
Validates pack directory with 8 checks.

```json
{
  "ok": true,
  "pack_dir": "petition_pack/",
  "draft_safe": true,
  "pack_version": "0.8.0",
  "errors": [],
  "warnings": [],
  "counts": {
    "total_documents": 4,
    "petition_ready": 2,
    "citation_only": 1,
    "research_lead_only": 0,
    "excluded": 1
  },
  "checks": {
    "required_files_present": true,
    "draft_safe_flag_correct": true,
    "placeholders_in_draft_skeleton": true,
    "legislation_verified_placeholder": true,
    "petition_instructions_forbids_invention": true,
    "citation_bank_only_safe_docs": true,
    "hash_manifest_valid": true,
    "metadata_only_draft_usable": true
  }
}
```

**Inspection checks:**

| Check | Description |
|---|---|
| `required_files_present` | All 7 required files exist |
| `draft_safe_flag_correct` | `draft_safe` flag matches authority classification |
| `placeholders_in_draft_skeleton` | Placeholder count preserved |
| `legislation_verified_placeholder` | No hardcoded unverified law refs |
| `petition_instructions_forbids_invention` | No-invention rule present |
| `citation_bank_only_safe_docs` | No excluded docs in citation bank |
| `hash_manifest_valid` | Content hashes match source documents |
| `metadata_only_draft_usable` | metadata_only never marked draft usable |

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

## Legislation (v0.10)

### `search_legislation`

```json
{
  "ok": true,
  "query": "konut kirası",
  "sources": ["mevzuat"],
  "legislation_type": null,
  "total_results": 3,
  "results": [
    {
      "document_id": "mevzuat-001",
      "source": "mevzuat",
      "title": "Kira Kanunu",
      "legislation_no": "6570",
      "gazette_date": "1972-07-08",
      "legislation_type": "Kanun",
      "legislation_type_id": "kanun",
      "type_confidence": "high",
      "summary": null,
      "content_status": "full_text",
      "court": null
    }
  ],
  "warnings": [],
  "recommended_next_steps": ["Mevzuat araması tamamlandı."],
  "version": "0.10.0",
  "rule": "Yasak: Bu modül hiçbir surette mevzuat numarası uydurmaz."
}
```

### `get_legislation_document`

```json
{
  "ok": true,
  "document_id": "mevzuat-001",
  "source": "mevzuat",
  "title": "Kira Kanunu",
  "legislation_no": "6570",
  "gazette_date": "1972-07-08",
  "legislation_type": "Kanun",
  "legislation_type_id": "kanun",
  "type_confidence": "high",
  "content_status": "full_text",
  "content_hash": "sha256...",
  "citation_check": {
    "ok": true,
    "quote_usable": true,
    "draft_usable": true,
    "warnings": []
  },
  "article_count": 40,
  "text_length": 15200,
  "warnings": [],
  "recommended_next_steps": ["Tam metin mevcut; alıntı için kullanılabilir."],
  "version": "0.10.0",
  "rule": "Yasak: Bu modül hiçbir surette mevzuat numarası uydurmaz."
}
```

### `search_legislation_articles`

```json
{
  "ok": true,
  "document_id": "mevzuat-001",
  "source": "mevzuat",
  "title": "Kira Kanunu",
  "article_number": "6",
  "article_query": null,
  "total_articles_found": 40,
  "matching_articles": [
    {
      "number": "6",
      "text": "Kira sözleşmesi...",
      "preview": "Kira sözleşmesiwritten text..."
    }
  ],
  "content_status": "full_text",
  "warnings": [],
  "recommended_next_steps": ["1 madde bulundu."],
  "version": "0.10.0",
  "rule": "Yasak: Bu modül hiçbir surette mevzuat numarası uydurmaz."
}
```

### `get_legislation_article_tree`

```json
{
  "ok": true,
  "document_id": "mevzuat-001",
  "source": "mevzuat",
  "title": "Kira Kanunu",
  "article_count": 40,
  "section_count": 3,
  "part_count": 2,
  "tree": {
    "parts": [
      {
        "title": "BİRİNCİ KISIM",
        "sections": [
          {
            "title": "BİRİNCİ BÖLÜM",
            "articles": [
              {"number": "1", "title": "MADDE 1 - ...", "preview": "..."}
            ]
          }
        ]
      }
    ]
  },
  "flat_article_list": [
    {"number": "1", "preview": "...", "parent_part": "BİRİNCİ KISIM", "parent_section": "BİRİNCİ BÖLÜM"}
  ],
  "warnings": [],
  "recommended_next_steps": ["40 madde, 2 kısım, 3 bölüm bulundu."],
  "version": "0.10.0",
  "rule": "Yasak: Bu modül hiçbir surette mevzuat numarası uydurmaz."
}
```

### `get_legislation_gerekce`

```json
{
  "ok": true,
  "document_id": "mevzuat-001",
  "source": "mevzuat",
  "title": "Kira Kanunu",
  "found": true,
  "genel_gerekce": "Bu kanunun gerekçesi...",
  "madde_gerekceleri": [
    {"article": "1", "gerekce": "Madde 1 gerekçesi..."},
    {"article": "2", "gerekce": "Madde 2 gerekçesi..."}
  ],
  "raw_text": "...(first 2000 chars)...",
  "warnings": [],
  "recommended_next_steps": ["Gerekçe metni bulundu; doğrudan alıntılanabilir."],
  "version": "0.10.0",
  "rule": "Yasak: Bu modül hiçbir surette mevzuat numarası uydurmaz."
}
```

### `get_legislation_source_status`

```json
{
  "ok": true,
  "sources": [
    {"source_id": "mevzuat", "display_name": "Mevzuat", "status": "experimental"}
  ],
  "overall_ok": true,
  "source_count": 1,
  "healthy_sources": ["mevzuat"],
  "degraded_sources": [],
  "warnings": [],
  "recommended_next_steps": ["Tüm kaynaklar sağlıklı."],
  "version": "0.10.0",
  "rule": "Yasak: Bu modül hiçbir surette mevzuat numarası uydurmaz."
}
```

### `format_legislation_citation`

```json
{
  "formatted_citation": "Kanun No: 6570 RG: 1972-07-08 \"Kira Kanunu\"",
  "style": "full",
  "legislation_no": "6570",
  "gazette_date": "1972-07-08",
  "legislation_type": "Kanun",
  "title": "Kira Kanunu",
  "warnings": []
}
```

## Semantic Search (v0.11)

### `build_semantic_index`

```json
{
  "ok": true,
  "fts5_exists": true,
  "fts5_row_count": 42,
  "vectors_count": 42,
  "documents_total": 42,
  "warnings": [],
  "recommended_next_steps": [
    "Use hybrid_search() to query the index.",
    "Call get_index_status() to verify index health."
  ],
  "version": "0.11.0"
}
```

### `semantic_search`

```json
{
  "ok": true,
  "query": "konut tahliye",
  "results": [
    {
      "document_id": "abc-123",
      "source": "yargitay",
      "title": "Yargıtay Kararı",
      "court": "Yargıtay",
      "chamber": "3. Hukuk Dairesi",
      "decision_date": "2024-01-15",
      "score": 0.854321,
      "snippet": "...text around match...",
      "content_status": "full_text",
      "quote_usable": true,
      "draft_usable": true
    }
  ],
  "total_matches": 5,
  "method": "tfidf_cosine",
  "warnings": [],
  "version": "0.11.0"
}
```

### `hybrid_search`

```json
{
  "ok": true,
  "query": "konut tahliye",
  "results": [
    {
      "document_id": "abc-123",
      "source": "yargitay",
      "title": "Yargıtay Kararı",
      "court": "Yargıtay",
      "chamber": "3. Hukuk Dairesi",
      "decision_date": "2024-01-15",
      "bm25_score": -3.21,
      "cosine_score": 0.85,
      "hybrid_score": 0.78,
      "snippet": "...text around match...",
      "content_status": "full_text",
      "quote_usable": true,
      "draft_usable": true
    }
  ],
  "total_matches": 5,
  "method": "hybrid",
  "hybrid_weight": 0.6,
  "warnings": [],
  "recommended_next_steps": [],
  "version": "0.11.0"
}
```

### `get_index_status`

```json
{
  "ok": true,
  "fts5_exists": true,
  "fts5_document_count": 42,
  "vectors_table_exists": true,
  "vectors_count": 42,
  "total_cached_documents": 42,
  "unindexed_documents": 0,
  "warnings": [],
  "recommended_next_steps": [],
  "version": "0.11.0"
}
```

### `rebuild_index`

Same output as `build_semantic_index` with `force_rebuild=True`. All existing FTS5 tables and vector tables are dropped and recreated.

## Chamber Profiling (v0.12)

### `get_chamber_overview`

```json
{
  "ok": true,
  "court_filter": null,
  "total_chambers": 8,
  "total_documents": 150,
  "chambers": [
    {
      "court": "Yargıtay",
      "chamber": "3. Hukuk Dairesi",
      "document_count": 25,
      "content_available_count": 20,
      "earliest_date": "2020-01-15",
      "latest_date": "2024-12-01",
      "recent_count": 10
    }
  ],
  "warnings": [],
  "recommended_next_steps": ["Chamber overview retrieved."],
  "version": "0.12.0"
}
```

### `profile_chamber`

```json
{
  "ok": true,
  "chamber": "3. Hukuk Dairesi",
  "court_filter": null,
  "metrics": {
    "total_documents": 25,
    "content_available_count": 20,
    "content_status_distribution": {"full_text": 18, "metadata_only": 7},
    "quote_usable_count": 18,
    "draft_usable_count": 18,
    "earliest_date": "2020-01-15",
    "latest_date": "2024-12-01",
    "date_range_years": 4.9
  },
  "top_keywords": [
    {"word": "kira", "count": 15},
    {"word": "tahliye", "count": 12},
    {"word": "sözleşme", "count": 8}
  ],
  "recent_documents": [
    {"document_id": "doc-001", "title": "Tahliye Kararı", "decision_date": "2024-12-01"}
  ],
  "warnings": [],
  "recommended_next_steps": ["Profile generated for chamber '3. Hukuk Dairesi'."],
  "version": "0.12.0"
}
```

### `chamber_timeline`

```json
{
  "ok": true,
  "chamber_filter": "3. Hukuk Dairesi",
  "court_filter": null,
  "year_range": {"start": 2020, "end": 2024},
  "total_documents": 25,
  "timeline": [
    {"year": 2020, "count": 3},
    {"year": 2021, "count": 5},
    {"year": 2022, "count": 4},
    {"year": 2023, "count": 6},
    {"year": 2024, "count": 7}
  ],
  "warnings": [],
  "version": "0.12.0"
}
```

### `find_similar_chambers`

```json
{
  "ok": true,
  "target_chamber": "3. Hukuk Dairesi",
  "similar_chambers": [
    {
      "chamber": "2. Hukuk Dairesi",
      "court": "Yargıtay",
      "similarity_score": 0.4523,
      "shared_keywords": ["kira", "tahliye", "sözleşme", "borçlar"],
      "document_count": 18
    }
  ],
  "warnings": [],
  "recommended_next_steps": ["Found 1 chambers with similar topic profiles."],
  "version": "0.12.0"
}
```

## Release Readiness (CLI)

> **M-103 (v5.0.0):** Release yönetimi MCP araçları kaldırıldı; yalnızca
> CLI `release v1-readiness` kaldı.

### `final_v1_readiness` (CLI: `emsal-mcp release v1-readiness --json`)

```json
{
  "ok": true,
  "ready": true,
  "criteria": {
    "all_modules_importable": true,
    "has_stable_sources": true,
    "release_smoke_ok": true,
    "no_unavailable_sources": true
  },
  "blocking_issues": [],
  "recommendation": "SHIP: v1.0.0 cikisa hazir.",
  "checks": {"...": "module/source/smoke detayları"},
  "version": "5.0.0",
  "generated_at": "2026-06-10T12:00:00+00:00"
}
```
