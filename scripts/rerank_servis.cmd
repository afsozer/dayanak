@echo off
REM Yeniden siralayici servisi (scripts\rerank_servis.py): torch'lu ortamda, Dayanak sunucusundan ayri surec.
REM Gorev: EmsalRerank (oturum acilisinda). Log: %LOCALAPPDATA%\dayanak\rerank.log
REM Dayanak tarafi: yerel-ayar.cmd icinde DAYANAK_RERANK_URL=http://127.0.0.1:8791
setlocal
call "%~dp0dayanak-env.cmd"
if "%DAYANAK_RERANK_HF_CACHE%"=="" set DAYANAK_RERANK_HF_CACHE=%DAYANAK_BENCH_DIR%\models
set HF_HUB_CACHE=%DAYANAK_RERANK_HF_CACHE%
REM model yerel onbellekten: acilista ag yoksa takilmasin, yeniden indirmesin
set HF_HUB_OFFLINE=1
set HF_HUB_DISABLE_TELEMETRY=1
set LOGDIR=%LOCALAPPDATA%\dayanak
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
"%DAYANAK_TORCH_PY%" -u "%~dp0rerank_servis.py" > "%LOGDIR%\rerank.log" 2>&1
