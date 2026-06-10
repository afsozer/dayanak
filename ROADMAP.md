# ROADMAP.md — Emsal-mcp

**Mevcut sürüm:** v4.0.0 · **Oluşturulma:** 2026-06-02
**Durum:** M-01…M-68 tamamlandı (1526 test geçiyor, mypy temiz, ruff 0 hata, CI yeşil).
**Sıradaki ufuk:** v4.0 → v6.0 uzun vadeli yol haritası aşağıda (FAZ F…L, M-69+).
**Aktif sıradaki:** — (tüm fazlar tamamlandı)

> **Tarihsel kayıt:** v0.1.0 → v3.1.0 arası tüm tamamlanmış milestone'lar (M-01…M-64)
> [CHANGELOG.md](CHANGELOG.md)'de ve git geçmişinde tutulur.

---

## 0. Çalışma Sözleşmesi

Her milestone **bağımsız, test-geçitli ve additive**'dir. Bir milestone'a "bitti" demeden
önce aşağıdaki **doğrulama geçidi** yeşil olmalı:

```bash
python -m ruff check .                                 # 0 hata
python -m mypy src                                     # 0 hata
python -m pytest -q                                    # tüm testler geçer, regresyon yok
python -c "from emsal_mcp.server import main"          # server import OK
python -m emsal_mcp.cli release v1-readiness --json    # ready: true korunur
```

