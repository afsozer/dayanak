# Emsal-mcp Kapsamlı Rapor: v0.1.0 → v0.13.0

**Tarih:** 2026-05-29  
**Son Sürüm:** `0.13.0`  
**Depo:** `C:\Users\Sozer\Emsal-mcp`  
**Commit Sayısı:** 16 (baseline → v0.13)  

---

## 1. Yönetici Özeti

Emsal-mcp, **resmi / public kaynak odaklı, citation-safe bir hukuk araştırma ve dilekçe hazırlama sistemidir.** `local-yargi` projesinin ardılı olarak sıfırdan Python ile geliştirilmiş; JSON/MCP kontratlı, test edilebilir, uydurma yapmayan bir mimari üzerine inşa edilmiştir.

13 sürüm boyunca aşağıdaki yetenekler kazandırılmıştır:

| Yetenek Alanı | Sürüm | Temel Bileşenler |
|---|---|---|
| Temel Altyapı | v0.1–0.4 | 10 kaynak adapter, cache v2, contract foundation, smoke katmanı |
| Araştırma | v0.5–0.6 | Research workflow bundle, citation verification/format |
| Dilekçe | v0.7–0.9 | Petition pack v2, controlled draft, DOCX export, UDF toolkit |
| Mevzuat | v0.10 | Legislation search, article tree, gerekçe extraction |
| Arama | v0.11 | FTS5 + TF-IDF cosine hybrid semantic search |
| Analitik | v0.12 | Chamber profiling: overview, timeline, similarity |
| Release | v0.13 | Command center, v1 readiness gate, version bump |

**Son Durum:** 513 test, 0 lint hatası, 54 MCP aracı, 65+ CLI alt komutu, 10 kaynak adapter.

---

## 2. Mimari Genel Bakış

```
src/emsal_mcp/
├── __init__.py           # __version__ = "0.13.0"
├── models.py             # Pydantic modeller: Document, SearchResult, SourceCapability, CachedDocument, ...
├── cache.py              # SQLite Cache v2: documents_v2, local search, backup/export/import
├── safety.py             # Citation safety: citation_check, build_input_pack
├── document.py           # Kontrollü taslak ve export
├── citation.py           # v0.6: Citation extraction, format, verify
├── petition.py           # v0.7–0.8: Petition pack, outline, controlled draft
├── exporter.py           # v0.8: DOCX export validation, export bundle
├── udf.py                # v0.9: Native UDF read/write + toolkit wrappers
├── research.py           # v0.5: Research topic, bundle refresh, quality dashboard
├── legislation.py        # v0.10: Mevzuat search, articles, tree, gerekçe
├── semantic.py           # v0.11: FTS5 + TF-IDF cosine hybrid search
├── chamber.py            # v0.12: Chamber overview, profile, timeline, similarity
├── release.py            # v0.13: Command center, v1 readiness, version bump
├── verification.py       # Offline smoke, cache integrity
├── cli.py                # Typer CLI: 8 alt uygulama, 65+ komut
├── server.py             # FastMCP server: 54 MCP aracı
└── sources/
    ├── base.py           # SourceClient abstract base + HTTP helpers
    ├── bedesten.py       # Bedesten/Yargıtay adapter (shared base)
    ├── mevzuat.py        # Mevzuat/Bedesten adapter (legislation)
    ├── simple_public.py  # AYM, Danıştay, GİB, Uyuşmazlık, Rekabet, Sayıştay
    ├── registry.py       # Source registry, capabilities, smoke_all
    └── __init__.py
```

**Temel Tasarım İlkeleri:**
- **Uydurma yok:** Eksik metadata → uyarı, asla invented value
- **Citation-safe:** `quote_usable` / `draft_usable` flagleri her belgede
- **Test edilebilir:** Tüm fonksiyonlar `sources_override` / `cache` parametresi kabul eder
- **Graceful degradation:** Kaynak yok → structured error dict, exception yok
- **Additive:** Her yeni modül geriye dönük uyumlu; mevcut API bozulmaz

---

## 3. Sürüm Sürüm Dağılım

### v0.1 — Baseline MVP
**Commit:** `5f833f6`

