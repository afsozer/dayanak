@echo off
setlocal
call "%~dp0dayanak-env.cmd"
cd /d "%DAYANAK_REPO%"
echo %date% %time% sema > %DAYANAK_DATA_DIR%\import.log
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from dayanak.cache import Cache; from dayanak import semantic; c=Cache(); semantic._ensure_fts5(c.db); semantic._ensure_embedding_vectors(c.db); print('sema ok', c.path); c.close()" >> %DAYANAK_DATA_DIR%\import.log 2>&1
.venv\Scripts\python.exe -u scripts\import_hf_parquet.py --src %DAYANAK_HF_DIR%\data >> %DAYANAK_DATA_DIR%\import.log 2>&1
echo %date% %time% IMPORT-EXIT %errorlevel% >> %DAYANAK_DATA_DIR%\import.log
