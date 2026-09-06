@echo off
set PYTHONUTF8=1
cd /d D:\Emsal-mcp
echo %date% %time% START > D:\emsal-data\crawl_logs\degisiklik_doldur.log
D:\Emsal-mcp\.venv\Scripts\python.exe scripts\mevzuat_degisiklik_doldur.py --db D:\emsal-data\cache.sqlite3 >> D:\emsal-data\crawl_logs\degisiklik_doldur.log 2>&1
echo %date% %time% DEGISIKLIK-EXIT %errorlevel% >> D:\emsal-data\crawl_logs\degisiklik_doldur.log
