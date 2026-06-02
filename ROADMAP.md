# ROADMAP.md — Emsal-mcp

**Mevcut sürüm:** v3.1.0 · **Oluşturulma:** 2026-06-02
**Durum:** M-01…M-68 tamamlandı (1526 test geçiyor, mypy temiz, ruff 0 hata, CI aktif). Yeni milestone yok.

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

Tüm aktif milestone'lar tamamlandı (M-01…M-68). Yeni iş için CHANGELOG.md'ye bakın.
