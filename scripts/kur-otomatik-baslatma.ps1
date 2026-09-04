# Emsal crawl + panel icin Windows Zamanlanmis Gorev kurulumu.
#
#   .\scripts\kur-otomatik-baslatma.ps1           -> kurar (varsa gunceller)
#   .\scripts\kur-otomatik-baslatma.ps1 -Durum    -> gorevlerin durumunu yazar
#   .\scripts\kur-otomatik-baslatma.ps1 -Kaldir   -> gorevleri siler
#
# Yonetici gerekmez: gorevler kullanici oturumunda calisir.
#
# EmsalCrawlMaster : oturum acilisindan 1 dk sonra crawl_master.ps1'i baslatir.
#                    Master kendi mutex kilidini tuttugu icin gorev yanlislikla
#                    iki kez tetiklense bile ikinci ornek hemen cikar.
# EmsalPanel       : paneli 127.0.0.1:8799'da baslatir (pencere acmaz).

param(
    [switch]$Kaldir,
    [switch]$Durum
)

$ErrorActionPreference = 'Stop'

$root       = Split-Path -Parent $PSScriptRoot
$master     = Join-Path $root 'crawl_master.ps1'
$panel      = Join-Path $root 'scripts\panel.py'
$pythonw    = Join-Path $root '.venv\Scripts\pythonw.exe'
$pwshPath   = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwshPath) { $pwshPath = 'C:\Program Files\PowerShell\7\pwsh.exe' }
$crawlTask  = 'EmsalCrawlMaster'
$panelTask  = 'EmsalPanel'

function Kisayol-Yollari {
    # Masaustu OneDrive'a yonlendirilmis olabilir; kayittan gercek yolu al.
    @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Emsal Paneli.url'),
        (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Emsal Paneli.url')
    )
}

function Yaz-Durum {
    foreach ($ad in @($crawlTask, $panelTask)) {
        $g = Get-ScheduledTask -TaskName $ad -ErrorAction SilentlyContinue
        if (-not $g) { Write-Host "  $ad : KURULU DEGIL"; continue }
        $bilgi = Get-ScheduledTaskInfo -TaskName $ad
        Write-Host ("  {0,-18} durum={1}  son calisma={2}  sonuc={3}" -f `
            $ad, $g.State, $bilgi.LastRunTime, $bilgi.LastTaskResult)
    }
}

if ($Durum) {
    Write-Host 'Zamanlanmis gorevler:'
    Yaz-Durum
    $mutex = [System.Threading.Mutex]::new($false, 'Local\EmsalCrawlMaster')
    $bos = $mutex.WaitOne(0)
    if ($bos) { $mutex.ReleaseMutex(); Write-Host '  crawl master : CALISMIYOR' }
    else      { Write-Host '  crawl master : CALISIYOR' }
    $mutex.Dispose()
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8799/api/saglik' -TimeoutSec 3 -UseBasicParsing
        Write-Host "  panel        : AYAKTA ($($r.StatusCode)) -> http://127.0.0.1:8799"
    } catch {
        Write-Host '  panel        : ERISILEMIYOR'
    }
    return
}

if ($Kaldir) {
    foreach ($ad in @($crawlTask, $panelTask)) {
        if (Get-ScheduledTask -TaskName $ad -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $ad -Confirm:$false
            Write-Host "Silindi: $ad"
        }
    }
    foreach ($k in (Kisayol-Yollari)) {
        if (Test-Path $k) { Remove-Item $k -Force; Write-Host "Kisayol silindi: $k" }
    }
    return
}

# ---- on kontroller ----------------------------------------------------------
foreach ($p in @($master, $panel, $pythonw, $pwshPath)) {
    if (-not (Test-Path $p)) { throw "Bulunamadi: $p" }
}

# ---- ortak ayarlar ----------------------------------------------------------
# ExecutionTimeLimit 0  : gunlerce surecek crawl'i Windows kesmesin
# RestartCount/Interval : cokerse kendiliginden geri gelsin
# MultipleInstances Ignore: gorev iki kez tetiklenirse ikincisi acilmasin
$ayar = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -DontStopOnIdleEnd `
    -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$asIslemci = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

# ---- crawl gorevi -----------------------------------------------------------
$crawlEylem = New-ScheduledTaskAction -Execute $pwshPath `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$master`"" `
    -WorkingDirectory $root

$crawlTetik = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$crawlTetik.Delay = 'PT1M'   # ag/Tailscale ayaga kalksin diye 1 dk gecikme

Register-ScheduledTask -TaskName $crawlTask -Action $crawlEylem -Trigger $crawlTetik `
    -Settings $ayar -Principal $asIslemci -Force `
    -Description 'Emsal korpus crawl master (rate limit 12, kaldigi sayfadan devam eder)' | Out-Null
Write-Host "Kuruldu: $crawlTask (oturum acilisi + 1 dk)"

# ---- panel gorevi -----------------------------------------------------------
$panelEylem = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "`"$panel`"" -WorkingDirectory $root

$panelTetik = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$panelTetik.Delay = 'PT20S'

Register-ScheduledTask -TaskName $panelTask -Action $panelEylem -Trigger $panelTetik `
    -Settings $ayar -Principal $asIslemci -Force `
    -Description 'Emsal kutuphane paneli — http://127.0.0.1:8799' | Out-Null
Write-Host "Kuruldu: $panelTask (http://127.0.0.1:8799)"

# ---- masaustu + baslat menusu kisayollari -----------------------------------
# Ikon icin taraycinin exe'si en anlasiliri; yoksa Windows'un internet ikonu.
$ikon = @(
    'C:\Program Files\Google\Chrome\Application\chrome.exe',
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$ikonSatiri = if ($ikon) { "IconFile=$ikon`nIconIndex=0" }
              else { "IconFile=$env:SystemRoot\System32\shell32.dll`nIconIndex=14" }

foreach ($kisayol in (Kisayol-Yollari)) {
    "[InternetShortcut]`nURL=http://127.0.0.1:8799`n$ikonSatiri" |
        Set-Content -Path $kisayol -Encoding ascii
    Write-Host "Kisayol: $kisayol"
}

Write-Host ''
Write-Host 'Durum:'
Yaz-Durum
