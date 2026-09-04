@echo off
setlocal
call D:\Emsal-mcp\scripts\emsal-env.cmd
cd /d D:\Emsal-mcp
echo %date% %time% sema > D:\emsal-data\import.log
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from emsal_mcp.cache import Cache; from emsal_mcp import semantic; c=Cache(); semantic._ensure_fts5(c.db); semantic._ensure_embedding_vectors(c.db); print('sema ok', c.path); c.close()" >> D:\emsal-data\import.log 2>&1
.venv\Scripts\python.exe -u scripts\import_hf_parquet.py --src D:\hf-datasets\turkish-court-decisions\data >> D:\emsal-data\import.log 2>&1
echo %date% %time% IMPORT-EXIT %errorlevel% >> D:\emsal-data\import.log
