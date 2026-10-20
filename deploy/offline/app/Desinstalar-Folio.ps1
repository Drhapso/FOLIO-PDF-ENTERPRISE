param(
    [switch]$KeepData,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$root = (Get-Item -LiteralPath $PSScriptRoot).FullName.TrimEnd("\")
if (-not (Test-Path -LiteralPath (Join-Path $root "Folio.exe"))) { throw "Esta carpeta no es una instalacion de Folio PDF." }
if (-not $Force) {
    $answer = Read-Host "Se desinstalara Folio PDF de $root. Continuar? (S/N)"
    if ($answer -notmatch '^[sS]') { Write-Host "Cancelado."; exit 0 }
    if (-not $KeepData) { $KeepData = (Read-Host "Conservar configuracion y datos locales? (S/N)") -match '^[sS]' }
}
$running = @(Get-Process -Name Folio -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path.StartsWith($root + "\", [StringComparison]::OrdinalIgnoreCase)
})
foreach ($process in $running) { Stop-Process -Id $process.Id -Force }
if ($running.Count) { Start-Sleep -Seconds 2 }

Set-Location -LiteralPath $env:TEMP
if ($KeepData) {
    $backup = "$root-datos-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    New-Item -ItemType Directory -Path $backup | Out-Null
    foreach ($item in @("instance", "config\site_config.json")) {
        $source = Join-Path $root $item
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $backup -Recurse -Force }
    }
    Write-Host "Datos conservados en $backup"
}
foreach ($link in @(
    (Join-Path ([Environment]::GetFolderPath("Programs")) "Folio PDF"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Folio PDF.lnk")
)) {
    if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Recurse -Force }
}
Remove-Item -LiteralPath $root -Recurse -Force
Write-Host "Folio PDF se desinstalo correctamente."
if (-not $Force) { Read-Host "Pulse Enter para cerrar" | Out-Null }
