@echo off
REM Aylik birlestirme: delta kararlarini GPU'da parcali gom -> toplu FAISS indeksine ekle -> delta satirlarini sil.
REM Iki venv: torch (%EMSAL_BENCH_DIR%\venv) ve faiss (repo .venv) ayni surecte cokuyor; asamalar ayri surec.
setlocal
call "%~dp0emsal-env.cmd"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set STAMP=%%i
set LOG=%EMSAL_LOG_DIR%\monthly_%STAMP%.log
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set STAMP=%%i
set NAME=delta-%STAMP%
echo %date% %time% basladi %NAME% > "%LOG%"
cd /d "%EMSAL_REPO%"
"%EMSAL_TORCH_PY%" -X utf8 scripts\embed_delta_chunks.py --name %NAME% >> "%LOG%" 2>&1
if errorlevel 3 ( echo %date% %time% delta bos, is yok >> "%LOG%" & goto :end )
if errorlevel 1 ( echo %date% %time% GOMME HATASI >> "%LOG%" & goto :end )
.venv\Scripts\emsal-mcp.exe semantic bulk-append %EMSAL_BULK_VEC_DIR% %NAME% >> "%LOG%" 2>&1
if errorlevel 1 ( echo %date% %time% APPEND HATASI, delta satirlari korundu >> "%LOG%" & goto :end )
.venv\Scripts\python.exe -X utf8 scripts\drop_delta_rows.py %NAME% >> "%LOG%" 2>&1
.venv\Scripts\emsal-mcp.exe semantic build-matrix --json >> "%LOG%" 2>&1
.venv\Scripts\emsal-mcp.exe semantic bulk-status --json >> "%LOG%" 2>&1
:end
echo %date% %time% BITTI >> "%LOG%"
