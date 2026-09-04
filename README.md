# Emsal-mcp

> **v5.0.0** — 14 core + 30 extended MCP tools (44 total) · 142 CLI commands · 68 test files · 42 source modules
>
> [![CI](https://github.com/brachindul/emsal-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/brachindul/emsal-mcp/actions/workflows/ci.yml)

Resmî ve kamuya açık Türk hukuk kaynaklarında (emsal kararlar ve mevzuat) citation-safe arama, araştırma ve belge hazırlık için MCP sunucusu.

## Kırmızı çizgiler

- Karar, metadata, tarih, esas/karar no, daire, atıf veya kanun maddesi uydurulmaz.
- `full_text` / `html_markdown` içeriği olmayan belgeler quote/draft için kullanılmaz.
- `quoteUsable` ve `draftUsable` sadece tam metin/HTML markdown varsa `true` olur.
- Rate-limit bilinçli olarak muhafazakâr değildir; tek kullanıcı/tek bilgisayar hedeflenmiştir.

## Kaynaklar

Registry: Bedesten/Yargıtay, AYM, Danıştay, Uyuşmazlık, Rekabet, Sayıştay, GİB, Mevzuat, Resmî Gazete, KVKK.

## Kurulum

```powershell
# Windows
cd <repo-dizini>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,mcp]"

# macOS / Linux
cd <repo-dizini>
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp]"

emsal-mcp version
emsal-mcp release command-center --json
```

## CLI örnekleri

```powershell
emsal-mcp sources
emsal-mcp search bedesten "muvazaa" --limit 5
emsal-mcp get bedesten DOCUMENT_ID
emsal-mcp smoke --offline
```

## MCP server

```powershell
emsal-mcp-server
```

## Korpus crawl + panel

Uzun soluklu korpus taraması (Bedesten'den yıl yıl karar indirme) bir master
script ile yürür, durumu tarayıcıdan izlenir.

```powershell
.\scripts\kur-otomatik-baslatma.ps1          # oturum açılışına ekler (yönetici gerekmez)
.\scripts\kur-otomatik-baslatma.ps1 -Durum   # ne çalışıyor?
.\scripts\kur-otomatik-baslatma.ps1 -Kaldir  # geri al
```

| Parça | Ne yapar |
|---|---|
| `crawl_master.ps1` | Yılları sırayla tarar. Tek örnek kilidi (mutex), `crawl_logs\crawl_state.json`'a checkpoint yazar — PC kapanırsa kaldığı **yıl ve sayfadan** devam eder. |
| `scripts\panel.py` | http://127.0.0.1:8799 — canlı crawl durumu, yıl hedefleri, kütüphane dağılımı, hız/tahmin. Ek bağımlılık yok. |
| Zamanlanmış görevler | `EmsalCrawlMaster` (oturum + 1 dk), `EmsalPanel` (oturum + 20 sn). |

Notlar:

- Rate limit `EMSAL_RATE_LIMIT_MAX=12`. Ölçüldü: 12'de 429 yok (~2.800 belge/saat),
  15'te 429 cooldown döngüsüne girip hız sıfırlanıyor.
- Panel, `cache.sqlite3` (21 GB) üzerinde yıl sayımı yapmaz — tek bir yıl sorgusu
  tam tablo taraması yüzünden ~60 sn sürüyor. Sayımlar `~/.emsal-mcp/panel_stats.sqlite3`
  içinde artımlı (yalnız yeni `rowid`'ler) tutulur, günde bir kez tam sayım yapılır.
- Yıl hedefleri Bedesten'in `total` alanından ölçülür (`crawl_logs\hedefler.json`),
  tahmin edilmez.

## Özellikler

| Modül | Sürüm | Araç Sayısı | Açıklama |
|-------|-------|-------------|----------|
| **Core** (search, get, capabilities, smoke) | v0.1–0.4 | 5 | Kaynak arama, belge erişimi, yetenek keşfi |
| **Cache v2** | v0.3 | 3 | Yerel arama, istatistikler, belge listeleme |
| **Research** | v0.5 | 3 | Konu araştırması, bundle yenileme, kalite paneli |
| **Citation** | v0.6 | 2 | Hukuk alıntı formatlama ve doğrulama |
| **Petition Pack** | v0.7–0.8 | 6 | Dilekçe paketi, denetim, anahat, kontrollü taslak |
| **UDF Toolkit** | v0.9 | 5 | UDF durumu, yazar kılavuzu, DOCX/UDF dönüşümü |
| **Legislation** | v0.10 | 8 | Mevzuat arama, madde analizi, ağaç yapısı, gerekçe |
| **Semantic Search** | v0.11 | 5 | FTS5 BM25 + TF-IDF cosine hibrit arama |
| **Chamber Profiling** | v0.12 | 4 | Daire analizi, profil, zaman çizelgesi, benzerlik |
| **Release Management** | v0.13 | 4 | Komuta merkezi, sürüm, v1 hazırlık, özet |

**Toplam:** 44 MCP tool (14 core + 30 extended) · 142 CLI komutu · 67 test dosyası

> Varsayılan profil `core` (14 araç). Geri kalanı `load_extended_tools` ile
> kategori kategori yüklenir. Bir core facade'ın zaten kapsadığı 33 eski araç
> M-110'da, atıf grafının 6 aracı M-111'de silindi — eşleme için
> `docs/MCP_CONTRACTS.md`.