- 9 kaynak adapter: bedesten, yargitay, mevzuat, aym, danistay, gib, uyusmazlik, rekabet, sayistay
- Citation safety checks (`citation_check`, `exact_quote`)
- UDF read/write round-trip (native, LibreOffice gerektirmez)
- Export bundle (DOCX + ZIP manifest with hashes)
- Offline smoke test
- CLI (`emsal-mcp`) ve MCP server (`emsal-mcp-server`)

### v0.2 — Contract Foundation
**Commit:** `a7e9996`

- `SourceCapability` model: typed capability descriptors
- `SourceStatus` enum: `stable`, `partial`, `experimental`, `unavailable`
- KİK unavailable placeholder (graceful, exception throw etmez)
- Content-status enrichment alanları
- Per-source `known_limitations`
- Dokümantasyon: `docs/JSON_CONTRACTS.md`, `docs/MCP_CONTRACTS.md`
- 30+ capability contract test

### v0.3 — Cache v2 + Local Search
**Commits:** `4357844`, `2e19b18`

- SQLite `documents_v2` tablosu: 22 kolon (metadata, content, hash, access tracking)
- `CachedDocument` Pydantic model: `from_document()` / `to_document()` round-trip
- Local search: filtre (source, court, chamber, date, esas_no, karar_no), sort (5 mod), snippet
- CLI: `emsal-mcp cache stats/list/search-local/delete/prune/backup/export/import`
- MCP tools: `search_local_cache`, `get_cache_stats`, `list_cached_documents`
- Schema version: `2`, hash verification ile integrity

### v0.4 — Adapter Hardening & Source Smoke
**Commit:** `15d155b`

- `SourceSmokeResult` model: `offline_ok`, `online_ok`, per-source warnings
- `SourceClient.smoke()`: offline-safe default, override edilebilir
- `smoke_all()` / `smoke_all_sync()`: tüm kaynaklarda smoke
- CLI: `emsal-mcp sources-smoke --offline/--online`
- Base utility hardening: `decode_b64()` (empty bytes on failure), `check_http_response()`, `finalize_document()` (min 50 char sanity)
- Adapter düzeltmeleri: Bedesten/Yargıtay item_type normalizasyonu, Mevzuat `mevzuatAdi` priority, AYM fallback metadata_only, Danıştay Accept header, GİB query normalization
- 73 yeni adapter test (toplam 199)

### v0.5 — Research Workflow Bundles
**Commits:** `1b1bb96`, `12d8cff`

- `research_topic()`: kaynak ara → belge çek → bundle oluştur
- `refresh_research_bundle()`: mevcut bundle'dan re-run, hash diff, dry_run
- `research_quality_dashboard()`: full_text_ratio, citation_safe_ratio, metadata_only_count, draft_readiness_score
- Bundle yapısı: `index.md`, `bundle.json`, `results.json`, `documents/*.md`, `manifests/hash-manifest.json`, `warnings.json`
- CLI: `emsal-mcp research topic/refresh/dashboard`
- 30+ research test

### v0.6 — Citation Verification + Formatting
**Commit:** `2f6cce5`

- `extract_citation_candidates()`: regex-based Turkish legal citation extraction (Yargıtay, Danıştay, AYM, Sayıştay, Rekabet, Ticaret Mahkemesi...)
- Confidence scoring: high (5+ fields), medium (3-4), low (<3)
- `format_legal_citation()`: 3 stil (petition, parenthetical, short)
- `verify_legal_citation()`: full pipeline — extract → local cache → live search → rank → fetch → format
- CLI: `emsal-mcp cite format/verify`
- 45 citation test

### v0.7 — Petition Pack v2 + Inspect
**Commit:** `60e2a49`

- `prepare_drafting_input_pack()`: authority classification (petition_ready / citation_only / research_lead_only / excluded)
- `inspect_petition_pack()`: 8 validation check
- Pack yapısı: `petition-brief.json`, `citation-bank.md`, `argument-map.md`, `petition-instructions.md`, `draft-skeleton.md`, `source-documents/*.md`, `hash-manifest.json`
- No-invention enforcement: petition-instructions.md + inspect validation
- CLI: `emsal-mcp petition pack/inspect`
- 30+ petition test

### v0.8 — Controlled Draft + DOCX/Export Validation
**Commit:** `bc793bf`

