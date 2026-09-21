@echo off
REM emsal-mcp'yi streamable-http MCP sunucusu olarak yayinlar. Dinleme adresi EMSAL_MCP_HOST
REM (varsayilan 127.0.0.1; ag uzerinden yayin icin scripts\yerel-ayar.cmd icinde ayarla).
REM Log: %LOCALAPPDATA%\emsal-mcp\mcp_http.log
setlocal
call "%~dp0emsal-env.cmd"
set EMSAL_MCP_TRANSPORT=streamable-http
if "%EMSAL_MCP_HOST%"=="" set EMSAL_MCP_HOST=127.0.0.1
if "%EMSAL_MCP_PORT%"=="" set EMSAL_MCP_PORT=8790
if "%EMSAL_TOOL_THREADS%"=="" set EMSAL_TOOL_THREADS=6
if "%EMSAL_TOOL_TIMEOUT%"=="" set EMSAL_TOOL_TIMEOUT=180
set LOGDIR=%LOCALAPPDATA%\emsal-mcp
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "%EMSAL_REPO%"
".venv\Scripts\python.exe" -m emsal_mcp.server > "%LOGDIR%\mcp_http.log" 2>&1
