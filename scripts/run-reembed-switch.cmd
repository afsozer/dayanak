@echo off
set PYTHONUTF8=1
call "%~dp0emsal-env.cmd"
cd /d "%EMSAL_REPO%"
set LOG=%EMSAL_LOG_DIR%\reembed_switch.log
echo %date% %time% SWITCH START >> %EMSAL_LOG_DIR%\reembed_switch_console.log
.venv\Scripts\python.exe -X utf8 scripts\reembed_switch.py --log %LOG% >> %EMSAL_LOG_DIR%\reembed_switch_console.log 2>&1
echo %date% %time% SWITCH-EXIT %errorlevel% >> %LOG%
