"""Example source adapter — demonstrates the Adapter SDK pattern.

This file is a **commented-out example**. It is NOT registered in the
source registry and will NOT appear in the capability matrix. Use it as
a template when building your own adapter.

To use this as a starting point:
1. Copy this file and rename it.
2. Update source_id, name, and the API endpoints.
3. Implement the search/get_document methods with real HTTP calls.
4. Call register_adapter() to make it available.
"""
from __future__ import annotations

# from typing import Any
#
# from emsal_mcp.models import (
#     ContentStatus,
#     Document,
#     SearchResult,
#     SourceSmokeResult,
#     SourceStatus,
#     build_error,
# )
# from emsal_mcp.sources.base import SourceClient, client
#
#
# class ExampleAdapter(SourceClient):
#     """Minimal REST adapter demonstrating the Adapter SDK pattern."""
#
#     source_id = "example"
#     name = "Example REST Source"
#     public = True
#
#     # ── Capability declarations ───────────────────────────────────────
#     _capability_status = SourceStatus.EXPERIMENTAL
#     _supports_search = True
#     _supports_get_document = True
#     _supports_full_text = False
#     _supports_pdf_link = False
#     _supports_metadata_only = True
#     _supports_workflow = False
#     _live_smoke_recommended = True
#     _known_limitations: list[str] = [
#         "Example adapter — not a real data source.",
#     ]
#     _notes: str = "Template adapter for the Adapter SDK."
#
#     _BASE_URL = "https://api.example.com/v1"
#
#     # ── Search ────────────────────────────────────────────────────────
#
#     async def search(self, query: str, limit: int = 10, **filters: Any) -> list[SearchResult]:
#         """Search the example API and return SearchResult list.
#
#         On HTTP errors, return a single UNAVAILABLE result rather than
#         crashing — follows the graceful-unavailable pattern used by
#         existing adapters (GibClient, UyusmazlikClient, etc.).
#         """
#         try:
#             async with client() as http:
#                 resp = await http.get(
#                     f"{self._BASE_URL}/search",
#                     params={"q": query, "limit": limit},
#                 )
#                 resp.raise_for_status()
#                 data = resp.json()
#         except Exception as exc:
#             return [
#                 SearchResult(
#                     source=self.source_id,
#                     document_id="unavailable:example-search",
#                     title="Example source unavailable",
#                     summary=f"Search failed: {exc}",
#                     content_status=ContentStatus.UNAVAILABLE,
#                     metadata={"query": query, "error": str(exc)},
#                     recommended_next_step="Check example API status.",
#                 )
#             ]
#
#         results: list[SearchResult] = []
#         for item in data.get("results", [])[:limit]:
#             results.append(
#                 SearchResult(
#                     source=self.source_id,
#                     document_id=str(item.get("id", "")),
#                     title=item.get("title", "Untitled"),
#                     summary=item.get("summary"),
#                     court=item.get("court"),
#                     chamber=item.get("chamber"),
#                     decision_date=item.get("date"),
#                     content_status=ContentStatus.METADATA_ONLY,
#                     metadata=item,
#                     recommended_next_step=None,
#                 )
#             )
#         return results
#
#     # ── Get Document ──────────────────────────────────────────────────
#
#     async def get_document(self, document_id: str, **kwargs: Any) -> Document:
#         """Fetch a single document by ID from the example API."""
#         try:
#             async with client() as http:
#                 resp = await http.get(f"{self._BASE_URL}/documents/{document_id}")
#                 resp.raise_for_status()
#                 data = resp.json()
#         except Exception as exc:
#             return Document(
#                 source=self.source_id,
#                 document_id=document_id,
#                 title="Example source error",
#                 content_status=ContentStatus.UNAVAILABLE,
#                 metadata={"error": str(exc)},
#                 recommended_next_step="Check example API status.",
#             )
#
#         return Document(
#             source=self.source_id,
#             document_id=document_id,
#             title=data.get("title", "Untitled"),
#             court=data.get("court"),
#             chamber=data.get("chamber"),
#             decision_date=data.get("date"),
#             content_status=ContentStatus.METADATA_ONLY,
#             metadata=data,
#             recommended_next_step=None,
#         )
#
#     # ── Smoke test ────────────────────────────────────────────────────
#
#     async def smoke(self, online: bool = False) -> SourceSmokeResult:
#         """Offline-safe smoke + optional online probe."""
#         result = SourceSmokeResult(source_id=self.source_id)
#         result.search_callable = self._supports_search
#         result.get_document_callable = self._supports_get_document
#
#         if not online:
#             return result
#
#         try:
#             async with client() as http:
#                 resp = await http.get(f"{self._BASE_URL}/health")
#                 resp.raise_for_status()
#             result.online_ok = True
#         except Exception as exc:
#             result.online_ok = False
#             result.warnings.append(f"Online smoke failed: {exc}")
#
#         return result
#
#
# # ── Registration (for plugins / testing) ───────────────────────────────
#
# def register() -> None:
#     """Register this adapter with the Emsal-mcp source registry.
#
#     Call this once at application startup, after importing:
#         from emsal_mcp.sources.example_adapter import register
#         register()
#     """
#     from emsal_mcp.sources.registry import register_adapter
#     register_adapter(ExampleAdapter.source_id, ExampleAdapter())
