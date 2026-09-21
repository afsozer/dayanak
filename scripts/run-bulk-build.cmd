@echo off
setlocal
call "%~dp0emsal-env.cmd"
cd /d "%EMSAL_REPO%"
echo %date% %time% basladi > %EMSAL_DATA_DIR%\bulk-build.log
.venv\Scripts\emsal-mcp.exe semantic bulk-build %EMSAL_BULK_VEC_DIR% >> %EMSAL_DATA_DIR%\bulk-build.log 2>&1
echo %date% %time% BUILD-EXIT %errorlevel% >> %EMSAL_DATA_DIR%\bulk-build.log
