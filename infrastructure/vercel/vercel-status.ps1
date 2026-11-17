<# Growth IA - etat des derniers deploiements Vercel du projet lie (ecrit logs\vercel-status.txt) #>
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$token = (Get-Content (Join-Path $Root ".vercel-token") -Raw).Trim()
$p = Get-Content (Join-Path $Root ".vercel\project.json") -Raw | ConvertFrom-Json
$h = @{ Authorization = "Bearer $token" }
$out = @()
$d = Invoke-RestMethod -Headers $h -Uri "https://api.vercel.com/v6/deployments?projectId=$($p.projectId)&teamId=$($p.orgId)&limit=5"
foreach ($x in $d.deployments) { $out += "{0} | {1} | {2} | https://{3} | {4}" -f $x.uid, $x.state, $x.target, $x.url, ([DateTimeOffset]::FromUnixTimeMilliseconds($x.created).ToLocalTime().ToString("HH:mm:ss")) }
$proj = Invoke-RestMethod -Headers $h -Uri "https://api.vercel.com/v9/projects/$($p.projectId)?teamId=$($p.orgId)"
$out += "domains: " + (($proj.targets.production.alias) -join ", ")
$out += "envs: " + (Invoke-RestMethod -Headers $h -Uri "https://api.vercel.com/v9/projects/$($p.projectId)/env?teamId=$($p.orgId)").envs.Count
if ($d.deployments.Count -gt 0) {
  $ev = Invoke-RestMethod -Headers $h -Uri "https://api.vercel.com/v3/deployments/$($d.deployments[0].uid)/events?teamId=$($p.orgId)&limit=-1&builds=1"
  $out += "--- events (last 40) ---"
  $out += ($ev | Select-Object -Last 40 | ForEach-Object { $_.text })
}
$out | Set-Content -Encoding UTF8 (Join-Path $Root "logs\vercel-status.txt")
Get-Content (Join-Path $Root "logs\vercel-status.txt")
