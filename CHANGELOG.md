# CHANGELOG.md

All notable changes to emsal-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **M-69:** Hibrit embeddings GA — Reciprocal Rank Fusion (RRF) test kapsamı tamamlandı. `_rrf_fusion()` birim testleri (9 adet: 2'li/3'lü sıralayıcı, boş küme, limit, metadata koruma) ve `hybrid_search_rrf()` entegrasyon testleri (7 adet: temel arama, dense dahil, boş cache, determinizm, limit, tekilleştirme, RRF vs lineer karşılaştırma) eklendi. Mevcut RRF altyapısı (`semantic.py` — `_rrf_fusion`, `hybrid_search_rrf`, `_fts5_search`, `_tfidf_search`) doğrulandı. BM25 + TF-IDF + dense 3-sinyal RRF tümlemesi test edildi. Toplam 16 yeni test.
- **M-71:** Getirme değerlendirme koşumu (eval harness) — `eval_metrics.py`: `recall_at_k()`, `ndcg_at_k()`, `evaluate_search()` ile altın sorgu setine karşı arama kalitesi ölçümü. `eval/golden_queries.json` ile 5 sentetik sorgu. CLI: `emsal-mcp eval run`. MCP: `run_evaluation`. 21 test.
- **M-69:** Embeddings GA — Reciprocal Rank Fusion (RRF) hibrit skorlama eklendi. `hybrid_search_rrf()` BM25 + TF-IDF + opsiyonel dense embedding sonuçlarını rank pozisyonuyla birleştirir (skor normalizasyonu gerekmez). CLI: `emsal-mcp semantic hybrid --rrf --dense`. MCP: `hybrid_search_rrf`. 1570 test.

### Added
- **M-60:** Adaptör yanıt-şeması doğrulaması — `SourceClient` sınıfına `_check_response_schema()` metodu eklendi. Bedesten, Mevzuat, Danıştay, GİB, Sayıştay adaptörleri için beklenen JSON yanıt anahtarları (`_search_response_keys`, `_get_document_response_keys`) tanımlandı. API şema değişimi (primary key kaybı) saptandığında `_capability_status` runtime'da `STABLE` → `PARTIAL` olarak düşürülür. Fallback zinciri korunur; HTML tabanlı adaptörler (AYM, Uyuşmazlık, Rekabet) doğrulamaya dahil edilmez. 26 yeni test (10 birim + 16 entegrasyon) eklendi.
- **M-61:** Kaynak sağlık izleme — `SourceSmokeResult` modeline `schema_health` alanı eklendi. `SourceClient._schema_signature()` metodu ile her adaptörün beklenen şema anahtarlarının hash imzası hesaplanır. Şema imzaları `~/.emsal_mcp/.emsal_schema_sigs.json` dosyasında kalıcı olarak saklanır; smoke testleri arası çapraz çalıştırmalarda imza değişimi saptanıp uyarı üretilir. `smoke_all_sync` çıktısı artık kaynak-başı şema sağlık durumu içerir. 18 yeni test eklendi.
- **M-62:** mypy sıkılaştırma — `check_untyped_defs=true`, `warn_return_any=true` aktif edildi. 85 mypy hatası giderildi: `legislation.py` (32 `Document | None` tip daraltması), `research_watch.py` (21 `Cache | None`), `verification.py`/`cli.py`/`sources/` ve yaprak modüllerdeki tüm tip uyumsuzlukları düzeltildi. `python -m mypy src` tamamen temiz. Geçit doğrulamasına mypy dahil edildi.
- **M-63:** Yola-bağımsız kurulum — README.md ve INSTALL.md'deki sabit `C:\Users\Sozer\Emsal-mcp` yolu `<repo-dizini>` placeholder'ı ile değiştirildi. Her iki platform (Windows/macOS/Linux) için aktivasyon örnekleri eklendi. README altbilgisindeki güncel olmayan araç/komut/test sayıları düzeltildi.
- **M-64:** CI iskeleti — `.github/workflows/ci.yml` mevcut (Python 3.11/3.12 matrix, ruff, pytest, mypy, import-smoke, release readiness). README'ye CI durum rozeti eklendi. Tüm açık milestone'lar tamamlandı.

### Fixed
- **CI cross-platform:** `prepare_petition_outline`, `prepare_controlled_petition_draft` ve `prepare_export_package_bundle` çıktı dizinini guard'sız `mkdir(parents=True)` ile oluşturuyordu. Linux'ta `/nonexistent` gibi bir yol kök dizinde `PermissionError` fırlatıp exception olarak sızıyordu (Windows'ta farklı davrandığı için 5 graceful-degradation testi lokalde geçip CI'da fail ediyordu). `mkdir` artık `try/except OSError` ile sarıldı; hata durumunda `OUTPUT_DIR_ERROR` yapısal hatası dönüyor. Her platformda tutarlı; CI (3.11/3.12) yeşil.
- **Citation provenance:** Bedesten/Mevzuat `getDocumentContent` yalnızca içerik döndürdüğü için ID ile çekilen belgenin esas/karar/tarih alanları boş kalıyor ve tam metin mevcutken bile `citation_check` başarısız oluyordu (`quoteUsable=false`). `models.merge_search_metadata()` eklendi (fill-empty-only, uydurma/çıkarım yok); `research_topic` fetch döngüsünde arama API'sinin döndürdüğü yapısal metadata belgeye taşınıyor. Canlı doğrulandı: `quoteUsable False → True`. 2 hermetik test.
- **M-57:** Hermetik test düzeltmesi — `test_status_nonexistent_env` artık LibreOffice kurulu/kurulu olmayan tüm makinelerde aynı sonucu veriyor. UDF toolkit'inin binary keşfi (`_discover_libreoffice`, `_discover_unoconv`) ve dizin çözümlemesi (`_resolve_toolkit_dir`) enjekte edilebilir hale getirildi; testler tamamen ortamdan bağımsız (hermetik).
- **M-58:** README drift tespiti — README başlığındaki sürüm/modül/araç sayıları artık koddan otomatik türetiliyor (`scripts/gen_readme_counts.py`). Drift durumunda `tests/test_readme_drift.py` CI'da hata verir.
- **M-59:** Doküman konsolidasyonu — `docs/INDEX.md` tüm 11 dokümanı kapsayacak şekilde güncellendi (API.md, COOKBOOK.md, GLOSSARY.md, ERROR_CATALOG.md, LICENSES.md eklendi). Kök dizinde yalnızca README, CHANGELOG, INSTALL, ROADMAP + Makefile kaldı.
- **M-60:** Adaptör yanıt-şeması doğrulaması — `SourceClient.validate_response_schema()` ile her adaptör beklenen JSON anahtarlarını bildiriyor; şema drift'i durumunda `_capability_status` runtime'da `PARTIAL`'a düşürülüyor, legacy fallback zinciri güvenlik ağı olarak korunuyor. Bedesten, Mevzuat, Danıştay, GİB, Sayıştay adaptörleri için schema tanımlandı. 26 test.
- **M-61:** Smoke genişletme — `SourceSmokeResult`'a `schema_health` alanı eklendi; her adaptörün beklenen/gerçek şema imzası smoke çıktısında görünür. Şema drift'i tespit edilince `drift_detected: true` + `drift_detail` raporlanır. 7 test.
- **M-65:** Provenance açığı — `get`/`citation-check` komutlarına cache fallback eklendi. `cache.get_document()` ile daha önce `search`/`store_document` akışından cache'lenmiş metadata (esas_no, karar_no, decision_date) `merge_search_metadata()` ile belgeye taşınır. Yalnızca cache'teki yapısal API verisi kullanılır, uydurma yok. CLI ve MCP `get_document` araçları güncellendi.
- **M-66:** Tarih makuliyet doğrulaması — `finalize_document()`'a `_check_date_plausibility()` eklendi. Yılı [1920, current_year+1] dışındaki `decision_date` değerleri warnings'e işaretlenir, `metadata_confidence` "low" olarak düşürülür. Tarih değeri asla değiştirilmez. ISO (YYYY-MM-DD) ve TR (DD.MM.YYYY) formatları desteklenir.
- **M-67:** Watch kurtarma sinyali — `run_watch` diff raporuna `citation_safe_count`, `citation_safe_delta` ve `content_recovery_signal` eklendi. Önceki çalıştırmada 0 tam metinli belge varken şimdi >0 olduğunda "Kaynak içeriği geri geldi" sinyali üretilir. Sayaç cache'te `watch_cs:{name}` anahtarıyla saklanır.
- **M-68:** Lint borcu — `pyproject.toml`'da `extend-ignore = ["D100", "D101", "D103", "E402"]` tanımlandı. D=advisory docstring kuralları, E402=bilinçli lazy import'lar (M-52). `ruff check .` → 0 hata (gerçek geçit yeşil).

