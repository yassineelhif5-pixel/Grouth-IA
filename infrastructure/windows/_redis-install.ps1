# Installe Redis pour Windows (portage open source tporadowski 5.0.14.1, licence BSD) dans tools\redis, sans droits administrateur.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $root "tools\redis"
if (Test-Path (Join-Path $dest "redis-server.exe")) { Write-Host "Redis deja installe : $dest"; exit 0 }
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$zip = Join-Path $env:TEMP "redis-win.zip"
$url = "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"
Write-Host "Telechargement de Redis : $url"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $dest -Force
Remove-Item $zip -ErrorAction SilentlyContinue
@"
bind 127.0.0.1
port 6379
protected-mode yes
maxmemory 256mb
maxmemory-policy allkeys-lru
save ""
appendonly no
"@ | Set-Content -Encoding ASCII (Join-Path $dest "growth.conf")
Write-Host "Redis installe dans $dest"
