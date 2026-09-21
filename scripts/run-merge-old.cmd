@echo off
call "%~dp0emsal-env.cmd"
cd /d "%EMSAL_REPO%"
set LOG=%EMSAL_LOG_DIR%\merge_old_laptop.log
echo %date% %time% START > %LOG%
for /f "tokens=2" %%i in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().AddMinutes(-2).ToString(\"yyyy-MM-ddTHH:mm:ss\")"') do set SINCE=%%i
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().AddMinutes(-2).ToString(\"yyyy-MM-ddTHH:mm:ss\")"') do set SINCE=%%i
.venv\Scripts\python.exe -X utf8 scripts\merge_old_laptop.py >> %LOG% 2>&1
if errorlevel 1 ( echo MERGE HATASI >> %LOG% & echo %date% %time% MERGEOLD-EXIT 2 >> %LOG% & exit /b 2 )
.venv\Scripts\python.exe -X utf8 scripts\embed_new_docs.py --since %SINCE% >> %LOG% 2>&1
echo %date% %time% MERGEOLD-EXIT %errorlevel% >> %LOG%
