@echo off
set PYTHONUTF8=1
call "%~dp0dayanak-env.cmd"
cd /d "%DAYANAK_REPO%"
set LOG=%DAYANAK_LOG_DIR%\reembed_switch.log
echo %date% %time% SWITCH START >> %DAYANAK_LOG_DIR%\reembed_switch_console.log
.venv\Scripts\python.exe -X utf8 scripts\reembed_switch.py --log %LOG% >> %DAYANAK_LOG_DIR%\reembed_switch_console.log 2>&1
echo %date% %time% SWITCH-EXIT %errorlevel% >> %LOG%
