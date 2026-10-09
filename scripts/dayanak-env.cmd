@echo off
REM Tum betiklerin ortak ortami. Elle calistirma icin:
REM   call scripts\dayanak-env.cmd && .venv\Scripts\dayanak semantic bulk-status
REM Makineye ozel degerler (veri dizini, dinleme adresi, yedek hedefi) repoya girmez:
REM scripts\yerel-ayar.ornek.cmd dosyasini scripts\yerel-ayar.cmd olarak kopyalayip doldur.
set PYTHONIOENCODING=utf-8
for %%I in ("%~dp0..") do set DAYANAK_REPO=%%~fI
if exist "%~dp0yerel-ayar.cmd" call "%~dp0yerel-ayar.cmd"
REM 2.0.0 oncesi adlar (EMSAL_*) hala verilebilir; DAYANAK_* karsiligi yoksa kopyalanir.
for /f "tokens=1* delims==" %%A in ('set EMSAL_ 2^>nul') do call :eski_ad %%A "%%B"
REM PDF/UDF donusumu icin LibreOffice (winget kurulumu PATH eklemez)
set PATH=%PATH%;%ProgramFiles%\LibreOffice\program
if "%DAYANAK_DATA_DIR%"=="" set DAYANAK_DATA_DIR=%USERPROFILE%\.dayanak
if "%DAYANAK_BENCH_DIR%"=="" set DAYANAK_BENCH_DIR=%DAYANAK_DATA_DIR%\bench
if "%DAYANAK_HF_DIR%"=="" set DAYANAK_HF_DIR=%DAYANAK_DATA_DIR%\hf-datasets\turkish-court-decisions
if "%DAYANAK_LOG_DIR%"=="" set DAYANAK_LOG_DIR=%DAYANAK_DATA_DIR%\crawl_logs
if "%DAYANAK_TORCH_PY%"=="" set DAYANAK_TORCH_PY=%DAYANAK_BENCH_DIR%\venv\Scripts\python.exe
if "%DAYANAK_CACHE_PATH%"=="" set DAYANAK_CACHE_PATH=%DAYANAK_DATA_DIR%\cache.sqlite3
if "%DAYANAK_BULK_VEC_DIR%"=="" set DAYANAK_BULK_VEC_DIR=%DAYANAK_BENCH_DIR%\vec
if "%DAYANAK_EMBEDDING_PROVIDER%"=="" set DAYANAK_EMBEDDING_PROVIDER=fastembed-multilingual-e5
if "%DAYANAK_EMBEDDING_CACHE_DIR%"=="" set DAYANAK_EMBEDDING_CACHE_DIR=%DAYANAK_DATA_DIR%\models\fastembed
if not exist "%DAYANAK_LOG_DIR%" mkdir "%DAYANAK_LOG_DIR%"
goto :eof

:eski_ad
set "_ad=%1"
set "_ad=DAYANAK_%_ad:~6%"
if not defined %_ad% set "%_ad%=%~2"
set "_ad="
goto :eof
