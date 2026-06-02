# ROADMAP.md — Emsal-mcp

**Mevcut sürüm:** v3.1.0 · **Oluşturulma:** 2026-06-02
**Durum:** Çekirdek olgun (1470 test geçiyor, citation-safety sağlam). Bu roadmap, kalan
sağlamlık/taşınabilirlik/doküman borçlarını kapatmaya odaklanır.

> **Tarihsel kayıt:** v0.1.0 → v3.1.0 arası tüm tamamlanmış milestone'lar (M-01…M-56)
> [CHANGELOG.md](CHANGELOG.md)'de ve git geçmişinde tutulur. Bu dosya yalnızca **ileriye
> dönük** çalışmayı içerir; tamamlanan iş buradan CHANGELOG'a taşınır ve burada tutulmaz.

---

## 0. Çalışma Sözleşmesi

Her milestone **bağımsız, test-geçitli ve additive**'dir. Bir milestone'a "bitti" demeden
önce aşağıdaki **doğrulama geçidi** yeşil olmalı:

```bash
python -m ruff check .                                 # 0 hata
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

## FAZ A — Doğruluk & Hijyen (yüksek öncelik, küçük efor)

### M-58 — README & sürüm tutarlılığı
**Sorun:** README başlığı "v1.0.0 · 10 source modules" diyor; gerçek v3.1.0, 36 modül.
Tool/CLI sayıları elle yazılmış ve geride kalmış.
- README başlığını gerçek sürüm/modül sayısıyla güncelle.
- Sayıları (MCP tool, CLI komutu, test dosyası) elle yazmak yerine `scripts/` altında bir
  üreteç ile README'ye gömülen bir bölümden doldur (CI'da drift kontrolü).
- **Bitti sayılır:** README'deki tüm sayılar koddan türetilir; sürüm pyproject ile eşleşir;
  drift testi suite'te.

### M-59 — Doküman konsolidasyonu
**Sorun:** Kök dizinde dağınık geçmiş dokümanlar birikmişti (temizlendi). Kalan referanslar
güncel tutulmalı.
- `docs/INDEX.md`'i sil(in)en dosyalara referans kalmayacak şekilde güncelle.
- Kök dizinde yalnızca: `README.md`, `CHANGELOG.md`, `INSTALL.md`, `ROADMAP.md`, `Makefile`.
  Geri kalan tüm açıklayıcı dokümanlar `docs/` altında.
- **Bitti sayılır:** `docs/INDEX.md` kırık link içermez; kök dizinde 4 .md dosyası kalır.

---

## FAZ B — Dış Bağımlılık Sağlamlığı (orta öncelik)

### M-60 — Adaptör yanıt-şeması doğrulaması
**Sorun:** Bedesten vb. resmî/sözleşmesiz endpoint'lere bağlı; `data.get(...)` zincirleme
fallback'leri şema değişimini sessizce yutuyor.
- Her adaptör için beklenen yanıt şeması (zorunlu alanlar) tanımla; eksikse yapısal
  `error` + `warnings` döndür, sessizce boş liste döndürme.
- Şema sürümü/etag benzeri bir "kaynak imzası" logla; beklenmeyen şekil saptanınca
  capability'yi runtime'da `partial`/`unavailable`'a düşür.
- **Bitti sayılır:** Bozuk/değişmiş yanıt simüle eden testler yapısal hata üretir; sessiz boş dönüş yok.

### M-61 — Kaynak sağlık izleme (smoke genişletme)
- `smoke` komutunu, her adaptör için son başarılı şema imzasını saklayıp karşılaştıracak
  şekilde genişlet; kaynak kırıldığında erken uyarı.
- **Bitti sayılır:** `emsal-mcp smoke` çıktısı kaynak-başı şema-sağlık durumu içerir.

---

## FAZ C — Tip Güvenliği (orta öncelik)

### M-62 — mypy sıkılaştırma
**Sorun:** `check_untyped_defs=false`, `warn_return_any=false` — 121 annotation var ama
enforce edilmiyor.
- Modül modül `check_untyped_defs=true`'ya geç (önce yaprak modüller: `safety`, `models`, `citation`).
- `warn_return_any=true` ve `disallow_untyped_defs` kademeli olarak aç.
- mypy'yi CI doğrulama geçidine ekle.
- **Bitti sayılır:** `python -m mypy src` temiz; geçit komutlarına mypy eklenir.

---

## FAZ D — Taşınabilirlik & Dağıtım (düşük öncelik, scope kararı)

> Not: Proje bilinçli olarak "tek kullanıcı/tek makine" hedefli. Bu faz yalnızca paylaşım/
> dağıtım hedefi netleşirse yapılır.

### M-63 — Yola-bağımsız kurulum
- README/INSTALL'daki literal `C:\Users\Sozer\...` yollarını `<repo>` placeholder'ı ve
  platform-bağımsız örneklerle değiştir.
- Kurulumu mevcut çalışma dizininden bağımsız hale getir; sabit kullanıcı yolu varsayımlarını kaldır.
- **Bitti sayılır:** Temiz bir makinede README adımları birebir çalışır.

### M-64 — CI iskeleti
- `.github/` altında ruff + pytest + mypy + import-smoke çalıştıran minimal workflow.
- **Bitti sayılır:** Push'ta geçit otomatik koşar; README'de durum rozeti.

---

## Öncelik Sırası

`M-57 → M-58 → M-59` (hijyen, hızlı kazanım) → `M-60 → M-61` (en yüksek teknik risk:
dış API kırılganlığı) → `M-62` → (gerekirse) `M-63 → M-64`.
