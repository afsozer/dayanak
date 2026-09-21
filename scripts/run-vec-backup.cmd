@echo off
call "%~dp0emsal-env.cmd"
set LOG=%EMSAL_DATA_DIR%\vec-backup.log
if "%EMSAL_YEDEK_HEDEF%"=="" ( echo EMSAL_YEDEK_HEDEF tanimsiz, bkz. scripts\yerel-ayar.ornek.cmd & exit /b 9 )
if "%EMSAL_VEC_YEDEK_UZAK_DIR%"=="" set EMSAL_VEC_YEDEK_UZAK_DIR=%EMSAL_YEDEK_UZAK_DIR%-vec
set UZAKSCP=%EMSAL_VEC_YEDEK_UZAK_DIR:\=/%
echo %date% %time% basladi > %LOG%
ssh -o StrictHostKeyChecking=accept-new %EMSAL_YEDEK_HEDEF% "mkdir %EMSAL_VEC_YEDEK_UZAK_DIR% 2>nul & echo ok" >> %LOG% 2>&1
scp -q -o StrictHostKeyChecking=accept-new %EMSAL_BULK_VEC_DIR%\*.npy %EMSAL_BULK_VEC_DIR%\*.parquet %EMSAL_BULK_VEC_DIR%\*.json %EMSAL_YEDEK_HEDEF%:%UZAKSCP%/ >> %LOG% 2>&1
echo %date% %time% BACKUP-EXIT %errorlevel% >> %LOG%
