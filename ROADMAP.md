# ROADMAP.md — Emsal-mcp v0.2 Contract Foundation

## Vision

Emsal-mcp is a citation-safe MCP legal research and document drafting system.
v0.2 establishes a **Contract Foundation** that makes every source's capabilities
explicit and machine-readable, enabling downstream consumers (LLM agents, CLI
users, CI pipelines) to make informed decisions without guessing.

## v0.1 (shipped)

- Basic source clients: bedesten, yargitay, mevzuat, aym, danistay, gib,
  uyusmazlik, rekabet, sayistay
- Citation safety checks (`citation_check`, `exact_quote`)
- UDF read/write round-trip
- Export bundle (DOCX + ZIP manifest with hashes)
- Offline smoke test
- CLI (`emsal-mcp`) and MCP server (`emsal-mcp-server`)

## v0.2 — Contract Foundation (current)

### SourceCapability model (`models.py`)

Canonical snake_case fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `source_id` | `str` | required | Unique machine identifier |
| `display_name` | `str` | required | Human-readable name |
| `status` | `SourceStatus` | `"stable"` | `stable` / `partial` / `experimental` / `unavailable` |
| `supports_search` | `bool` | `True` | Whether `search()` is functional |
| `supports_get_document` | `bool` | `True` | Whether `get_document()` is functional |
| `supports_full_text` | `bool` | `True` | Whether source can provide quote/draft usable text |
| `supports_pdf_link` | `bool` | `False` | Whether source preserves PDF links |
| `supports_metadata_only` | `bool` | `True` | Whether metadata-only fallback is possible |
| `supports_article_search` | `bool` | `False` | Whether legislation/article search is supported |
| `supports_type_filter` | `bool` | `False` | Whether source-specific type filters are supported |
| `supports_workflow` | `bool` | `True` | Whether source is usable in workflow tools |
| `live_smoke_recommended` | `bool` | `True` | Whether to include in live smoke tests |
| `known_limitations` | `list[str]` | `[]` | Explicit, non-fabricated limitations |
| `notes` | `str` | `""` | Operational notes |

Legacy camelCase aliases (`citationSafeRule`, `noFabrication`) are kept for
backward compatibility via `populate_by_name` and `to_legacy_dict()`.

### KIK (Kamu İhale Kurumu / EKAP v2)

Added as an **unavailable placeholder** in the capability matrix:
- `status: "unavailable"`, `supports_search: false`, `supports_get_document: true`
- `get_source("kik")` returns a structured placeholder client
- `search()` returns a single `content_status="unavailable"` result instead of raising
- `get_document()` returns a metadata-only placeholder that is never quote/draft usable
- `known_limitations` explicitly records the EKAP v2 HTTP 401/auth/token limitation

### Registry refactor (`sources/registry.py`)

- `registry()` now returns 10 sources (including KIK)
- `capabilities()` returns a list of dicts, each with all required keys
- `get_source()` returns KIK as a graceful unavailable placeholder

### CLI / MCP improvements

- `emsal-mcp sources --json` outputs the full capability matrix
- MCP `source_capabilities` tool returns the same shape
- Both include `citationSafeRule` and `noFabrication` for backward compat

## Future (v0.3+)

- Live smoke tests with configurable rate limits (NOT in v0.2)
- Partial sources (`status: "partial"`) for degraded-access scenarios
- Capability-based tool routing in MCP (auto-select sources by capability)
- Source health monitoring and circuit-breaker patterns
