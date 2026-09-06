@echo off
REM Haftalik mevzuat guncellemesi (Faz 2b). Pazar 03:00 - EmsalMevzuatWeekly.
REM
REM Tam cekimden farki: --only-changed metni INDIRMEDEN once "degismis mi"
REM sorusunu ucuz sinyallerle cevaplar (Bedesten kayitTarihi + RG tarih/sayi).
REM Olcum 05.09.2026: mevzuat.gov.tr listelemesinde guncelleme tarihi ALANI YOK,
REM tek sinyal Bedesten kayitTarihi. Tam cekim ~13 bin belge x 0,45 s = ~1,6 sa;
REM haftalik kosu ~200 listeleme istegi + degisen kayit kadar metin = dakikalar.
REM
REM Cakisma: gunluk karar crawl'i 04:30, aylik birlestirme ayin 1'i 02:00.
REM Bu is Pazar 03:00'te baslar ve normalde 10 dk'da biter.
setlocal
call D:\Emsal-mcp\scripts\emsal-env.cmd
cd /d D:\Emsal-mcp
set LOG=D:\emsal-data\crawl_logs\mevzuat_weekly.log
set /a N=0
:retry
set /a N+=1
echo %date% %time% haftalik deneme %N% basladi >> "%LOG%"
.venv\Scripts\python.exe -X utf8 scripts\mevzuat_pull.py --only-changed --gun 10 ^
  --tur KANUN --tur KHK --tur CBK --tur YONETMELIK --tur CB_YONETMELIK ^
  --tur TEBLIGLER --tur CB_KARAR --sleep 0.5 >> "%LOG%" 2>&1
set RC=%errorlevel%
echo %date% %time% haftalik deneme %N% rc=%RC% >> "%LOG%"
if %RC% EQU 0 goto :done
REM Kaynak zaman zaman erisilemez oluyor; 30 dk bekleyip yeniden dene (en fazla 6).
if %N% GEQ 6 goto :done
timeout /t 1800 /nobreak >nul
goto :retry
:done
if %RC% NEQ 0 goto :end
REM Faz 2b/2c/3 art-islemleri: degisiklik tablosu (tum korpus, ~16 dk) ve
REM semantik indeks (yalniz yeni/degismis maddeler gomulur). ust_baslik yeni
REM cekimlerde upsert sirasinda ayristirici tarafindan dolduruluyor.
echo %date% %time% degisiklik doldurma basladi >> "%LOG%"
.venv\Scripts\python.exe -X utf8 scripts\mevzuat_degisiklik_doldur.py --db %EMSAL_CACHE_PATH% > D:\emsal-data\crawl_logs\degisiklik_doldur.log 2>&1
echo %date% %time% degisiklik doldurma rc=%errorlevel% >> "%LOG%"
call D:\Emsal-mcp\scripts\mevzuat_semantic.cmd
echo %date% %time% semantik indeks rc=%errorlevel% >> "%LOG%"
:end
echo %date% %time% WEEKLY-EXIT %RC% >> "%LOG%"
