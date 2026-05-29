# CHANGELOG_SESSION_v0.13→v2.0.0.md — Full Session Changelog

**Oturum:** 2026-05-29  
**Başlangıç:** v0.13.0 (513 test, 0 lint, 54 MCP aracı)  
**Bitiş:** v2.0.0 (1174 test, 0 lint, 54+ MCP aracı)  
**Commit sayısı:** 22  
**Değişen dosya:** 67 (+18,500 / −549 satır)  
**Yeni modül:** 17  
**Yeni test dosyası:** 18  

---

## FAZ 1 — Sağlamlaştırma ve v1.0.0

### M-01: Doküman & Roadmap Senkronizasyonu
- `CHANGELOG.md` → v0.11.0, v0.12.0, v0.13.0 girdileri eklendi  
- `ROADMAP.md` → sürüm sırası düzeltildi (v0.10 ortada kalmıştı), v0.11–v0.13 eklendi  
- `docs/JSON_CONTRACTS.md` → Legislation, Semantic, Chamber, Release v0.13 kontratları eklendi  
- `docs/MCP_CONTRACTS.md` → 54 aracın tamamı 10 modül grubunda belgelendi  
- `README.md` → 1.0.0 sürümü, 54 araç/65+ komut/513 test vurgusu, hızlı başlangıç  

### M-02: Test Boşluğu Kapatma & Coverage
- `pytest-cov` eklendi (dev dependency)  
- Coverage: **%76 → %84** (+8%)  
- Test sayısı: **513 → 618** (+105)  
- `build_error()` helper'ı `models.py`'ye eklendi — canonical error dict formatı  
- `udf.py` → ad-hoc error'lar `build_error()` ile değiştirildi  
- Yeni test dosyaları: `test_release.py` (32), `test_drafter.py` (26), `test_document.py` (17)  

### M-03: Hata & Kontrat Tutarlılık Denetimi
- **51 ad-hoc error dict** `build_error()` ile normalize edildi (9 modülde: citation, petition, exporter, legislation, semantic, chamber, release, udf, safety)  
- 48 benzersiz error code kataloglandı (`KNOWN_ERROR_CODES`)  
- **47 invariant test** (`tests/test_invariants.py`): metadata_only→draft_usable, citation never fabricates, graceful degradation, placeholder preservation, build_error shape  
- Test sayısı: **618 → 697**  

### M-04: Yapılandırma & Gözlemlenebilirlik
- `config.py` (308 satır) — `EmsalConfig` sınıfı: cache_path, user_agent, udf_toolkit_dir, log_level, http_timeout, kik_api_token, circuit_breaker_threshold, retry_max_attempts, rate_limit_enabled  
- Env override: `EMSAL_CACHE_PATH`, `EMSAL_LOG_LEVEL`, `KIK_API_TOKEN`, `EMSAL_CB_THRESHOLD`, `EMSAL_RETRY_MAX`...  
- `test_config.py` (191 satır) — tüm config özellikleri test edildi  

### M-05: v1.0.0 Release
- Sürüm: `0.13.0` → `1.0.0`  
- `RELEASE_NOTES_v1.0.0.md` oluşturuldu  
- `final_v1_readiness()` → ready: true, tüm kriterler yeşil  

---

## FAZ 2 — Veri Katmanı & Arama Olgunluğu

### M-06: Cache Bütünlüğü & Bakım
- `cache.py` genişletildi: `vacuum_cache()`, `cleanup_orphans()`, `check_integrity_full()`  
- Schema migration: v2 → v3 (otomatik, `schema_meta` tablosu)  
- `CACHE_SCHEMA_VERSION = 3`  
- Yetim `search_vectors` ve `documents_v2_fts` satır temizliği  
- CLI: `emsal-mcp cache compact`, `cleanup-orphans`, `integrity-check`  
- MCP: 3 yeni araç  
- `test_cache_maintenance.py` — 30 test  

### M-07: Semantic Search v2
- **Türkçe suffix-stripping query expansion**: 10 kural (çoğul, hal ekleri, iyelik, mastar...)  
- `_expand_query()` → orijinal + stemlenmiş varyantlar FTS5 OR sorgusu için  
- **Snippet highlighting**: `_generate_snippet()` artık `**highlight**` marker'ları döndürüyor  
- **Per-source filter**: `hybrid_search()` ve `semantic_search()` CLI'ına `--source`, `--court`, `--chamber` filtreleri eklendi  
- `hybrid_weight` validasyonu: 0.0–1.0 aralık kontrolü, geçersiz → `build_error()`  
- Test sayısı: +36 (toplam 769)  

