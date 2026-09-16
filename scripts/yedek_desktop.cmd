@echo off
REM Haftalik yedek (Pazar 06:00, EmsalYedek): mevzuat tablolari + parquet disi kararlar + git bundle + mevzuat vektorleri + HF parquet (yalniz eksikse) -> desktop D:\emsal-yedek
call D:\Emsal-mcp\scripts\emsal-env.cmd
cd /d D:\Emsal-mcp
set LOG=D:\emsal-data\crawl_logs\yedek.log
set DST=Sozer@100.115.136.91
set OUT=D:\emsal-bench\yedek
echo %date% %time% YEDEK START > %LOG%
if not exist %OUT% mkdir %OUT%
.venv\Scripts\python.exe -X utf8 scripts\yedek_export.py %OUT% >> %LOG% 2>&1
if errorlevel 1 ( echo EXPORT HATASI >> %LOG% & echo %date% %time% YEDEK-EXIT 2 >> %LOG% & exit /b 2 )
git bundle create %OUT%\emsal-mcp.bundle --all >> %LOG% 2>&1
ssh -o BatchMode=yes %DST% "cmd /c if not exist D:\emsal-yedek\hf-datasets mkdir D:\emsal-yedek\hf-datasets" >> %LOG% 2>&1
scp -q -o BatchMode=yes %OUT%\mevzuat.sqlite3 %OUT%\karar-delta.sqlite3 %OUT%\emsal-mcp.bundle %DST%:D:/emsal-yedek/ >> %LOG% 2>&1
if errorlevel 1 ( echo SCP HATASI >> %LOG% & echo %date% %time% YEDEK-EXIT 3 >> %LOG% & exit /b 3 )
scp -q -r -o BatchMode=yes D:\emsal-data\mevzuat-vec %DST%:D:/emsal-yedek/ >> %LOG% 2>&1
ssh -o BatchMode=yes %DST% "cmd /c dir /b D:\emsal-yedek\hf-datasets\turkish-court-decisions\*.parquet 2>nul | find /c \".parquet\"" > %OUT%\_pq.txt 2>>%LOG%
set /p PQ=<%OUT%\_pq.txt
echo desktopta parquet: %PQ% >> %LOG%
if "%PQ%"=="0" scp -q -r -o BatchMode=yes D:\hf-datasets\turkish-court-decisions %DST%:D:/emsal-yedek/hf-datasets/ >> %LOG% 2>&1
ssh -o BatchMode=yes %DST% "cmd /c dir /s D:\emsal-yedek | findstr /c:\"Dosya\" /c:\"File(s)\"" >> %LOG% 2>&1
echo %date% %time% YEDEK-EXIT 0 >> %LOG%
