@echo off
REM Faz 2c mevzuat semantik indeksi: maddeleri GPU'da gom -> FAISS
REM IndexFlatIP indeksini yeniden kur.  Artimli: yalniz yeni/degismis maddeler
REM gomulur (mevzuat_madde_vektor tablosu), indeks her seferinde bastan kurulur
REM (flat indeks, ~0,5 sn).
REM Ne zaman: gecelik mevzuat cekimi (EmsalMevzuatPull) bittikten sonra ve
REM haftalik guncelleme kosusundan sonra.
REM Iki venv: torch (%EMSAL_BENCH_DIR%\venv) ile faiss (repo .venv) ayni
REM surecte cokuyor; asamalar ayri surec.
setlocal
call "%~dp0emsal-env.cmd"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set STAMP=%%i
set LOG=%EMSAL_LOG_DIR%\mevzuat_semantic_%STAMP%.log
set NAME=mevzuat-%STAMP%
echo %date% %time% basladi %NAME% > "%LOG%"
cd /d "%EMSAL_REPO%"
"%EMSAL_TORCH_PY%" -X utf8 scripts\embed_mevzuat_madde.py --name %NAME% >> "%LOG%" 2>&1
if errorlevel 3 ( echo %date% %time% yeni madde yok, indeks korundu >> "%LOG%" & goto :end )
if errorlevel 1 ( echo %date% %time% GOMME HATASI >> "%LOG%" & goto :end )
.venv\Scripts\python.exe -X utf8 scripts\build_mevzuat_index.py --json >> "%LOG%" 2>&1
if errorlevel 1 ( echo %date% %time% INDEKS HATASI >> "%LOG%" & goto :end )
:end
echo %date% %time% BITTI >> "%LOG%"