## [3.1.0] — 2026-05-30

### Added
- **M-54: Test Suite Speed & Organization:** Session-scoped cache fixtures, module-level pytest markers (`unit`/`integration`), `conftest.py` with shared fixtures. Unit tests run in ~4s, integration in ~74s.
- **M-55: Dependency & Security Hygiene:** Pinned version ranges for all optional extras, `docs/LICENSES.md` documenting all 13 dependencies (zero copyleft).
- **M-56: Consolidation:** Version bumped to 3.1.0.

### Changed
- **FAZ 11 (Documentation):** Document accuracy audit (M-41), docstring coverage 100% (M-42), usage cookbook with 8 recipes (M-43), TR/EN glossary with 77 terms (M-44).
- **FAZ 12 (Fixes):** Dead code sweep confirmed clean (M-45), edge-case hardening with 46 tests (M-46), type annotations completed for 121 functions (M-47), error catalog with 76 codes (M-48), determinism audit — no flaky tests found (M-49).
- **FAZ 13 (Performance):** Cache FTS5 optimization + schema v4 migration (M-50), cursor streaming for memory reduction (M-51), lazy imports — server startup 11x faster (M-52), TF-IDF norm precompute + regex precompile (M-53).

---

## [3.0.2] — 2026-05-30

### Fixed
- **Stopped tracking generated research artifacts:** untracked 24 files under `.emsal_research/` (synthetic `fake_source` research bundles regenerated by the test suite). The directory was already in `.gitignore` but had been committed before that rule existed, causing perpetual phantom "modified" diffs. Files remain on disk; only the git tracking is removed.

### Changed
- Version bumped to 3.0.2.

---

## [3.0.1] — 2026-05-30

### Fixed
- **Removed dead duplicate PDF module:** deleted orphan `pdf_extract.py` (151 lines) and its test `test_pdf_extract.py`. The wired-in production module is `pdf_extractor.py` (imported by `server.py` and `cli.py`); the duplicate was unused leftover from an earlier M-27 iteration, referenced only by its own test.

### Changed
- Version bumped to 3.0.1.

---

## [3.0.0] — 2026-05-29

### Added
- **Golden Corpus & Snapshot Tests (`tests/fixtures/sample_decisions.json`, `tests/test_snapshots.py`):** 5 synthetic Turkish legal decisions for deterministic regression testing of citation extraction, petition pack, hybrid search, and legislation parsing.
- **Documentation Index (`docs/INDEX.md`):** Comprehensive index of all 11 project documents.
- **Version bumped to 3.0.0.**

### Changed
- All M-24 → M-40 milestones complete (17 milestones, 249 new tests).
- Final test count: 1423 passed, 0 lint errors.

---

## [2.5.0] — 2026-05-29

### Added
- **PII Detection & Privacy (`privacy.py`):** TCKN, phone, email scanning with `scan_pii()`, `redact_pii()` (copy-safe, original unmodified), and `audit_privacy()` for file/directory scanning. MCP tools: `privacy_scan`, `privacy_redact`, `privacy_audit`. CLI: `emsal-mcp privacy scan/redact/audit`.
- **Citation Graph Export (`citation_graph.py`):** `export_graph()` supporting JSON (node-link), DOT (Graphviz), and Mermaid formats with optional sub-graph export by document_id + BFS traversal. CLI: `emsal-mcp graph export --format json/dot/mermaid`. MCP tool: `export_citation_graph`.

---

## [2.4.0] — 2026-05-29

### Added
- **Multi-Machine Cache Sync (`cache.py`):** `sync_cache()` with additive merge, conflict resolution (newest `retrieved_at` wins), content hash mismatch detection. CLI: `emsal-mcp cache sync`. MCP tool: `sync_cache`.
- **Adapter SDK (`docs/ADAPTER_SDK.md`, `sources/example_adapter.py`):** Documentation and example for creating custom source adapters. Plugin registry: `register_adapter()` for runtime adapter injection.
- **Research Watchlist (`research_watch.py`):** `add_watch()`, `list_watches()`, `run_watch()` (diff report on new/changed docs), `remove_watch()`. Stores in `watch_configs` SQLite table. CLI: `emsal-mcp watch add/list/run/remove`. MCP: 4 tools.

---

## [2.3.0] — 2026-05-29

### Added
- **HTTP REST API Server (`api_server.py`):** stdlib `http.server`-based API with read-only endpoints: `/version`, `/health`, `/sources`, `/sources/smoke`, `/release/readiness`, `/cache/stats`. Optional auth via `EMSAL_API_TOKEN`. CORS headers. CLI: `emsal-mcp api serve`. Optional extra: `[api]`.
- **Fuzzy Dedup v2 (`dedup.py`):** `find_fuzzy_duplicates()` using M-24 dense embedding cosine similarity + date proximity. Embedding similarity only SUGGESTS candidates — never auto-merges. Excludes M-09 cluster members. CLI: `emsal-mcp cache fuzzy-duplicates`.
- **Async Concurrency (`concurrency.py`):** Semaphore-based limited parallelism for `research_topic` and batch fetches with configurable `max_concurrency`. Compatible with M-17 circuit breaker + M-18 retry.
- **Adaptive Throttle & Calibrate (`calibrate.py`):** `calibrate_source()` measures safe request rate per source, returns config suggestions. CLI: `emsal-mcp calibrate <source>`.
- **Benchmark Suite (`benchmark.py`):** Deterministic micro-benchmark for index build, hybrid search, dense search latency on synthetic static corpus. CLI: `emsal-mcp benchmark run --json`.
- **Embedding Cache (`embeddings.py`):** `content_hash`-keyed embedding cache; same content embedded once. Provider change invalidates cache. Disk usage reporting via `index_sync_status()`.