### M-08: Citation Graph (Atıf Ağı)
- Yeni modül: `citation_graph.py` (638 satır)  
- `citation_edges` tablosu: citing_doc → cited_doc, confidence (high/medium/low), match_type  
- `build_citation_graph()` — cache'teki belgelerden atıf çıkar, eşleştir, kenar oluştur  
- `get_citation_graph()`, `find_citing_documents()`, `find_cited_documents()`  
- Confidence: high (esas+karar eşleşmesi), medium (court+date), low (keyword)  
- İdempotent: `INSERT OR IGNORE` ile tekrar çalıştırmada duplication yok  
- CLI: `emsal-mcp graph build/show/citing/cited/stats`  
- MCP: 5 araç  
- `test_citation_graph.py` — 23 test  

### M-09: Çapraz-Kaynak Deduplication & Merge
- Yeni modül: `dedup.py` (436 satır)  
- `dedup_clusters` + `dedup_members` tabloları  
- `find_duplicates()` — court + esas_no + karar_no ile gruplama  
- Kanonik seçim: full_text > html_markdown > metadata_only (deterministik)  
- False-merge önleme: sadece aynı court+e+k ile gruplama, title-only merge yok  
- CLI: `emsal-mcp cache find-duplicates/dedup-cluster/dedup-stats/merge-cluster`  
- `test_dedup.py` — 18 test  

### M-10: Arama Analitik & Kalite Metrikleri
- Yeni modül: `search_analytics.py` (322 satır)  
- `search_history` tablosu: sorgu, sonuç sayısı, empty_result flag, cache_hit, süre  
- Auto-recording: `cache.py` `search_local()` her çağrıyı kaydeder (fire-and-forget)  
- `get_search_analytics()` — empty_result_rate, cache_hit_rate, top_queries, daily_activity  
- `get_source_coverage()` — kaynak başına belge sayısı ve full_text oranı  
- CLI: `emsal-mcp analytics report/empty-queries/top-queries/source-coverage`  
- MCP: 4 araç  
- `test_search_analytics.py` — 25 test  

---

## FAZ 3 — Dilekçe & Belge Üretimi

### M-11: Petition Template Library
- Yeni modül: `templates.py` (263 satır)  
- 4 şablon: **Dava Dilekçesi**, **Cevap Dilekçesi**, **Temyiz Dilekçesi**, **İstinaf Dilekçesi**  
- Hepsi `{{PLACEHOLDER}}` sözleşmesine uygun  
- `render_template_to_skeleton()` → DISCLAIMER_HEADER dahil markdown üretir  
- `petition.py` genişletildi: `prepare_drafting_input_pack(template_name=...)`  
- CLI: `emsal-mcp template list/show/render`, `--template` flag petition pack'e eklendi  
- `test_templates.py` — 40 test  

### M-12: Argument Builder
- Yeni modül: `argument.py` (718 satır)  
- `build_argument_chain()` — iddia → dayanak otorite → karşı-argüman zinciri  
- **Invariant**: sadece `petition_ready` otoriteler `supporting_authorities`'te görünür  
- `score_argument()` — 0.0–1.0 arası güç skoru  
- `render_arguments_to_markdown()` — zincirleri markdown'a dönüştürür  
- CLI: `emsal-mcp argument build/score/render`  
- MCP: 3 araç  
- `test_argument.py` — 43 test (4 safety invariant test dahil)  

### M-13: Multi-Issue Petition Pack
- `petition.py` genişletildi: `build_multi_issue_pack()`, `inspect_multi_issue_pack()`  
- Her mesele için izole `citation-bank.md` + `argument-map.md`  
- Kaynak belgeler tüm meseleler arasında paylaşımlı (deduplicated)  
- `hash-manifest.json` tüm meseleleri kapsar  
- Backward compatible: mevcut single-issue API bozulmadı  
- CLI: `emsal-mcp petition multi-pack/multi-inspect`  
- Test sayısı: +30 (toplam 948)  

### M-14: Draft Diff & Versiyonlama
- Yeni modül: `draft_diff.py` (586 satır)  
- `diff_drafts()` — stdlib `difflib` ile unified diff, placeholder değişim tespiti  
- `track_placeholders()` — doldurulan/boş placeholder sayımı, `ready_for_submission` flag  
- `get_fill_report()` — eksik placeholder'ların section context'li raporu  
- `save_draft_version()` — `.versions/<id>/` altına snapshot  
- CLI: `emsal-mcp draft diff/placeholders/fill-report/save-version`  
- `test_draft_diff.py` — 24 test  

