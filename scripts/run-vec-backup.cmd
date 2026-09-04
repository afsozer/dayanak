@echo off
echo %date% %time% basladi > D:\emsal-data\vec-backup.log
ssh -o StrictHostKeyChecking=accept-new Sozer@100.115.136.91 "mkdir D:\emsal-vec-backup 2>nul & echo ok" >> D:\emsal-data\vec-backup.log 2>&1
scp -q -o StrictHostKeyChecking=accept-new D:\emsal-bench\vec\*.npy D:\emsal-bench\vec\*.parquet D:\emsal-bench\vec\*.json Sozer@100.115.136.91:D:/emsal-vec-backup/ >> D:\emsal-data\vec-backup.log 2>&1
echo %date% %time% BACKUP-EXIT %errorlevel% >> D:\emsal-data\vec-backup.log
