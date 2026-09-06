@echo off
set PYTHONUTF8=1
cd /d D:\Emsal-mcp
echo %date% %time% START > D:\emsal-data\crawl_logs\ust_baslik_doldur.log
D:\Emsal-mcp\.venv\Scripts\python.exe scripts\mevzuat_ust_baslik_doldur.py --db D:\emsal-data\cache.sqlite3 >> D:\emsal-data\crawl_logs\ust_baslik_doldur.log 2>&1
echo %date% %time% USTBASLIK-EXIT %errorlevel% >> D:\emsal-data\crawl_logs\ust_baslik_doldur.log
