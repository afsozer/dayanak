@echo off
REM Dayanak'i streamable-http MCP sunucusu olarak yayinlar. Dinleme adresi DAYANAK_MCP_HOST
REM (varsayilan 127.0.0.1; ag uzerinden yayin icin scripts\yerel-ayar.cmd icinde ayarla).
REM Log: %LOCALAPPDATA%\dayanak\mcp_http.log
setlocal
call "%~dp0dayanak-env.cmd"
set DAYANAK_MCP_TRANSPORT=streamable-http
if "%DAYANAK_MCP_HOST%"=="" set DAYANAK_MCP_HOST=127.0.0.1
if "%DAYANAK_MCP_PORT%"=="" set DAYANAK_MCP_PORT=8790
if "%DAYANAK_TOOL_THREADS%"=="" set DAYANAK_TOOL_THREADS=6
if "%DAYANAK_TOOL_TIMEOUT%"=="" set DAYANAK_TOOL_TIMEOUT=180
set LOGDIR=%LOCALAPPDATA%\dayanak
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "%DAYANAK_REPO%"
".venv\Scripts\python.exe" -m dayanak.server > "%LOGDIR%\mcp_http.log" 2>&1
