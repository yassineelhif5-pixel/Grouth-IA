<#
  Growth IA - pousse les variables d'environnement vers Vercel (production + preview).
  - Jeton : fichier .vercel-token a la racine du projet (cree sur https://vercel.com/account/tokens).
  - Valeurs : fichier .env.vercel a la racine (CLE=valeur, une par ligne ; jamais commite).
  - Cree le projet Vercel s'il n'existe pas, puis met a jour chaque variable (upsert, chiffree).
  Usage : powershell -ExecutionPolicy Bypass -File infrastructure\vercel\vercel-env.ps1 [-Project growth-ia]
#>
param([string]$Project = "growth-ia", [string]$EnvFile = ".env.vercel", [string]$Scope = "")
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$tokenFile = Join-Path $Root ".vercel-token"
if (-not (Test-Path $tokenFile) -or -not (Get-Content $tokenFile -Raw).Trim()) {
  Write-Host "Jeton Vercel manquant : collez-le dans le fichier .vercel-token a la racine du projet." -ForegroundColor Red; exit 1
}
$token = (Get-Content $tokenFile -Raw).Trim()
$headers = @{ Authorization = "Bearer $token" }
$api = "https://api.vercel.com"

if (-not $Scope) { $scopeFile = Join-Path $Root ".vercel-scope"; if (Test-Path $scopeFile) { $Scope = (Get-Content $scopeFile -Raw).Trim() } }
$teamQs = ""
if ($Scope) {
  $teams = (Invoke-RestMethod -Headers $headers -Uri "$api/v2/teams?limit=100").teams
  $team = $teams | Where-Object { $_.slug -eq $Scope -or $_.id -eq $Scope }
  if (-not $team) {
    Write-Host "Le jeton n'a pas acces au compte/equipe Vercel '$Scope'." -ForegroundColor Red
    Write-Host ("Comptes accessibles avec ce jeton : " + (($teams | ForEach-Object { $_.slug }) -join ", ")) -ForegroundColor Yellow
    Write-Host "Creez le jeton depuis le compte '$Scope' (https://vercel.com/account/tokens, portee : $Scope)." -ForegroundColor Yellow
    exit 2
  }
  $teamQs = "teamId=$($team.id)"
  Write-Host "Cible Vercel : $($team.slug) ($($team.id))" -ForegroundColor Cyan
}
function Url([string]$path, [string]$qs = "") { $q = @($qs, $teamQs) | Where-Object { $_ }; if ($q) { "$api$path`?" + ($q -join "&") } else { "$api$path" } }

$me = Invoke-RestMethod -Headers $headers -Uri (Url "/v2/user")
Write-Host "Compte Vercel : $($me.user.username)" -ForegroundColor Cyan

try {
  $proj = Invoke-RestMethod -Headers $headers -Uri (Url "/v9/projects/$Project")
  Write-Host "Projet existant : $($proj.name)"
} catch {
  if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
  $proj = Invoke-RestMethod -Method Post -Headers $headers -ContentType "application/json" -Uri (Url "/v11/projects") `
          -Body (@{ name = $Project; framework = $null } | ConvertTo-Json)
  Write-Host "Projet cree : $($proj.name)" -ForegroundColor Green
}

$envPath = Join-Path $Root $EnvFile
if (-not (Test-Path $envPath)) { Write-Host "Fichier $EnvFile introuvable." -ForegroundColor Red; exit 1 }
$count = 0
foreach ($line in Get-Content $envPath -Encoding UTF8) {
  if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
  $key, $value = $line -split '=', 2
  $key = $key.Trim(); $value = $value.TrimEnd("`r")
  if (-not $key) { continue }
  if ($value -eq "") { Write-Host "  - $key ignoree (valeur vide)" -ForegroundColor Yellow; continue }
  $body = @{ key = $key; value = $value; type = "encrypted"; target = @("production", "preview") } | ConvertTo-Json
  Invoke-RestMethod -Method Post -Headers $headers -ContentType "application/json; charset=utf-8" `
    -Uri (Url "/v10/projects/$($proj.id)/env" "upsert=true") -Body ([Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
  Write-Host "  + $key" -ForegroundColor Green
  $count++
}
Write-Host "$count variable(s) enregistree(s) sur Vercel (production + preview), valeurs chiffrees." -ForegroundColor Cyan
