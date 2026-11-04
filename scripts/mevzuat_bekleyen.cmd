@echo off
REM Ertelenmis yururluk takibi. Her gun 06:15 - EmsalMevzuatBekleyen.
REM
REM Dipnotunda "Mevzuat Bilgi Sistemine islenecek" yazan ve yururluk tarihi
REM gelmis maddelerin belgelerini Bedesten kayitTarihi sinyaline bakmadan
REM yeniden ceker (4.11.2026: TMK 444 ve HMK 149 31.10'da yururluge girdi,
REM haftalik kosu degisikligi gormedi). Kaynak henuz islememisse metin ayni
REM gelir, hicbir sey yazilmaz; ertesi gun yine denenir.
REM
REM Cakisma: haftalik mevzuat Pazar 03:00 (~30 dk), karar crawl'i 04:30.
setlocal
call "%~dp0dayanak-env.cmd"
cd /d "%DAYANAK_REPO%"
set LOG=%DAYANAK_LOG_DIR%\mevzuat_bekleyen.log
echo %date% %time% bekleyen yenileme basladi >> "%LOG%"
.venv\Scripts\python.exe -X utf8 scripts\mevzuat_bekleyen_yenile.py >> "%LOG%" 2>&1
set RC=%errorlevel%
echo %date% %time% bekleyen yenileme rc=%RC% >> "%LOG%"
REM 3 = guncellenen belge yok: basari, semantik indekse gerek yok.
if %RC% EQU 3 goto :yok
if %RC% NEQ 0 goto :end
call "%~dp0mevzuat_semantic.cmd"
echo %date% %time% semantik indeks rc=%errorlevel% >> "%LOG%"
goto :end
:yok
set "RC=0"
:end
echo %date% %time% BEKLEYEN-EXIT %RC% >> "%LOG%"