---

## [2.2.0] — 2026-05-29

### Added
- **Cross-Encoder Reranker (`embeddings.py`):** `rerank_results()` — optional re-ranking of top-k hybrid results using fastembed cross-encoder (model: `ms-marco-MiniLM-L-6-v2`). Graceful passthrough when unavailable. CLI: `--rerank` flag on `hybrid_search`. MCP: `rerank` parameter.
- **Incremental Index (`semantic.py`):** `update_indexes()` — content-hash-based delta indexing for both TF-IDF (`search_vectors`) and dense (`embedding_vectors`) stores. `get_index_sync_status()` reports out-of-sync counts. CLI: `emsal-mcp semantic update-indexes` / `sync-status`.
- **PDF/OCR Content Extraction (`pdf_extract.py`):** `extract_pdf_text()` with optional `pypdf` text-layer extraction. OCR opt-in only with `metadata_confidence=low` warning. `promote_pdf_to_full_text()` — promotes `pdf_only` documents to `full_text` when text extractable. Optional extra: `[ocr]`.

---

## [2.1.0] — 2026-05-29

### Added
- **Dense Embedding Semantic Search (`embeddings.py`):** Pluggable `EmbeddingProvider` ABC ported from local-yargi.
  - **`LocalHashProvider`** (id=`local-hash-v1`, 128 dims): Deterministic hash-based embedding — zero deps, always available. Always the default. SHA-256 token hashing + pseudo-random vector indices + trigram sub-word similarity + L2 normalization.
  - **`FastEmbedProvider`** (id=`fastembed-minilm-l6-v2`, 384 dims, model `all-MiniLM-L6-v2`): Lazy import fastembed. `MAX_TEXT_CHARS=8000`, batch_size configurable. Graceful `EMBEDDING_BACKEND_UNAVAILABLE` when not installed.
  - **Provider Factory:** Priority: CLI arg > `EMSAL_EMBEDDING_PROVIDER` env > `local-hash-v1` default.
  - **BLOB Vector Storage:** `embedding_vectors` table with float32-packed BLOBs (not JSON), separate from TF-IDF `search_vectors`. Content-hash dedup on re-index.
- **Hybrid v3 (`semantic.py`):** 3-signal merge: `w_bm25·BM25norm + w_tfidf·cosine + w_dense·dense_score`. Weights from config (`EMSAL_HYBRID_W_*`). `w_dense=0` → exact v2 regression (test-proven). `build_embedding_index()`, `embedding_search()`, `get_embedding_index_status()`. CLI: `emsal-mcp semantic embed-index/embed-search/providers/embedding-status`. MCP: 4 tools. Optional extra: `[embeddings]`.
- **Version bumped to 0.10.3 → 2.1.0.**

---

## [2.0.0] — 2026-05-29

### Added (M-06 → M-23, FAZ 2-5)

**Data & Search (FAZ 2 — M-06→M-10):**
- **Cache Maintenance (`cache.py`):** `vacuum_cache()`, `cleanup_orphans()` (orphan `search_vectors`/FTS5 rows), `check_integrity_full()` (PRAGMA + orphan + schema + hash + row counts). Schema migration v2→v3 with `schema_meta` table. `CACHE_SCHEMA_VERSION=3`. CLI: `emsal-mcp cache compact/cleanup-orphans/integrity-check`.
- **Semantic Search v2 (`semantic.py`):** Turkish suffix-stripping query expansion (10 rules), snippet highlighting with `**markers**`, per-source filter support in hybrid search, `hybrid_weight` validation (0.0–1.0).
- **Citation Graph (`citation_graph.py`):** `build_citation_graph()` — extract cross-document references, match against cache (confidence: high/medium/low), store edges in `citation_edges` table. `get_citation_graph()`, `find_citing_documents()`, `find_cited_documents()`, `get_citation_graph_stats()`. CLI: `emsal-mcp graph`. Never fabricates — only detectable verified references.
- **Cross-Source Dedup (`dedup.py`):** `find_duplicates()` clusters by `(court, esas_no, karar_no)`. Deterministic canonical selection: `full_text` > `html_markdown` > `metadata_only`. False-merge prevention: no title-only grouping. `dedup_clusters` + `dedup_members` tables. CLI: `emsal-mcp cache find-duplicates/dedup-cluster/dedup-stats/merge-cluster`.
- **Search Analytics (`search_analytics.py`):** `search_history` table with auto-recording from `search_local()`. `get_search_analytics()` — empty_result_rate, cache_hit_rate, top_queries, daily_activity. `get_source_coverage()`. CLI: `emsal-mcp analytics`.

**Petition & Document (FAZ 3 — M-11→M-15, controller-heavy):**
- **Template Library (`templates.py`):** 4 petition templates (Dava, Cevap, Temyiz, İstinaf) with `{{PLACEHOLDER}}` convention. `render_template_to_skeleton()` with DISCLAIMER_HEADER. `prepare_drafting_input_pack(template_name=...)`. CLI: `emsal-mcp template`.
- **Argument Builder (`argument.py`):** `build_argument_chain()` — claim → supporting authority → counter-argument. Only `petition_ready` in `supporting_authorities` (metadata-only leak invariant). `score_argument()` (0.0–1.0). CLI: `emsal-mcp argument`.
- **Multi-Issue Pack (`petition.py`):** `build_multi_issue_pack()` with isolated per-issue `citation-bank.md` + `argument-map.md`. Shared source documents, hash-manifest across all issues. Backward compatible single-issue API.
- **Draft Diff (`draft_diff.py`):** Unified diff via stdlib `difflib`, `track_placeholders()` with fill status, `get_fill_report()`, `save_draft_version()` for version snapshots. CLI: `emsal-mcp draft`.
- **Export Format Expansion (`exporter.py`):** `export_plain_text()`, `export_to_format()` unified dispatcher (docx/txt always, pdf/udf toolkit-gated), `get_export_capabilities()`. Disclaimer preserved in all formats.

**Sources (FAZ 4 — M-16→M-19):**
- **KİK Adapter (`sources/registry.py`):** Optional token auth via `KIK_API_TOKEN`/`EKAP_API_TOKEN` env vars. Token present → `EXPERIMENTAL`, absent → `UNAVAILABLE` (existing behavior preserved). `docs/KIK_RESEARCH.md`.
- **Circuit Breaker (`circuit.py`):** State machine (CLOSED→OPEN→HALF_OPEN→CLOSED) with configurable threshold (default 5 failures) and recovery timeout (300s). `circuit_state` SQLite table. `_with_circuit()` opt-in wrapper on `SourceClient`. CLI: `emsal-mcp circuit`.
- **Retry & Rate-Limit (`sources/base.py`):** `_with_retry()` exponential backoff (1s, 2s, 4s...). `RateLimiter` token-bucket (default OFF — single-user preserved). Config: `EMSAL_RETRY_MAX`, `EMSAL_RETRY_DELAY`, `EMSAL_RATE_LIMIT_ENABLED`.
- **Capability Routing (`router.py`):** `get_capable_sources()`, `route_search()`, `route_get_document()` — auto-select sources by capability matrix. Deterministic: same input → same routing. CLI: `emsal-mcp router`.

