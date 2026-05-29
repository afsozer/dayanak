# ROADMAP_LONG_HORIZON.md — Emsal-mcp v0.14 → v2.0+

**Oluşturulma:** 2026-05-29
**Başlangıç noktası:** v0.13.0 (513 test, 0 lint, 54 MCP aracı, 10 kaynak adapter, v1 readiness gate yeşil)
**Hedef kitle:** OpenCode orchestrator + Ralph-loop ile otonom, uzun soluklu yürütme

---

## 0. Bu Roadmap Nasıl Kullanılır (Ralph-Loop Sözleşmesi)

Bu belge, orchestrator'ın işi alt görevlere bölüp `controller` ve `mimo-worker`'lara delege etmesi için tasarlandı. Her milestone (M-xx) **bağımsız, test-geçitli ve additive** bir birimdir.

**Orchestrator için çalışma protokolü:**

1. Sıradaki tamamlanmamış milestone'u seç (en küçük numara). Aynı anda **tek milestone**.
2. Milestone'u "Görevler" listesindeki atomik adımlara böl. Her adımı uygun worker'a ver:
   - `controller` → mimari kararlar, yeni modül iskeleti, kontrat tasarımı, riskli refactor, güvenlik-değişmezleri, final review.
   - `mimo-worker` / `explore` → kod tabanı keşfi, rutin implementasyon, test yazımı, mekanik düzenleme, lint düzeltme.
3. Her adımdan sonra **DOĞRULAMA GEÇİDİNİ** çalıştır (aşağıda). Geçit kırmızıysa düzelt, sonra devam et.
4. Milestone'un "Bitti Sayılır" (Definition of Done) koşullarının **HEPSİ** sağlanmadan bir sonrakine geçme.
5. Tüm hedef milestone'lar bitip doğrulanana kadar `<promise>DONE</promise>` **YAZMA**. Bloklanırsan, sahte tamamlama yerine blokeri açıkla ve kullanıcıdan girdi iste.

**Her milestone için zorunlu DOĞRULAMA GEÇİDİ:**

```bash
python -m ruff check .                                    # 0 hata olmalı
python -m pytest tests/ -q                                # tüm testler geçmeli (regresyon yok)
python -c "from emsal_mcp.server import main"             # server import OK
python -m emsal_mcp.cli release command-center --json     # overall_readiness korunmalı
python -m emsal_mcp.cli release v1-readiness --json       # ready: true kalmalı
```

**İhlal edilemez değişmezler (her milestone'da korunur):**

1. **Uydurma yok** — hiçbir kod karar no, madde no, tarih, mevzuat no uydurmaz; eksikler `warnings`'e gider.
2. **Citation safety** — `quote_usable` / `draft_usable` flagleri korunur; `metadata_only` asla `draft_usable` olamaz.
3. **Graceful degradation** — exception değil, structured error dict.
4. **Additive** — eski API bozulmaz, eski testler geçer.
5. **Core'da sıfır yeni ağır bağımlılık** — stdlib + sqlite3 önceliği; yeni runtime bağımlılığı ancak gerekçeli ve opsiyonel olabilir.
6. **Testte canlı ağ yok** — fake/mock source client'lar; `sources_override` / `cache` injection.

---

## FAZ 1 — Sağlamlaştırma ve v1.0.0 (M-01 → M-05)

Amaç: yeni özellik eklemeden önce mevcut yüzeyi sertleştirmek, dokümantasyonu hizalamak ve v1.0.0'ı çıkarmak. Ralph-loop için **ideal ısınma fazı** — düşük riskli, yüksek doğrulanabilirlik.

### M-01 — Doküman & Roadmap Senkronizasyonu
- **Sorun:** `ROADMAP.md` v0.11/v0.12/v0.13'ü içermiyor; `CHANGELOG.md` v0.10.0'da kalmış.
- **Görevler:**
  - `CHANGELOG.md`'yi v0.11.0 → v0.13.0 girdileriyle tamamla (REPORT'tan).
  - `ROADMAP.md`'ye v0.10–v0.13 bölümlerini ekle, sürüm sırasını düzelt (şu an karışık).
  - `docs/JSON_CONTRACTS.md` ve `docs/MCP_CONTRACTS.md`'yi 54 aracın tamamını kapsayacak şekilde güncelle.
  - README varsa kurulum + hızlı başlangıç bölümünü 54 araç/65 komutla hizala.
- **Bitti sayılır:** Her sürümün CHANGELOG + ROADMAP girdisi var; kontrat dokümanları araç sayısıyla eşleşiyor; doğrulama geçidi yeşil.
- **Worker:** `mimo-worker` (metin işi), `controller` (kontrat doğruluğu review).

### M-02 — Test Boşluğu Kapatma & Coverage Ölçümü
- **Görevler:**
  - `coverage.py` ekle (dev-only), `pytest --cov` ile satır kapsamı raporu üret; hedef baz çizgisini kaydet.
  - Kapsam < %70 olan modülleri tespit et (özellikle `server.py`, `cli.py` ağır olabilir).
  - En düşük kapsamlı 3 modüle hedefli test ekle (happy + error + edge path).
