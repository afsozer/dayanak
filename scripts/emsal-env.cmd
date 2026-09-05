@echo off
REM Elle calistirma icin: call D:\Emsal-mcp\scripts\emsal-env.cmd && .venv\Scripts\emsal-mcp semantic bulk-status
set PYTHONIOENCODING=utf-8
REM PDF/UDF donusumu icin LibreOffice (winget kurulumu PATH eklemez)
set PATH=%PATH%;C:\Program Files\LibreOffice\program
set EMSAL_CACHE_PATH=D:\emsal-data\cache.sqlite3
set EMSAL_BULK_VEC_DIR=D:\emsal-bench\vec
set EMSAL_EMBEDDING_PROVIDER=fastembed-multilingual-e5
set EMSAL_EMBEDDING_CACHE_DIR=D:\emsal-data\models\fastembed
