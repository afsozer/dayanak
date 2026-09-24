# Gunluk artimli crawl (korpus sunucusu). HF korpusu (kesim: Yargitay May 2026, Emsal Haz 2026)
# tabani sagliyor; bu betik yalniz YENI yayimlanan kararlari ceker.
#   * Son N ay, ay pencereleriyle (Bedesten sortDirection guvenilmez; pencere sart)
#   * 5 tur: YARGITAYKARARI ISTINAFHUKUK YERELHUKUK DANISTAYKARAR KYB
#   * --incremental: cache'deki karar icin tam metin cekmez, ust uste 300 gorulmusse durur
#   * Sonra yeni kararlar dense delta indeksine gomulur (embed_new_docs.py) ve
#     hizli matris yenilenir (semantic build-matrix). Toplu FAISS indeksi degismez.
param([int]$Ay = 3, [int]$IstekLimiti = 10, [int]$MaxDocs = 2000, [int]$MaxPages = 150)
$ErrorActionPreference = 'Continue'
$root   = Split-Path -Parent $PSScriptRoot
# Makineye ozel yollar: ortam degiskeni > scripts\yerel-ayar.cmd ("set AD=deger") > ~\.emsal_mcp
$yerel = Join-Path $PSScriptRoot 'yerel-ayar.cmd'
if (Test-Path $yerel) {
    foreach ($s in Get-Content $yerel) {
        # -cmatch (buyuk/kucuk harf duyarli) SART: -match kulturu kullanir; tr-TR'de
        # 'I' kucultulunce noktasiz i olur ve [A-Za-z]'ye girmez, adinda I gecen her
        # degisken (EMSAL_DATA_DIR ...) sessizce atlanir (22-24 Eyl crawl'i ~\.emsal_mcp'ye yazdi).
        if ($s -cmatch '^\s*[Ss][Ee][Tt]\s+([A-Za-z_][A-Za-z0-9_]*)=(.+?)\s*$' -and -not [Environment]::GetEnvironmentVariable($Matches[1])) {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2])
        }
    }
}
function Varsayilan($ad, $deger) { if (-not [Environment]::GetEnvironmentVariable($ad)) { [Environment]::SetEnvironmentVariable($ad, $deger) } }
Varsayilan 'EMSAL_DATA_DIR' (Join-Path $HOME '.emsal_mcp')
Varsayilan 'EMSAL_BENCH_DIR' (Join-Path $env:EMSAL_DATA_DIR 'bench')
Varsayilan 'EMSAL_LOG_DIR' (Join-Path $env:EMSAL_DATA_DIR 'crawl_logs')
$logDir = $env:EMSAL_LOG_DIR
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("crawl_" + (Get-Date -Format 'yyyyMMdd_HHmm') + '.log')
function L($m) { $line = (Get-Date -Format 'HH:mm:ss') + ' ' + $m; $line | Tee-Object -FilePath $log -Append | Out-Null; Write-Host $line }

$mutex = [System.Threading.Mutex]::new($false, 'Local\EmsalCrawlDaily')
if (-not $mutex.WaitOne(0)) { L 'zaten calisiyor, cikiyorum'; exit 0 }

$env:PYTHONIOENCODING = 'utf-8'
Varsayilan 'EMSAL_CACHE_PATH' (Join-Path $env:EMSAL_DATA_DIR 'cache.sqlite3')
Varsayilan 'EMSAL_BULK_VEC_DIR' (Join-Path $env:EMSAL_BENCH_DIR 'vec')
Varsayilan 'EMSAL_EMBEDDING_PROVIDER' 'fastembed-multilingual-e5'
Varsayilan 'EMSAL_EMBEDDING_CACHE_DIR' (Join-Path $env:EMSAL_DATA_DIR 'models\fastembed')
$env:EMSAL_RATE_LIMIT_MAX = "$IstekLimiti"
$py = Join-Path $root '.venv\Scripts\python.exe'
Set-Location $root
$runStart = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss')
L "basladi; ay=$Ay limit=$IstekLimiti"

$types = @('YARGITAYKARARI', 'ISTINAFHUKUK', 'YERELHUKUK', 'DANISTAYKARAR', 'KYB')
$totalStored = 0
for ($m = 0; $m -lt $Ay; $m++) {
    $first = (Get-Date -Day 1).AddMonths(-$m)
    $last  = $first.AddMonths(1).AddSeconds(-1)
    $sd = $first.ToString('yyyy-MM-ddT00:00:00.000Z'); $ed = $last.ToString('yyyy-MM-ddT23:59:59.999Z')
    foreach ($t in $types) {
        $page = 1; $calls = 0
        while ($calls -lt 8) {
            $calls++
            $out = & $py -X utf8 -m emsal_mcp.cli corpus crawl --item-type $t --incremental --sort desc `
                --start-date $sd --end-date $ed --start-page $page --max-docs $MaxDocs --max-pages $MaxPages `
                --stop-after-seen 300 --json 2>&1 | Out-String
            try { $j = ($out -replace '^[^{]*', '') | ConvertFrom-Json } catch { L "$t $($first.ToString('yyyy-MM')): JSON yok: $($out.Substring(0,[Math]::Min(300,$out.Length)))"; Start-Sleep 60; continue }
            $totalStored += [int]$j.stored
            L ("{0} {1}: stored={2} scanned={3} cached={4} reason={5} next_page={6} 429={7} {8}s" -f $t, $first.ToString('yyyy-MM'), $j.stored, $j.scanned, $j.skipped_cached, $j.stopped_reason, $j.next_page, $j.rate_limit_retries, $j.time_seconds)
            if ($j.stopped_reason -in @('max_docs', 'max_pages') -and $j.next_page -gt $page) { $page = [int]$j.next_page; continue }
            if ($j.stopped_reason -match 'error|exception|solr') { Start-Sleep 300; continue }
            break
        }
    }
}
L "crawl bitti: toplam yeni $totalStored karar"
if ($totalStored -gt 0) {
    L 'dense delta gomme'
    & $py -X utf8 scripts\embed_new_docs.py --since $runStart 2>&1 | ForEach-Object { L "  $_" }
    L 'build-matrix'
    & $py -X utf8 -m emsal_mcp.cli semantic build-matrix --json 2>&1 | Select-Object -Last 3 | ForEach-Object { L "  $_" }
}
L 'BITTI'