- `prepare_petition_outline()`: structured outline from pack, authority filtering
- `prepare_controlled_petition_draft()`: draft.md, draft.json, footnotes.json, warnings.json
- draft.json metadata: paragraph_count, section_count, footnote_count, placeholder_count, readiness_score/level, finalization_risk_score
- Safety invariants: no metadata-only leak, placeholder preservation, disclaimer header
- `prepare_docx_export()`: validated DOCX with disclaimer, footnotes, placeholder check
- `prepare_export_package_bundle()`: complete bundle with post-creation hash verification
- CLI: `emsal-mcp petition outline/draft/export-docx/export-bundle`
- 49 controlled draft test

### v0.9 — UDF Toolkit Integration
**Commit:** `24e34fd`

- `get_udf_toolkit_status()`: LibreOffice/unoconv availability check, env var (`EMSAL_UDF_TOOLKIT_DIR` / `UDF_TOOLKIT_DIR`)
- `get_udf_authoring_instructions()`: JSON/markdown formatında authoring adımları
- Safe wrappers: `convert_udf_to_docx()`, `convert_udf_to_pdf()`, `convert_docx_to_udf_experimental()` — hepsi structured error dict döner, exception throw etmez
- DOCX→UDF experimental: `experimental=True` zorunlu, UYAP manual round-trip uyarısı her zaman
- Improved `probe_udf()`: format_id, content_xml_preview, text_length, warnings
- CLI: `emsal-mcp udf status/authoring-instructions/to-docx/to-pdf/docx-to-udf-experimental`
- 35 UDF test (toplam 389)

### v0.10 — Advanced Legislation (Mevzuat)
**Commits:** `0466ea0`, `cc9aeaa`

| Fonksiyon | Açıklama |
|---|---|
| `search_legislation()` | Mevzuat kaynağında arama, tip filtresi (Kanun, KHK, Yönetmelik...) |
| `get_legislation_document()` | Tam metin belge + citation_check + article count |
| `search_legislation_articles()` | Belge içinde madde ara (numara / anahtar kelime) |
| `get_legislation_article_tree()` | KISIM → BÖLÜM → MADDE hiyerarşik ağaç |
| `get_legislation_gerekce()` | GENEL GEREKÇE + MADDE GEREKÇELERİ extraction |
| `get_legislation_source_status()` | Mevzuat kaynak sağlık kontrolü |
| `format_legislation_citation()` | Mevzuat atıf formatlama (full/short/article) |
| `get_legislation_types()` | 11 Türk mevzuat türü listesi |

- Heuristic `_classify_type()`: regex ile mevzuat türü sınıflandırma, Turkish suffix handling
- CLI: `emsal-mcp legislation search/get/articles/tree/gerekce/status/types/format` (8 komut)
- MCP: 8 legislation tool
- 53 legislation test (toplam 442)

### v0.11 — Semantic/Hybrid Search
**Commit:** `74fb605`

- **SQLite FTS5** virtual table: `documents_v2_fts` — tokenized full-text search, BM25 ranking
- **Content-sync triggers:** INSERT/UPDATE/DELETE otomatik index güncelleme
- **TF-IDF cosine similarity:** pure Python implementasyonu, `search_vectors` tablosunda sparse vector storage
- **Hybrid ranking:** `final_score = hybrid_weight * BM25 + (1 - hybrid_weight) * cosine`
- `build_semantic_index()`: FTS5 + TF-IDF index oluşturma
- `semantic_search()`: sadece TF-IDF cosine
- `hybrid_search()`: FTS5 BM25 + TF-IDF cosine birleşik
- `get_index_status()`: index sağlık / istatistik
- `rebuild_index()`: force rebuild
- **Zero yeni dependency:** stdlib + sqlite3 only
- CLI: `emsal-mcp semantic index/search/hybrid/status/rebuild`
- 57 semantic test (toplam 499)

### v0.12 — Chamber Profiling
**Commit:** `fd53dff`

| Fonksiyon | Açıklama |
|---|---|
| `get_chamber_overview()` | Tüm daireler: belge sayısı, tarih aralığı, son aktivite |
| `profile_chamber()` | Detaylı daire profili: metrics, top 20 keywords, recent docs |
| `chamber_timeline()` | Yıllara göre karar dağılımı (ISO + DD.MM.YYYY destekler) |
| `find_similar_chambers()` | Jaccard similarity ile benzer daire bulma |

