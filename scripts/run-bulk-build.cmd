@echo off
setlocal
call D:\Emsal-mcp\scripts\emsal-env.cmd
cd /d D:\Emsal-mcp
echo %date% %time% basladi > D:\emsal-data\bulk-build.log
.venv\Scripts\emsal-mcp.exe semantic bulk-build D:\emsal-bench\vec >> D:\emsal-data\bulk-build.log 2>&1
echo %date% %time% BUILD-EXIT %errorlevel% >> D:\emsal-data\bulk-build.log
