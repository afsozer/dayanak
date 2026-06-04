# ROADMAP.md — Emsal-mcp

**Mevcut sürüm:** v3.1.0 · **Oluşturulma:** 2026-06-02
**Durum:** M-01…M-68 tamamlandı (1526 test geçiyor, mypy temiz, ruff 0 hata, CI yeşil).
**Sıradaki ufuk:** v4.0 → v6.0 uzun vadeli yol haritası aşağıda (FAZ F…L, M-69+).
**Aktif sıradaki:** FAZ L — Karar Arama & Semantik Parite (M-92…M-96), YargiMCP-Pro kıyas bulguları.

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

## FAZ L — Karar Arama & Semantik Parite (v4.1) 🆕

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

- **M-95 — Gerçek embedding varsayılanı.** Şu an `embedding_search` varsayılanı `LocalHashProvider` (anlam taşımayan hash). [`embeddings.py`](src/emsal_mcp/embeddings.py) altyapısı (`embedding_vectors` tablosu, brute-force cosine, `build_embedding_index`) zaten yazılı. Yapılacak: `fastembed` (opsiyonel `embeddings` extra, zaten var) ile gerçek bir çok-dilli/Türkçe model (ör. `intfloat/multilingual-e5-small` veya BGE-m3) sağlayıcısı ekle; config ile seçilebilir yap; `fastembed` yoksa hash'e **graceful fallback** (çekirdek stdlib+sqlite3 değişmezi korunur). **Bitti sayılır:** `embeddings` extra kuruluyken gerçek embedding ile anlamsal arama çalışır; kurulu değilken eski davranış bozulmaz; eval (M-71) recall@k düşmez.

- **M-96 — Niş korpus reçetesi + eval.** [`crawl_full_text`](src/emsal_mcp/corpus_builder.py:16) ile konu-bazlı korpus inşa akışını dökümante et (`docs/COOKBOOK.md`'ye reçete) ve `eval/golden_queries.json`'a semantik-arama vakaları ekle; M-95 öncesi/sonrası recall@k + nDCG farkını ölç. **Bitti sayılır:** "niş korpus crawl → embed → semantik arama" reçetesi çalışır biçimde belgeli; eval gerçek embedding kazancını sayısal gösterir.

**Öncelik (FAZ L içi):** M-94 (sıfır efor, yüksek getiri) → M-92 + M-93 (altyapı zaten var) → M-95 → M-96. Ulusal korpus (eski "M-?") **kapsam dışı**.

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