**Packaging & v2 (FAZ 5 — M-20→M-23):**
- **Packaging:** `pyproject.toml` hygiene, `INSTALL.md` (6 methods), optional extras `[mcp]`, `[udf]`, `[dev]`, `[embeddings]`.
- **CI Pipeline:** `.github/workflows/ci.yml` (Python 3.11/3.12 matrix, lint+test+smoke), `Makefile`.
- **MCP Hardening (`server_utils.py`):** Input validation decorator on 5 critical tools, 48 error code catalog, `_track_request` concurrency counter, server-level smoke test.
- **`build_error()` helper (`models.py`):** Canonical error dict shape across all modules — 51 ad-hoc error dicts normalized.
- **Invariant Test Suite (`test_invariants.py`):** 47 tests covering metadata-only→draft_usable, citation no-fabrication, graceful degradation, placeholder preservation, sources_override safety.

---

## [1.0.0] — 2026-05-29

### Added (M-01 → M-05, FAZ 1)

- **Config System (`config.py`):** `EmsalConfig` class with env-override for cache path, user agent, UDF toolkit, log level, HTTP timeout, KIK token, circuit breaker, retry, rate-limit.
- **`emsal-mcp doctor` command:** Environment diagnostics (Python version, cache access, toolkit status, source smoke summary).
- **Coverage measurement (`pytest-cov`):** Coverage baseline established (76%→84%).
- **Documentation sync:** `CHANGELOG.md` updated for v0.11–v0.13, `ROADMAP.md` section order fixed, contract docs expanded to 54 tools, `README.md` updated.
- **Version bumped to 1.0.0.** `RELEASE_NOTES_v1.0.0.md` generated. `final_v1_readiness` gate green.

---

## [0.13.0] — 2026-05-29

### Added

- **Release Command Center** (`release.py`):
  - **`release_command_center()`**: runs comprehensive pre-release verification
    (smoke tests, source capabilities, module imports, FTS5 index health, chamber
    overview, UDF toolkit). Returns structured dict with overall_readiness score
    (0–100), checks_passed/total, per-check ok/fail, warnings, and
    recommended_actions.
  - **`version_bump(current_version, bump_type)`**: calculates next version
    string from major/minor/patch bump. Returns ok, current_version, bump_type,
    next_version. Does not modify files.
  - **`final_v1_readiness()`**: v1.0.0 go/no-go gate checking all modules
    importable, has stable sources, release smoke passes, only KİK is
    unavailable. Returns ok, ready, criteria with pass/fail, version.
  - **`generate_release_summary(version)`**: human-readable + JSON release
    summary with version, date, test count, module count, source stats, UDF
    status, warnings, recommended_actions.

- **4 CLI Commands** under `emsal-mcp release`:
  - `command-center [--json]`
  - `version-bump [--major|--minor|--patch] [--json]`
  - `v1-readiness [--json]`
  - `summary [--json]`

- **4 MCP Tools**:
  - `release_command_center`: comprehensive pre-release verification
  - `version_bump`: calculate next version
  - `final_v1_readiness`: v1.0.0 go/no-go gate
  - `generate_release_summary`: release summary in markdown + JSON

- **Tests**: `tests/test_release.py` with test cases covering command center
  scoring, version bump types, v1 readiness criteria, summary generation,
  CLI and MCP imports.

### Changed

- **Version bumped to 0.13.0** in `__init__.py` and `pyproject.toml`.
- **All v0.12 tests pass** (513 total, all passing).

### Backward Compatibility

- All v0.12 tests continue to pass (513 total tests, all passing).
- Release module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.

## [0.12.0] — 2026-05-29

### Added

- **Chamber Profiling Module** (`chamber.py`):
  - **`get_chamber_overview(court=None)`**: returns all chambers with document
    counts, date ranges, and last activity. Optional court filter. Returns ok,
    chamber_count, chambers list with name, court, document_count,
    date_range_earliest, date_range_latest, last_activity.
  - **`profile_chamber(chamber, court=None)`**: detailed chamber profile with
    metrics (document_count, avg_text_length, content_status_distribution),
    top 20 keywords (Turkish stopword-filtered), and recent documents.
  - **`chamber_timeline(chamber=None, court=None, start_year=None,
    end_year=None)`**: year-grouped decision distribution supporting both
    ISO and DD.MM.YYYY date formats. Returns timeline with year, count,
    earliest, latest.
  - **`find_similar_chambers(chamber, court=None, limit=5)`**: Jaccard
    similarity on keyword sets to find related chambers. Returns ok, chamber,
    similar_chambers with similarity score and shared keywords.

- **Turkish stopword filtering**: "ve", "bir", "bu", "ile", "hakkında",
  "ilişkin", "için", "üzerinde", "olarak", "sonra" and more excluded
  from keyword extraction.

- **4 CLI Commands** under `emsal-mcp chamber`:
  - `overview [--court] [--json]`
  - `profile <chamber> [--court] [--json]`
  - `timeline [--chamber] [--court] [--start-year] [--end-year] [--json]`
  - `similar <chamber> [--court] [--limit] [--json]`

- **4 MCP Tools**:
  - `chamber_overview`: list all chambers with document counts
  - `profile_chamber`: detailed chamber profile with keywords
  - `chamber_timeline`: year-grouped decision distribution
  - `find_similar_chambers`: Jaccard similarity chamber matching

- **Tests**: `tests/test_chamber.py` with 14 test cases covering overview
  structure, profile metrics/keywords, timeline year grouping, similarity
  scoring, NULL chamber/date edge cases, CLI and MCP imports.

### Changed

- **Version bumped to 0.12.0** in `__init__.py` and `pyproject.toml`.

### Backward Compatibility

- All v0.11 tests continue to pass (499 total tests, all passing).
- Chamber module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.

## [0.11.0] — 2026-05-29

### Added

- **Semantic/Hybrid Search Module** (`semantic.py`):
  - **SQLite FTS5 virtual table** (`documents_v2_fts`): tokenized full-text
    search with BM25 ranking. Content-sync triggers auto-update index on
    INSERT/UPDATE/DELETE in `documents_v2`.
  - **TF-IDF cosine similarity**: pure Python implementation with
    `search_vectors` table for sparse vector storage. No external ML deps.
  - **Hybrid ranking**: `final_score = hybrid_weight * BM25 +
    (1 - hybrid_weight) * cosine_similarity`.
  - **`build_semantic_index()`**: creates FTS5 + TF-IDF index from cached
    documents. Returns ok, fts_count, vector_count, duration_ms.
  - **`semantic_search(query, limit=10)`**: TF-IDF cosine-only search.
    Returns ok, query, results with document_id, score, snippet, source.
  - **`hybrid_search(query, limit=10, hybrid_weight=0.5)`**: combined
    FTS5 BM25 + TF-IDF cosine ranking. Returns ok, query, results.
  - **`get_index_status()`**: index health and statistics. Returns ok,
    fts_count, vector_count, documents_indexed, last_rebuild.
  - **`rebuild_index(force=False)`**: force rebuild of semantic index.

