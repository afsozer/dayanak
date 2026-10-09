@echo off
call "%~dp0dayanak-env.cmd"
cd /d "%DAYANAK_REPO%"
set GIT_TERMINAL_PROMPT=0
set GCM_INTERACTIVE=never
echo %date% %time% PUSH START > %DAYANAK_LOG_DIR%\push.log
git push origin master --tags >> %DAYANAK_LOG_DIR%\push.log 2>&1
echo %date% %time% PUSH-EXIT %errorlevel% >> %DAYANAK_LOG_DIR%\push.log
