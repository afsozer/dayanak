@echo off
call "%~dp0emsal-env.cmd"
cd /d "%EMSAL_REPO%"
set GIT_TERMINAL_PROMPT=0
set GCM_INTERACTIVE=never
echo %date% %time% PUSH START > %EMSAL_LOG_DIR%\push.log
git push origin master --tags >> %EMSAL_LOG_DIR%\push.log 2>&1
echo %date% %time% PUSH-EXIT %errorlevel% >> %EMSAL_LOG_DIR%\push.log
