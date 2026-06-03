# ROADMAP.md — Emsal-mcp

**Mevcut sürüm:** v3.1.0 · **Oluşturulma:** 2026-06-02
**Durum:** M-01…M-68 tamamlandı (1526 test geçiyor, mypy temiz, ruff 0 hata, CI yeşil).
**Sıradaki ufuk:** v4.0 → v6.0 uzun vadeli yol haritası aşağıda (FAZ F…K, M-69+).

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

- **M-73 — KİK/EKAP canlı.** Şu an `unavailable` (401/token). Auth/token akışını çöz; çözülemezse
  resmî kısıtı dokümante et, placeholder davranışını koru.
- **M-74 — Yeni kaynaklar.** BAM (bölge adliye), Bölge İdare Mahkemeleri, İçtihatı Birleştirme
  kararları, Resmî Gazete, KVKK kararları — her biri capability matrisine açık durumla girer.
- **M-75 — Adaptör SDK 2.0.** Bildirimsel (declarative) adaptör tanımı, otomatik kontrat testleri,
  M-60/M-61 şema-drift uyarılarını kaynak-başı sağlık paneline bağla.
- **M-76 — Toplu derlem (corpus) oluşturucu.** Zamanlanmış artımlı tarama, ölçekli dedup,
  yerel derlem inşası — büyük analiz/eval için temel. Rate-limit'e saygılı, tek-kullanıcı dostu.

## FAZ H — Akıl Yürütme & Belge Üretimi (v5.0)

Hedef: getirmeden **anlama ve taslağa**. Tümü citation-safe sınırları içinde.

- **M-77 — Argüman madenciliği.** Karardan *holding* / *ratio decidendi* / uyuşmazlık konusu
  çıkarımı (metinden, işaretli; uydurma değil). Belirsizse `warnings` + düşük confidence.
- **M-78 — Çapraz referans çözücü.** Madde ↔ karar ↔ gerekçe bağlama; bir kararın atıf yaptığı
  mevzuatı ve onu izleyen içtihadı otomatik ilişkilendirme (M-72 atıf grafiği üzerine).
- **M-79 — Tutarlılık/çelişki denetleyici.** Bir dilekçede atfedilen otoriteler arası çelişki
  (örn. bozulmuş/değiştirilmiş içtihat) tespiti ve uyarı.
- **M-80 — Yapılandırılmış taslak üretimi.** Şablonlu dilekçe/mütalaa üretimi; her cümle bir
  alıntı-güvenli kaynağa bağlı, bağlanamayan ifade `[DOĞRULANMADI]` ile işaretli.

## FAZ I — Platform & Dağıtım (v5.5)

Hedef: "tek makine" tasarımını bozmadan, isteyene paylaşılabilir/dağıtılabilir hale getir.

- **M-81 — Paketleme & sürümleme.** PyPI yayını, sürümlenmiş release'ler, opsiyonel Docker imajı,
  `pipx` ile tek komut kurulum.
- **M-82 — HTTP/SSE MCP taşıması + REST sağlamlaştırma.** stdio dışında uzak transport; `api_server`
  için auth, rate-limit, sürüm uçları.
- **M-83 — Çok-kullanıcı/sunucu modu (opsiyonel).** Kullanıcı-başı cache izolasyonu, kimlik,
  kota. Varsayılan tek-kullanıcı modu değişmez; bu yalnızca opt-in profil.
- **M-84 — Gözlemlenebilirlik.** Yapısal log, metrikler, opsiyonel tracing; hata kataloğuyla
  (76 kod) entegre teşhis.

## FAZ J — Kullanıcı Deneyimi & Ekosistem (v6.0)

Hedef: CLI/MCP ötesinde erişilebilirlik.

- **M-85 — Web panosu.** Arama, belge görüntüleme, dilekçe paketi/taslak yönetimi için hafif yerel UI.
- **M-86 — Entegrasyon kılavuzları & örnek ajanlar.** Claude Desktop / IDE / Agent SDK için hazır
  reçeteler; "hukuk araştırma ajanı" referans örneği.
- **M-87 — Üçüncü-taraf kaynak eklenti ekosistemi.** SDK 2.0 üzerine harici adaptör paketleri
  (entry-point keşfi), topluluk katkısı için kontrat + örnek.
- **M-88 — İngilizce yüzey (i18n).** Mesaj kataloğu ve dokümanların TR/EN ikiliği; çekirdek
  hukuk verisi TR kalır.

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

- **M-89 — Gerçek MCP-protokol E2E testleri.** stdio üzerinden `initialize` → `tools/call`
  ile asıl sunucu yolunu test et (sadece fonksiyon-mock değil). En az birer happy-path:
  `search_decisions`, `get_document`, `hybrid_search`. Async dekoratör bug'ı tam burada
  yaşıyordu; bu test onu yakalardı. Canlı ağ yok — mock transport/sources_override.
- **M-90 — Hata-yolu invariant testleri.** "Kaynak hatası → exception değil yapısal sonuç"
  kuralını HER araçta zorla: 404/500/timeout/şema-bozuk senaryoları. Mevcut suite 404/500'ün
  *raise* etmesini doğru sayıyordu (yanlış varsayım); bu, graceful-degradation değişmezini
  test düzeyinde sabitler.
- **M-91 — Opt-in load/limit smoke.** Canlı (varsayılan kapalı) bir smoke: kısa bir burst
  atıp rate-limiter'ın 429'u önlediğini ve `Retry-After` cooldown'ının çalıştığını doğrular.
  Sunucu pencere davranışı değişirse erken uyarı.

**Öncelik:** M-89 → M-90 (ikisi düşük efor, yüksek koruma) → M-91. Bu üçü olmadan benzer
"entegrasyon yüzeyi" hataları yine kaçar.

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