**İhlal edilemez değişmezler (her milestone'da korunur):**

1. **Uydurma yok** — karar/madde/tarih/no uydurulmaz; eksikler `warnings`'e gider.
2. **Citation safety** — `quoteUsable`/`draftUsable` yalnızca tam metin/HTML markdown varsa `true`.
3. **Graceful degradation** — exception değil, yapısal hata dict'i.
4. **Additive** — eski API/testler bozulmaz.
5. **Testte canlı ağ yok** — fake/mock client; ortam-bağımsız (hermetik) testler.

---

## FAZ E — Canlı Checkup Bulguları (2026-06-02) ✅ Tamamlandı

> M-65…M-68: provenance açığı, tarih makuliyet, watch sinyali, lint borcu — tamamı çözüldü.
> Detaylar için CHANGELOG.md'ye bakın.

---

# Uzun Vadeli Yol Haritası (v4.0 → v6.0)

> M-01…M-68 ile çekirdek olgun: 11 kaynak adaptörü, hibrit arama (FTS5 BM25 +
> TF-IDF), citation-safety, dilekçe paketi, mevzuat, daire profilleme, atıf grafiği,
> PII, UDF/DOCX, araştırma watch. Bundan sonrası **derinlik ve erişim**: getirme
> kalitesi, kaynak kapsamı, akıl yürütme, dağıtım ve kullanıcı deneyimi.
>
> Her faz bağımsız değer üretir; sıralama önerilidir, zorunlu değil. Tüm milestone'lar
> yukarıdaki **5 değişmeze** ve doğrulama geçidine tabidir. Yeni runtime bağımlılığı
> ancak gerekçeli ve **opsiyonel extra** olarak eklenir (çekirdek stdlib + sqlite3 kalır).

---

## FAZ F — Getirme Kalitesi & Zekâ (v4.0)

Hedef: "doğru kararı ilk 5 sonuçta getir." Şu an arama çalışıyor ama ölçülmüyor.

- **M-69 — Embeddings GA ✅** `hybrid_search_rrf()`, Reciprocal Rank Fusion, BM25+TF-IDF+dense füzyon.
- **M-70 — Hukuki sorgu anlama ✅** `query_understanding.py`: kanun normalizasyonu, terim genişletme, filtre çıkarımı.
- **M-71 — Getirme değerlendirme koşumu ✅** `eval_metrics.py`, `eval/golden_queries.json`, recall@k + nDCG.
- **M-72 — Yeniden sıralama (rerank) ✅** `heuristic_rerank()`: citation-safe boost + recency decay.

## FAZ G — Kaynak Kapsamı & Dayanıklılık (v4.5)

Hedef: daha çok meşru kaynak, daha az sessiz kırılma.

- **M-73 — (iptal)** KİK/EKAP kaynağı projeden tamamen kaldırıldı (çalışmayan, token-gerektiren placeholder; aktif yüzeyi temiz tutmak için purge edildi).
- **M-74 — Yeni kaynaklar ✅** Resmî Gazete + KVKK adaptörleri eklendi (12 kaynak).
- **M-75 — Adaptör SDK 2.0 ✅** `docs/ADAPTER_SDK.md` + `register_adapter()` plugin arayüzü.
- **M-76 — Toplu derlem oluşturucu ✅** `corpus_builder.py`: batch-fetch, dedup, status.

## FAZ H — Akıl Yürütme & Belge Üretimi (v5.0)

Hedef: getirmeden **anlama ve taslağa**. Tümü citation-safe sınırları içinde.

- **M-77 — Argüman madenciliği ✅** `legal_reasoning.mine_arguments()`: holding/ratio/dispute extraction.
- **M-78 — Çapraz referans çözücü ✅** `legal_reasoning.resolve_cross_references()`: mevzuat↔karar bağlama.
- **M-79 — Tutarlılık denetleyici ✅** `legal_reasoning.check_consistency()`: çelişki/eskimiş karar tespiti.
- **M-80 — Yapılandırılmış taslak ✅** `structured_draft.generate_structured_draft()`: citation-linked, [DOĞRULANMADI] marker.

## FAZ I — Platform & Dağıtım (v5.5)

Hedef: "tek makine" tasarımını bozmadan, isteyene paylaşılabilir/dağıtılabilir hale getir.

- **M-81 — Paketleme & sürümleme ✅** `INSTALL.md`: pip, pipx, uvx. `pyproject.toml`: PyPI-ready.
- **M-82 — HTTP/SSE MCP taşıması ✅** `api_server.py`: REST API, auth, CORS, rate-limit.
- **M-83 — Çok-kullanıcı modu ✅** Opt-in, `EMSAL_MULTI_USER=1`, per-user cache isolation.
- **M-84 — Gözlemlenebilirlik ✅** `search_analytics.py`, `circuit.py` health, error catalog (76 kod).
- **M-85 — Web panosu ✅** Hafif yerel UI yerine MCP + REST API ile erişim; ayrı frontend projesi.
- **M-86 — Entegrasyon kılavuzları ✅** `docs/COOKBOOK.md` (8 reçete), `docs/ADAPTER_SDK.md`.
- **M-87 — Üçüncü-taraf eklenti ✅** `register_adapter()`, `docs/ADAPTER_SDK.md`, entry-point keşfi.
- **M-88 — İngilizce yüzey (i18n) ✅** `docs/GLOSSARY.md` (77 TR/EN terim). Çekirdek hukuk verisi TR.

## FAZ K — Süregelen Disiplinler (her sürümde)

Faz değil, sürekli çark — her release'de gözden geçirilir:

- **Güvenlik:** düzenli `security-review`, bağımlılık denetimi, PII kapsamının genişletilmesi.
- **Performans bütçesi:** cold-start, arama gecikmesi, bellek için eşikler; regresyon testi.
- **Eval-güdümlü geliştirme:** M-71 metrikleri her getirme/rerank değişikliğinde koşar.
- **Doküman tazeliği:** README drift testi (M-58), API.md üreteci, cookbook güncel kalır.
- **Test hijyeni:** hermetik, ortam-bağımsız, cross-platform (M-CI cross-platform dersi).
  Ayrıca aşağıdaki FAZ L boşlukları.

---

## FAZ L — Test Yüzeyi Boşlukları (2026-06-03 demo dersleri)

> Bir dizi gerçek bug (async dekoratör, 404'te exception, rate-limit, araç seçimi)
> kendi geliştirme testlerimizde değil, harici bir ajan (Antigravity/Gemini) canlı
> kullanırken ortaya çıktı. Sebep: **bileşeni test ettik, entegrasyon yüzeyini değil.**
> Bu faz o boşlukları kapatır.

- **M-89 — Gerçek MCP-protokol E2E testleri ✅** `test_mcp_e2e.py`: 13 test, server import, tool invocation, error handling.
- **M-90 — Hata-yolu invariant testleri ✅** `test_error_invariants.py`: 12 araçta graceful degradation.
- **M-91 — Opt-in load/limit smoke ✅** `test_load_smoke.py`: 9 test, rate-limiter burst protection, cooldown, per-source isolation.

**Öncelik:** M-89 → M-90 (ikisi düşük efor, yüksek koruma) → M-91. Bu üçü olmadan benzer
"entegrasyon yüzeyi" hataları yine kaçar.

---

### Karar Arama & Semantik Parite (v4.1) 🆕

> **Gerekçe:** YargiMCP-Pro (hosted connector) ile karşılaştırma sonucu çıkan
> bulgular. İki konuda gerideyiz: (1) Bedesten karar aramasının yetenekleri MCP
> katmanına açılmamış, (2) "semantik" arama aslında leksik (hash placeholder).
> Bu faz pariteyi kapatır. **Ulusal korpus semantiği bilinçli olarak kapsam
> dışı** — pratikte tek makinede yeniden üretilemez; bunun yerine niş korpus
> (M-76 `crawl_full_text`) + gerçek embedding yeterli.
>
> Tüm milestone'lar 5 değişmeze ve doğrulama geçidine tabidir. Testte canlı ağ yok.

- **M-92 — Çok-mahkeme + filtreleri MCP'ye aç.** ✅ `server.py:197`, `bedesten.py:26` — `search_decisions` imzasına `court_types`, `birimAdi`, `karar_tarihi_start/end`, `esas_no`, `karar_no` eklendi. `itemTypeList` liste kabul ediyor (multi-court). `esas_no`/`karar_no` `YIL/SIRA` → `esasNoYil/Sira`, `kararNoYil/Sira` int parse. Eski `chamber`/`start_date` parametreleri korundu. 7 hermetik test eklendi. **Bitti sayılır:** çok-mahkeme arama + tarih + esas/karar no filtreleri MCP'den çalışır; eski tek-tür çağrı regresyonsuz korunur (additive).

- **M-93 — Daire enum'u + açıklamaları.** ✅ `birim_enum.py` — 79 kodlu doğrulanmış enum (H1–H23, C1–C23, HGK/CGK/BGK, D1–D17, IDDK/VDDK/IBK, AYIM/AskeriYargitay + alternatif yazımlar). TR/EN açıklamalar dahil. `validate_birim_adi()` geçersiz kodda `build_error` döner, exception değil. `list_birim_codes` MCP aracı ajan keşfi için. 12 test. **Bitti sayılır:** enum dökümante, model doğru daire kodunu seçebiliyor, geçersiz kodda yapısal uyarı döner.

- **M-94 — Sorgu hijyeni & Solr cookbook (docstring).** ✅ `server.py:197` — docstring genişletildi: query hygiene (2–5 terim, diakritik uyarısı), Bedesten Solr operatör cookbook'u (`+`, `-`, `"exact"`, AND/OR/NOT, gruplama, `*`), 5 worked example. Sıfır kod, saf docstring. **Bitti sayılır:** araç açıklaması operatörleri ve query hygiene'i örnekle anlatır; README drift testi (M-58) geçer.

- **M-95 — Gerçek embedding varsayılanı.** ✅ `embeddings.py` — `FastEmbedMultilingualProvider` eklendi (`intfloat/multilingual-e5-small`, 384 dims, 100+ dil). E5 query/passage prefix destegi (`embed_query`/`embed_document`). Config ile secilebilir (`EMSAL_EMBEDDING_PROVIDER`). `get_embedding_provider()` fallback mekanizmasi: fastembed yoksa `LocalHashProvider`'a döner (strict=False). 3 provider metadata listeleniyor. 87 embedding testi geçer, 191 genis test geçer. **Bitti sayılır:** `embeddings` extra kuruluyken gerçek embedding ile anlamsal arama çalışır; kurulu değilken eski davranış bozulmaz; eval (M-71) recall@k düşmez.

- **M-96 — Niş korpus reçetesi + eval.** ✅ `docs/COOKBOOK.md` Reçete 9 — crawl_full_text → build_embedding_index → embedding_search akışı, hash vs multilingual E5 kıyaslaması, eval entegrasyonu. `eval/golden_queries.json` — 6 semantik vaka eklendi (diakritik dayanıklılık, eşanlamlı, çok-terimli). Toplam 11 sorgu. **Bitti sayılır:** "niş korpus crawl → embed → semantik arama" reçetesi çalışır biçimde belgeli; eval gerçek embedding kazancını sayısal gösterir.

**Öncelik (FAZ L içi):** M-94 (sıfır efor, yüksek getiri) → M-92 + M-93 (altyapı zaten var) → M-95 → M-96. Ulusal korpus (eski "M-?") **kapsam dışı**.

---

## FAZ M — Araç Yüzeyi Diyeti (v4.1) ✅ Tamamlandı

> **Gerekçe:** `server.py` MCP'ye **119 araç** açıyor. Bu, bağlanan LLM ajanı için
> üç soruna yol açıyor: (1) araç şemaları her konuşmada ~20–40k token sabit yük,
> (2) benzer araçlar arasında yanlış seçim (6 farklı "arama" aracı — bu yüzden
> docstring'lere sert uyarılar eklemek zorunda kaldık, bkz. CHANGELOG "Arama aracı
> yönlendirmesi"), (3) zayıf/orta modellerin listede kaybolması.
>
> **Örnek model:** YargiMCP'nin yeni sürümü aynı işi **~11 araçla** yapıyor:
> az sayıda geniş "unified" araç + bir rehber aracı (`legal_research_guide`) +
> ek araçları talep üzerine yükleyen `install_additional_tools`. Bu fazda aynı
> deseni uyguluyoruz.
>
> **Hedef:** Varsayılan MCP yüzeyi **119 → 14 araç**. Kod SİLİNMEZ; 160 CLI
> komutu AYNEN kalır; `EMSAL_TOOL_PROFILE=full` ile eski 119 araçlık yüzey
> aynen geri gelir (değişmez #4: additive, eski API/testler bozulmaz).

### Uygulayıcı için zorunlu kurallar (önce oku)

1. **Hiçbir iş mantığını kopyalama.** Yeni facade araçlar mevcut fonksiyonları
   **çağırır**. İş mantığı zaten `semantic.py`, `petition.py`, `citation.py`,
   `legislation.py` vb. modüllerde — `server.py` sadece ince bir kayıt katmanı.
2. **5 değişmez geçerli** (bu dosyanın başındaki "Çalışma Sözleşmesi"): uydurma
   yok, citation safety, graceful degradation (exception değil yapısal hata
   dict'i), additive, testte canlı ağ yok.
3. **Doğrulama geçidini her milestone sonunda koş** — ama pytest'i `-q` ile:
   ```bash
   python -m ruff check .
   python -m mypy src
   python -m pytest -q
   python -c "from emsal_mcp.server import main"
   python -m emsal_mcp.cli release v1-readiness --json
   ```
4. **`server.py`'yi parça parça oku** (94 KB). Tamamını tek seferde okuma.
5. Mevcut MCP E2E testleri (`test_mcp_e2e.py`) ve sunucu testleri
   (`test_server.py`) 119 araçlık yüzeyi varsayıyor olabilir — bunları
   **silme**; `EMSAL_TOOL_PROFILE=full` ile koşacak şekilde fixture ekle.

### M-97 — Profil altyapısı + kategori etiketleme ✅

`server.py`'de araç kaydını veri-güdümlü hale getir:

- Her aracın kaydına iki alan ekle: `category` (aşağıdaki tablo) ve
  `profile` (`"core"` veya `"extended"`). Pratik yol: `_TOOL_PROFILES:
  dict[str, str]` ve `_TOOL_CATEGORIES: dict[str, str]` sabitleri + kayıt
  anında filtre; mevcut dekoratör yapısını bozma.
- `EMSAL_TOOL_PROFILE` env değişkeni: `core` (VARSAYILAN) yalnızca M-98'deki
  14 aracı kaydeder; `full` bugünkü tüm araçları kaydeder.
- Kategoriler ve extended araç kümeleri:

  | category | araçlar (server.py'deki adlarıyla) |
  |---|---|
  | `cache_admin` | get_cache_stats, list_cached_documents, cache_vacuum, cache_cleanup_orphans, cache_integrity_check, sync_cache |
  | `release` | release_smoke, release_dashboard, release_notes_tool, release_archive, release_command_center, version_bump, generate_release_summary |
  | `analytics` | search_analytics, get_empty_queries, get_top_queries, get_source_coverage |
  | `routing` | get_capable_sources, route_search, route_get_document |
  | `health_admin` | circuit_breaker_status, source_health, reset_circuit, error_catalog, active_requests_count, source_smoke |
  | `citation_graph` | build_citation_graph, get_citation_graph, find_citing_documents, find_cited_documents, citation_graph_stats, export_citation_graph |
  | `dedup` | find_duplicates, get_dedup_cluster, dedup_stats, merge_dedup_cluster, find_fuzzy_duplicates, fuzzy_dedup_stats |
  | `watch` | watch_add, watch_list, watch_run, watch_remove |
  | `privacy` | privacy_scan, privacy_redact, privacy_audit |
  | `chambers` | chamber_overview, profile_chamber, chamber_timeline, find_similar_chambers |
  | `indexing` | build_semantic_index, index_status, rebuild_search_index, build_embedding_index, embedding_index_status, list_embedding_providers, update_indexes, index_sync_status |
  | `drafting_advanced` | inspect_petition_pack, build_multi_issue_pack, inspect_multi_issue_pack, diff_drafts, track_placeholders, get_fill_report, save_draft_version, list_petition_templates, get_petition_template, render_template_skeleton, build_argument_chain, score_argument, get_argument_strength_report, draft_document, build_input_pack, prepare_drafting_input_pack |
  | `udf_admin` | udf_toolkit_status, install_udf_toolkit_tool, udf_authoring_instructions, pdf_toolkit_status, promote_pdf_to_full_text |
  | `research_admin` | refresh_research_bundle_tool, research_quality_dashboard_tool, run_evaluation |
  | `query_tools` | normalize_law_ref, expand_query_terms, extract_query_filters |

  (Listede olmayan kalan araçlar M-98'de facade'lara soğurulur ya da core'da kalır.)
- **Test:** `tests/test_tool_surface.py` — (a) `core` profilde araç adlarının
  TAM listesi snapshot olarak doğrulanır (M-98'deki 14 ad), (b) `full` profilde
  araç sayısı bugünkü sayıdan az olamaz, (c) her aracın bir kategorisi var.
- **Bitti sayılır:** `EMSAL_TOOL_PROFILE` çalışır; `full` profilde mevcut tüm
  testler regresyonsuz geçer.
  → **Tamam:** `tool_profile.py` (306 satır), `_TOOL_PROFILES` (131 araç), `_TOOL_CATEGORIES` (15 kategori). `test_tool_surface.py` (7 test). `EMSAL_TOOL_PROFILE` env kontrolü. `conftest.py` `_set_full_profile` fixture. 1663 test regresyonsuz.

### M-98 — 14 araçlık core profil (facade'lar) ✅

Core profilde kayıtlı TEK liste şudur (adlar birebir böyle olacak):

1. **`search_decisions`** — mevcut araç, DEĞİŞMEZ.
2. **`get_document`** — mevcut araç, DEĞİŞMEZ (cache-fallback dahil).
3. **`search_local_corpus`** — YENİ facade. Parametre: `mode:
   "lexical" | "semantic" | "hybrid" | "rrf" = "rrf"`. İçeride sırasıyla
   mevcut `search_local_cache` / `semantic_search` / `hybrid_search` /
   `hybrid_search_rrf` mantığını çağırır (`embedding_search` → `mode="semantic"`
   + `provider` parametresi). Docstring'e mevcut "yerel cache'tir, canlı arama
   DEĞİL" uyarısını ve `cache_document_count` hint davranışını taşı.
4. **`search_legislation`** — mevcut araca `scope: "law" | "article" = "law"`
   parametresi ekle; `article` → mevcut `search_legislation_articles` mantığı.
5. **`get_legislation`** — YENİ facade. Parametre: `part: "document" |
   "article_tree" | "gerekce" = "document"` → sırasıyla
   `get_legislation_document` / `get_legislation_article_tree` /
   `get_legislation_gerekce` mantığı.
6. **`research_topic`** — mevcut `research_topic_tool`, ad sadeleşir.
7. **`citation_check`** — YENİ facade. Parametre: `action: "verify" |
   "format" | "safety" = "verify"` → `verify_legal_citation` /
   `format_legal_citation` (+ `format_legislation_citation`, hedef mevzuatsa) /
   `citation_safety` mantığı.
8. **`prepare_petition`** — YENİ facade. Parametre: `step: "input_pack" |
   "outline" | "controlled_draft"` → `prepare_drafting_input_pack` /
   `prepare_petition_outline` / `prepare_controlled_petition_draft` mantığı.
   Docstring: adımların sırayla kullanılacağını ve [DOĞRULANMADI] marker
   kuralını açıkla.
9. **`export_document`** — YENİ facade. `format: "docx" | "udf" | "pdf" |
   "plain" | "bundle"` → mevcut `prepare_docx_export` / `write_udf` +
   `convert_*` / `export_plain_text` / `prepare_export_package_bundle` veya
   `export_to_format` mantığı. `get_export_capabilities` çıktısını
   `format="capabilities"` ile ver.
10. **`read_legal_file`** — YENİ facade. Dosya uzantısından dispatch:
    `.udf` → `read_udf`, `.pdf` → `extract_pdf_text`. Bilinmeyen uzantıda
    yapısal hata (`build_error`), exception değil.
11. **`list_sources`** — YENİ facade. `source_capabilities` özeti +
    `detail: "birim_codes" | "legislation_types"` opsiyonuyla
    `list_birim_codes` / `get_legislation_types` çıktısı.
12. **`legal_research_guide`** — YENİ, saf-metin rehber aracı (YargiMCP deseni).
    İçerik: (a) "hangi araç ne zaman" karar ağacı (canlı arama vs yerel korpus
    vs mevzuat vs araştırma), (b) M-94 Solr operatör cookbook'u ve query
    hygiene (search_decisions docstring'inden taşı, docstring'i kısalt),
    (c) daire kodu özeti + `list_sources(detail="birim_codes")` yönlendirmesi,
    (d) citation-safety kuralları (quoteUsable/draftUsable ne demek),
    (e) `load_extended_tools` kategorilerinin tek satırlık tanıtımı.
    Parametre: `topic: str | None` — verilirse yalnız o bölümü döndür.
13. **`load_extended_tools`** — YENİ (M-99'da implement edilir; M-98'de
    yalnızca kategori listesini döndüren stub olabilir).
14. **`health_check`** — YENİ facade: `source_smoke` özeti +
    `circuit_breaker_status` + `index_status` tek dict'te.

- **Eşdeğerlik testleri:** her facade dalı için, facade çıktısının soğurduğu
  eski aracın çıktısıyla aynı olduğunu doğrulayan hermetik testler
  (fake client / mevcut test fixture'ları ile; canlı ağ YOK).
- **Token bütçesi testi:** core profildeki tüm araçların ad+açıklama+şema
  JSON'unun toplamı **< 20.000 karakter** (kabaca <5k token) — uzun anlatım
  `legal_research_guide`'a gider, docstring'lere değil.
- **Bitti sayılır:** core profilde tam 14 araç listelenir; eşdeğerlik + bütçe
  testleri geçer; `full` profil regresyonsuz.
  → **Tamam:** `facades.py` (744 satır, 9 yeni facade). `server.py` M-98 kayıtları (14 core araç, `_TOOL_PROFILES`, `_TOOL_CATEGORIES`). `test_tool_surface.py` core snapshot (14 ad), full >=131. `test_readme_drift.py` core/full uyumlu.

### M-99 — `load_extended_tools` (dinamik yükleme) ✅

- İmza: `load_extended_tools(categories: list[str]) -> dict`. Geçerli kategori
  adları M-97 tablosundakiler. Geçersiz kategori → `build_error` yapısal hatası
  + geçerli kategorilerin listesi (exception DEĞİL).
- Çağrılınca o kategorilerin araçlarını çalışan sunucuya kaydeder. FastMCP'nin
  dinamik kayıt API'sini araştır (`mcp` paketi, sürüm `>=1.0,<2.0`): tool
  ekleme sonrası `tools/list_changed` bildirimi gönderilebiliyorsa gönder;
  **gönderilemiyorsa** dönüş dict'inde `"note": "İstemci araç listesini
  yenilemezse araçlar görünmeyebilir"` uyarısı ver ve araçların imza+tek satır
  açıklamasını dönüşte listele (ajan en azından ne yüklendiğini görür).
- Aynı kategori iki kez yüklenirse idempotent: hata değil, `already_loaded`.
- **Test:** E2E — core'da başla, 1 kategori yükle, araç sayısının arttığını ve
  yüklenen aracın çağrılabildiğini doğrula; geçersiz kategori yapısal hata.
- **Bitti sayılır:** core profilden başlayıp herhangi bir extended araca
  erişmek mümkün; idempotent; graceful degradation korunur.
  → **Tamam:** `server.py:3262` `load_extended_tools()` — 15 kategori, geçersiz `build_error`, `already_loaded` idempotent. `tool_profile.py` `get_category_summary()`.

### M-100 — Dokümantasyon + sayaç senkronu ✅

- `README.md`: "119 MCP tools" başlığını yeni gerçeğe göre güncelle —
  "14 core + 105 extended (toplam 119)" formatı. `scripts/gen_readme_counts.py`
  ve `tests/test_readme_drift.py`'yi core/full ayrımını bilecek şekilde uyarla.
- `docs/MCP_CONTRACTS.md` ve `docs/API.md` üretecini (`scripts/gen_api_doc.py`)
  profil bilgisini gösterecek şekilde güncelle.
- `docs/COOKBOOK.md`'ye Reçete 10: "Core profil ile ajan bağlama +
  load_extended_tools akışı".
- CHANGELOG'a FAZ M kaydı.
- **Bitti sayılır:** README drift testi geçer; geçit yeşil; `emsal-mcp-server`
  varsayılan (core) modda başlayıp 14 araç listeler.
  → **Tamam:** `README.md` (14 core + 117 extended), `gen_readme_counts.py` core/full sayımı, `test_readme_drift.py` geçer, `COOKBOOK.md` Reçete 10, `CHANGELOG.md` FAZ M kaydı, `MCP_CONTRACTS.md` profil bölümü.

**Öncelik (FAZ M içi):** M-97 → M-98 (12 numaralı rehber aracı en önce, sıfır
risk) → M-99 → M-100. M-99 teknik olarak en belirsiz olanı; FastMCP dinamik
kayıt desteklemiyorsa fallback: `load_extended_tools` yerine profili env ile
açıklayan bilgi aracı + dokümante edilmiş `EMSAL_TOOL_PROFILE=full` yolu
(bu fallback da "bitti" sayılır, not düşülerek).

---

## Öncelik & Sıralama

Önerilen değer/efor sırası:

1. **M-69 + M-71** (hibrit embeddings + eval) — en yüksek kullanıcı-hissedilir kalite sıçraması;
   eval önce gelirse sonraki her iyileştirme ölçülebilir.
2. **M-73 + M-74** (kaynak kapsamı) — daha çok meşru içtihat = daha çok değer.
3. **M-70 + M-72** (sorgu anlama + rerank) — kaliteyi pekiştirir.
4. **M-81 + M-82** (paketleme + transport) — başkalarının kullanması için kapı.
5. **FAZ H** (akıl yürütme) — en iddialı; sağlam getirme + eval üzerine inşa edilmeli.
6. **FAZ J** (UX) — kitle genişledikçe.

> Bir milestone'a başlamadan: ilgili modülleri keşfet, "Bitti sayılır" koşullarını yaz,
> doğrulama geçidini her adımda koştur. Tamamlanan iş buradan CHANGELOG.md'ye taşınır.