- Turkish stopword filtering: "ve", "bir", "bu", "ile", "hakkında", "ilişkin"...
- Content status distribution analizi
- NULL chamber / NULL date edge case handling
- CLI: `emsal-mcp chamber overview/profile/timeline/similar`
- 14 chamber test (toplam 513)

### v0.13 — Release Command Center + v1 Stabilization
**Commit:** `f754d1b`

| Fonksiyon | Açıklama |
|---|---|
| `release_command_center()` | Tüm kontrolleri çalıştırır: smoke, capabilities, module imports, FTS5 index, chamber overview, UDF toolkit |
| `version_bump()` | Sürüm hesaplama (major/minor/patch) — dosya değiştirmez |
| `final_v1_readiness()` | v1.0.0 çıkış kapısı: module imports, stable sources, smoke, bloklayıcı sorun kontrolü |
| `generate_release_summary()` | İnsan-okunur + JSON formatında release özeti |

- Command center: 100 üzerinden readiness skoru
- v1 readiness: 4 kriter (all modules importable, has stable sources, release smoke ok, only KİK unavailable) → go/no-go
- CLI: `emsal-mcp release command-center/version-bump/v1-readiness/summary`
- Sürüm: `0.10.0` → `0.13.0`

---

## 4. Kaynak Adapterları

| # | source_id | Display Name | Status | Özellikler |
|---|-----------|-------------|--------|-----------|
| 1 | `bedesten` | Bedesten İçtihat | stable | Search, full_text (b64 HTML), item_type normalization |
| 2 | `yargitay` | Yargıtay | stable | Search, full_text, `_default_item_type` |
| 3 | `mevzuat` | Mevzuat/Bedesten | experimental | Legislation search, type filter, article search, HTML→markdown |
| 4 | `aym` | Anayasa Mahkemesi | stable | Search, metadata_only fallback on short content |
| 5 | `danistay` | Danıştay | stable | Search, AJAX endpoint, Accept header |
| 6 | `gib` | Gelir İdaresi | stable | Search, query normalization, HTML-stripped titles |
| 7 | `uyusmazlik` | Uyuşmazlık Mahkemesi | stable | Search, graceful UNAVAILABLE on parser failure |
| 8 | `rekabet` | Rekabet Kurumu | stable | Search, graceful UNAVAILABLE on parser failure |
| 9 | `sayistay` | Sayıştay | stable | Search, graceful UNAVAILABLE on parser failure |
| 10 | `kik` | Kamu İhale Kurumu | unavailable | Placeholder, HTTP 401, graceful degradation |

**Base URL:** `https://bedesten.adalet.gov.tr` (ortak Bedesten API)

---

## 5. Modül Envanteri

| Modül | Sürüm | Satır | Fonksiyon | Açıklama |
|---|---|---|---|---|
| `models.py` | — | 413 | 8 model + helpers | Core Pydantic models, enums, finalize_document |
| `cache.py` | v2 | 500+ | 15+ | SQLite cache v2, local search, maintenance |
| `safety.py` | — | 120+ | 3 | Citation safety, input pack, exact quote |
| `document.py` | — | 150+ | 3 | Controlled draft, export, markdown_to_docx |
| `citation.py` | v0.6 | 887 | 5+ | Extract, format, verify legal citations |
| `petition.py` | v0.8 | 1389 | 5+ | Petition pack, outline, controlled draft |
| `exporter.py` | v0.8 | 300+ | 2 | DOCX export validation, bundle |
| `udf.py` | v0.9 | 500+ | 8+ | Native UDF + toolkit wrappers |
| `research.py` | v0.5 | 500+ | 3 | Research topic, refresh, dashboard |
| `legislation.py` | v0.10 | 791 | 8 | Mevzuat search, articles, tree, gerekçe |
| `semantic.py` | v0.11 | 833 | 5 | FTS5 + TF-IDF hybrid search |
| `chamber.py` | v0.12 | 662 | 4 | Chamber overview, profile, timeline, similarity |
| `release.py` | v0.13 | 400+ | 9+ | Smoke, dashboard, history, command center, v1 readiness |
| `verification.py` | — | 100+ | 3 | Offline smoke, cache integrity, hash verify |
| `cli.py` | — | 826 | 65+ | Typer CLI: 8 alt uygulama |
| `server.py` | — | 896 | 54 | FastMCP server: 54 MCP aracı |

