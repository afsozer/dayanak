@echo off
REM Gunluk Resmi Gazete baslik dizini guncellemesi (onerilen gorev: EmsalRgDizin, her gun 07:30).
REM Son 7 gunu yeniden ceker (yayimlanmamis 404'ler, sonradan eklenen mukerrerler) + eksik gunleri
REM kaldigi yerden tamamlar. Dizin bossa once elle: dayanak rg backfill --from 2000-06-27
REM (~2-3 saat, sunucuyu yormamak icin 0,7 sn aralikli).
REM Log isaretleri: "RG-EXIT n" -> ops_status.py / health_check scheduled_jobs.rg_dizin.
REM Cakisma: karar crawl'i 04:30, haftalik mevzuat Pazar 03:00; bu is dakikalar surer.
setlocal
call "%~dp0dayanak-env.cmd"
cd /d "%DAYANAK_REPO%"
set LOG=%DAYANAK_LOG_DIR%\rg_dizin.log
echo %date% %time% rg update basladi >> "%LOG%"
.venv\Scripts\python.exe -X utf8 -m dayanak.cli rg update --days 7 >> "%LOG%" 2>&1
set RC=%errorlevel%
REM Dizindeki kanunlarin tam metni (scripts/rg_kanun_cek.py, 4.11.2026): mevzuat.gov.tr
REM bircok degisiklik kanununu listelemiyor; korpusta olmayan kanunlar RG'den alinir.
REM rc 0 = yazilan/silinen var (semantik indeks yenilenir), 3 = yok, 1 = hata.
echo %date% %time% rg kanun cekimi basladi >> "%LOG%"
.venv\Scripts\python.exe -X utf8 scripts\rg_kanun_cek.py >> "%LOG%" 2>&1
set KRC=%errorlevel%
echo %date% %time% rg kanun rc=%KRC% >> "%LOG%"
if %KRC% EQU 0 call "%~dp0mevzuat_semantic.cmd"
if %KRC% EQU 1 if %RC% EQU 0 set "RC=1"
echo %date% %time% RG-EXIT %RC% >> "%LOG%"
exit /b %RC%
