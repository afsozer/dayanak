@echo off
call "%~dp0emsal-env.cmd"
call "%~dp0mevzuat_semantic.cmd"
echo %date% %time% SEMANTIC-EXIT %errorlevel% >> %EMSAL_LOG_DIR%\mevzuat_semantic_marker.log
