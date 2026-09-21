@echo off
REM Makineye ozel ayarlar. Bu dosyayi scripts\yerel-ayar.cmd adiyla kopyala ve doldur;
REM yerel-ayar.cmd .gitignore'dadir. emsal-env.cmd, crawl_incremental.ps1 ve
REM scripts\_yollar.py bu dosyadaki "set AD=deger" satirlarini okur.
REM Bos birakilan her sey %USERPROFILE%\.emsal_mcp altindan turetilir.

REM Korpus (cache.sqlite3), loglar, model onbellegi
set EMSAL_DATA_DIR=D:\emsal-data
REM Vektor sidecar'lari (vec, vec2), torch venv'i, yedek ciktisi
set EMSAL_BENCH_DIR=D:\emsal-bench
REM HF veri kumesi klonu (turkish-court-decisions)
set EMSAL_HF_DIR=D:\hf-datasets\turkish-court-decisions

REM HTTP MCP sunucusunun dinleyecegi adres (varsayilan 127.0.0.1)
set EMSAL_MCP_HOST=127.0.0.1

REM Haftalik yedegin gidecegi makine (ssh kullanici@adres) ve oradaki dizin
set EMSAL_YEDEK_HEDEF=kullanici@yedek-makine
set EMSAL_YEDEK_UZAK_DIR=D:\emsal-yedek
REM run-vec-backup.cmd hedef dizini (bos: <EMSAL_YEDEK_UZAK_DIR>-vec)
set EMSAL_VEC_YEDEK_UZAK_DIR=
