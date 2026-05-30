# Dead Code Report — M-45 Sweep

**Date:** 2026-05-30
**Scope:** `src/emsal_mcp/*.py` (excluding `sources/` sub-packages and test files)
**Method:** Symbol-level cross-reference across all src modules, CLI, server, and tests

---

## Summary

| Category | Count |
|----------|-------|
| HIGH confidence dead items | 0 |
| MEDIUM confidence (test-only public API) | 8 symbols across 2 modules |
| Duplicate/orphan modules | 0 |
| Unused imports (F401) in src/ | 0 |
| Safe removals performed | 0 |

**Verdict: No safe removals warranted.** The codebase is clean.

---

## 1. Duplicate / Orphan Modules

| Check | Result |
|-------|--------|
| `pdf_extract.py` vs `pdf_extractor.py` | **No duplicate.** Only `pdf_extractor.py` exists. |
| Orphan modules (never imported by any src module) | **None.** All modules are imported by CLI, server, or other src modules. |

---

## 2. Unused Imports (ruff F401)

`src/emsal_mcp/` is **clean** — zero F401 violations.

Two F401 violations exist in `scripts/` (outside scope):
- `scripts/gen_api_doc.py:9` — `sys` imported but unused
- `scripts/inventory_messages.py:14` — `ast` imported but unused

---

## 3. Test-Only Public Symbols (MEDIUM confidence)

These public symbols are never imported by CLI or server but are exercised by test suites. They are **intentional public API** and should NOT be removed.

### concurrency.py — never imported by CLI/server

| Symbol | Type | Notes |
|--------|------|-------|
| `get_concurrency_status()` | function | Tested in `test_concurrency.py` |
| `run_concurrently()` | function | Tested in `test_concurrency.py` |
| `run_document_fetches()` | function | Tested in `test_concurrency.py` |
| `run_source_searches()` | function | Tested in `test_concurrency.py` |

**Rationale:** Provides semaphore-based parallel execution utility. Tested, documented, public API. May be wired into CLI/server in a future milestone.

### drafter.py — never imported by CLI/server

| Symbol | Type | Notes |
|--------|------|-------|
| `assemble_draft()` | function | Tested in `test_drafter.py` |
| `validate_draft_body()` | function | Tested in `test_drafter.py` |

**Rationale:** Controlled draft assembly from safe InputPack. Tested, documented, public API. Referenced in `verification.py` smoke test import.

---

## 4. All Private Helpers — Internal Only, NOT Dead

Every `_`-prefixed private helper was verified to be called within its own module by its public API function. None are orphaned. Examples:

- `citation._detect_court`, `_detect_chamber`, etc. → called by `extract_citation_candidates()`
- `citation_graph._normalize_no`, `_match_*`, etc. → called by `get_citation_graph()`
- `draft_diff._placeholder_section`, `_detect_sections`, etc. → called by `diff_drafts()`
- `semantic._cosine_similarity`, `_ensure_fts5`, etc. → called by `semantic_search()`
- `exporter._verify_export_bundle`, `_strip_markdown`, `_check_toolkit_available` → called by `prepare_export_package_bundle()` / `export_plain_text()` / `get_export_capabilities()`
- `petition._hash_file`, `_hash_manifest`, etc. → called by `prepare_drafting_input_pack()`
- `circuit._get_semaphore` → called by `get_concurrency_status()` (within concurrency.py)

---

## 5. Cross-Module Usage Verification

All public symbols from non-CLI/non-server modules were verified against:

1. **CLI imports** (`cli.py` uses `from .module import ...` syntax)
2. **Server imports** (`server.py` uses `from .module import ...` syntax)
3. **Cross-module imports** (e.g., `sources/base.py` imports `circuit.record_success`)
4. **Test imports** (test files)

Key findings:

| Module | Imported by CLI | Imported by Server | Imported by other src | Tests only |
|--------|:-:|:-:|:-:|:-:|
| `citation.py` | Yes | Yes | Yes (citation_graph) | — |
| `circuit.py` | Yes | Yes | Yes (sources/base) | — |
| `concurrency.py` | No | No | No | Yes |
| `drafter.py` | No | No | No (noqa only) | Yes |
| `models.py` | Yes | Yes | Yes (many) | — |
| `pdf_extractor.py` | Yes | Yes | No | — |
| `verification.py` | No | No | Yes (release.py) | — |

---

## 6. One Candidate: `verification.smoke_test_online`

| Symbol | File | Referenced in src | Referenced in tests | Confidence |
|--------|------|:-:|:-:|:-:|
| `smoke_test_online()` | `verification.py:76` | **No** | **No** | HIGH (dead) |

This function is defined but never called by any module or test. However:

- It is a **public API function** (no underscore prefix)
- It provides online source connectivity testing
- It is documented and part of the verification module's API surface
- The task rule says: *"NEVER delete code that MIGHT be used (M-xx CLI tools, MCP tools, or public API)"*

**Decision: NOT removed** — public API, may be wired into CLI in future.

---

## 7. Actions Taken

| Action | Result |
|--------|--------|
| Remove duplicate `pdf_extract.py` | N/A — does not exist |
| Remove unused imports (F401) | N/A — src/ is clean |
| Remove dead utility functions | None qualify for safe removal |
| Run `ruff check .` | 40 D100/D101/D103 warnings (docstrings), 0 errors |
| Run `pytest tests/ -q` | 1409 passed (baseline preserved) |
