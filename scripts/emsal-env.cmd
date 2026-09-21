@echo off
REM Tum betiklerin ortak ortami. Elle calistirma icin:
REM   call scripts\emsal-env.cmd && .venv\Scripts\emsal-mcp semantic bulk-status
REM Makineye ozel degerler (veri dizini, dinleme adresi, yedek hedefi) repoya girmez:
REM scripts\yerel-ayar.ornek.cmd dosyasini scripts\yerel-ayar.cmd olarak kopyalayip doldur.
set PYTHONIOENCODING=utf-8
for %%I in ("%~dp0..") do set EMSAL_REPO=%%~fI
if exist "%~dp0yerel-ayar.cmd" call "%~dp0yerel-ayar.cmd"
REM PDF/UDF donusumu icin LibreOffice (winget kurulumu PATH eklemez)
set PATH=%PATH%;%ProgramFiles%\LibreOffice\program
if "%EMSAL_DATA_DIR%"=="" set EMSAL_DATA_DIR=%USERPROFILE%\.emsal_mcp
if "%EMSAL_BENCH_DIR%"=="" set EMSAL_BENCH_DIR=%EMSAL_DATA_DIR%\bench
if "%EMSAL_HF_DIR%"=="" set EMSAL_HF_DIR=%EMSAL_DATA_DIR%\hf-datasets\turkish-court-decisions
if "%EMSAL_LOG_DIR%"=="" set EMSAL_LOG_DIR=%EMSAL_DATA_DIR%\crawl_logs
if "%EMSAL_TORCH_PY%"=="" set EMSAL_TORCH_PY=%EMSAL_BENCH_DIR%\venv\Scripts\python.exe
if "%EMSAL_CACHE_PATH%"=="" set EMSAL_CACHE_PATH=%EMSAL_DATA_DIR%\cache.sqlite3
if "%EMSAL_BULK_VEC_DIR%"=="" set EMSAL_BULK_VEC_DIR=%EMSAL_BENCH_DIR%\vec
if "%EMSAL_EMBEDDING_PROVIDER%"=="" set EMSAL_EMBEDDING_PROVIDER=fastembed-multilingual-e5
if "%EMSAL_EMBEDDING_CACHE_DIR%"=="" set EMSAL_EMBEDDING_CACHE_DIR=%EMSAL_DATA_DIR%\models\fastembed
if not exist "%EMSAL_LOG_DIR%" mkdir "%EMSAL_LOG_DIR%"