- **Bitti sayılır:** Coverage raporu üretiliyor; toplam kapsam ölçülüp dokümante edildi; en az 3 modülde kapsam arttı; tüm testler geçiyor.
- **Worker:** `mimo-worker`.

### M-03 — Hata & Kontrat Tutarlılığı Denetimi
- **Görevler:**
  - Tüm public fonksiyonların dönüş sözleşmesini tara: her biri `ok`, `warnings`, `recommended_next_steps` (uygunsa) içeriyor mu?
  - Tutarsız error dict şekillerini normalize et (tek bir `build_error()` helper'ı, additive).
  - `safety.py` değişmezlerini doğrulayan bir "invariant test suite" ekle: metadata_only→draft_usable=False her yolda test edilir.
- **Bitti sayılır:** Error şekilleri tek helper'dan geçiyor; invariant test suite yeşil; regresyon yok.
- **Worker:** `controller` (tasarım), `mimo-worker` (uygulama).

### M-04 — Yapılandırma & Gözlemlenebilirlik Katmanı
- **Görevler:**
  - `config.py` ekle: env-tabanlı ayarlar (cache yolu, timeout, user-agent, UDF dir) tek yerde, defaultlu, doğrulamalı.
  - Opsiyonel yapısal logging (stdlib `logging`, default WARNING; `EMSAL_LOG_LEVEL` ile ayarlanır). Stdout JSON kirliliği yapmaz.
  - `emsal-mcp doctor` komutu: ortam teşhisi (Python sürümü, cache erişimi, opsiyonel toolkit, kaynak smoke özeti).
- **Bitti sayılır:** `config.py` mevcut, env override test edildi; `doctor` komutu JSON çıktı veriyor; logging core JSON kontratlarını kirletmiyor.
- **Worker:** `controller` (config tasarımı), `mimo-worker`.

### M-05 — v1.0.0 Release
- **Görevler:**
  - `version_bump --minor` mantığıyla 0.13.0 → 1.0.0 (major) bump; `__version__` ve `pyproject`/`package` metadata güncelle.
  - `final_v1_readiness` go/no-go yeşil olmalı.
  - `RELEASE_NOTES_v1.0.0.md` üret (`generate_release_summary` çıktısından + insan-okunur özet).
  - Git tag önerisi hazırla (commit kullanıcı onayıyla).
- **Bitti sayılır:** Sürüm 1.0.0; v1-readiness ready:true; release notes mevcut; tüm geçitler yeşil. **NOT: commit/tag kullanıcı onayı ister.**
- **Worker:** `controller`.

---

## FAZ 2 — Veri Katmanı & Arama Olgunluğu (M-06 → M-10)

Amaç: arama/cache yüzeyini üretim-kalitesine taşımak. Hâlâ ağ-bağımsız ve stdlib öncelikli.

### M-06 — Cache Bütünlüğü & Bakım
- Cache vacuum/compaction komutu, yetim `search_vectors`/`fts` satırlarını temizleme, integrity-check raporu, otomatik migration sürüm kontrolü.
- **Bitti sayılır:** `cache integrity-check` ve `cache vacuum` komutları; bozuk-DB testi; migration idempotent.

### M-07 — Semantic Search v2
- BM25 + TF-IDF'e ek: query expansion (Türkçe stemming/suffix-stripping heuristics), snippet highlighting, per-source filtreli hybrid arama, configurable `hybrid_weight` validation.
- **Bitti sayılır:** Türkçe sorgu genişletme testli; hybrid arama kaynak filtresi destekliyor; relevance regresyonu yok.

### M-08 — Citation Graph (Atıf Ağı)
- Belgeler arası atıf ilişkilerini cache'ten çıkar: "bu karar hangi kararlara atıf yapıyor / hangi kararlar buna atıf yapıyor" (yalnızca tespit edilebilen, uydurma yok).
- `citation_graph()` + `find_citing_documents()` MCP araçları. Graf SQLite'ta saklanır.
- **Bitti sayılır:** Atıf çıkarımı sadece doğrulanabilir referanslardan; graf inşa testli; eksik veri warning.

### M-09 — Çapraz-Kaynak Deduplication & Merge
- Aynı kararın farklı kaynaklardan gelen kopyalarını tespit (esas/karar no + tarih + hash benzerliği); kanonik kayıt + alternatif kaynak listesi.
- **Bitti sayılır:** Dedup heuristic'i false-merge yapmıyor (test ile kanıtlı); kanonik seçim deterministik.

### M-10 — Arama Analitik & Kalite Metrikleri
- `search analytics`: sorgu başarı oranı, boş-sonuç sorguları, kaynak kapsama dağılımı, cache hit ratio.
- **Bitti sayılır:** Analitik komutu JSON; metrikler cache'ten deterministik üretiliyor.

---

## FAZ 3 — Dilekçe & Belge Üretimi Derinleştirme (M-11 → M-15)

Amaç: petition pipeline'ını gerçek kullanım senaryolarına yaklaştırmak — **citation-safe değişmezleri en kritik olduğu faz.** `controller` ağırlıklı.

### M-11 — Petition Template Library
- Birden fazla dilekçe şablonu (dava dilekçesi, cevap, temyiz, istinaf, icra itiraz). Her şablon `{{PLACEHOLDER}}` sözleşmesine uyar.
- **Bitti sayılır:** ≥4 şablon; her biri inspect'ten geçiyor; placeholder koruması testli.

### M-12 — Argument Builder
- `argument-map.md`'yi yapılandırılmış argüman zincirine dönüştür: iddia → dayanak otorite → karşı-argüman alanı. Yalnızca `petition_ready` otoriteler dayanak olabilir.
- **Bitti sayılır:** Argüman zinciri sadece safe otoriteler; metadata-only sızıntısı yok (invariant test).

### M-13 — Çok-Konulu (Multi-Issue) Pack
- Tek dilekçede birden fazla hukuki mesele; her mesele için ayrı citation-bank ve argüman bölümü.
- **Bitti sayılır:** Multi-issue pack inspect geçiyor; her mesele izole; hash-manifest tutarlı.

### M-14 — Draft Diff & Versiyonlama
- Taslak revizyonları arası diff (`draft v1` vs `v2`), placeholder doldurma takibi, "neyin hâlâ doldurulması gerektiği" raporu.
- **Bitti sayılır:** Diff deterministik; placeholder-kalan raporu doğru; eski draft formatı okunabilir.

### M-15 — Export Format Genişletme
- Markdown → DOCX zaten var; PDF (opsiyonel toolkit), düz-metin ve UYAP-UDF export yolu netleştirilir. Toolkit yoksa graceful.
- **Bitti sayılır:** Her format toolkit yoksa structured error; disclaimer her formatta korunuyor.

---

## FAZ 4 — Kaynak Genişleme & Dayanıklılık (M-16 → M-19)

Amaç: kaynak katmanını çoğaltmak ve ağ dayanıklılığı eklemek.

### M-16 — KİK Adapter Aktivasyonu (Araştırma)
- KİK'in 401 auth akışını araştır; token/oturum mekanizmasını **opsiyonel ve config'li** ekle. Token yoksa `unavailable` kalır (mevcut davranış korunur).
- **Bitti sayılır:** Auth akışı opsiyonel; tokensiz davranış değişmedi; canlı çağrı testte yok.

### M-17 — Source Health Monitoring & Circuit Breaker
- Per-source başarı/hata sayacı, ardışık hata eşiğinde geçici devre-kesme, otomatik recovery. (ROADMAP "Future" maddesi.)
- **Bitti sayılır:** Circuit breaker durum-makinesi testli; açık devrede graceful error; recovery testli.

### M-18 — Retry & Rate-Limit Politikaları
- Configurable exponential backoff, opsiyonel rate limit (default kapalı — tek-kullanıcı varsayımı korunur). Canlı smoke için kullanılır.
- **Bitti sayılır:** Backoff deterministik testlenebilir (zaman mock); default davranış değişmedi.

### M-19 — Capability-Based Tool Routing
- MCP'de yetenek-tabanlı otomatik kaynak seçimi: "full_text gerektiren" sorgular yalnızca destekleyen kaynaklara yönlenir. (ROADMAP "Future" maddesi.)
- **Bitti sayılır:** Routing capability matrisinden deterministik; yanlış-yönlendirme testle dışlanmış.

---

## FAZ 5 — Paketleme, Dağıtım & v2.0 (M-20 → M-23)

### M-20 — Packaging & Distribution
- `pyproject.toml` hijyeni, entry points doğrulama, `pipx`/`uvx` kurulum talimatı, opsiyonel ekstralar (`[udf]`, `[dev]`).
- **Bitti sayılır:** Temiz ortamda `pip install .` + `emsal-mcp version` çalışıyor (CI/script ile doğrulanır).

### M-21 — CI Pipeline Tanımı
- GitHub Actions (veya yerel eşdeğeri) workflow: lint + test + smoke matrix. **Kullanıcı onayıyla** push.
- **Bitti sayılır:** Workflow dosyası lint+test+smoke koşuyor; yerel `act`/dry-run ile doğrulandı.

### M-22 — MCP Server Sertleştirme
- Tüm 54 aracın input şema validasyonu, hata yüzeyi standardizasyonu, opsiyonel concurrency guard, server-level smoke test.
- **Bitti sayılır:** Her araç geçersiz girdide structured error; server smoke testli.

### M-23 — v2.0.0 Mimari Gözden Geçirme
- Birikmiş teknik borcu konsolide et; modül sınırlarını netleştir; gerekirse iç API'leri (public yüzeyi koruyarak) yeniden düzenle; v2 readiness gate.
- **Bitti sayılır:** Tüm faz milestone'ları tamam; v2 readiness yeşil; major bump kullanıcı onayıyla.

---

## Yürütme Sırası & Bağımlılıklar

```
FAZ 1 (M-01..M-05)  → v1.0.0      [ÖNCE BU; düşük risk, loop ısınması]
FAZ 2 (M-06..M-10)  → veri/arama
FAZ 3 (M-11..M-15)  → dilekçe     [controller-ağırlıklı, en hassas]
FAZ 4 (M-16..M-19)  → kaynaklar
FAZ 5 (M-20..M-23)  → v2.0.0
FAZ 6 (M-24)        → dense embedding (fastembed)  → v2.1.0
FAZ 7 (M-25..M-28)  → arama/bilgi kalitesi  [M-24'e dayanır]
FAZ 8 (M-29..M-32)  → performans/ölçeklenebilirlik
FAZ 9 (M-33..M-36)  → erişim/entegrasyon
FAZ 10 (M-37..M-40) → gizlilik/üretim olgunluğu  → v3.0.0
```

- Fazlar sıralı; faz içi milestone'lar çoğunlukla sıralı (M-08 M-06/M-07'ye dayanır).
- Her milestone tek commit (veya küçük commit serisi) — **commit kullanıcı onayı ister**, loop otomatik push etmez.
- Orchestrator her milestone başında bu dosyayı tekrar okur, biten milestone'u `[x]` işaretler (additive edit).

