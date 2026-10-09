@echo off
REM Haftalik yedek (Pazar 06:00, EmsalYedek): mevzuat tablolari + parquet disi kararlar + git bundle + mevzuat vektorleri + HF parquet (yalniz eksikse) -> yedek makinesi (DAYANAK_YEDEK_HEDEF)
call "%~dp0dayanak-env.cmd"
cd /d "%DAYANAK_REPO%"
set LOG=%DAYANAK_LOG_DIR%\yedek.log
set DST=%DAYANAK_YEDEK_HEDEF%
if "%DST%"=="" ( echo DAYANAK_YEDEK_HEDEF tanimsiz, bkz. scripts\yerel-ayar.ornek.cmd >> %LOG% & exit /b 9 )
set UZAK=%DAYANAK_YEDEK_UZAK_DIR%
set UZAKSCP=%UZAK:\=/%
set OUT=%DAYANAK_BENCH_DIR%\yedek
echo %date% %time% YEDEK START > %LOG%
if not exist %OUT% mkdir %OUT%
.venv\Scripts\python.exe -X utf8 -u scripts\yedek_export.py %OUT% >> %LOG% 2>&1
if errorlevel 1 ( echo EXPORT HATASI >> %LOG% & echo %date% %time% YEDEK-EXIT 2 >> %LOG% & exit /b 2 )
git bundle create %OUT%\dayanak.bundle --all >> %LOG% 2>&1
ssh -o BatchMode=yes %DST% "cmd /c if not exist %UZAK%\hf-datasets mkdir %UZAK%\hf-datasets" >> %LOG% 2>&1
scp -q -o BatchMode=yes %OUT%\mevzuat.sqlite3 %OUT%\karar-delta.sqlite3 %OUT%\dayanak.bundle %DST%:%UZAKSCP%/ >> %LOG% 2>&1
if errorlevel 1 ( echo SCP HATASI >> %LOG% & echo %date% %time% YEDEK-EXIT 3 >> %LOG% & exit /b 3 )
scp -q -r -o BatchMode=yes %DAYANAK_DATA_DIR%\mevzuat-vec %DST%:%UZAKSCP%/ >> %LOG% 2>&1
REM HF parquet (5,1 GB) yalniz bir kez kopyalanir; basari isareti laptopta _pq_done.txt
if exist %OUT%\_pq_done.txt ( echo parquet zaten kopyali >> %LOG% ) else (
  scp -q -r -o BatchMode=yes %DAYANAK_HF_DIR% %DST%:%UZAKSCP%/hf-datasets/ >> %LOG% 2>&1
  if not errorlevel 1 ( echo kopyalandi > %OUT%\_pq_done.txt & echo parquet kopyalandi >> %LOG% ) else ( echo PARQUET KOPYA HATASI >> %LOG% )
)
ssh -o BatchMode=yes %DST% "cmd /c dir /s %UZAK% | findstr /c:\"Dosya\" /c:\"File(s)\"" >> %LOG% 2>&1
echo %date% %time% YEDEK-EXIT 0 >> %LOG%
