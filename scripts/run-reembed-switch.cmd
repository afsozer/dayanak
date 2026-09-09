@echo off
set PYTHONUTF8=1
call D:\Emsal-mcp\scripts\emsal-env.cmd
cd /d D:\Emsal-mcp
set LOG=D:\emsal-data\crawl_logs\reembed_switch.log
echo %date% %time% SWITCH START >> D:\emsal-data\crawl_logs\reembed_switch_console.log
.venv\Scripts\python.exe -X utf8 scripts\reembed_switch.py --log %LOG% >> D:\emsal-data\crawl_logs\reembed_switch_console.log 2>&1
echo %date% %time% SWITCH-EXIT %errorlevel% >> %LOG%