- **Zero new dependencies**: stdlib + sqlite3 only.

- **5 CLI Commands** under `emsal-mcp semantic`:
  - `index [--force-rebuild] [--json]`
  - `search <query> [--limit] [--json]`
  - `hybrid <query> [--limit] [--weight] [--json]`
  - `status [--json]`
  - `rebuild [--json]`

- **5 MCP Tools**:
  - `build_semantic_index`: create FTS5 + TF-IDF index
  - `semantic_search`: TF-IDF cosine search
  - `hybrid_search`: combined BM25 + cosine ranking
  - `index_status`: index health and stats
  - `rebuild_search_index`: force index rebuild

- **Tests**: `tests/test_semantic.py` with 57 test cases covering FTS5
  indexing, TF-IDF vector computation, cosine similarity, hybrid ranking,
  empty index handling, rebuild, status, CLI and MCP imports.

### Changed

- **Version bumped to 0.11.0** in `__init__.py` and `pyproject.toml`.

### Backward Compatibility

- All v0.10 tests continue to pass (442 total tests, all passing).
- Semantic module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.
- FTS5 and search_vectors tables are created on first use; no migration.

## [0.10.0] — 2026-05-29

### Added

- **Legislation (Mevzuat) Module** (`legislation.py`):
  - **`search_legislation(query, sources, legislation_type, limit)`**: search
    Mevzuat source with optional legislation type filter (Kanun, KHK,
    Yönetmelik, etc.). Returns structured dict with ok, query, results,
    total_results, legislation_type, warnings, recommended_next_steps.
  - **`get_legislation_document(document_id, source)`**: fetch full legislation
    document with citation_check integration, article count, and content
    status. Returns ok, title, citation_check, article_count, text_length.
  - **`search_legislation_articles(document_id, article_number, article_query,
    source)`**: search articles within a document by number or keyword query.
    Parses MADDE entries from legislation text. Returns matching_articles
    with number/text/preview.
  - **`get_legislation_article_tree(document_id, source)`**: builds hierarchical
    KISIM → BÖLÜM → MADDE tree from legislation text. Recognizes part and
    section headers. Returns tree, flat_article_list, part_count,
    section_count, article_count. Flat texts produce zero hierarchy counts.
  - **`get_legislation_gerekce(document_id, source)`**: extracts GENEL GEREKÇE
    and MADDE GEREKÇELERİ from legislation text. Parses individual article
    rationales into structured list.
  - **`get_legislation_source_status()`**: aggregate Mevzuat source health via
    smoke tests. Returns overall_ok, healthy_sources, degraded_sources.
  - **`format_legislation_citation(document, style)`**: format legislation
    citations with styles full/short/article.
  - **`get_legislation_types()`**: returns 11 Turkish legislation types with
    type_id and display_name.

- **Heuristic classification**: `_classify_type()` uses regex on title and
  metadata fields (mevzuatTur, documentType) to classify legislation documents.
  Handles Turkish suffixes (Kanun → Kanunu, Yönetmelik → Yönetmeliği).
  Returns type_id, display_name, confidence. Never fabricates.

- **12 CLI Commands** under `emsal-mcp legislation`:
  - `search <query> [--legislation-type] [--limit] [--json]`
  - `get <document_id> [--source] [--json]`
  - `articles <document_id> [--article-number] [--article-query] [--json]`
  - `tree <document_id> [--source] [--json]`
  - `gerekce <document_id> [--source] [--json]`
  - `status [--json]`
  - `types [--json]`
  - `format [--title] [--legislation-no] [--gazette-date] [--style] [--json]`

- **8 MCP Tools**:
  - `search_legislation`: search Mevzuat source with type filter
  - `get_legislation_document`: fetch full legislation document
  - `search_legislation_articles`: search articles within document
  - `get_legislation_article_tree`: build part/section/article hierarchy
  - `get_legislation_gerekce`: extract rationale sections
  - `legislation_source_status`: check source health
  - `format_legislation_citation`: format legislation citations
  - `get_legislation_types`: list known legislation types

- **Tests**: `tests/test_legislation.py` with 53 test cases covering:
  - Type classification (11 types, Turkish suffixes, metadata fallback)
  - Search (basic, type filter, no results, error handling, structure)
  - Document fetch (basic, articles, citation check, metadata only)
  - Article search (all, specific, keyword, not found, no content)
  - Article tree (hierarchy, flat, no content, structure)
  - Gerekçe (found, genel only, none, article parsing, structure)
  - Source status (healthy, degraded, structure)
  - Citation formatting (full/short/article, dict/Document, errors)
  - Module constants (version, no-invention rule)
  - CLI and MCP imports

### Changed

- **Version bumped to 0.10.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.10 legislation module details.
- **Existing test** updated for flexible version assertion.

### Backward Compatibility

- All v0.9 tests continue to pass (442 total tests, all passing).
- Legislation module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.

## [0.9.0] — 2026-05-29

### Added

- **UDF Toolkit Integration** (`udf.py`):
  - **`get_udf_toolkit_status()`**: checks external UDF toolkit (LibreOffice/
    unoconv) availability. Returns structured status dict with `ok`, `enabled`,
    `toolkit_dir`, `libreoffice_path`, `unoconv_path`, `version`, `warnings`.
    Reads from `EMSAL_UDF_TOOLKIT_DIR` or `UDF_TOOLKIT_DIR` env vars.
  - **`get_udf_authoring_instructions(format='json|markdown')`**: returns UDF
    authoring steps and warnings. JSON format includes toolkit status;
    markdown format returns human-readable instructions.
  - **`convert_udf_to_docx(file_path, out_path=None)`**: convert UDF to DOCX
    via LibreOffice. Returns structured error dict if toolkit unavailable or
    file not found; never raises.
  - **`convert_udf_to_pdf(file_path, out_path=None)`**: convert UDF to PDF
    via LibreOffice. Same graceful error handling.
  - **`convert_docx_to_udf_experimental(file_path, out_path=None,
    experimental=False)`**: convert DOCX to UDF. Requires `experimental=True`.
    Always includes UYAP manual round-trip warning. Text extraction via
    `word/document.xml` parse.

- **Improved `probe_udf()`**: now returns `format_id`, `content_xml_preview`
  (truncated to 500 chars), `text_length`, and `warnings` list. Missing files
  include a warning message.

- **CLI Commands**:
  - `emsal-mcp udf status [--json]` — toolkit availability status
  - `emsal-mcp udf authoring-instructions [--format json|markdown] [--json]`
  - `emsal-mcp udf to-docx <path> [--out-path] [--json]`
  - `emsal-mcp udf to-pdf <path> [--out-path] [--json]`
  - `emsal-mcp udf docx-to-udf-experimental <path> [--out-path] [--experimental] [--json]`

