@echo off
call D:\Emsal-mcp\scripts\mevzuat_semantic.cmd
echo %date% %time% SEMANTIC-EXIT %errorlevel% >> D:\emsal-data\crawl_logs\mevzuat_semantic_marker.log
