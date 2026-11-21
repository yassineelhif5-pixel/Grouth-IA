# Arrete Growth IA : processus ecoutant sur 8000 (API), 5173 (site), 6379 (Redis), plus runserver / celery / vite / fenetres _run-*.bat.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ids = New-Object System.Collections.Generic.HashSet[int]
foreach ($port in 8000, 5173, 6379) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { [void]$ids.Add([int]$_.OwningProcess) }
}
Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -ne $PID -and $_.CommandLine -and (
    $_.CommandLine -match 'manage\.py"?\s+runserver' -or
    $_.CommandLine -match 'celery(\.exe)?"?\s+-A\s+config' -or
    ($_.Name -eq 'node.exe' -and $_.CommandLine -match 'vite' -and $_.CommandLine -like "*$root*") -or
    ($_.Name -eq 'cmd.exe' -and $_.CommandLine -match '_run-(api|web|worker|beat|redis)\.bat') -or
    $_.Name -eq 'redis-server.exe')
} | ForEach-Object { [void]$ids.Add([int]$_.ProcessId) }
foreach ($id in $ids) { if ($id -gt 4) { & taskkill /PID $id /T /F 2>$null | Out-Null } }
Start-Sleep -Seconds 2
$left = @(8000, 5173, 6379 | ForEach-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue })
Write-Host ("Growth IA arrete ({0} processus). Ports encore occupes : {1}" -f $ids.Count, $left.Count)
