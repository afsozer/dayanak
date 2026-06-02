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

## FAZ B — Dış Bağımlılık Sağlamlığı (orta öncelik)

## FAZ C — Tip Güvenliği (orta öncelik)

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

`M-57 → M-58 → M-59` (hijyen, hızlı kazanım) → (gerekirse) `M-63 → M-64`.