---

## 6. CLI Komut Ağacı

```
emsal-mcp
├── version
├── sources [--json]
├── sources-smoke [--offline|--online] [--json]
├── search <source> <query> [--limit] [--page] [--json]
├── get <source> <document_id> [--json]
├── citation-check <source> <document_id> [--json]
├── build-input-pack <matter> <issue> [--docs-json] [--json]
├── draft-document <title> <body> [--docs-json] [--json]
├── export-docx <out_path> <matter> <issue> [--docs-json] [--json]
├── export-bundle <out_dir> <matter> <issue> [--docs-json] [--json]
├── smoke [--json]
│
├── udf
│   ├── probe <path> [--json]
│   ├── read <path>
│   ├── to-md <path> [--out]
│   ├── write <text_file> <out> [--title-centered]
│   ├── status [--json]
│   ├── authoring-instructions [--format json|markdown] [--json]
│   ├── to-docx <path> [--out-path] [--json]
│   ├── to-pdf <path> [--out-path] [--json]
│   └── docx-to-udf-experimental <path> [--out-path] [--experimental] [--json]
│
├── release
│   ├── dashboard [--json]
│   ├── history [--json]
│   ├── compare [--json]
│   ├── notes [--json]
│   ├── archive [out_dir] [--json]
│   ├── command-center [--json]
│   ├── version-bump [--major|--minor|--patch] [--json]
│   ├── v1-readiness [--json]
│   └── summary [--json]
│
├── cache
│   ├── stats [--json]
│   ├── list [--source] [--limit] [--offset] [--json]
│   ├── search-local <query> [--source] [--court] [--chamber] [--sort] [--limit] [--json]
│   ├── delete <document_id> <source>
│   ├── prune
│   ├── backup <path>
│   ├── export <path>
│   └── import <path>
│
├── research
│   ├── topic <query> [--sources] [--fetch-count] [--filters-json] [--output-dir] [--json]
│   ├── refresh <bundle_path> [--dry-run] [--json]
│   └── dashboard <bundle_path> [--json]
│
├── cite
│   ├── format [--document-id] [--source] [--style petition|parenthetical|short] [--json]
│   └── verify [--text] [--file-path] [--source] [--limit] [--fetch] [--no-live] [--live-only] [--min-score] [--json]
│
├── petition
│   ├── pack <matter> <issue> [--docs-json] [--research-bundle] [--out-dir] [--strict] [--json]
│   ├── inspect <pack_dir> [--json]
│   ├── outline <pack_dir> [--out-dir] [--json]
│   ├── draft <pack_dir> [--outline-path] [--out-dir] [--json]
│   ├── export-docx [--draft-path] [--draft-json-path] [--out-path] [--pack-dir] [--json]
│   └── export-bundle <pack_dir> [--draft-dir] [--docx-path] [--out-dir] [--json]
│
├── legislation
│   ├── search <query> [--legislation-type] [--limit] [--json]
│   ├── get <document_id> [--source] [--json]
│   ├── articles <document_id> [--article-number] [--article-query] [--source] [--json]
│   ├── tree <document_id> [--source] [--json]
│   ├── gerekce <document_id> [--source] [--json]
│   ├── status [--json]
│   ├── types [--json]
│   └── format [--title] [--legislation-no] [--gazette-date] [--style] [--json]
│
├── semantic
│   ├── index [--force-rebuild] [--json]
│   ├── search <query> [--limit] [--json]
│   ├── hybrid <query> [--limit] [--weight] [--json]
│   ├── status [--json]
│   └── rebuild [--json]
│
└── chamber
    ├── overview [--court] [--json]
    ├── profile <chamber> [--court] [--json]
    ├── timeline [--chamber] [--court] [--start-year] [--end-year] [--json]
    └── similar <chamber> [--court] [--limit] [--json]
```

---

## 7. MCP Araç Envanteri (54 Araç)

### Temel (v0.1–0.4): 11 araç
- `search_decisions`, `get_document`, `source_capabilities`, `source_smoke`
- `citation_safety`, `build_input_pack`, `draft_document`, `export_bundle`
- `read_udf`, `write_udf`
- `search_local_cache`, `get_cache_stats`, `list_cached_documents`

