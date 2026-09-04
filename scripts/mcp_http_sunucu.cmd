@echo off
REM emsal-mcp'yi Tailscale agina streamable-http MCP sunucusu olarak yayinlar (sozer-pc).
REM Korpus: D:\emsal-data\cache.sqlite3 (11 M karar, HF), vektorler D:\emsal-bench\vec, toplu FAISS indeksi cache'in yaninda.
REM Log: %LOCALAPPDATA%\emsal-mcp\mcp_http.log
setlocal
set PYTHONIOENCODING=utf-8
set EMSAL_MCP_TRANSPORT=streamable-http
if "%EMSAL_MCP_HOST%"=="" set EMSAL_MCP_HOST=100.77.229.110
if "%EMSAL_MCP_PORT%"=="" set EMSAL_MCP_PORT=8790
if "%EMSAL_TOOL_THREADS%"=="" set EMSAL_TOOL_THREADS=6
if "%EMSAL_TOOL_TIMEOUT%"=="" set EMSAL_TOOL_TIMEOUT=180
set EMSAL_CACHE_PATH=D:\emsal-data\cache.sqlite3
set EMSAL_BULK_VEC_DIR=D:\emsal-bench\vec
set EMSAL_EMBEDDING_PROVIDER=fastembed-multilingual-e5
set EMSAL_EMBEDDING_CACHE_DIR=D:\emsal-data\models\fastembed
set LOGDIR=%LOCALAPPDATA%\emsal-mcp
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m emsal_mcp.server > "%LOGDIR%\mcp_http.log" 2>&1
