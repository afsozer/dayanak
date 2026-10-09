@echo off
call "%~dp0dayanak-env.cmd"
set LOG=%DAYANAK_DATA_DIR%\vec-backup.log
if "%DAYANAK_YEDEK_HEDEF%"=="" ( echo DAYANAK_YEDEK_HEDEF tanimsiz, bkz. scripts\yerel-ayar.ornek.cmd & exit /b 9 )
if "%DAYANAK_VEC_YEDEK_UZAK_DIR%"=="" set DAYANAK_VEC_YEDEK_UZAK_DIR=%DAYANAK_YEDEK_UZAK_DIR%-vec
set UZAKSCP=%DAYANAK_VEC_YEDEK_UZAK_DIR:\=/%
echo %date% %time% basladi > %LOG%
ssh -o StrictHostKeyChecking=accept-new %DAYANAK_YEDEK_HEDEF% "mkdir %DAYANAK_VEC_YEDEK_UZAK_DIR% 2>nul & echo ok" >> %LOG% 2>&1
scp -q -o StrictHostKeyChecking=accept-new %DAYANAK_BULK_VEC_DIR%\*.npy %DAYANAK_BULK_VEC_DIR%\*.parquet %DAYANAK_BULK_VEC_DIR%\*.json %DAYANAK_YEDEK_HEDEF%:%UZAKSCP%/ >> %LOG% 2>&1
echo %date% %time% BACKUP-EXIT %errorlevel% >> %LOG%
