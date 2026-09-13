@echo off
call D:\Emsal-mcp\scripts\emsal-env.cmd
cd /d D:\Emsal-mcp
set LOG=D:\emsal-data\crawl_logs\mevzuat_post.log
echo %date% %time% POST START > %LOG%
.venv\Scripts\python.exe -X utf8 scripts\mevzuat_degisiklik_doldur.py --db %EMSAL_CACHE_PATH% > D:\emsal-data\crawl_logs\degisiklik_doldur.log 2>&1
echo %date% %time% degisiklik rc=%errorlevel% >> %LOG%
call D:\Emsal-mcp\scripts\mevzuat_semantic.cmd
echo %date% %time% semantik rc=%errorlevel% >> %LOG%
echo %date% %time% POST-EXIT 0 >> %LOG%
