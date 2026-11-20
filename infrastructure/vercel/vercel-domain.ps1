<#
  Growth IA - rattache un domaine personnalise au projet Vercel et indique l'enregistrement DNS a creer.
  Ecrit le resultat dans logs\vercel-domain.txt.
  Usage : powershell -ExecutionPolicy Bypass -File infrastructure\vercel\vercel-domain.ps1 -Domain growthai.zirconai.fr
#>
param([Parameter(Mandatory = $true)][string]$Domain, [string]$Project = "growth-ia")
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Domain = $Domain.Trim().ToLower()
$token = (Get-Content (Join-Path $Root ".vercel-token") -Raw).Trim()
$p = Get-Content (Join-Path $Root ".vercel\project.json") -Raw | ConvertFrom-Json
$h = @{ Authorization = "Bearer $token" }
$t = "teamId=$($p.orgId)"
$api = "https://api.vercel.com"
$out = @("Domaine : $Domain", "Projet : $($p.projectName) ($($p.projectId))")

try {
  $r = Invoke-RestMethod -Method Post -Headers $h -ContentType "application/json" -Uri "$api/v10/projects/$($p.projectId)/domains?$t" -Body (@{ name = $Domain } | ConvertTo-Json)
  $out += "Ajout au projet : OK (verified=$($r.verified))"
} catch {
  $msg = $_.ErrorDetails.Message
  if ($msg -match "already") { $out += "Ajout au projet : deja present" } else { $out += "Ajout au projet : ERREUR $msg" }
}
try {
  $d = Invoke-RestMethod -Headers $h -Uri "$api/v9/projects/$($p.projectId)/domains/$Domain`?$t"
  $out += "verified=$($d.verified)"
  if ($d.verification) { $out += "Verification requise :"; $d.verification | ForEach-Object { $out += "  $($_.type) $($_.domain) -> $($_.value)" } }
} catch { $out += "Lecture du domaine : ERREUR $($_.ErrorDetails.Message)" }
try {
  $c = Invoke-RestMethod -Headers $h -Uri "$api/v6/domains/$Domain/config?$t"
  $out += "misconfigured=$($c.misconfigured)  configuredBy=$($c.configuredBy)"
  if ($c.recommendedCNAME) { $out += "CNAME recommande : " + (($c.recommendedCNAME | ForEach-Object { $_.value }) -join ", ") }
  if ($c.recommendedIPv4) { $out += "A recommande : " + (($c.recommendedIPv4 | ForEach-Object { $_.value -join "," }) -join " ") }
} catch { $out += "Config DNS : ERREUR $($_.ErrorDetails.Message)" }

$apex = ($Domain -split "\.")[-2..-1] -join "."
$out += "--- DNS actuel ---"
try { $out += "NS $apex : " + ((Resolve-DnsName $apex -Type NS -ErrorAction Stop | Where-Object { $_.NameHost } | ForEach-Object { $_.NameHost }) -join ", ") } catch { $out += "NS $apex : $($_.Exception.Message)" }
try { $out += "$Domain : " + ((Resolve-DnsName $Domain -ErrorAction Stop | ForEach-Object { "$($_.Type) $($_.NameHost)$($_.IPAddress)" }) -join " | ") } catch { $out += "$Domain : pas encore d'enregistrement DNS" }
$out | Set-Content -Encoding UTF8 (Join-Path $Root "logs\vercel-domain.txt")
$out
