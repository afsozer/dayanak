@echo off
setlocal
call "%~dp0dayanak-env.cmd"
cd /d "%DAYANAK_REPO%"
echo %date% %time% basladi > %DAYANAK_DATA_DIR%\bulk-build.log
.venv\Scripts\dayanak.exe semantic bulk-build %DAYANAK_BULK_VEC_DIR% >> %DAYANAK_DATA_DIR%\bulk-build.log 2>&1
echo %date% %time% BUILD-EXIT %errorlevel% >> %DAYANAK_DATA_DIR%\bulk-build.log
