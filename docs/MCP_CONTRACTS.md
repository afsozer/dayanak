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
```

## Backward compatibility

- `source_capabilities` returns dicts with both `source_id` (snake_case) and
  v0.1 keys (`source`, `name`, `public`, `tools`, `citationSafeRule`,
  `noFabrication`) for legacy consumers.
- All document/search models retain their v0.1 field names.
- New fields are additive and optional for clients. Existing tool names must not
  be removed within the 0.x/1.x compatibility window; any rename must be added as
  an alias first.

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
