@echo off
REM Gunluk Resmi Gazete baslik dizini guncellemesi (onerilen gorev: EmsalRgDizin, her gun 07:30).
REM Son 7 gunu yeniden ceker (yayimlanmamis 404'ler, sonradan eklenen mukerrerler) + eksik gunleri
REM kaldigi yerden tamamlar. Dizin bossa once elle: emsal-mcp rg backfill --from 2000-06-27
REM (~2-3 saat, sunucuyu yormamak icin 0,7 sn aralikli).
REM Log isaretleri: "RG-EXIT n" -> ops_status.py / health_check scheduled_jobs.rg_dizin.
REM Cakisma: karar crawl'i 04:30, haftalik mevzuat Pazar 03:00; bu is dakikalar surer.
setlocal
call "%~dp0emsal-env.cmd"
cd /d "%EMSAL_REPO%"
set LOG=%EMSAL_LOG_DIR%\rg_dizin.log
echo %date% %time% rg update basladi >> "%LOG%"
.venv\Scripts\python.exe -X utf8 -m emsal_mcp.cli rg update --days 7 >> "%LOG%" 2>&1
set RC=%errorlevel%
echo %date% %time% RG-EXIT %RC% >> "%LOG%"
exit /b %RC%
