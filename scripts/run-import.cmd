@echo off
setlocal
call "%~dp0emsal-env.cmd"
cd /d "%EMSAL_REPO%"
echo %date% %time% sema > %EMSAL_DATA_DIR%\import.log
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from emsal_mcp.cache import Cache; from emsal_mcp import semantic; c=Cache(); semantic._ensure_fts5(c.db); semantic._ensure_embedding_vectors(c.db); print('sema ok', c.path); c.close()" >> %EMSAL_DATA_DIR%\import.log 2>&1
.venv\Scripts\python.exe -u scripts\import_hf_parquet.py --src %EMSAL_HF_DIR%\data >> %EMSAL_DATA_DIR%\import.log 2>&1
echo %date% %time% IMPORT-EXIT %errorlevel% >> %EMSAL_DATA_DIR%\import.log
