# Emsal-mcp 1.0.0 Release Notes

**Released:** 2026-05-29
**From:** v0.13.0 (513 tests, 0 lint, 54 MCP tools, 10 source adapters)
**Readiness:** 100% — SHIP

---

## Summary

Emsal-mcp 1.0.0 marks the production-ready milestone after 13 development
versions and 5 hardening milestones. All verification gates are green.

## Modules (13/13 importable)

| Module | Description |
|---|---|
| citation | Legal citation extraction, formatting, verification |
| petition | Petition pack v2, inspect, outline, controlled draft |
| exporter | DOCX export validation, export bundle |
| udf | Native UDF read/write + toolkit wrappers |
| legislation | Mevzuat search, article tree, gerekçe |
| semantic | FTS5 + TF-IDF cosine hybrid search |
| chamber | Chamber overview, profile, timeline, similarity |
| research | Research topic, bundle refresh, quality dashboard |
| safety | Citation safety, input pack, exact quote |
| cache | SQLite cache v2, local search |
| models | Pydantic models, enums, helpers |
| document | Controlled draft, markdown to DOCX, export bundle |
| verification | Offline smoke, cache integrity, hash verify |

## Sources (10 registered, 5 stable)

- Stable: bedesten, yargitay, aym, danistay, gib
- Partial/experimental: mevzuat, uyusmazlik, rekabet, sayistay
- Unavailable: kik (HTTP 401, auth/token flow required)

## Data

- 13 cached documents
- 4 chambers profiled
- FTS5 search index operational

## Configuration & Observability (new in v1.0.0)

- Central `config.py` with env-based settings (cache path, timeout, user-agent, UDF dir, log level)
- `emsal-mcp doctor` command for environment diagnostics
- Structured logging via stdlib `logging` (stderr only, never pollutes JSON contracts)
- Error normalization via `build_error()` helper

## Test Coverage (improved in v1.0.0)

| Module | Before | After |
|---|---|---|
| document.py | 23% | 100% |
| drafter.py | 18% | 100% |
| verification.py | 57% | 71% |
| release.py | 12% | 87% |
| server.py | 9% | 69% |
| **TOTAL** | **76%** | **84%** |

Total: 650 tests, 0 lint errors.

## Key Invariants (preserved)

1. No fabrication — no invented case numbers, dates, legislation numbers
2. Citation safety — quote_usable/draft_usable flags enforced
3. Graceful degradation — structured error dicts, no exceptions for expected errors
4. Additive — no breaking changes to existing API
5. Zero new heavy dependencies — stdlib + sqlite3 priority

## Known Limitations

- KİK source unavailable (HTTP 401 requires auth/token)
- UDF toolkit optional (requires LibreOffice/unoconv, controlled by env vars)
- Mevzuat adapter status: experimental (base64 HTML decode, type filtering works)

## Verification Gate

```
python -m ruff check .                                    # All checks passed
python -m pytest tests/ -q                                # 650 passed
python -c "from emsal_mcp.server import main"             # Server import OK
python -m emsal_mcp.cli release command-center --json     # overall_readiness: 100
python -m emsal_mcp.cli release v1-readiness --json       # ready: true
```

## Next Steps

- M-06: Cache integrity & maintenance (vacuum, orphan cleanup, migration control)
- M-07: Semantic search v2 (Turkish stemming, snippet highlighting)
- M-08: Citation graph (inter-document citation relationships)