- **MCP Tools**:
  - `udf_toolkit_status`: check toolkit availability
  - `udf_authoring_instructions`: authoring steps and warnings
  - `convert_udf_to_docx_tool`: UDF → DOCX conversion
  - `convert_udf_to_pdf_tool`: UDF → PDF conversion
  - `convert_docx_to_udf_experimental_tool`: DOCX → UDF (experimental)

- **Tests**: `tests/test_udf.py` expanded from 7 to 35 test cases covering:
  - Toolkit status disabled by default, dict shape, env config, env priority
  - Authoring instructions JSON/markdown format, warnings, version
  - Safe wrappers: missing toolkit returns error, file not found, structured dict
  - Experimental flag enforcement for DOCX→UDF
  - Native UDF round-trip unchanged (write/read/markdown/unicode/title_centered)
  - CLI and MCP imports

### Changed

- **Version bumped to 0.9.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.9 UDF toolkit integration details.
- **Existing tests** updated for version assertion flexibility.

### Backward Compatibility

- All v0.8 tests continue to pass (389 total tests, all passing).
- UDF toolkit functions are additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.
- `UDF_AUTHORING_WARNING` moved to top-level constant (value unchanged).

## [0.8.0] — 2026-05-29

### Added

- **Controlled Draft Module** (`petition.py`):
  - **`prepare_petition_outline(pack_dir, out_dir=None)`**: generates a
    structured outline from a petition pack with sections, placeholders,
    and authority classification.  Only `petition_ready` authorities may
    supply direct content; `citation_only` appear only in the bibliography
    section with a warning flag.
  - **`prepare_controlled_petition_draft(pack_dir, outline_path=None,
    out_dir=None)`**: produces a controlled petition draft with four
    output files:
    - `draft.md`: Markdown draft with disclaimer header, section content,
      and footnotes.  Only `petition_ready` authorities supply direct
      quotes; `citation_only` appear in bibliography warnings only.
      All `{{PLACEHOLDER}}` patterns are preserved verbatim.
    - `draft.json`: structured metadata with `paragraph_count`,
      `section_count`, `footnote_count`, `placeholder_count`,
      `blocking_warning_count`, `readiness_score`, `readiness_level`,
      and `finalization_risk_score`.
    - `footnotes.json`: footnote references from `petition_ready`
      authorities only, plus `citation_only_bibliography` list.
    - `warnings.json`: warnings with `blocking`/`warning`/`info` levels.
  - **Disclaimer header**: automatic `DISCLAIMER_HEADER` in draft output
    and DOCX exports, warning that the document requires attorney review.
  - **Readiness scoring**: `readiness_score` (0.0–1.0) based on
    petition_ready ratio; `readiness_level` maps to high/medium/low/none;
    `finalization_risk_score` combines blocking warnings and readiness.
  - **No metadata-only leak**: `citation_only` authorities never appear
    in direct quotes or footnotes; they are restricted to bibliography.

- **DOCX Export Validation** (`exporter.py`):
  - **`prepare_docx_export(draft_path=None, draft_json=None, out_path=None,
    pack_dir=None)`**: creates a validated DOCX with disclaimer header,
    footnotes/citations, and placeholder preservation.  Returns
    `checksum_sha256`, `file_size`, and `validation` dict with:
    - `zip_valid`: DOCX opens as valid ZIP
    - `disclaimer_present`: disclaimer text found in DOCX body
    - `footnotes_consistent`: footnote count matches petition_ready count
    - `placeholders_preserved`: all original `{{…}}` patterns present
    - `validation_warnings`: list of non-fatal warnings
    - `export_readiness`: overall boolean (all checks pass)

- **Export Package Bundle v2** (`exporter.py`):
  - **`prepare_export_package_bundle(pack_dir, draft_dir=None,
    docx_path=None, out_dir=None)`**: creates a complete export bundle
    containing: draft.md, draft.json, footnotes.json, warnings.json,
    petition-pack.json, citation-bank.md, source-documents/,
    manifest.json, hash-manifest.json, verification.txt.
  - **Post-creation verification**: hash-manifest integrity, required
    files present, manifest valid JSON, DOCX ZIP validity (if included).

- **CLI Commands**:
  - `emsal-mcp petition outline <pack_dir> [--out-dir] [--json]`
  - `emsal-mcp petition draft <pack_dir> [--outline-path] [--out-dir] [--json]`
  - `emsal-mcp petition export-docx [--draft-path] [--draft-json-path] [--out-path] [--pack-dir] [--json]`
  - `emsal-mcp petition export-bundle <pack_dir> [--draft-dir] [--docx-path] [--out-dir] [--json]`

- **MCP Tools**:
  - `prepare_petition_outline`: generate structured outline from pack
  - `prepare_controlled_petition_draft`: generate controlled draft with scoring
  - `prepare_docx_export`: create validated DOCX export
  - `prepare_export_package_bundle`: create complete export bundle with verification

- **Tests**: `tests/test_controlled_draft.py` with 49 test cases covering:
  - Outline generation (sections, placeholders, authority filtering)
  - Controlled draft output (disclaimer, footnotes, warnings, scoring)
  - No metadata-only leak (citation_only not in direct quotes)
  - Placeholder preservation (all skeleton placeholders in draft)
  - DOCX validation (ZIP valid, disclaimer present, footnotes consistent)
  - Export bundle (manifest validation, hash integrity, post-verification)
  - CLI and MCP imports

### Changed

- **Version bumped to 0.8.0** in `__init__.py`, `pyproject.toml`, and
  `petition.py` (`PACK_VERSION`, `CONTROLLED_DRAFT_VERSION`).
- **`ROADMAP.md`** updated with v0.8 controlled draft details.
- **Existing tests** updated for version assertion flexibility.

### Backward Compatibility

- All v0.7 tests continue to pass (361 total tests, all passing).
- Petition module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.
- `PACK_VERSION` updated but existing pack files remain readable.

## [0.7.0] — 2026-05-29

### Added

- **Petition Pack v2** (`petition.py`): core v0.7 petition drafting workflow
  with `prepare_drafting_input_pack()` and `inspect_petition_pack()`.
- **`prepare_drafting_input_pack()`**: classifies authorities as
  `petition_ready`, `citation_only`, `research_lead_only`, or `excluded`
  using citation safety, content_status, metadata/provenance, and
  content_hash.  Generates a structured pack directory with:
  - `petition-brief.json`: authority classification metadata
  - `citation-bank.md`: citation-safe reference list (no excluded docs)
  - `argument-map.md`: authority classification map with research leads
  - `petition-instructions.md`: explicit no-invention rules
  - `draft-skeleton.md`: petition template with `{{PLACEHOLDER}}` format
  - `petition-pack.json`: pack metadata with counts and files
  - `source-documents/*.md`: full-text docs for safe authorities
  - `hash-manifest.json`: content hashes for source documents
