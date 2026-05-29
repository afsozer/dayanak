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
```

- Fazlar sıralı; faz içi milestone'lar çoğunlukla sıralı (M-08 M-06/M-07'ye dayanır).
- Her milestone tek commit (veya küçük commit serisi) — **commit kullanıcı onayı ister**, loop otomatik push etmez.
- Orchestrator her milestone başında bu dosyayı tekrar okur, biten milestone'u `[x]` işaretler (additive edit).

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
| 4 | M-16 KİK adapter | [ ] |
| 4 | M-17 Health/circuit breaker | [ ] |
| 4 | M-18 Retry/rate-limit | [ ] |
| 4 | M-19 Capability routing | [ ] |
| 5 | M-20 Packaging | [ ] |
| 5 | M-21 CI pipeline | [ ] |
| 5 | M-22 MCP sertleştirme | [ ] |
| 5 | M-23 v2.0.0 review | [ ] |
