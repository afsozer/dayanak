@echo off
cd /d D:\Emsal-mcp
set GIT_TERMINAL_PROMPT=0
set GCM_INTERACTIVE=never
echo %date% %time% PUSH START > D:\emsal-data\crawl_logs\push.log
git push origin master --tags >> D:\emsal-data\crawl_logs\push.log 2>&1
echo %date% %time% PUSH-EXIT %errorlevel% >> D:\emsal-data\crawl_logs\push.log