### Release (v0.1–0.13): 8 araç
- `release_smoke`, `release_dashboard`, `release_notes_tool`, `release_archive`
- `release_command_center`, `version_bump`, `final_v1_readiness`, `generate_release_summary`

### UDF (v0.9): 5 araç
- `udf_toolkit_status`, `udf_authoring_instructions`, `convert_udf_to_docx_tool`, `convert_udf_to_pdf_tool`, `convert_docx_to_udf_experimental_tool`

### Research (v0.5): 3 araç
- `research_topic_tool`, `refresh_research_bundle_tool`, `research_quality_dashboard_tool`

### Citation (v0.6): 2 araç
- `format_legal_citation`, `verify_legal_citation`

### Petition (v0.7–0.8): 6 araç
- `prepare_drafting_input_pack`, `inspect_petition_pack`
- `prepare_petition_outline`, `prepare_controlled_petition_draft`
- `prepare_docx_export`, `prepare_export_package_bundle`

### Legislation (v0.10): 8 araç
- `search_legislation`, `get_legislation_document`, `search_legislation_articles`
- `get_legislation_article_tree`, `get_legislation_gerekce`, `legislation_source_status`
- `format_legislation_citation`, `get_legislation_types`

### Semantic (v0.11): 5 araç
- `build_semantic_index`, `semantic_search`, `hybrid_search`, `index_status`, `rebuild_search_index`

### Chamber (v0.12): 4 araç
- `chamber_overview`, `profile_chamber`, `chamber_timeline`, `find_similar_chambers`

---

## 8. Test Kapsamı

| Test Dosyası | Test Sayısı | Kapsadığı Sürüm |
|---|---|---|
| `test_adapters.py` | ~73 | v0.2–0.4 |
| `test_capability_contract.py` | ~30 | v0.2 |
| `test_cache_v2.py` | ~30 | v0.3 |
| `test_cli_cache.py` | ~10 | v0.3 |
| `test_research.py` | ~30 | v0.5 |
| `test_citation.py` | ~45 | v0.6 |
| `test_petition.py` | ~30 | v0.7 |
| `test_controlled_draft.py` | ~49 | v0.8 |
| `test_udf.py` | ~35 | v0.9 |
| `test_legislation.py` | ~53 | v0.10 |
| `test_semantic.py` | ~57 | v0.11 |
| `test_chamber.py` | ~14 | v0.12 |
| `test_verification.py` | ~4 | genel |
| `test_models.py` | ~10 | genel |
| `test_release.py` | ~10 | genel |

**Toplam: 513 test, 0 hata, ~11 sn.**

**Test Prensipleri:**
- Tüm testlerde **sıfır canlı ağ çağrısı** — fake/mock source client'lar kullanılır
- Her modül `sources_override` / `cache` parametresi ile test injection'ı destekler
- Hem `ok=True` hem `ok=False` path'leri test edilir
- Turkish karakterler, edge case'ler (boş DB, NULL değerler, metadata_only) kapsanır

---

## 9. Temel Değişmezler (Key Invariants)

1. **Uydurma yok (No Fabrication):** Hiçbir fonksiyon mevzuat numarası, madde numarası, karar tarihi, esas/karar no uydurmaz. Eksik alanlar `warnings` listesine eklenir.

2. **Citation Safety:** Her belge `quote_usable` ve `draft_usable` boolean flag'leri taşır. `metadata_only` / `pdf_only` belgeler asla `draft_usable` olamaz.

3. **Metadata-only leak yok:** `citation_only` belgeler kontrollü taslakta doğrudan alıntı veya dipnot olarak görünmez; sadece bibliyografyada yer alır.

4. **Placeholder koruması:** `draft-skeleton.md` içindeki tüm `{{PLACEHOLDER}}` pattern'leri taslak çıktısında verbatim korunur.

5. **Graceful degradation:** Kaynak bulunamazsa, ağ hatası olursa veya UDF toolkit eksikse — exception throw edilmez, structured error dict dönülür.

6. **Backward compatibility:** Her yeni sürüm additive'dir; önceki sürümün API'si bozulmaz. Tüm eski testler geçmeye devam eder.