- **`inspect_petition_pack()`**: validates pack directory structure with
  checks: required files, draft_safe flag, placeholdersInDraftSkeleton,
  legislationVerified placeholder, petitionInstructionsForbidsInvention,
  citationBankOnlySafeDocs, hashManifestValid, metadataOnlyDraftUsable.
  Returns ok/draft_safe/errors/warnings/counts/checks.
- **Authority classification**: metadata_only and pdf_only documents are
  NEVER draft usable (petition_ready).  Unavailable documents are always
  excluded.  Hash mismatches cause exclusion.
- **No-invention enforcement**: petition-instructions.md contains explicit
  prohibition against fabrication, metadata invention, and unverified
  citations.  Inspect validates the rule is present.
- **CLI commands**: `emsal-mcp petition pack`, `emsal-mcp petition inspect`
  with `--json` output.
- **MCP tools**: `prepare_drafting_input_pack`, `inspect_petition_pack`
  exposed via FastMCP server.
- **Tests**: `tests/test_petition.py` with 30+ test cases covering authority
  classification (metadata_only/pdf_only never draft usable, full_text
  petition_ready, unavailable excluded), pack file generation, inspect
  validation, hash manifest, no-invention rule enforcement, placeholder
  preservation, cache logging, and research bundle loading.

### Changed

- **Version bumped to 0.7.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.7 petition pack details.

### Backward Compatibility

- All v0.6 tests continue to pass (existing tests unaffected).
- Petition module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.

## [0.6.0] — 2026-05-29

### Added

- **Citation extraction** (`citation.py`): regex-based extraction of Turkish
  legal citation patterns from text. Detects Yargıtay, Danıştay, AYM,
  Sayıştay, Rekabet Kurulu, Ticaret Mahkemesi, and more. Extracts court,
  chamber, date (DD.MM.YYYY / YYYY-MM-DD / Turkish month names), esas_no,
  karar_no, and document_id-like references.
- **Confidence scoring**: high (5+ fields), medium (3-4 fields), low (<3 fields).
  Missing fields produce warnings, never fabricated values.
- **`format_legal_citation()`**: format a citation from Document model or dict.
  Three styles: petition, parenthetical, short. Uses only existing metadata;
  warnings for missing date/chamber/esas/karar/source_url. Includes
  quote_usable/draft_usable/content_status/source_url/confidence.
- **`verify_legal_citation()`**: full verification pipeline — load text/file,
  extract candidates, search local cache (unless live_only), live search
  (unless no_live), rank by metadata match score, optionally fetch docs,
  return structured result with candidates, search_attempts,
  matched_documents, formatted_citations, verification_findings, warnings,
  recommended_next_steps, timing.
- **CLI commands**: `emsal-mcp cite format`, `emsal-mcp cite verify` with
  `--json` output.
- **MCP tools**: `format_legal_citation`, `verify_legal_citation` exposed
  via FastMCP server.
- **Tests**: `tests/test_citation.py` with 45 test cases covering extraction
  (all court types, Turkish chars, dates, confidence, limits, warnings),
  formatting (all styles, missing metadata no fabrication, output contract),
  verification (cache-only, live fake, no_live/live_only, file input,
  strategy debug, timing, output contract).

### Changed

- **Version bumped to 0.6.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.6 citation verification details.

### Backward Compatibility

- All v0.5 tests continue to pass (199+ existing tests unaffected).
- Citation module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.

## [0.5.0] — 2026-05-29

### Added

- **Research workflow** (`research.py`): core v0.5 research pipeline with
  `research_topic()`, `refresh_research_bundle()`, and `research_quality_dashboard()`.
- **`research_topic()`**: searches configured sources, fetches documents up to
  fetch_count, stores in cache, builds output directory with `index.md`,
  `bundle.json`, `results.json`, `documents/*.md`, `manifests/hash-manifest.json`,
  and `warnings.json`. Never fabricates metadata. Returns structured dict with
  query, sources, filters, result_count, fetched_count, content_status_summary,
  citation_safe_count, metadata_only_count, generated_files, warnings,
  recommended_next_steps.
- **`refresh_research_bundle()`**: reads `bundle.json`, re-runs with same
  query/sources, supports `dry_run`, reports new_documents/changed_documents/
  hash_changed, preserves manual notes between `<!-- MANUAL_NOTES_START/END -->`
  markers in `index.md`.
- **`research_quality_dashboard()`**: reads bundle results and computes
  full_text_ratio, citation_safe_ratio, metadata_only_count, pdf_only_count,
  unavailable_count, source_distribution, missing_metadata_count,
  duplicate_citation_count, draft_readiness_score, recommendations.
- **`sources_override` parameter**: all three functions accept optional
  `sources_override` dict for injecting fake source clients in tests (no
  live network required).
- **CLI commands**: `emsal-mcp research topic`, `emsal-mcp research refresh`,
  `emsal-mcp research dashboard` with `--json` output.
- **MCP tools**: `research_topic_tool`, `refresh_research_bundle_tool`,
  `research_quality_dashboard_tool` exposed via FastMCP server.
- **Tests**: `test_research.py` with 30+ test cases covering bundle file
  creation, manifest hash correctness, dashboard metrics, refresh dry_run,
  manual notes preservation, empty source handling, cache storage, CLI/MCP
  imports, and no-network fake source client path.

### Changed

- **Version bumped to 0.5.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.5 research workflow details.
- **`docs/JSON_CONTRACTS.md`** updated with research bundle contracts.
- **`docs/MCP_CONTRACTS.md`** updated with research MCP tool contracts.

### Backward Compatibility

- All v0.4 tests continue to pass (199+ existing tests unaffected).
- Research module is additive; no breaking changes to existing API.
- New CLI commands and MCP tools are additive.

## [0.4.0] — 2026-05-29

### Added

- **`SourceSmokeResult` model** (`models.py`): per-source smoke test result
  with `offline_ok`, `online_ok`, `search_callable`, `get_document_callable`,
  `min_content_length_ok`, `warnings`, `errors`, `tested_at`.
- **`SourceClient.smoke()` method** (`base.py`): offline-safe default smoke
  test for all sources. Override for online-specific checks.
- **`smoke_all()` / `smoke_all_sync()`** (`registry.py`): run smoke tests
  for all registered sources (async and sync wrappers).
- **`finalize_document()` helper** (`models.py`): min content length sanity
  (downgrades full_text/html_markdown to metadata_only if < 50 chars),
  content_hash auto-computation, structured warnings via metadata.
- **`check_http_response()` helper** (`base.py`): consistent HTTP status
  handling across all adapters; raises `HTTPStatusError` on 4xx/5xx.
- **CLI `sources-smoke` command** (`cli.py`): `emsal-mcp sources-smoke
  --offline/--online --json` for per-source smoke summaries.
- **MCP `source_smoke` tool** (`server.py`): `source_smoke(online=False)`
  returns per-source smoke results.
- **Source smoke summaries in `release_smoke()`** (`release.py`):
  `release_smoke` now includes `source_smoke` and `source_smoke_ok` in
  its `checks` dict.
