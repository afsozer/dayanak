@echo off
call "%~dp0dayanak-env.cmd"
call "%~dp0mevzuat_semantic.cmd"
echo %date% %time% SEMANTIC-EXIT %errorlevel% >> %DAYANAK_LOG_DIR%\mevzuat_semantic_marker.log
