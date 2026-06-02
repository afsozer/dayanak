# ROADMAP.md — Emsal-mcp

**Mevcut sürüm:** v3.1.0 · **Oluşturulma:** 2026-06-02
**Durum:** M-01…M-64 tamamlandı (1526 test geçiyor, mypy temiz, CI aktif). 2026-06-02
canlı checkup'ında 4 açık bulgu tespit edildi → **FAZ E (M-65…M-68)** aşağıda.

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

## FAZ E — Canlı Checkup Bulguları (2026-06-02)

> Adalet Bakanlığı API'si geri geldikten sonra yapılan canlı testte tespit edildi.
> M-60..M-64 tamamlandıktan **sonra** açıldı. Sıra: M-65 → M-66 → M-67 → M-68.

### M-65 — İzole `get`/`citation-check` provenance açığı
**Sorun:** `getDocumentContent` yalnızca içerik döndürüyor (esas/karar/tarih yok).
`research_topic` akışı M-bugfix (`merge_search_metadata`) ile çözüldü, **ama** tek başına
`get <source> <id>` ve `citation-check <source> <id>` çağrılarında `sr` context'i yok →
provenance boş → tam metin varken bile `quoteUsable=false`.
- `get`/`citation-check` yolunda cache fallback ekle: daha önce `search`/`store_document`
  ile kaydedilmiş SearchResult/Document'tan provenance'ı `merge_search_metadata` ile doldur
  (`cache.get_document(id, source)` zaten mevcut).
- Yine uydurma yok — yalnızca daha önce yapısal API'den gelip cache'lenmiş metadata kullanılır.
- **Bitti sayılır:** `search` sonrası `citation-check <source> <id>` çağrısı, tam metinli
  belge için `quoteUsable=true` döndürür; cache'te yoksa eski davranış (false + sebep) korunur.

### M-66 — Tarih makuliyet doğrulaması (data-quality)
**Sorun:** Canlı testte `decision_date="21.09.6006"` gibi bozuk tarihler kaynaktan geldiği
gibi geçiyor; model hiç doğrulamıyor.
- `finalize_document`/model katmanında makuliyet kontrolü: yılı `[1920, içinde bulunulan yıl+1]`
  dışındaki tarihleri **silme/uydurma değil**, `warnings`'e işaretle ve
  `metadata_confidence`'ı düşür.
- **Bitti sayılır:** İmkânsız tarihli belge `warnings` içerir; geçerli tarihler etkilenmez; testler hermetik.

### M-67 — Watch kurtarma sinyali
**Sorun:** `run_watch` diff'i yalnızca yeni belge sayısını veriyor; cm-service geri gelip
**alıntılanabilir** (tam metin) belge oluştuğunda ayrı bir sinyal yok.
- Diff raporuna `citation_safe_count` ve önceki çalıştırmaya göre `citation_safe_delta` ekle;
  `0 → N` geçişini "kaynak içeriği geri geldi" olarak işaretle.
- **Bitti sayılır:** `watch run` çıktısı citation-safe sayısını ve değişimini raporlar.

### M-68 — Lint borcu kararı (advisory docstrings)
**Sorun:** `ruff check .` 262 D100/D101/D103 uyarısı veriyor (M-42'de advisory bırakılmıştı);
gerçek geçit yeşil ama "0 hata" iddiasıyla tutarsız.
- Ya bu kuralları kademeli kapat (modül/sınıf docstring ekle) ya da `pyproject.toml`'da
  resmî olarak `extend-ignore`'a al; ROADMAP geçit metnini gerçekle hizala.
- **Bitti sayılır:** `ruff check .` 0 hata **veya** geçit metni advisory durumu açıkça belirtir.
