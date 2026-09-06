@echo off
REM Aylik birlestirme (sozer-pc): delta kararlarini GPU'da parcali gom -> toplu FAISS indeksine ekle -> delta satirlarini sil.
REM Iki venv: torch (D:\emsal-bench\venv) ve faiss (D:\Emsal-mcp\.venv) ayni surecte cokuyor; asamalar ayri surec.
setlocal
call D:\Emsal-mcp\scripts\emsal-env.cmd
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set STAMP=%%i
set LOG=D:\emsal-data\crawl_logs\monthly_%STAMP%.log
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set STAMP=%%i
set NAME=delta-%STAMP%
echo %date% %time% basladi %NAME% > "%LOG%"
cd /d D:\Emsal-mcp
D:\emsal-bench\venv\Scripts\python.exe -X utf8 scripts\embed_delta_chunks.py --name %NAME% >> "%LOG%" 2>&1
if errorlevel 3 ( echo %date% %time% delta bos, is yok >> "%LOG%" & goto :end )
if errorlevel 1 ( echo %date% %time% GOMME HATASI >> "%LOG%" & goto :end )
.venv\Scripts\emsal-mcp.exe semantic bulk-append %EMSAL_BULK_VEC_DIR% %NAME% >> "%LOG%" 2>&1
if errorlevel 1 ( echo %date% %time% APPEND HATASI, delta satirlari korundu >> "%LOG%" & goto :end )
.venv\Scripts\python.exe -X utf8 scripts\drop_delta_rows.py %NAME% >> "%LOG%" 2>&1
.venv\Scripts\emsal-mcp.exe semantic build-matrix --json >> "%LOG%" 2>&1
.venv\Scripts\emsal-mcp.exe semantic bulk-status --json >> "%LOG%" 2>&1
:end
echo %date% %time% BITTI >> "%LOG%"
