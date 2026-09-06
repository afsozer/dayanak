# EmsalMcpHttp saglik kontrolu: streamable-http ucu GET'e 406 (Not Acceptable) doner.
# Kullanim: powershell -NoProfile -ExecutionPolicy Bypass -File reembed_health.ps1 [-Url ...] [-Retries 12]
param(
  [string]$Url = "http://100.77.229.110:8790/mcp",
  [int]$Retries = 12,
  [int]$DelaySec = 5
)
for ($i = 1; $i -le $Retries; $i++) {
  $code = 0
  try {
    $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
    $code = [int]$r.StatusCode
  } catch {
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
  }
  Write-Output ("deneme {0}/{1}: {2} -> {3}" -f $i, $Retries, $Url, $code)
  if ($code -eq 406 -or ($code -ge 200 -and $code -lt 300)) { exit 0 }
  Start-Sleep -Seconds $DelaySec
}
Write-Output "SAGLIK BASARISIZ"
exit 1