### M-15: Export Format Expansion
- `exporter.py` genişletildi: `export_plain_text()`, `export_to_format()`, `get_export_capabilities()`  
- Format'lar: `docx` (her zaman), `txt` (her zaman), `pdf` (toolkit ile), `udf` (toolkit + experimental)  
- Toolkit yoksa graceful `TOOLKIT_UNAVAILABLE` error  
- Disclaimer header tüm format'larda korunur  
- `{{PLACEHOLDER}}` koruması tüm çıktılarda  
- CLI: `emsal-mcp export txt/format/capabilities`  
- MCP: 3 araç  
- `test_export_format.py` — 33 test  

---

## FAZ 4 — Kaynak Genişleme & Dayanıklılık

### M-16: KİK Adapter Aktivasyonu
- `docs/KIK_RESEARCH.md` — KİK/EKAP API araştırma belgesi (endpoint'ler, auth mekanizmaları)  
- `sources/registry.py` → `_KikClient` opsiyonel token auth destekler  
- Token env: `KIK_API_TOKEN` veya `EKAP_API_TOKEN`  
- Token varsa → `EXPERIMENTAL`; yoksa → `UNAVAILABLE` (mevcut davranış korundu)  
- Auth testi: `smoke(online=True)` ile token doğrulama  
- `test_adapters.py` → 15 KİK test eklendi  

### M-17: Source Health Monitoring & Circuit Breaker
- Yeni modül: `circuit.py` (350 satır)  
- State machine: `CLOSED → (5 failure) → OPEN → (300s) → HALF_OPEN → CLOSED`  
- `circuit_state` SQLite tablosu: per-source failure/success sayacı  
- `is_circuit_open()` / `record_success()` / `record_failure()`  
- `_with_circuit()` → `SourceClient` base'e OPT-IN wrapper  
- Config: `EMSAL_CB_THRESHOLD`, `EMSAL_CB_TIMEOUT`  
- CLI: `emsal-mcp circuit status/health/reset`  
- MCP: 3 araç  
- `test_circuit.py` — 35 test  

### M-18: Retry & Rate-Limit
- `sources/base.py` genişletildi: `_with_retry()` — exponential backoff (1s, 2s, 4s...)  
- `RateLimiter` sınıfı — token-bucket, default OFF  
- `RateLimitError` exception  
- Config: `EMSAL_RETRY_MAX`, `EMSAL_RETRY_DELAY`, `EMSAL_RATE_LIMIT_ENABLED`  
- Default davranış değişmedi — retry ve rate-limit OPT-IN  
- `_with_retry()` → `asyncio.sleep()` ile mock'lanabilir delay  
- `test_retry.py` — 43 test  

### M-19: Capability-Based Tool Routing
- Yeni modül: `router.py` (244 satır)  
- `get_capable_sources(capability)` → capability matrisinden uygun kaynakları döndürür  
- `route_search()` → gerekli capability'lere göre otomatik kaynak seçimi  
- `route_get_document()` → tercih edilen kaynak + fallback  
- Deterministik: aynı input → aynı routing  
- CLI: `emsal-mcp router capable-sources/search/get-document`  
- MCP: 3 araç  
- `test_router.py` — 32 test  

---

## FAZ 5 — Paketleme, Dağıtım & v2.0.0

### M-20: Packaging & Distribution
- `pyproject.toml` hijyeni: `license`, `authors`, `[project.scripts]`, `[build-system]`  
- Optional extras: `[mcp]`, `[udf]`, `[dev]` (pytest, ruff, pytest-cov)  
- `INSTALL.md` — 6 kurulum yöntemi (pip, pipx, uvx, dev, mcp, udf)  
- Entry points: `emsal-mcp` ve `emsal-mcp-server` doğrulandı  

### M-21: CI Pipeline
- `.github/workflows/ci.yml` — GitHub Actions: Python 3.11/3.12 matrix, lint+test+smoke  
- `Makefile` — `make lint`, `make test`, `make coverage`, `make clean`  
- `.gitignore` — `.coverage`, `htmlcov/` eklendi  

### M-22: MCP Server Hardening
- Yeni modül: `server_utils.py` (194 satır)  
- `validate_tool_input()` decorator — 5 kritik araca input validasyonu eklendi  
- Validator'lar: `validate_non_empty`, `validate_positive_int`, `validate_range`, `validate_is_dict_with_keys`  
- `KNOWN_ERROR_CODES` — 48 hata kodu kataloglandı  
- `_track_request` decorator + `get_active_requests()` — bilgi amaçlı concurrency sayacı  
- MCP: `error_catalog()`, `active_requests_count()` araçları  
- `test_server.py` — 39 test  

### M-23: v2.0.0 Architectural Review
- Sürüm: `1.0.0` → `2.0.0`  
- Tüm 23 milestone tamamlandı  
- `ROADMAP_LONG_HORIZON.md` → tüm satırlar `[x]`  
- `final_v1_readiness()` → ready: true  
- Son durum: **1174 test, 0 lint, 54+ MCP aracı, 65+ CLI komutu**

---

## Yeni Modül Envanteri

| # | Modül | Satır | Açıklama |
|---|-------|------|----------|
| 1 | `config.py` | 308 | Merkezi env-tabanlı konfigürasyon |
| 2 | `templates.py` | 263 | 4 dilekçe şablonu |
| 3 | `argument.py` | 718 | Yapılandırılmış argüman zinciri |
| 4 | `draft_diff.py` | 586 | Taslak diff, placeholder takip, versiyonlama |
| 5 | `citation_graph.py` | 638 | Belgeler arası atıf ağı |
| 6 | `dedup.py` | 436 | Çapraz-kaynak deduplikasyon |
| 7 | `search_analytics.py` | 322 | Arama analitiği ve kalite metrikleri |
| 8 | `circuit.py` | 350 | Circuit breaker state machine |
| 9 | `router.py` | 244 | Capability-based kaynak routing |
| 10 | `server_utils.py` | 194 | MCP input validasyonu, error catalog |

## Yeni Test Dosyaları

| # | Test Dosyası | Test Sayısı | Kapsadığı |
|---|-------------|------------|-----------|
| 1 | `test_invariants.py` | 47 | 6 güvenlik değişmezi |
| 2 | `test_templates.py` | 40 | Şablon kütüphanesi |
| 3 | `test_argument.py` | 43 | Argüman zinciri + invariants |
| 4 | `test_draft_diff.py` | 24 | Diff, placeholder, versiyon |
| 5 | `test_export_format.py` | 33 | Çoklu format export |
| 6 | `test_citation_graph.py` | 23 | Atıf ağı |
| 7 | `test_dedup.py` | 18 | Deduplikasyon |
| 8 | `test_search_analytics.py` | 25 | Arama analitiği |
| 9 | `test_cache_maintenance.py` | 30 | Cache bakım |
| 10 | `test_circuit.py` | 35 | Circuit breaker |
| 11 | `test_retry.py` | 43 | Retry + rate-limit |
| 12 | `test_router.py` | 32 | Capability routing |
| 13 | `test_server.py` | 39 | MCP server hardening |
| 14 | `test_release.py` | 32 | Release fonksiyonları |
| 15 | `test_drafter.py` | 26 | Draft/export |
| 16 | `test_document.py` | 17 | Document işlemleri |
| 17 | `test_config.py` | 18 | Konfigürasyon |
| 18 | `test_cli.py` (genişletildi) | +14 | CLI/MCP integration |

---

## Test Sayısı Gelişimi

| Aşama | Test Sayısı | Delta |
|-------|------------|-------|
| Başlangıç (v0.13.0) | 513 | — |
| M-02 sonrası | 618 | +105 |
| M-03 sonrası | 697 | +79 |
| M-07 sonrası | 769 | +72 |
| M-08 sonrası | 792 | +23 |
| M-09 sonrası | 810 | +18 |
| M-10 sonrası | 835 | +25 |
| M-11 sonrası | 875 | +40 |
| M-12 sonrası | 918 | +43 |
| M-13 sonrası | 948 | +30 |
| M-14 sonrası | 972 | +24 |
| M-15 sonrası | 1005 | +33 |
| M-16 sonrası | 1025 | +20 |
| M-17 sonrası | 1060 | +35 |
| M-18 sonrası | 1103 | +43 |
| M-19 sonrası | 1135 | +32 |
| M-22 sonrası | 1174 | +39 |
| **Final (v2.0.0)** | **1174** | **+661** |

---

## Commit Log (22 commits)

```
4aa114c release: M-23 v2.0.0 architectural review — bump to 2.0.0
355745a feat: M-22 MCP server hardening
724b54c ci: M-21 GitHub Actions workflow
e0819a9 chore: M-20 packaging hygiene
02ee343 feat: M-19 capability-based routing
2e3bfe9 feat: M-18 retry + rate-limit
3446e12 feat: M-17 circuit breaker
c5dd704 feat: M-16 KIK adapter
98270af feat: M-15 export format expansion
0f7288f feat: M-14 draft diff versioning
cc1857b feat: M-13 multi-issue petition pack
a2e5862 feat: M-12 argument builder
6ec78cd feat: M-11 petition template library
c95d4b2 feat: M-10 search analytics
2aa920a feat: M-09 cross-source dedup
67ee446 feat: M-08 citation graph
8faf368 feat: M-07 semantic v2
ae3d06b feat: M-06 cache maintenance
f12cf87 feat: M-03 error normalization + invariants
a99ef46 feat: M-02 coverage + test gap
73105ac docs: M-01 documentation sync
```