7. **Zero dependency for core features:** Semantic search, chamber profiling ve legislation parsing tamamen stdlib + sqlite3 ile çalışır. Harici ML kütüphanesi gerektirmez.

8. **Conservative rate limiting yok:** Tek kullanıcı / tek makine hedeflendiği için rate limiting eklenmemiştir.

---

## 10. v0.13.0 Mevcut Durum

### Release Command Center Çıktısı (örnek):
```json
{
  "ok": true,
  "version": "0.13.0",
  "overall_readiness": 100,
  "checks_passed": 3,
  "checks_total": 3,
  "checks": {
    "release_smoke": { "ok": true },
    "source_capabilities": {
      "ok": true,
      "source_count": 10,
      "unavailable_sources": ["kik"],
      "stable_sources": ["bedesten", "yargitay", "aym", "danistay", "gib", "uyusmazlik", "rekabet", "sayistay"]
    },
    "module_imports": { "ok": true, "passed": 13, "total": 13 }
  },
  "warnings": ["UDF toolkit not available"],
  "recommended_actions": ["BİLGİ: Küçük uyarılar var; release sonrası takip edin."]
}
```

### Bilinen Durum:
- **KİK:** `unavailable` (HTTP 401, auth/token flow gerekli) — beklendiği gibi, bloklayıcı değil
- **UDF Toolkit:** Varsayılan olarak devre dışı (`EMSAL_UDF_TOOLKIT_DIR` veya `UDF_TOOLKIT_DIR` env var ile aktifleştirilir)
- **LibreOffice / unoconv:** PATH'te bulunamadı — isteğe bağlı, sadece UDF↔DOCX dönüşümleri için gerekli
- **Mevzuat adapter:** `experimental` statüsünde — base64 HTML decode, type filtering çalışıyor

### Commit Geçmişi:
```
f754d1b feat: add v0.13 release command center with v1 readiness gate and version bump
fd53dff feat: add v0.12 chamber profiling with overview timeline and similarity search
74fb605 feat: add v0.11 semantic hybrid search with FTS5 and TF-IDF cosine
cc9aeaa fix: clean v0.10 legislation imports and tests
0466ea0 feat: add v0.10 legislation module with search article tree gerekce
24e34fd feat: add udf toolkit integration
bc793bf feat: add controlled draft export validation
60e2a49 feat: add petition pack workflow
2f6cce5 feat: add citation verification
12d8cff fix: clean research test lint
1b1bb96 feat: add research workflow bundles
15d155b feat: harden source adapters
2e19b18 fix: harden cache v2 integrity
4357844 feat: add v0.3 cache local search
a7e9996 feat: add v0.2 contract foundation
5f833f6 chore: baseline emsal mcp mvp
```

---

## 11. Doğrulama Kontrol Listesi

| Kontrol | Durum |
|---|---|
| `python -m ruff check .` | ✅ All checks passed! |
| `python -m pytest tests/ -v --tb=short` | ✅ 513 passed |
| `python -m emsal_mcp.cli release command-center --json` | ✅ overall_readiness: 100 |
| `python -m emsal_mcp.cli release v1-readiness --json` | ✅ ready: true |
| `python -m emsal_mcp.cli legislation types --json` | ✅ 11 types |
| `python -m emsal_mcp.cli semantic status --json` | ✅ index OK |
| `python -m emsal_mcp.cli chamber overview --json` | ✅ chambers listed |
| `python -c "from emsal_mcp.server import main"` | ✅ Server imports OK |
| Tüm modüller import edilebilir | ✅ 13/13 |
| Tüm kaynak adapterlar register edilmiş | ✅ 10/10 (9 stable + 1 unavailable) |

---

## 12. Referans Dosyalar

| Dosya | Açıklama |
|---|---|
| `ROADMAP.md` | Sürüm sürüm roadmap (v0.1–v0.13) |
| `CHANGELOG.md` | Detaylı değişiklik günlüğü (v0.1.0–v0.10.0) |
| `docs/JSON_CONTRACTS.md` | JSON çıktı kontratları |
| `docs/MCP_CONTRACTS.md` | MCP araç kontratları |
| `REPORT_v0.1.0_to_v0.13.0.md` | Bu rapor |