- **Tests**: `tests/test_adapters.py` with 73 test cases covering
  SourceSmokeResult model, decode_b64 error handling, finalize_document,
  mocked adapter search/get_document for all 10 sources, CLI smoke
  command, document status sanity, KIK graceful contract, no-error-HTML
  citation-safe invariant.

### Changed

- **`decode_b64()`** (`base.py`): now returns empty bytes on failure
  instead of raising; prevents false `full_text` from corrupt base64.
- **`client()` User-Agent** (`base.py`): updated to `EmsalMcp/{version}`
  with GitHub URL; consistent across all adapters.
- **Bedesten/Yargıtay** (`bedesten.py`): item_type normalization accepts
  lowercase/Turkish-char variants; source_id preserved through
  `_default_item_type` class attribute; `decode_b64` failures result in
  `UNAVAILABLE` not false `full_text`.
- **Mevzuat** (`mevzuat.py`): source_id/title fixed (`mevzuatAdi` prioritized);
  `decode_b64` failures properly surface as `UNAVAILABLE`; capability
  status set to `experimental`.
- **AYM** (`simple_public.py`): fallback to `metadata_only` when parsed
  content is too short; `finalize_document` applied.
- **Danıştay** (`simple_public.py`): `Accept` header added for AJAX
  endpoint; min content length check; `finalize_document` applied.
- **GİB** (`simple_public.py`): query normalization via dict; HTML
  stripped from titles; structured field-based text construction;
  `finalize_document` applied.
- **Uyuşmazlık** (`simple_public.py`): graceful `UNAVAILABLE` on parser
  failures (search and get_document); `finalize_document` applied.
- **Rekabet** (`simple_public.py`): graceful `UNAVAILABLE` on parser
  failures; `finalize_document` applied.
- **Sayıştay** (`simple_public.py`): graceful `UNAVAILABLE` on parser
  failures; `finalize_document` applied.
- **Registry** (`registry.py`): `smoke_all()` / `smoke_all_sync()` added;
  `YargitayClient` now has `_default_item_type`; KIK has `smoke()`.
- **Version bumped to 0.4.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.4 details.

### Backward Compatibility

- All v0.3 tests continue to pass (199/199).
- `SourceSmokeResult` is a new additive model; no breaking changes.
- `smoke()` is opt-in on `SourceClient`; existing subclasses inherit
  the offline-safe default.
- `finalize_document()` is additive; existing code paths unaffected.

### Added

- **`CachedDocument` model** (`models.py`): extended document model for cache v2
  with rich metadata (`title`, `court`, `chamber`, `decision_date`, `esas_no`,
  `karar_no`, `source_url`, `content_status`, `markdown`, `full_text`,
  `content_hash`, `metadata_json`, `raw_json`, `retrieved_at`,
  `last_accessed_at`, `access_count`, `quote_usable`, `draft_usable`,
  `metadata_confidence`, `warnings_json`). Round-trip via `from_document()` /
  `to_document()`.
- **`documents_v2` table** (`cache.py`): SQLite table with indexed columns for
  local search. Backward-compatible: legacy `documents` table preserved.
- **Local search service** (`cache.py`): `search_local()` with filters (source,
  court, chamber, date, esas_no, karar_no, document_id, content_status,
  draft_usable, quote_usable), sorts (relevance, decision_date_desc/asc,
  fetched_at_desc/asc), snippets, and limit. No network required.
- **CLI `cache` subcommands** (`cli.py`): `stats`, `list`, `search-local`,
  `delete`, `prune`, `backup`, `export`, `import`.
- **MCP cache tools** (`server.py`): `search_local_cache`, `get_cache_stats`,
  `list_cached_documents`.
- **CLI `get` integration**: `emsal-mcp get` now stores documents in both legacy
  and v2 cache tables via `store_document()`.
- **CLI `search` integration**: search results stored in cache for later local
  search.
- **Cache maintenance**: `cache_stats()`, `list_cached_documents()`,
  `delete_cached_document()`, `prune_search_cache()`, `backup_cache()`,
  `export_json()`, `import_json()`.
- **Cache integrity check**: `documents_v2` table included in verification.
- **Tests**: `test_cache_v2.py` (schema, store/read, hash verification, local
  search filters/sorts/snippets, maintenance operations), `test_cli_cache.py`
  (CLI subcommands, MCP imports, CLI get integration).

### Changed

- **Version bumped to 0.3.0** in `__init__.py` and `pyproject.toml`.
- **`ROADMAP.md`** updated with v0.3 Cache v2 + Local Search.
- **`docs/JSON_CONTRACTS.md`** and **`docs/MCP_CONTRACTS.md`** updated with cache
  v2 contracts.

### Backward Compatibility

- All v0.2 tests continue to pass.
- Legacy `documents` table preserved alongside `documents_v2`.
- `store_document()` writes to both tables for seamless migration.

## [0.2.0] — 2026-05-29

### Added

- **`SourceCapability` model** (`models.py`): typed capability descriptor with
  `source_id`, `display_name`, `status` (`SourceStatus` enum), `supports_search`,
  `supports_get_document`, `supports_full_text`, `supports_pdf_link`,
  `supports_metadata_only`, `supports_article_search`, `supports_type_filter`,
  `supports_workflow`, `live_smoke_recommended`, `known_limitations`, `notes`.
- **`SourceStatus` enum**: `stable`, `partial`, `experimental`, `unavailable`.
- **`to_legacy_dict()`**: produces both snake_case and camelCase keys for
  backward compatibility (`citationSafeRule`, `noFabrication`).
- **`SourceClient.capability_model()`**: returns a typed `SourceCapability`
  instance from any source client.
- **KIK unavailable placeholder**: present in capability matrix with
  `status: "unavailable"`; `get_source("kik")` returns a graceful placeholder
  client whose search/get methods return unavailable/metadata-only contract
  payloads instead of crashing MCP calls.
- **Content-status enrichment fields** on search/document models:
  `content_status_label`, `content_available`, `full_text_available`,
  `metadata_confidence`, `metadata_confidence_reason`, `recommended_next_step`.
- **Per-source known_limitations**: each source client now declares explicit,
  non-fabricated limitations (e.g. "base64-encoded HTML", "PDF-only links").
- **Documentation**: `ROADMAP.md`, `CHANGELOG.md`, `docs/JSON_CONTRACTS.md`,
  `docs/MCP_CONTRACTS.md`.
- **Tests**: `tests/test_capability_contract.py` with 30+ test cases covering
  capability model, KIK graceful degradation, CLI JSON shape, MCP import,
  enrichment fields, and document/search contract.

### Changed

- **`sources/registry.py`** refactored: `capabilities()` now returns the full
  capability matrix for all 10 sources; KIK is a structured unavailable
  placeholder.
- **`sources/base.py`**: `SourceClient.capabilities()` now delegates to
  `capability_model().to_legacy_dict()`.

### Backward Compatibility

- All existing tests updated and passing.
- `capabilities()` output retains v0.1 keys (`source`, `name`, `public`,
  `tools`, `citationSafeRule`, `noFabrication`) alongside v0.2 fields.
- `get_source("kik")` now returns a structured client (was raising RuntimeError).

## [0.1.0] — 2026-05-28

Initial release.
