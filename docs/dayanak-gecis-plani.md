# Emsal MCP → Dayanak ad değişikliği planı

9 Eki 2026'da karar verildi: proje adı **Dayanak**, PyPI paketi çıplak `dayanak`.
Sebep: "Emsal" jenerik bir kelime, UYAP'ın kendi hizmetinin adı (emsal.uyap.gov.tr),
aynı alanda ticari bir "Emsal AI" (11 M karar iddiası) ile PyPI'da başkasına ait
`emsal` paketi var. `dayanak` ve `dayanak-mcp` PyPI'da ve GitHub'da boştu.
Künye de düşünüldü, ASCII yazımı (kunye) markadan kopacağı için elendi.

## Ad eşlemesi

| eski | yeni |
|---|---|
| PyPI `emsal-mcp` | `dayanak` (sürüm 2.0.0) |
| Python modülü `emsal_mcp` | `dayanak` |
| komut `emsal-mcp` / `emsal-mcp-server` | `dayanak` / `dayanak-server` |
| ortam değişkeni `EMSAL_*` | `DAYANAK_*` (eski adlar okunmaya devam eder) |
| veri dizini `~/.emsal_mcp`, `~/.emsal-mcp` | `~/.dayanak` (yeni dizin yoksa eskisi kullanılır) |
| log `%LOCALAPPDATA%\emsal-mcp` | `%LOCALAPPDATA%\dayanak` |
| MCP sunucu adı `emsal-mcp` | `dayanak` |
| Registry `io.github.afsozer/emsal-mcp` | `io.github.afsozer/dayanak` |
| GitHub `afsozer/emsal-mcp` | `afsozer/dayanak` |
| site `/projeler/emsal-mcp` | `/projeler/dayanak` (eskisi 301) |

Değişmeyenler: araç adları (`search_decisions` vb.), "emsal" kaynak kimliği,
Bedesten'in `emsalKararList` alanı, `emsal.uyap.gov.tr`, sozer-pc'deki zamanlanmış
görev adları (`EmsalMcpHttp`, `EmsalCrawlDaily`...; görünmez, yeniden kurmaya değmez),
korpusun diskteki yeri (`D:\emsal-data`).

## Aşamalar

### 1. Depo içi (bu oturum, yerel commit)
- [x] `src/emsal_mcp` → `src/dayanak`, tüm import ve referanslar
- [x] `EMSAL_*` → `DAYANAK_*`; `dayanak/__init__.py` eski adları yeni adlara kopyalar
- [x] veri dizini çözümleyicisi (yeni yoksa eski dizin)
- [x] betikler: `emsal-env.cmd` → `dayanak-env.cmd`, `.exe` adları, yerel-ayar eski adları da kabul eder
- [x] pyproject, server.json, README (TR/EN), INSTALL, SECURITY, docs
- [x] eski PyPI adı için uyumluluk paketi `compat/emsal-mcp` (1.2.0: `dayanak`'ı çeker,
      `emsal_mcp` importunu ve eski komutları yönlendirir, uyarı basar)
- [x] publish.yml: `v*` → dayanak, `emsal-mcp-v*` → uyumluluk paketi
- [x] CHANGELOG 2.0.0, testler yeşil

### 2. Dış hesaplar (kullanıcı onayıyla)
- [x] GitHub repo rename `afsozer/emsal-mcp` → `afsozer/dayanak` (eski URL yönlenir), açıklama/konu
- [x] PyPI: `dayanak` için pending trusted publisher (repo `afsozer/dayanak`, `publish.yml`, ortam `pypi`);
      `emsal-mcp` projesinin trusted publisher'ı yeni repo adına güncellenir (kullanıcı, pypi.org)
- [x] push + `v2.0.0` etiketi → `dayanak` yayımı; `emsal-mcp-v1.2.0` etiketi → uyumluluk sürümü
- [x] MCP Registry: `io.github.afsozer/dayanak` yayımı, eski kayıt `deprecated`
- [ ] mcprush listesi: ad, açıklama, repo ve kurulum komutu
- [ ] avfatihsozer.com: proje sayfaları (TR/EN) yeni slug + 301, `KORPUS`/`PROJELER`
- [x] diğer depolardaki atıflar: doktor-mcp, belgelik, telekumanda (yalnız metin/URL)

