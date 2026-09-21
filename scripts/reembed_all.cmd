@echo off
REM Parcalama duzeltmesi (chunking v2) sonrasi TUM korpusun yeniden gommesi + otomatik gecis.
REM Sure: gomme ~29-38 sa (olcum: RTX 4060'ta 220-292 parca/sn, ~30,4 M parca) + indeks ~1,2 sa.
REM Adimlar: 1) HF parquet -> vec2  2) parquet disi kararlar -> vec2  3) hazirlik indeksi
REM          4) dogrulama + canliya gecis (scripts/reembed_switch.py, ~1-2 dk kesinti)
REM Her adim yeniden calistirilabilir: bitmis parquet dosyalari done.json ile atlanir.
REM Log: %EMSAL_LOG_DIR%\reembed.log (son satir: REEMBED-EXIT <rc>)
REM   rc 0 tamam | 2 parquet gomme | 3 delta gomme | 4 indeks kurulumu | 10+ gecis (bkz. reembed_switch.py)
setlocal
call "%~dp0emsal-env.cmd"
set LOG=%EMSAL_LOG_DIR%\reembed.log
set VEC2=%EMSAL_BENCH_DIR%\vec2
set STAGE=%EMSAL_DATA_DIR%\staging
set RC=0
if not exist %EMSAL_LOG_DIR% mkdir %EMSAL_LOG_DIR%
if not exist "%STAGE%" mkdir "%STAGE%"
if not exist "%VEC2%" mkdir "%VEC2%"
cd /d "%EMSAL_REPO%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set STAMP=%%i
echo. >> "%LOG%"
echo ===== REEMBED basladi %date% %time% (chunking v2) >> "%LOG%"

echo --- 1/4 HF parquet gomme (vec2) %time% >> "%LOG%"
"%EMSAL_TORCH_PY%" -X utf8 scripts\embed_parquet_worker.py --files "%EMSAL_HF_DIR%/data/*/*.parquet" --out "%VEC2%" --device cuda --model-cache %EMSAL_BENCH_DIR%\models >> "%LOG%" 2>&1
if errorlevel 1 ( set RC=2 & echo PARQUET GOMME HATASI >> "%LOG%" & goto :end )

echo --- 2/4 parquet disi kararlar (uyap_arsiv, crawl deltasi) %time% >> "%LOG%"
"%EMSAL_TORCH_PY%" -X utf8 scripts\reembed_delta.py --old-vec %EMSAL_BULK_VEC_DIR% --out "%VEC2%" --name delta-reembed-%STAMP% >> "%LOG%" 2>&1
if errorlevel 3 (
  echo delta bos, atlandi >> "%LOG%"
) else (
  if errorlevel 1 ( set RC=3 & echo DELTA GOMME HATASI >> "%LOG%" & goto :end )
)

echo --- 3/4 hazirlik indeksi (%STAGE%, canliya dokunmaz) %time% >> "%LOG%"
.venv\Scripts\python.exe -X utf8 scripts\build_bulk_index.py --vec "%VEC2%" --cache "%STAGE%\cache.sqlite3" >> "%LOG%" 2>&1
if errorlevel 1 ( set RC=4 & echo INDEKS KURULUM HATASI >> "%LOG%" & goto :end )

echo --- 4/4 dogrulama + gecis %time% >> "%LOG%"
.venv\Scripts\python.exe -X utf8 scripts\reembed_switch.py >> "%LOG%" 2>&1
set RC=%errorlevel%

:end
echo ===== REEMBED bitti %date% %time% >> "%LOG%"
echo REEMBED-EXIT %RC% >> "%LOG%"
exit /b %RC%
