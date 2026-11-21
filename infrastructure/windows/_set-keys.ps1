# Saisie masquee des cles manquantes, ecrites dans .env (copie de sauvegarde .env.avant-cles). Rien n'est affiche ni journalise.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $root ".env"
if (-not (Test-Path (Join-Path $root ".env.avant-cles"))) { Copy-Item $envFile (Join-Path $root ".env.avant-cles") }
$keys = @(
  @{ Name = "ANTHROPIC_API_KEY"; Help = "Cle API Claude (console.anthropic.com > API Keys, commence par sk-ant-)" },
  @{ Name = "SUPABASE_SERVICE_ROLE_KEY"; Help = "Cle secrete Supabase (Dashboard > Project Settings > API Keys > service_role / secret)" }
)
$lines = [System.Collections.Generic.List[string]](Get-Content $envFile)
foreach ($k in $keys) {
  Write-Host ""
  Write-Host $k.Help
  $sec = Read-Host -AsSecureString ("{0} (Entree pour laisser inchange)" -f $k.Name)
  $val = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)).Trim()
  if ($val) {
    $kept = [System.Collections.Generic.List[string]]($lines | Where-Object { $_ -notmatch ("^" + $k.Name + "=") })
    $kept.Add("$($k.Name)=$val")
    $lines = $kept
    Write-Host ("  {0} enregistree." -f $k.Name)
  } else { Write-Host "  inchangee." }
}
[IO.File]::WriteAllLines($envFile, [string[]]$lines, (New-Object Text.UTF8Encoding($false)))  # UTF-8 sans BOM
Write-Host ""
Write-Host "Cles enregistrees dans .env."
