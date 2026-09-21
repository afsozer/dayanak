@echo off
call "%~dp0emsal-env.cmd"
set PYTHONUTF8=1
cd /d "%EMSAL_REPO%"
echo %date% %time% START > %EMSAL_LOG_DIR%\ust_baslik_doldur.log
.venv\Scripts\python.exe scripts\mevzuat_ust_baslik_doldur.py --db %EMSAL_CACHE_PATH% >> %EMSAL_LOG_DIR%\ust_baslik_doldur.log 2>&1
echo %date% %time% USTBASLIK-EXIT %errorlevel% >> %EMSAL_LOG_DIR%\ust_baslik_doldur.log
