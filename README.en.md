# Emsal-mcp

> **v1.1.1** — 11 core + 36 extended MCP tools (47 total) · 152 CLI commands · 79 test files · 48 source modules
>
> [![CI](https://github.com/afsozer/emsal-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/afsozer/emsal-mcp/actions/workflows/ci.yml)

**Project page:** [avfatihsozer.com/en/projects/emsal-mcp](https://avfatihsozer.com/en/projects/emsal-mcp) · Türkçe: [README.md](README.md)

An MCP server for citation-safe search, research and document preparation
across official and publicly available Turkish legal sources (case law and
legislation).

It works in two ways:

- **Local corpus:** 11.1 million decisions and the complete body of current
  legislation in a single SQLite file, with FTS5 full-text search plus FAISS
  semantic search. No network required.
- **Live sources:** adapters for Bedesten (the Ministry of Justice's decision
  search system) / Court of Cassation, Constitutional Court (AYM), Council of
  State, Court of Jurisdictional Disputes, Competition Authority, Court of
  Accounts, Revenue Administration (GİB), mevzuat.gov.tr, Official Gazette and
  KVKK.

## Red lines

- No decision, metadata, date, docket/decision number, chamber, citation or statutory article is ever fabricated.
- Documents without `full_text` / `html_markdown` content are not used for quoting or drafting.
- `quoteUsable` and `draftUsable` are `true` only when full text or HTML markdown is present.
- The rate limit is deliberately not conservative; the target is a single user on a single machine.

## Corpus

Measured on 16 September 2026, live corpus (`cache.sqlite3`, 72 GB).

| Layer | Measure |
|---|---|
| Decisions | **11,108,242** documents (`documents_v2`). Base: HF `hamzabagirsakci/turkish-court-decisions` (11,045,085, CC0), topped up by a daily Bedesten crawl. |
| Legislation documents | **14,298** records / 14,171 current versions: 916 laws, 63 decree-laws (KHK), 33 Presidential decrees (CBK), 8,840 regulations (8,830 current), 4,446 communiqués (4,329 current) |
| Legislation articles | **303,454** articles, **96,186** amendment records |
| Decision semantic index | **29,554,075** chunk vectors: `intfloat/multilingual-e5-small` (384 dimensions), FAISS `IVF16384,PQ64` + fp16 sidecar refine, `nprobe=128`, chunking v2 |
| Legislation semantic index | **423,920** chunk vectors (from 303,454 articles), same model and index type |

Details and measurements: [`docs/BULK_INDEX.md`](docs/BULK_INDEX.md).

## Installation

### Quick install (without the corpus)

Emsal MCP also works without the 11-million-decision local corpus. In that case
decision and legislation searches run live against the official sources (Bedesten,
mevzuat.gov.tr, the Constitutional Court, the Council of State and others), and full
decision texts are fetched live as well. Only the tools that search the local corpus
(`search_local_corpus`, `mevzuat_korpus_ara`, `mevzuat_madde_getir`) return empty
results and point to the live tools. Python 3.11 or later is required.

```bash
# Run without installing (requires uv)
uvx --from emsal-mcp emsal-mcp-server

# or install permanently
pipx install emsal-mcp
```

To add it to Claude Code:

```bash
claude mcp add emsal -- uvx --from emsal-mcp emsal-mcp-server
```

Configuration for Claude Desktop or another MCP client:

```json
{
  "mcpServers": {
    "emsal": {
      "command": "uvx",
      "args": ["--from", "emsal-mcp", "emsal-mcp-server"]
    }
  }
}
```

The default tool profile exposes 11 core tools; set `EMSAL_TOOL_PROFILE=full` for all
of them. Fetched documents are cached in `~/.emsal_mcp/cache.sqlite3` (change it with
`EMSAL_CACHE_PATH`).

### Development install (with the corpus)

```powershell
# Windows
cd <repo-dizini>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,mcp,embeddings]"

# macOS / Linux
cd <repo-dizini>
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp,embeddings]"

emsal-mcp version
```

For semantic search to use the bulk FAISS index you also need
`pip install faiss-cpu`. Detailed installation: [`INSTALL.md`](INSTALL.md).

## Running

### HTTP (streamable-http) server

In the live deployment the server is started with `scripts\mcp_http_sunucu.cmd`;
this script sets up the environment variables itself and writes its log to
`%LOCALAPPDATA%\emsal-mcp\mcp_http.log`.

```powershell
.\scripts\mcp_http_sunucu.cmd
```

On Windows, the `EmsalMcpHttp` scheduled task runs the same script at logon.
Endpoint: `http://<host>:<port>/mcp`.

### stdio server

```powershell
call .\scripts\emsal-env.cmd
emsal-mcp-server
```

### Environment variables

| Variable | Purpose | Example value |
|---|---|---|
| `EMSAL_CACHE_PATH` | Corpus SQLite file | `<veri-dizini>\cache.sqlite3` |
| `EMSAL_BULK_VEC_DIR` | fp16 vector sidecars (for refine) | `<bench-dizini>\vec` |
| `EMSAL_EMBEDDING_PROVIDER` | Embedding provider | `fastembed-multilingual-e5` |
| `EMSAL_EMBEDDING_CACHE_DIR` | ONNX model cache | `<veri-dizini>\models\fastembed` |
| `EMSAL_MCP_TRANSPORT` | `stdio` (default) or `streamable-http` | `streamable-http` |
| `EMSAL_MCP_HOST` / `EMSAL_MCP_PORT` | HTTP listen address | `127.0.0.1` / `8790` |
| `EMSAL_TOOL_PROFILE` | `core` (default) or `full` | `core` |
| `EMSAL_TOOL_THREADS` | Thread pool for sync tools (0 = off) | `6` |
| `EMSAL_TOOL_TIMEOUT` | Per-tool limit in seconds | `180` |

For one-off CLI calls, `scripts\emsal-env.cmd` sets the same variables
(`call .\scripts\emsal-env.cmd && .venv\Scripts\emsal-mcp ...`).

Machine-specific values (data directory, listen address, backup target) are not
kept in the repo: copy `scripts\yerel-ayar.ornek.cmd` to
`scripts\yerel-ayar.cmd` and fill it in (it is in `.gitignore`). `emsal-env.cmd`,
`crawl_incremental.ps1` and the Python scripts (`scripts/_yollar.py`) read this
file; every path left empty is derived from `~/.emsal_mcp`.

## MCP tools

The default profile is `core`, which registers 11 tools. The rest are added to
the running server category by category with `load_extended_tools`. Contracts:
[`docs/MCP_CONTRACTS.md`](docs/MCP_CONTRACTS.md).

**Core (11):**

| Tool | What it does |
|---|---|
| `search_decisions` | Decision search across live sources (including routing) |
| `get_document` | Fetch a single document |
| `search_local_corpus` | FTS5 + semantic search over the local 11 M decision corpus |
| `search_legislation` | Legislation search on mevzuat.gov.tr |
| `get_legislation` | Fetch legislation text / an article |
| `mevzuat_korpus_ara` | Article-level search in the local legislation corpus |
| `mevzuat_madde_getir` | A single article from the local corpus |
| `research_topic` | Topic research package (bundle + quality dashboard) |
| `export_document` | Document export |
| `load_extended_tools` | Load extended categories at runtime |
| `health_check` | Source/breaker/index/scheduled job health |

**Extended (36), by category:**

| Category | Tool count | Tools |
|---|---|---|
| `legislation` | 1 | `mevzuat_degisiklik_raporu` |
| `drafting` | 2 | `citation_check`, `prepare_petition` |
| `files` | 1 | `read_legal_file` |
| `meta` | 2 | `list_sources`, `legal_research_guide` |
| `health_admin` | 4 | `circuit_breaker_status`, `source_health`, `source_smoke`, `check_government_servers_health` |
| `watch` | 4 | `watch_add`, `watch_list`, `watch_run`, `watch_remove` |
| `privacy` | 3 | `privacy_scan`, `privacy_redact`, `privacy_audit` |
| `chambers` | 4 | `chamber_overview`, `profile_chamber`, `chamber_timeline`, `find_similar_chambers` |
| `indexing` | 1 | `index_status` |
| `drafting_advanced` | 10 | `draft_document`, `export_bundle`, `inspect_petition_pack`, `build_multi_issue_pack`, `inspect_multi_issue_pack`, `list_petition_templates`, `get_petition_template`, `build_argument_chain`, `score_argument`, `get_argument_strength_report` |
| `udf_admin` | 4 | `udf_toolkit_status`, `udf_authoring_instructions`, `pdf_toolkit_status`, `promote_pdf_to_full_text` |

> Because the core profile's docstring budget (20,000 characters) was full,
> `citation_check`, `prepare_petition`, `read_legal_file`, `list_sources` and
> `legal_research_guide` were moved to extended on 6 September 2026; they come
> back with `load_extended_tools`.

## CLI examples

```powershell
emsal-mcp sources
emsal-mcp search bedesten "muvazaa" --limit 5
emsal-mcp get bedesten DOCUMENT_ID
emsal-mcp semantic bulk-status
emsal-mcp mevzuat korpus-ara "tahliye taahhüdü"
emsal-mcp smoke --offline
```

## Corpus crawl + dashboard

The long-running corpus crawl (downloading decisions from Bedesten year by
year) is driven by a master script, and its progress can be followed in the
browser.

```powershell
.\scripts\kur-otomatik-baslatma.ps1          # oturum açılışına ekler (yönetici gerekmez)
.\scripts\kur-otomatik-baslatma.ps1 -Durum   # ne çalışıyor?
.\scripts\kur-otomatik-baslatma.ps1 -Kaldir  # geri al
```

| Component | What it does |
|---|---|
| `crawl_master.ps1` | Crawls the years in order. Single-instance lock (mutex); writes a checkpoint to `crawl_logs\crawl_state.json`, so if the PC shuts down it resumes from the **year and page** where it stopped. |
| `scripts\panel.py` | http://127.0.0.1:8799: live crawl status, per-year targets, library distribution, speed/ETA. No extra dependencies. |
| Scheduled tasks | `EmsalCrawlMaster` (logon + 1 min), `EmsalPanel` (logon + 20 s). |

Notes:

- Rate limit `EMSAL_RATE_LIMIT_MAX=12`. Measured: no 429s at 12 (~2,800 documents/hour);
  at 15 it falls into a 429 cooldown loop and throughput drops to zero.
- The dashboard does not count years on `cache.sqlite3`: a single per-year query
  takes ~60 s because of a full table scan. Counts are kept incrementally (new
  `rowid`s only) in `~/.emsal-mcp/panel_stats.sqlite3`, with a full recount once a day.
- Per-year targets are measured from Bedesten's `total` field (`crawl_logs\hedefler.json`),
  not estimated.

## Operations

Scheduled jobs (Windows Task Scheduler, corpus server):

| Task | Schedule | Script | What it does |
|---|---|---|---|
| `EmsalMcpHttp` | at logon | `scripts\mcp_http_sunucu.cmd` | Serves the MCP server |
| `EmsalCrawlDaily` | daily 04:30 | `scripts\crawl_incremental.ps1` | Incremental decision crawl |
| `EmsalMevzuatWeekly` | Sunday 03:00 | `scripts\mevzuat_weekly.cmd` | Legislation update (+ post-processing `mevzuat_semantic.cmd`) |
| `EmsalMonthlyMerge` | 1st of the month 02:00 | `scripts\monthly_merge.cmd` | Merges delta vectors into the bulk FAISS index |

The `health_check` tool reports the last run of these jobs in the
`scheduled_jobs` block: it does not call `schtasks`, but reads the completion
marker each job writes to its own log file, plus the file timestamp. If a job is
overdue or finished with `rc != 0`, `overall` returns "degraded"
(`src/emsal_mcp/ops_status.py`). In the same output, the `tool_runtime` block
gives thread pool / timeout counters; if `runaway > 0`, the server should be
restarted.

## Documentation

| Document | Contents |
|---|---|
| [`docs/BULK_INDEX.md`](docs/BULK_INDEX.md) | Bulk corpus setup, FAISS index structure, chunking v2, measurements, pitfalls |
| [`docs/MCP_CONTRACTS.md`](docs/MCP_CONTRACTS.md) | MCP tool contracts, profiles, categories |
| [`docs/COOKBOOK.md`](docs/COOKBOOK.md) | Copy-and-run workflow recipes |
| [`docs/JSON_CONTRACTS.md`](docs/JSON_CONTRACTS.md) | JSON output contracts of the public API functions |
| [`docs/ERROR_CATALOG.md`](docs/ERROR_CATALOG.md) | Error codes and recommended actions |
| [`docs/INDEX.md`](docs/INDEX.md) | Index of all documents |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history |

## Tests

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests -q
ruff check src tests scripts
```

Tests that hit live sources are skipped by default; set
`EMSAL_LIVE_TESTS=1` to enable them.

## License

Licensed under the GNU Affero General Public License, version 3 only
(`AGPL-3.0-only`); the full text is in [LICENSE](LICENSE). If you modify the
software and offer it to others over a network, you must make your modified
source code available to those users under the same licence. See
[SECURITY.md](SECURITY.md) for how to report a vulnerability.

Copyright © 2026 Alpaslan Fatih Sözer

<!-- mcp-name: io.github.afsozer/emsal-mcp -->
