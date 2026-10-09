@echo off
call "%~dp0dayanak-env.cmd"
cd /d "%DAYANAK_REPO%"
set LOG=%DAYANAK_LOG_DIR%\mevzuat_post.log
echo %date% %time% POST START > %LOG%
.venv\Scripts\python.exe -X utf8 scripts\mevzuat_degisiklik_doldur.py --db %DAYANAK_CACHE_PATH% > %DAYANAK_LOG_DIR%\degisiklik_doldur.log 2>&1
echo %date% %time% degisiklik rc=%errorlevel% >> %LOG%
call "%~dp0mevzuat_semantic.cmd"
echo %date% %time% semantik rc=%errorlevel% >> %LOG%
echo %date% %time% POST-EXIT 0 >> %LOG%
