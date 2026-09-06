@echo off
REM EmsalReembed: tek seferlik yeniden gomme gorevi (parcalama v2).
REM Varsayilan 7 Eylul 2026 23:00; baska zaman icin: kur-reembed-gorevi.cmd 08.09.2026 23:00
REM /rl limited: yukseltilmis haklara gerek yok (D: uzerinde dosya yazimi + schtasks /end,/run).
setlocal
set SD=%1
set ST=%2
if "%SD%"=="" set SD=07.09.2026
if "%ST%"=="" set ST=23:00
schtasks /create /tn EmsalReembed /tr "cmd /c D:\Emsal-mcp\scripts\reembed_all.cmd" /sc once /sd %SD% /st %ST% /rl limited /f
if errorlevel 1 ( echo GOREV OLUSTURULAMADI & exit /b 1 )
schtasks /query /tn EmsalReembed /fo list
