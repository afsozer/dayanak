@echo off
REM Gecelik mevzuat cekimi (Faz 2 veri): yonetmelik + CB yonetmeligi + tebligler. CB karari (4.294) taranmis PDF, metin cikmiyor - OCR kararina kadar disarida.
REM mevzuat.gov.tr zaman zaman erisilemez oluyor (5 Eyl 22:46 ConnectError); betik hash ile kaldigi
REM yerden devam eder, o yuzden basarisiz olursa 15 dk bekleyip yeniden dener (en fazla 40 deneme ~10 sa).
setlocal
call D:\Emsal-mcp\scripts\emsal-env.cmd
cd /d D:\Emsal-mcp
set LOG=D:\emsal-data\crawl_logs\mevzuat_pull.log
set /a N=0
:retry
set /a N+=1
echo %date% %time% deneme %N% basladi >> "%LOG%"
.venv\Scripts\python.exe -X utf8 scripts\mevzuat_pull.py --tur YONETMELIK --tur CB_YONETMELIK --tur TEBLIGLER --sleep 0.5 >> "%LOG%" 2>&1
set RC=%errorlevel%
echo %date% %time% deneme %N% rc=%RC% >> "%LOG%"
if %RC% EQU 0 goto :done
if %N% GEQ 40 goto :done
timeout /t 900 /nobreak >nul
goto :retry
:done
echo %date% %time% PULL-EXIT %RC% >> "%LOG%"
