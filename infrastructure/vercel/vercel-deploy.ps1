<#
  Growth IA - deploiement en production sur Vercel (site React + API Django).
  Prerequis : .vercel-token a la racine, variables poussees avec vercel-env.ps1. Node.js requis (npx).
  Usage : powershell -ExecutionPolicy Bypass -File infrastructure\vercel\vercel-deploy.ps1 [-Project growth-ia]
#>
param([string]$Project = "growth-ia")
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$tokenFile = Join-Path $Root ".vercel-token"
if (-not (Test-Path $tokenFile)) { Write-Host "Jeton Vercel manquant (.vercel-token)." -ForegroundColor Red; exit 1 }
$token = (Get-Content $tokenFile -Raw).Trim()
$env:VERCEL_TELEMETRY_DISABLED = "1"

if (-not (Test-Path (Join-Path $Root ".vercel\project.json"))) {
  Write-Host "Liaison du dossier au projet Vercel $Project..."
  & npx --yes vercel@latest link --yes --project $Project --token $token
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Write-Host "Deploiement en production (build du site + fonction API)..." -ForegroundColor Cyan
& npx --yes vercel@latest deploy --prod --yes --token $token
exit $LASTEXITCODE
