# Emsal-mcp

> **v1.0.0** — 11 core + 36 extended MCP tools (47 total) · 145 CLI commands · 76 test files · 47 source modules
>
> [![CI](https://github.com/brachindul/emsal-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/brachindul/emsal-mcp/actions/workflows/ci.yml)

Resmî ve kamuya açık Türk hukuk kaynaklarında (emsal kararlar ve mevzuat)
citation-safe arama, araştırma ve belge hazırlık için MCP sunucusu.

İki şekilde çalışır:

- **Yerel korpus** — 11,1 milyon karar ve güncel mevzuatın tamamı tek bir
  SQLite dosyasında; FTS5 tam metin + FAISS anlamsal arama. Ağ gerekmez.
- **Canlı kaynaklar** — Bedesten/Yargıtay, AYM, Danıştay, Uyuşmazlık, Rekabet,
  Sayıştay, GİB, mevzuat.gov.tr, Resmî Gazete, KVKK adaptörleri.

## Kırmızı çizgiler

- Karar, metadata, tarih, esas/karar no, daire, atıf veya kanun maddesi uydurulmaz.
- `full_text` / `html_markdown` içeriği olmayan belgeler quote/draft için kullanılmaz.
- `quoteUsable` ve `draftUsable` sadece tam metin/HTML markdown varsa `true` olur.
- Rate-limit bilinçli olarak muhafazakâr değildir; tek kullanıcı/tek bilgisayar hedeflenmiştir.

## Korpus

Ölçüm tarihi 16 Eylül 2026, canlı korpus (`cache.sqlite3`, 72 GB).

| Katman | Ölçü |
|---|---|
| Kararlar | **11.108.242** belge (`documents_v2`). Taban: HF `hamzabagirsakci/turkish-court-decisions` (11.045.085, CC0), üstüne günlük Bedesten crawl'ı. |
| Mevzuat belgeleri | **14.298** kayıt / 14.171 güncel sürüm: 916 kanun, 63 KHK, 33 CBK, 8.840 yönetmelik (8.830 güncel), 4.446 tebliğ (4.329 güncel) |
| Mevzuat maddeleri | **303.454** madde, **96.186** değişiklik kaydı |
| Karar anlamsal indeksi | **29.554.075** parça vektörü — `intfloat/multilingual-e5-small` (384 boyut), FAISS `IVF16384,PQ64` + fp16 sidecar refine, `nprobe=128`, chunking v2 |
| Mevzuat anlamsal indeksi | **423.920** parça vektörü (303.454 maddeden), aynı model ve indeks tipi |

Ayrıntı ve ölçümler: [`docs/BULK_INDEX.md`](docs/BULK_INDEX.md).

## Kurulum

```powershell
# Windows
cd <repo-dizini>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,mcp,embeddings]"

# macOS / Linux
cd <repo-dizini>
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp,embeddings]"

emsal-mcp version
```

Anlamsal aramanın toplu FAISS indeksini kullanabilmesi için ayrıca
`pip install faiss-cpu` gerekir. Ayrıntılı kurulum: [`INSTALL.md`](INSTALL.md).

## Çalıştırma

### HTTP (streamable-http) sunucusu

Canlı kurulumda sunucu `scripts\mcp_http_sunucu.cmd` ile başlar; bu betik
ortam değişkenlerini kendi içinde kurar ve logu
`%LOCALAPPDATA%\emsal-mcp\mcp_http.log` dosyasına yazar.

```powershell
.\scripts\mcp_http_sunucu.cmd
```

Windows'ta `EmsalMcpHttp` zamanlanmış görevi aynı betiği oturum açılışında
çalıştırır. Uç nokta: `http://<host>:<port>/mcp`.

### stdio sunucusu

```powershell
call .\scripts\emsal-env.cmd
emsal-mcp-server
```

### Ortam değişkenleri

| Değişken | Ne işe yarar | Örnek değer |
|---|---|---|
| `EMSAL_CACHE_PATH` | Korpus SQLite dosyası | `<veri-dizini>\cache.sqlite3` |
| `EMSAL_BULK_VEC_DIR` | fp16 vektör sidecar'ları (refine için) | `<bench-dizini>\vec` |
| `EMSAL_EMBEDDING_PROVIDER` | Gömme sağlayıcısı | `fastembed-multilingual-e5` |
| `EMSAL_EMBEDDING_CACHE_DIR` | ONNX model önbelleği | `<veri-dizini>\models\fastembed` |
| `EMSAL_MCP_TRANSPORT` | `stdio` (varsayılan) veya `streamable-http` | `streamable-http` |
| `EMSAL_MCP_HOST` / `EMSAL_MCP_PORT` | HTTP dinleme adresi | `127.0.0.1` / `8790` |
| `EMSAL_TOOL_PROFILE` | `core` (varsayılan) veya `full` | `core` |
| `EMSAL_TOOL_THREADS` | Sync araçları için thread havuzu (0 = kapalı) | `6` |
| `EMSAL_TOOL_TIMEOUT` | Araç başına saniye sınırı | `180` |

Tek seferlik CLI çağrıları için `scripts\emsal-env.cmd` aynı değişkenleri
kurar (`call .\scripts\emsal-env.cmd && .venv\Scripts\emsal-mcp ...`).

Makineye özel değerler (veri dizini, dinleme adresi, yedek hedefi) repoda
tutulmaz: `scripts\yerel-ayar.ornek.cmd` dosyasını `scripts\yerel-ayar.cmd`
adıyla kopyalayıp doldurun (`.gitignore`'dadır). `emsal-env.cmd`,
`crawl_incremental.ps1` ve Python betikleri (`scripts/_yollar.py`) bu dosyayı
okur; boş bırakılan her yol `~/.emsal_mcp` altından türetilir.

## MCP araçları

Varsayılan profil `core` — 11 araç kayıtlı gelir. Geri kalanı çalışan sunucuya
`load_extended_tools` ile kategori kategori eklenir. Sözleşmeler:
[`docs/MCP_CONTRACTS.md`](docs/MCP_CONTRACTS.md).

**Core (11):**

| Araç | Ne yapar |
|---|---|
| `search_decisions` | Canlı kaynaklarda karar araması (yönlendirme dahil) |
| `get_document` | Tek belge getirme |
| `search_local_corpus` | Yerel 11 M karar korpusunda FTS5 + anlamsal arama |
| `search_legislation` | mevzuat.gov.tr üzerinde mevzuat araması |
| `get_legislation` | Mevzuat metni / madde getirme |
| `mevzuat_korpus_ara` | Yerel mevzuat korpusunda madde bazlı arama |
| `mevzuat_madde_getir` | Yerel korpustan tek madde |
| `research_topic` | Konu araştırması paketi (bundle + kalite panosu) |
| `export_document` | Belge dışa aktarma |
| `load_extended_tools` | Extended kategorileri çalışırken yükleme |
| `health_check` | Kaynak/breaker/indeks/zamanlanmış iş sağlığı |

**Extended (36), kategori bazında:**

| Kategori | Araç sayısı | Araçlar |
|---|---|---|
| `legislation` | 1 | `mevzuat_degisiklik_raporu` |
| `drafting` | 2 | `citation_check`, `prepare_petition` |
| `files` | 1 | `read_legal_file` |
| `meta` | 2 | `list_sources`, `legal_research_guide` |
| `health_admin` | 4 | `circuit_breaker_status`, `source_health`, `source_smoke`, `check_government_servers_health` |
| `watch` | 4 | `watch_add`, `watch_list`, `watch_run`, `watch_remove` |
| `privacy` | 3 | `privacy_scan`, `privacy_redact`, `privacy_audit` |
| `chambers` | 4 | `chamber_overview`, `profile_chamber`, `chamber_timeline`, `find_similar_chambers` |
| `indexing` | 1 | `index_status` |
| `drafting_advanced` | 10 | `draft_document`, `export_bundle`, `inspect_petition_pack`, `build_multi_issue_pack`, `inspect_multi_issue_pack`, `list_petition_templates`, `get_petition_template`, `build_argument_chain`, `score_argument`, `get_argument_strength_report` |
| `udf_admin` | 4 | `udf_toolkit_status`, `udf_authoring_instructions`, `pdf_toolkit_status`, `promote_pdf_to_full_text` |

> Core profilin docstring bütçesi (20.000 karakter) dolduğu için `citation_check`,
> `prepare_petition`, `read_legal_file`, `list_sources` ve `legal_research_guide`
> 6 Eylül 2026'da extended'a alındı; `load_extended_tools` ile geri gelirler.

## CLI örnekleri

```powershell
emsal-mcp sources
emsal-mcp search bedesten "muvazaa" --limit 5
emsal-mcp get bedesten DOCUMENT_ID
emsal-mcp semantic bulk-status
emsal-mcp mevzuat korpus-ara "tahliye taahhüdü"
emsal-mcp smoke --offline
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
- Panel, `cache.sqlite3` üzerinde yıl sayımı yapmaz — tek bir yıl sorgusu tam
  tablo taraması yüzünden ~60 sn sürüyor. Sayımlar `~/.emsal-mcp/panel_stats.sqlite3`
  içinde artımlı (yalnız yeni `rowid`'ler) tutulur, günde bir kez tam sayım yapılır.
- Yıl hedefleri Bedesten'in `total` alanından ölçülür (`crawl_logs\hedefler.json`),
  tahmin edilmez.

## İşletim

Zamanlanmış işler (Windows Görev Zamanlayıcı, korpus sunucusu):

| Görev | Zaman | Betik | Ne yapar |
|---|---|---|---|
| `EmsalMcpHttp` | oturum açılışı | `scripts\mcp_http_sunucu.cmd` | MCP sunucusunu yayınlar |
| `EmsalCrawlDaily` | her gün 04:30 | `scripts\crawl_incremental.ps1` | Artımlı karar crawl'ı |
| `EmsalMevzuatWeekly` | Pazar 03:00 | `scripts\mevzuat_weekly.cmd` | Mevzuat güncellemesi (+ art-işlem `mevzuat_semantic.cmd`) |
| `EmsalMonthlyMerge` | ayın 1'i 02:00 | `scripts\monthly_merge.cmd` | Delta vektörlerini toplu FAISS indeksine katar |

`health_check` aracı bu işlerin son koşusunu `scheduled_jobs` bloğunda
raporlar: `schtasks` çağırmaz, işlerin kendi log dosyalarına yazdığı bitiş
işaretini ve dosya zaman damgasını okur. Bir iş gecikmişse ya da `rc != 0`
ile bitmişse `overall` "degraded" döner (`src/emsal_mcp/ops_status.py`).
Aynı çıktıda `tool_runtime` bloğu thread havuzu / zaman aşımı sayaçlarını
verir; `runaway > 0` ise sunucu yeniden başlatılmalıdır.

## Belgeler

| Belge | İçerik |
|---|---|
| [`docs/BULK_INDEX.md`](docs/BULK_INDEX.md) | Toplu korpus kurulumu, FAISS indeks yapısı, chunking v2, ölçümler, tuzaklar |
| [`docs/MCP_CONTRACTS.md`](docs/MCP_CONTRACTS.md) | MCP araç sözleşmeleri, profiller, kategoriler |
| [`docs/COOKBOOK.md`](docs/COOKBOOK.md) | Kopyala-çalıştır iş akışı reçeteleri |
| [`docs/JSON_CONTRACTS.md`](docs/JSON_CONTRACTS.md) | Genel API fonksiyonlarının JSON çıktı sözleşmeleri |
| [`docs/ERROR_CATALOG.md`](docs/ERROR_CATALOG.md) | Hata kodları ve önerilen eylemler |
| [`docs/INDEX.md`](docs/INDEX.md) | Tüm belgelerin dizini |
| [`CHANGELOG.md`](CHANGELOG.md) | Sürüm geçmişi |

## Test

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest tests -q
ruff check src tests scripts
```

Canlı kaynağa giden testler varsayılan olarak atlanır; açmak için
`EMSAL_LIVE_TESTS=1`.

## Lisans

Tüm hakları saklıdır. Kaynak kod yalnızca inceleme amacıyla yayımlanmıştır;
yazılı izin olmadan kullanılamaz, kopyalanamaz, değiştirilemez veya dağıtılamaz.
