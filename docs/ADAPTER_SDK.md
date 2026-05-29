# Adapter SDK — How to Create a Source Adapter

Emsal-mcp supports custom source adapters via a lightweight plugin interface.
This document describes how to create, register, and test a new source adapter.

## Minimum Requirements

Every adapter **must**:

1. Extend `SourceClient` (from `emsal_mcp.sources.base`)
2. Set class attributes: `source_id` and `name`
3. Implement two abstract methods:
   - `async search(query, limit=10, **filters) -> list[SearchResult]`
   - `async get_document(document_id, **kwargs) -> Document`
4. Implement `async smoke(online=False) -> SourceSmokeResult`

## Capability Declarations

Override class-level attributes to declare what your adapter supports:

```python
class MyAdapter(SourceClient):
    source_id = "my_source"
    name = "My Custom Source"

    # Capability flags (defaults shown)
    _capability_status = SourceStatus.STABLE   # STABLE | PARTIAL | EXPERIMENTAL | UNAVAILABLE
    _supports_search = True
    _supports_get_document = True
    _supports_full_text = True
    _supports_pdf_link = False
    _supports_metadata_only = True
    _supports_workflow = True
    _live_smoke_recommended = True
    _known_limitations: list[str] = []
    _notes: str = ""
```

## Smoke Method

The `smoke()` method validates your adapter is operational. Override for
online-specific checks:

```python
async def smoke(self, online: bool = False) -> SourceSmokeResult:
    result = SourceSmokeResult(source_id=self.source_id)
    result.search_callable = self._supports_search
    result.get_document_callable = self._supports_get_document
    # Optional online check
    if online:
        try:
            # lightweight HTTP probe
            ...
            result.online_ok = True
        except Exception as exc:
            result.online_ok = False
            result.warnings.append(f"Online smoke failed: {exc}")
    return result
```

## Registry Registration

Use `register_adapter()` to add your adapter at runtime:

```python
from emsal_mcp.sources.registry import register_adapter

# Register an instance
adapter = MyAdapter()
register_adapter("my_source", adapter)
```

After registration, `get_source("my_source")` returns your adapter, and
it appears in the capability matrix.

**Note:** `register_adapter()` is for plugins and testing. It does NOT
persist across restarts — call it each time your application starts.

## Error Handling

Use the `build_error()` pattern for structured error dicts:

```python
from emsal_mcp.models import build_error

# In your adapter methods, on failure:
return build_error(
    "ADAPTER_ERROR",
    "My adapter failed to connect",
    source="my_source",
    retryable=True,
)
```

## Example: Simple REST Adapter

See `src/emsal_mcp/sources/example_adapter.py` for a fully commented
example that demonstrates the complete pattern.

## Testing Your Adapter

1. Create a test class that injects your adapter via `sources_override`
   or `register_adapter()`
2. Mock HTTP calls (use `unittest.mock.patch`)
3. Verify:
   - `search()` returns `list[SearchResult]` with correct source_id
   - `get_document()` returns `Document` with correct source
   - `smoke(online=False)` returns `offline_ok=True`
   - `capability_model()` returns correct flags
4. Run with: `python -m pytest tests/ -q`

## Integration with Research

Once registered, your adapter participates in `research_topic()` searches
when included in the sources list:

```python
from emsal_mcp.research import research_topic

result = research_topic(
    "my query",
    sources=["my_source"],
    fetch_count=5,
)
```

## Integration with CLI

Registered adapters appear in `emsal-mcp sources` and support
`emsal-mcp search my_source "query"`.
