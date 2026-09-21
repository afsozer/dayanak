# EmsalMcpHttp saglik kontrolu: streamable-http ucu GET'e 406 (Not Acceptable) doner.
# Kullanim: powershell -NoProfile -ExecutionPolicy Bypass -File reembed_health.ps1 [-Url ...] [-Retries 12]
param(
  [string]$Url = "",
  [int]$Retries = 12,
  [int]$DelaySec = 5
)
# Adres: -Url > EMSAL_MCP_HOST/EMSAL_MCP_PORT (reembed_switch.py yerel-ayar.cmd'den aktarir) > 127.0.0.1:8790
if (-not $Url) {
  $h = if ($env:EMSAL_MCP_HOST) { $env:EMSAL_MCP_HOST } else { "127.0.0.1" }
  $p = if ($env:EMSAL_MCP_PORT) { $env:EMSAL_MCP_PORT } else { "8790" }
  $Url = "http://${h}:${p}/mcp"
}
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
