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
- [ ] `src/emsal_mcp` → `src/dayanak`, tüm import ve referanslar
- [ ] `EMSAL_*` → `DAYANAK_*`; `dayanak/__init__.py` eski adları yeni adlara kopyalar
- [ ] veri dizini çözümleyicisi (yeni yoksa eski dizin)
- [ ] betikler: `emsal-env.cmd` → `dayanak-env.cmd`, `.exe` adları, yerel-ayar eski adları da kabul eder
- [ ] pyproject, server.json, README (TR/EN), INSTALL, SECURITY, docs
- [ ] eski PyPI adı için uyumluluk paketi `compat/emsal-mcp` (1.2.0: `dayanak`'ı çeker,
      `emsal_mcp` importunu ve eski komutları yönlendirir, uyarı basar)
- [ ] publish.yml: `v*` → dayanak, `emsal-mcp-v*` → uyumluluk paketi
- [ ] CHANGELOG 2.0.0, testler yeşil

### 2. Dış hesaplar (kullanıcı onayıyla)
- [ ] GitHub repo rename `afsozer/emsal-mcp` → `afsozer/dayanak` (eski URL yönlenir), açıklama/konu
- [ ] PyPI: `dayanak` için pending trusted publisher (repo `afsozer/dayanak`, `publish.yml`, ortam `pypi`);
      `emsal-mcp` projesinin trusted publisher'ı yeni repo adına güncellenir (kullanıcı, pypi.org)
- [ ] push + `v2.0.0` etiketi → `dayanak` yayımı; `emsal-mcp-v1.2.0` etiketi → uyumluluk sürümü
- [ ] MCP Registry: `io.github.afsozer/dayanak` yayımı, eski kayıt `deprecated`
- [ ] mcprush listesi: ad, açıklama, repo ve kurulum komutu
- [ ] avfatihsozer.com: proje sayfaları (TR/EN) yeni slug + 301, `KORPUS`/`PROJELER`
- [ ] diğer depolardaki atıflar: doktor-mcp, belgelik, telekumanda (yalnız metin/URL)

### 3. Çalışan kurulumlar
- [ ] sozer-pc `D:\Emsal-mcp`: bundle ile güncelle, `pip install -e .`, `yerel-ayar.cmd` yeni adlar,
      `EmsalMcpHttp` ve diğer görevlerin çağırdığı betikleri doğrula, `/health`
- [ ] istemci ayarları (Mac + sozer-pc + desktop): MCP sunucu adı `emsal` → `dayanak`
      (araç adları `mcp__dayanak__*` olur), URL aynı kalır
- [ ] Mac klasörü `~/Developer/emsal-mcp` → `~/Developer/dayanak` (venv yeniden kurulur,
      Claude proje hafıza dizini taşınır, kasaya `Projeler/dayanak` bağlanır)
- [ ] hafıza notları ve CV/LinkedIn'deki proje adı