---

## FAZ 6 — Dense Embedding Semantic Search (M-24)

Amaç: local-yargi'nin transformer-tabanlı anlamsal aramasının Python eşdeğerini Emsal'e getirmek. local-yargi `Xenova/all-MiniLM-L6-v2`'yi ONNX ile çalıştırıyordu; Python'da **fastembed** (ONNX runtime, torch'suz) ile aynı modeli kullanacağız. **Core sıfır-ağır-bağımlılık değişmezi korunur**: fastembed yalnızca opsiyonel `[embeddings]` extra'sından gelir; kurulu değilse sistem mevcut TF-IDF davranışına birebir döner.

### M-24 — fastembed Dense Embedding Provider + Hybrid v3

> **Önce bağlamı oku:** Referans implementasyon `C:\Users\Sozer\local-yargi\src\semantic\` altındadır — özellikle `transformersEmbeddingProvider.ts`, `providerFactory.ts`, `embeddingProvider.ts` (cosine), `vectorStore.ts`, `semanticSearch.ts`. Provider pattern + ayrı vektör store + env ile seçim + deterministik fake-provider testleri buradan model alınacak. Emsal tarafında dokunulacak dosya: `src/emsal_mcp/semantic.py` (mevcut TF-IDF `search_vectors` mantığı), `src/emsal_mcp/config.py`, `src/emsal_mcp/cli.py`, `src/emsal_mcp/server.py`, `pyproject.toml`.

- **Görevler (sırayla, her biri ayrı doğrulama geçidinden geçer):**

  1. **Provider soyutlaması — `src/emsal_mcp/embeddings.py` (yeni modül):**
     - Bir `EmbeddingProvider` protokolü/ABC tanımla: `id: str`, `dim: int`, `embed_texts(texts: list[str]) -> list[list[float]]`, `embed_query(text: str) -> list[float]`.
     - `LocalHashProvider` (id=`local-hash-v1`, dim=128): deterministik, **indirme/ağ yok**, saf stdlib (hash → sözde-rastgele yoğun vektör, L2-normalize). local-yargi'deki `localEmbeddingProvider.ts` muadili. **Core'da kalır, testlerin default'u budur.**
     - `FastEmbedProvider` (id=`fastembed-minilm-l6-v2`, dim=384, model `sentence-transformers/all-MiniLM-L6-v2`): fastembed'i **lazy import** et (fonksiyon içinde `import fastembed`). Kurulu değilse `build_error("EMBEDDING_BACKEND_UNAVAILABLE", ...)` döndür — exception fırlatma (graceful degradation değişmezi). Model cache dizini config'ten (`EMSAL_EMBEDDING_CACHE_DIR`, default `./data/models/fastembed`).
     - `get_embedding_provider(provider: str | None) -> EmbeddingProvider` factory: arg > env (`EMSAL_EMBEDDING_PROVIDER`) > default. Geçersiz id → `build_error`. local-yargi `providerFactory.ts` ile aynı önceliklendirme.
     - Metin normalizasyonu: whitespace daralt, max ~8000 char (local-yargi `MAX_TEXT_CHARS`), batch boyutu config'li (default 16).

  2. **Config genişlet — `config.py`:** `embedding_provider` (default `local-hash-v1`), `embedding_cache_dir`, `embedding_batch_size`, ve hybrid ağırlıkları `hybrid_w_bm25`, `hybrid_w_tfidf`, `hybrid_w_dense` (default'lar dense=0.0 olacak şekilde ki kurulum yoksa eski davranış korunsun). Tümü env-override'lı, mevcut `EmsalConfig` desenine uygun.

  3. **Dense vektör store — `semantic.py`:** Mevcut `search_vectors` (TF-IDF) tablosuna **DOKUNMA**. Paralel yeni tablo:
     ```sql
     CREATE TABLE IF NOT EXISTS embedding_vectors (
       document_id TEXT, source TEXT, provider_id TEXT, dim INTEGER,
       vector BLOB, norm REAL DEFAULT 0.0,
       PRIMARY KEY (document_id, source, provider_id)
     );
     ```
     Vektörü `array`/`struct` ile float32 BLOB olarak sakla (JSON değil; yoğun vektör için kompakt). `provider_id` PK'da çünkü farklı provider'lar farklı boyutta — local-yargi notu: "farklı provider için ayrı index". L2-norm precompute et (TF-IDF'teki `norm` deseni gibi).

  4. **Index + arama fonksiyonları — `semantic.py` (additive):**
     - `build_embedding_index(cache=None, provider=None, force_rebuild=False)`: cache'teki belgeleri batch'le embed et, `embedding_vectors`'a yaz. İdempotent (`INSERT OR REPLACE`). Provider unavailable → `build_error`, çökme yok.
     - `embedding_search(query, limit=10, provider=None, cache=None, filters...)`: sorguyu embed et, dense cosine ile sırala. Provider yoksa graceful `build_error` (öneri: `build_semantic_index` / TF-IDF kullan).
     - `get_embedding_index_status()`: provider, vektör sayısı, boyut, eksik-belge sayısı.

  5. **Hybrid v3 — `hybrid_search()` genişlet:** Üçüncü sinyal ekle: `final = w_bm25·BM25norm + w_tfidf·cosine_tfidf + w_dense·cosine_dense`. Ağırlıklar config'ten; **dense provider unavailable veya w_dense=0 ise mevcut iki-sinyal davranışı BİREBİR korunur** (regresyon testi ile kanıtla). Her üç skor normalize edilip birleştirilir; `method` alanı kullanılan sinyalleri raporlar.

  6. **CLI — `cli.py`:** `emsal-mcp semantic embed-index [--provider] [--force-rebuild] [--json]`, `emsal-mcp semantic embed-search <query> [--provider] [--limit] [--json]`, `emsal-mcp semantic providers [--json]` (mevcut/seçili provider listesi — local-yargi `getEmbeddingProviders` muadili). `hybrid` komutuna `--w-dense` opsiyonu.

  7. **MCP — `server.py`:** `build_embedding_index`, `embedding_search`, `embedding_index_status`, `list_embedding_providers` araçları. Mevcut `validate_tool_input` deseniyle input validasyonu.

  8. **Packaging — `pyproject.toml`:** `[project.optional-dependencies]` altına `embeddings = ["fastembed>=0.4"]` ekle. `INSTALL.md`'ye `pip install ".[embeddings]"` satırı + ilk kullanımda model indirme notu.

  9. **Testler — `tests/test_embeddings.py` (yeni):** TÜM testler `LocalHashProvider` veya enjekte edilen **fake provider** ile çalışır — **fastembed indirmesi YOK, ağ YOK** (6. değişmez). Kapsam: provider factory önceliklendirme, geçersiz id → build_error, fastembed yokken graceful build_error, dense index idempotency, embedding_search sıralaması, hybrid v3 ağırlık birleştirme, **w_dense=0 iken eski hybrid sonuçlarının birebir aynı olduğu regresyon testi**, BLOB round-trip doğruluğu.

- **Bitti sayılır (Definition of Done):**
  - `embeddings.py` mevcut; `LocalHashProvider` core'da, `FastEmbedProvider` lazy/opsiyonel.
  - fastembed **kurulu olmadan** tüm test paketi geçer; mevcut 1174 testte regresyon yok.
  - `w_dense=0` veya provider yokken hybrid sonuçları v2 ile birebir aynı (regresyon testi yeşil).
  - Yeni CLI + MCP araçları çalışır; provider unavailable durumunda structured `build_error` döner (exception yok).
  - `pyproject.toml`'da `[embeddings]` extra var; `INSTALL.md` güncel.
  - Zorunlu DOĞRULAMA GEÇİDİ yeşil (`ruff`, `pytest`, server import, release readiness).
  - 6 ihlal-edilemez değişmezin tamamı korunur (özellikle: core'da ağır bağımlılık yok, testte ağ yok, graceful degradation).
- **Worker dağılımı:**
  - `controller` → `embeddings.py` provider soyutlaması ve `embedding_vectors` şema/BLOB tasarımı, hybrid v3 ağırlık birleştirme mantığı, w_dense=0 regresyon garantisi.
  - `mimo-worker` / `explore` → local-yargi referans dosyalarını okuma/özetleme, CLI/MCP wiring, test yazımı, `INSTALL.md`/pyproject düzenleme.
- **Not:** Commit kullanıcı onayı ister; loop otomatik push etmez. Bu milestone tek başına v2.1.0 minor bump'ı hak eder (kullanıcı onayıyla).

---

---

## FAZ 7 — Arama & Bilgi Kalitesi (M-25 → M-28)

Amaç: M-24 dense embedding'in üstüne bilgi-getirme kalitesini üretim seviyesine taşımak. **M-24'e dayanır.**

### M-25 — Cross-Encoder Reranking
- **Boşluk:** Hybrid arama aday sıralar ama ilk-K sonucu yeniden-sıralayan (rerank) bir katman yok; gerçek alaka sırası zayıf kalabilir.
- **Görevler:** Opsiyonel cross-encoder reranker (`[embeddings]` extra'sından, fastembed rerank modeli veya benzeri, lazy import). `rerank_results(query, candidates, top_k)` — top-N hybrid adayını yeniden puanlar. Provider yoksa graceful passthrough (rerank atlanır, orijinal sıra korunur). CLI `--rerank` flag'i, MCP araç parametresi.
- **Bitti sayılır:** Reranker opsiyonel; kurulu değilken sonuçlar M-24 hybrid ile birebir (regresyon testi); rerank açıkken deterministik sıra; ağsız test (fake reranker).
- **Worker:** `controller` (rerank entegrasyon noktası), `mimo-worker` (wiring/test).

### M-26 — Incremental Index (Artımlı İndeksleme)
- **Boşluk:** `build_semantic_index` / `build_embedding_index` full-rebuild ağırlıklı; her yeni belgede tüm korpus yeniden işleniyor.
- **Görevler:** Değişiklik-takibi (`content_hash` + `indexed_at` karşılaştırması) ile sadece yeni/değişen belgeleri indeksle. `update_indexes(since=None)` hem TF-IDF hem dense store için. Yetim vektör temizliği M-06 `cleanup_orphans` ile entegre. IDF yeniden-hesaplama stratejisi (artımlı yaklaşık vs periyodik tam).
- **Bitti sayılır:** Artımlı güncelleme deterministik; full-rebuild ile aynı indeks durumunu üretir (eşdeğerlik testi); büyük korpusta tekrar-iş yapmaz.
- **Worker:** `controller` (IDF/tutarlılık stratejisi), `mimo-worker`.

### M-27 — PDF/Scanned İçerik Çıkarımı
- **Boşluk:** `pdf_only` belgeler `draft_usable=False` ile dışlanıyor; içerikleri hiç kullanılamıyor. Raporda PDF/OCR yolu yok.
- **Görevler:** Opsiyonel `[ocr]` extra (ör. `pypdf` metin-katmanı çıkarımı + opsiyonel OCR). Metin-katmanı olan PDF'lerden güvenli çıkarım → `pdf_only` yerine `full_text` (citation_check tekrar koşar). OCR yalnızca explicit opt-in (kalite belirsizliği → `metadata_confidence=low` + warning). **Uydurma yok:** çıkarım başarısız → değişmez `pdf_only`.
- **Bitti sayılır:** Metin-katmanlı PDF round-trip testli; OCR opt-in ve güven-düşük işaretli; çıkarım başarısızlığında belge statüsü korunur; toolkit yoksa graceful.
- **Worker:** `controller` (citation-safety statü geçişleri), `mimo-worker`.

### M-28 — Fuzzy Deduplication v2
- **Boşluk:** M-09 dedup salt-katı (court+esas+karar tam eşleşme); OCR/format farkı olan kopyaları kaçırır.
- **Görevler:** M-24 embedding'i kullanarak yakın-kopya tespiti (yüksek cosine + tarih yakınlığı). **False-merge koruması katı kalır:** embedding-benzerliği yalnızca *aday* önerir, otomatik merge yapmaz; eşik üstü adaylar `suspected_duplicate` olarak işaretlenir, merge kullanıcı/explicit onayı ister. M-09'un deterministik kanonik seçimi korunur.
- **Bitti sayılır:** Fuzzy aday tespiti testli; otomatik-merge YAPMADIĞI testle kanıtlı; M-09 katı-dedup davranışı bozulmaz.
- **Worker:** `controller` (false-merge güvenliği), `mimo-worker`.

---

## FAZ 8 — Performans & Ölçeklenebilirlik (M-29 → M-32)

Amaç: local-yargi'nin sahip olup Emsal'de eksik olan performans/dayanıklılık olgunluğunu kapatmak (concurrency, throttle, calibrate, benchmark).

### M-29 — Async Concurrency & Connection Pooling
- **Boşluk:** Kaynak çağrıları büyük ölçüde seri; çok-belge çekiminde paralellik ve bağlantı havuzu yok.
- **Görevler:** `research_topic` / toplu fetch'lerde sınırlı paralellik (semaphore ile, config'li `max_concurrency`). HTTP connection pooling/reuse. M-17 circuit breaker + M-18 retry ile uyumlu. Default tek-kullanıcı varsayımını bozmayan ölçülü eşzamanlılık.
- **Bitti sayılır:** Paralel fetch deterministik testlenebilir (mock); circuit/retry ile etkileşim testli; default davranış muhafazakâr.
- **Worker:** `controller` (concurrency tasarımı), `mimo-worker`.

### M-30 — Adaptive Throttle & Calibrate (local-yargi paritesi)
- **Boşluk:** local-yargi'de olan `calibrate` + adaptive throttle Emsal'de yok.
- **Görevler:** Kaynak başına gözlemlenen gecikme/hata oranına göre adaptif rate ayarı (M-18 üstüne). `emsal-mcp calibrate <source>` — güvenli istek hızını ölçer, config önerir. Tümü opt-in; default kapalı.
- **Bitti sayılır:** Calibrate komutu JSON öneri üretir; adaptif throttle mock-zamanla testli; default davranış değişmez.
- **Worker:** `controller`, `mimo-worker`.

### M-31 — Benchmark & Performans Pasaportu
- **Boşluk:** Arama/indeks/dense performansını ölçen, regresyon yakalayan bir harness yok.
- **Görevler:** `benchmark/` altında deterministik mikro-benchmark suite (indeks kurma, hybrid arama, dense arama gecikmeleri — sentetik sabit korpus). `emsal-mcp benchmark run --json` → metrik raporu + baseline karşılaştırma. CI'da opsiyonel (eşik aşımı uyarı).
- **Bitti sayılır:** Benchmark deterministik korpusla tekrarlanabilir; baseline dosyası; CI entegrasyonu opsiyonel.
- **Worker:** `mimo-worker`.

### M-32 — Embedding Cache & Lazy Materialization
- **Boşluk:** Dense embedding hesabı pahalı; belge değişmediyse yeniden-embed gereksiz.
- **Görevler:** `content_hash` anahtarlı embedding cache (M-26 ile entegre); aynı içerik bir kez embed edilir. Model/provider değişiminde otomatik invalidasyon (provider_id anahtarda). Disk kullanımı raporu.
- **Bitti sayılır:** Aynı içerik tekrar-embed edilmez (testle kanıtlı); provider değişince invalidasyon doğru; raporlama mevcut.
- **Worker:** `controller`, `mimo-worker`.

---

## FAZ 9 — Erişim & Entegrasyon (M-33 → M-36)

Amaç: aracı CLI+MCP dışına açmak, çok-makine ve otomasyon senaryolarını desteklemek, kaynak eklemeyi kolaylaştırmak.

### M-33 — HTTP/REST API Sunucu (Opsiyonel)
- **Boşluk:** Yalnızca CLI + MCP (stdio) arayüzü var; HTTP üzerinden erişim yok.
- **Görevler:** Opsiyonel `[api]` extra ile hafif HTTP sunucu (stdlib `http.server` veya minimal ASGI; ağır framework eklemeden). Mevcut fonksiyonları JSON endpoint'lere map et (read-only öncelik). Auth token opsiyonel (config). MCP kontratlarını yeniden-kullanır, mantığı çoğaltmaz.
- **Bitti sayılır:** Sunucu opsiyonel; endpoint'ler mevcut fonksiyonları çağırır; auth opt-in; testler ağsız (in-process client).
- **Worker:** `controller` (arayüz sınırı), `mimo-worker`.

### M-34 — Çok-Makine Cache Senkronizasyonu
- **Boşluk:** ROADMAP "Future" maddesi; cache tek-makine. Birden çok cihaz arası senkron yok.
- **Görevler:** Export/import üstüne (M-06) çakışma-çözümlü merge: `content_hash` + `retrieved_at` ile en-yeni kazanır; çift kayıt M-09 dedup'a yönlenir. `emsal-mcp cache sync <other_db>`. **Veri kaybı yok** (merge additive).
- **Bitti sayılır:** Sync idempotent ve çakışma-güvenli (test); veri kaybı yok; dedup ile uyumlu.
- **Worker:** `controller`, `mimo-worker`.

### M-35 — Kaynak Adapter SDK & Plugin Arayüzü
- **Boşluk:** Yeni kaynak eklemek core'a dokunmayı gerektiriyor; net bir genişletme sözleşmesi yok.
- **Görevler:** `SourceClient` base'i resmi bir genişletme kontratına dönüştür (dokümante: zorunlu metotlar, capability bildirimi, smoke). Entry-point tabanlı plugin keşfi (3. parti adapter `pip install` ile eklenebilir). `docs/ADAPTER_SDK.md` + örnek şablon adapter.
- **Bitti sayılır:** Örnek 3.parti adapter registry'e plugin olarak katılabiliyor (test); SDK dokümanı eksiksiz; mevcut 10 adapter bozulmaz.
- **Worker:** `controller` (kontrat tasarımı), `mimo-worker` (örnek + doküman).

### M-36 — Zamanlanmış Araştırma & Watchlist/Alert
- **Boşluk:** Tek-seferlik araştırma var; izleme/yeni-karar bildirimi yok.
- **Görevler:** `research_topic`'i kaydedilmiş "watch" tanımına dönüştür; `emsal-mcp watch add/list/run`. `run` → refresh + yeni/değişen kararları diff'le raporla (M-05 refresh deseni). Bildirim soyut (rapor/dosya; harici servis bağlamaz). Cron'u kullanıcı/OpenCode scheduler yönetir, araç sadece çalıştırılabilir komut sunar.
- **Bitti sayılır:** Watch tanımı kalıcı; `run` yeni-karar diff raporu üretir; deterministik test (fake source).
- **Worker:** `controller`, `mimo-worker`.

---

## FAZ 10 — Güven, Gizlilik & Üretim Olgunluğu (M-37 → M-40)

Amaç: hukuk verisiyle çalışan bir araçta kritik olan gizlilik, doğrulanabilirlik ve sürdürülebilirliği üretim seviyesine taşımak ve v3.0.0'a hazırlanmak.

### M-37 — PII Redaction & Gizlilik Denetimi
- **Boşluk:** `samples-private` gibi hassas veri var; çıktılarda PII maskeleme ve gizlilik denetimi yok. M-04 "veri müvekkil olmasın" uyarısı vardı ama enforcement yok.
- **Görevler:** Opsiyonel PII redaction (TC kimlik no, telefon, e-posta, ad-soyad pattern'leri) export/draft çıktılarında; default uyarı, opt-in maskeleme. `emsal-mcp privacy audit <path>` — bir bundle/draft'ta olası PII tarar, rapor verir. **Uydurma yok:** maskeleme verbatim metni değiştirmez, kopyada uygular.
- **Bitti sayılır:** PII tarayıcı testli (TR pattern'leri); maskeleme orijinali bozmaz (kopyada); audit JSON rapor; default davranış değişmez.
- **Worker:** `controller` (gizlilik kuralları), `mimo-worker`.

### M-38 — Golden Corpus & Snapshot Testleri
- **Boşluk:** Testler mock-ağırlıklı; gerçek-şekilli belge örnekleri üzerinde uçtan-uca regresyon yakalayan golden/snapshot testi yok.
- **Görevler:** `tests/fixtures/` altında anonimleştirilmiş sentetik belge korpusu (gerçek müvekkil verisi DEĞİL). Citation extraction, petition pack, hybrid arama için golden çıktı snapshot'ları. Snapshot diff CI'da regresyon yakalar.
- **Bitti sayılır:** Golden korpus sentetik/anonim; snapshot testleri yeşil; CI'da regresyon yakalıyor; gerçek hassas veri içermiyor (denetimli).
- **Worker:** `mimo-worker` (fixture/snapshot), `controller` (anonimlik review).

### M-39 — Atıf Grafiği Görselleştirme & Export
- **Boşluk:** M-08 citation graph veriyi tutuyor ama dışa-aktarım/görselleştirme yok.
- **Görevler:** Grafiği standart formatlara export (DOT/Graphviz, JSON-graph, opsiyonel Mermaid). `emsal-mcp graph export --format dot/json/mermaid`. Belge merkezli alt-graf çıkarma (n-hop). Salt-veri; render harici araç.
- **Bitti sayılır:** Export formatları deterministik; alt-graf çıkarımı testli; geçersiz format → build_error.
- **Worker:** `mimo-worker`.

### M-40 — Dokümantasyon Sitesi & v3.0.0 Review
- **Boşluk:** Dokümanlar dağınık markdown; tek bir gezilebilir doküman yüzeyi yok.
- **Görevler:** `docs/` içeriğini tutarlı bir yapıya topla (statik site üretimi opsiyonel; ağır bağımlılık eklemeden, ör. salt-markdown index). Tüm CLI/MCP/kontrat dokümanlarını M-24→M-39 ile hizala. Birikmiş teknik borç konsolidasyonu, modül sınırı gözden geçirme. v3 readiness gate.
- **Bitti sayılır:** Tüm yeni milestone'lar dokümante; doküman-araç tutarlılığı testli/denetli; v3 readiness yeşil; major bump kullanıcı onayıyla.
- **Worker:** `controller` (mimari review), `mimo-worker` (doküman).

---

## İlerleme Takibi

| Faz | Milestone | Durum |
|---|---|---|
| 1 | M-01 Doküman senkron | [x] |
| 1 | M-02 Test/coverage | [x] |
| 1 | M-03 Kontrat tutarlılık | [x] |
| 1 | M-04 Config/observability | [x] |
| 1 | M-05 v1.0.0 release | [x] |
| 2 | M-06 Cache bakım | [x] |
| 2 | M-07 Semantic v2 | [x] |
| 2 | M-08 Citation graph | [x] |
| 2 | M-09 Dedup/merge | [x] |
| 2 | M-10 Arama analitik | [x] |
| 3 | M-11 Template library | [x] |
| 3 | M-12 Argument builder | [x] |
| 3 | M-13 Multi-issue pack | [x] |
| 3 | M-14 Draft diff | [x] |
| 3 | M-15 Export formatları | [x] |
| 4 | M-16 KİK adapter | [x] |
| 4 | M-17 Health/circuit breaker | [x] |
| 4 | M-18 Retry/rate-limit | [x] |
| 4 | M-19 Capability routing | [x] |
| 5 | M-20 Packaging | [x] |
| 5 | M-21 CI pipeline | [x] |
| 5 | M-22 MCP sertleştirme | [x] |
| 5 | M-23 v2.0.0 review | [x] |
| 6 | M-24 Dense embedding (fastembed) | [x] |
| 7 | M-25 Cross-encoder reranking | [x] |
| 7 | M-26 Incremental index | [x] |
| 7 | M-27 PDF/OCR çıkarım | [x] |
| 7 | M-28 Fuzzy dedup v2 | [x] |
| 8 | M-29 Async concurrency/pooling | [x] |
| 8 | M-30 Adaptive throttle/calibrate | [x] |
| 8 | M-31 Benchmark suite | [x] |
| 8 | M-32 Embedding cache | [x] |
| 9 | M-33 HTTP/REST API | [x] |
| 9 | M-34 Çok-makine cache sync | [x] |
| 9 | M-35 Adapter SDK/plugin | [x] |
| 9 | M-36 Watchlist/alert | [x] |
| 10 | M-37 PII redaction/privacy | [x] |
| 10 | M-38 Golden corpus testleri | [x] |
| 10 | M-39 Atıf grafiği export | [x] |
| 10 | M-40 Docs sitesi + v3.0.0 | [x] |