### 3. Çalışan kurulumlar
- [x] sozer-pc `D:\Emsal-mcp`: bundle ile güncelle, `pip install -e .`, `yerel-ayar.cmd` yeni adlar,
      `EmsalMcpHttp` ve diğer görevlerin çağırdığı betikleri doğrula, `/health`
- [x] istemci ayarları (Mac + sozer-pc + desktop): MCP sunucu adı `emsal` → `dayanak`
      (araç adları `mcp__dayanak__*` olur), URL aynı kalır
- [x] Mac klasörü `~/Developer/emsal-mcp` → `~/Developer/dayanak` (venv yeniden kurulur,
      Claude proje hafıza dizini taşınır, kasaya `Projeler/dayanak` bağlanır)
- [ ] hafıza notları ve CV/LinkedIn'deki proje adı

## Durum (10 Eki 2026)

- PyPI: `dayanak` 2.0.0 ve `emsal-mcp` 1.2.0 (yalnız `dayanak>=2.0.0` çeker) yayında,
  ikisi de trusted publishing ile `afsozer/dayanak` deposundan. Temiz venv'de
  `pip install emsal-mcp==1.2.0` + eski `emsal-mcp-server` komutuyla MCP el sıkışması denendi.
- GitHub: `afsozer/dayanak` (eski URL yönleniyor), açıklama ve ana sayfa güncel, CI yeşil.
- Registry: `io.github.afsozer/dayanak` 2.0.0 aktif, `io.github.afsozer/emsal-mcp` deprecated.
- mcprush: listeler resmi Registry'den içe aktarılıyor, Studio'da ad değiştirme yok
  (sihirbaz yalnız ağ geçidi/barındırma için). `dayanak` kaydı içe aktarılınca claim edilecek,
  eski `afsozer/emsal-mcp` listesi ayrıca ele alınacak.
- Mac klasörü `~/Developer/dayanak`; venv yeniden kuruldu (pyarrow + faiss dahil), 2217 test geçti.
- sozer-pc `D:\Emsal-mcp` 8f2ccac'a alındı (bundle), venv'de editable `dayanak` 2.0.0, eski
  `emsal-mcp` dağıtımı ve `src\emsal_mcp` kalıntısı silindi. `yerel-ayar.cmd` DAYANAK_* adlarına
  çevrildi (yedek `yerel-ayar.cmd.bak-emsal`, ilk gecelik crawl geçince silinebilir);
  `D:\emsal-data\rg_backfill.cmd` da çevrildi. `EmsalMcpHttp` `python -m dayanak.server` ile
  çalışıyor, log `%LOCALAPPDATA%\dayanak\mcp_http.log`. Mac'ten HTTP ile ölçüldü: sunucu adı
  `dayanak`, 11.111.902 karar, arama sonuç veriyor.
- İstemciler (10 Eki): sunucu adı her yerde `dayanak`, araçlar `mcp__dayanak__*`. Mac: Claude Code,
  Claude Desktop, opencode (+ runpod ajanının `dayanak*: false` süzgeci), Codex (eski desktop
  adresi laptopa çevrildi). sozer-pc: iki `.claude.json`, Claude Desktop, opencode, Codex,
  Gemini/Antigravity izin listesi. desktop: iki `.claude.json`, opencode, Codex (eski stdio
  kopyasından HTTP'ye). Yedekler `*.bak-dayanak-20261010`. Skill'ler: dilekce-taslagi,
  cizgi-film, sohbet-reels.
- Kasa: `~/Kasa/Projeler/dayanak` → `docs`, Syncthing `kasa-dayanak` (sozer-pc'ye geldiği ölçüldü).
- belgelik (public) `eb82bac`: varsayılan komut `dayanak`, eski bayrak/değişken/modül yedek; CI yeşil,
  4857 canlı ingest denemesi geçti. Özel `belgelik-arsiv` (hakimlik-app) aynı eski kodu taşıyor,
  çalışan sunucu bu betikleri kullanmıyor.
- Bekleyen: site yayını (yan oturumda), mcprush'ın `dayanak`'ı Registry'den içe aktarması ve claim.
