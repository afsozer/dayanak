@echo off
call "%~dp0dayanak-env.cmd"
set PYTHONUTF8=1
cd /d "%DAYANAK_REPO%"
echo %date% %time% START > %DAYANAK_LOG_DIR%\degisiklik_doldur.log
.venv\Scripts\python.exe scripts\mevzuat_degisiklik_doldur.py --db %DAYANAK_CACHE_PATH% >> %DAYANAK_LOG_DIR%\degisiklik_doldur.log 2>&1
echo %date% %time% DEGISIKLIK-EXIT %errorlevel% >> %DAYANAK_LOG_DIR%\degisiklik_doldur.log
