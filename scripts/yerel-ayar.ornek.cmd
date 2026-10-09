@echo off
REM Makineye ozel ayarlar. Bu dosyayi scripts\yerel-ayar.cmd adiyla kopyala ve doldur;
REM yerel-ayar.cmd .gitignore'dadir. dayanak-env.cmd, crawl_incremental.ps1 ve
REM scripts\_yollar.py bu dosyadaki "set AD=deger" satirlarini okur.
REM Bos birakilan her sey %USERPROFILE%\.dayanak altindan turetilir.

REM Korpus (cache.sqlite3), loglar, model onbellegi
set DAYANAK_DATA_DIR=D:\emsal-data
REM Vektor sidecar'lari (vec, vec2), torch venv'i, yedek ciktisi
set DAYANAK_BENCH_DIR=D:\emsal-bench
REM HF veri kumesi klonu (turkish-court-decisions)
set DAYANAK_HF_DIR=D:\hf-datasets\turkish-court-decisions

REM HTTP MCP sunucusunun dinleyecegi adres (varsayilan 127.0.0.1)
set DAYANAK_MCP_HOST=127.0.0.1

REM Haftalik yedegin gidecegi makine (ssh kullanici@adres) ve oradaki dizin
set DAYANAK_YEDEK_HEDEF=kullanici@yedek-makine
set DAYANAK_YEDEK_UZAK_DIR=D:\emsal-yedek
REM run-vec-backup.cmd hedef dizini (bos: <DAYANAK_YEDEK_UZAK_DIR>-vec)
set DAYANAK_VEC_YEDEK_UZAK_DIR=
