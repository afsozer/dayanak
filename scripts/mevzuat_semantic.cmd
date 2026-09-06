@echo off
REM Faz 2c mevzuat semantik indeksi (sozer-pc): maddeleri GPU'da gom -> FAISS
REM IndexFlatIP indeksini yeniden kur.  Artimli: yalniz yeni/degismis maddeler
REM gomulur (mevzuat_madde_vektor tablosu), indeks her seferinde bastan kurulur
REM (flat indeks, ~0,5 sn).
REM Ne zaman: gecelik mevzuat cekimi (EmsalMevzuatPull) bittikten sonra ve
REM haftalik guncelleme kosusundan sonra.
REM Iki venv: torch (D:\emsal-bench\venv) ile faiss (D:\Emsal-mcp\.venv) ayni
REM surecte cokuyor; asamalar ayri surec.
setlocal
call D:\Emsal-mcp\scripts\emsal-env.cmd
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set STAMP=%%i
set LOG=D:\emsal-data\crawl_logs\mevzuat_semantic_%STAMP%.log
set NAME=mevzuat-%STAMP%
echo %date% %time% basladi %NAME% > "%LOG%"
cd /d D:\Emsal-mcp
D:\emsal-bench\venv\Scripts\python.exe -X utf8 scripts\embed_mevzuat_madde.py --name %NAME% >> "%LOG%" 2>&1
if errorlevel 3 ( echo %date% %time% yeni madde yok, indeks korundu >> "%LOG%" & goto :end )
if errorlevel 1 ( echo %date% %time% GOMME HATASI >> "%LOG%" & goto :end )
.venv\Scripts\python.exe -X utf8 scripts\build_mevzuat_index.py --json >> "%LOG%" 2>&1
if errorlevel 1 ( echo %date% %time% INDEKS HATASI >> "%LOG%" & goto :end )
:end
echo %date% %time% BITTI >> "%LOG%"
