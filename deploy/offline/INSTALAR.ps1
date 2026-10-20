param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Folio-PDF"),
    [switch]$NoShortcuts,
    [switch]$SkipCalibration
)
$ErrorActionPreference = "Stop"
$package = $PSScriptRoot
$payload = Join-Path $package "Folio"
$appScripts = Join-Path $package "app"
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Folio PDF"
$desktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "Folio PDF.lnk"

function Assert-Checksums([string]$Folder, [string]$ListName) {
    $list = Join-Path $Folder $ListName
    if (-not (Test-Path -LiteralPath $list -PathType Leaf)) { throw "Paquete incompleto: falta $list" }
    $count = 0
    foreach ($line in Get-Content -LiteralPath $list) {
        if (-not $line.Trim()) { continue }
        $parts = $line -split "  ", 2
        if ($parts.Count -ne 2 -or $parts[1] -match '(^|[\\/])\.\.([\\/]|$)' -or [IO.Path]::IsPathRooted($parts[1])) {
            throw "Lista de integridad no valida: $line"
        }
        $file = Join-Path $Folder $parts[1]
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Falta archivo del paquete: $($parts[1])" }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $parts[0]) {
            throw "Archivo alterado o danado: $($parts[1]). Vuelva a copiar el ZIP completo."
        }
        $count++
    }
    return $count
}

function New-Shortcut([string]$Path, [string]$Arguments, [string]$Description) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $link.Arguments = $Arguments
    $link.WorkingDirectory = $InstallDir
    $link.IconLocation = (Join-Path $InstallDir "Folio.exe") + ",0"
    $link.Description = $Description
    $link.Save()
}

Write-Host "=== Instalador offline de Folio PDF ===" -ForegroundColor Cyan
if (-not [Environment]::Is64BitOperatingSystem) { throw "Folio PDF requiere Windows de 64 bits (x64)." }
if ([Environment]::OSVersion.Version.Major -lt 10) { throw "Folio PDF requiere Windows 10 u 11." }
if (-not (Test-Path -LiteralPath (Join-Path $payload "Folio.exe") -PathType Leaf)) {
    throw "Paquete incompleto: extraiga TODO el ZIP en una carpeta antes de ejecutar INSTALAR."
}
$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd("\")
# Get-Item expande nombres cortos 8.3 (p. ej. %TEMP%) para comparar con la ruta de los procesos.
if (Test-Path -LiteralPath $InstallDir) { $InstallDir = (Get-Item -LiteralPath $InstallDir).FullName.TrimEnd("\") }
if ($InstallDir.StartsWith((Get-Item -LiteralPath $package).FullName.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) {
    throw "Elija una carpeta de instalacion fuera del paquete extraido."
}

Write-Host "Verificando integridad del paquete (puede tardar un minuto)..."
$verified = (Assert-Checksums $payload "SHA256SUMS.txt") + (Assert-Checksums $appScripts "APP-SHA256SUMS.txt")
Write-Host "Integridad correcta: $verified archivos." -ForegroundColor Green

$running = @(Get-Process -Name Folio -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path.StartsWith($InstallDir + "\", [StringComparison]::OrdinalIgnoreCase)
})
if ($running.Count) { throw "Folio esta en ejecucion desde $InstallDir. Cierre su ventana de servidor y repita la instalacion." }

if (Test-Path -LiteralPath $InstallDir) {
    $existing = @(Get-ChildItem -LiteralPath $InstallDir -Force)
    # Solo se reemplaza una instalacion de Folio o una carpeta vacia; nunca otra carpeta del usuario.
    if ($existing.Count -and -not (Test-Path -LiteralPath (Join-Path $InstallDir "Folio.exe"))) {
        throw "La carpeta $InstallDir ya existe y no es una instalacion de Folio. Indique otra con -InstallDir."
    }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$staging = "$InstallDir.nuevo-$stamp"
$previous = "$InstallDir.anterior-$stamp"
Write-Host "Copiando archivos a $InstallDir ..."
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    Copy-Item -Path (Join-Path $payload "*") -Destination $staging -Recurse -Force
    Copy-Item -Path (Join-Path $appScripts "*") -Destination $staging -Recurse -Force
    foreach ($text in @("LEEME.txt", "COMPLEMENTOS_ADICIONALES.txt")) {
        Copy-Item -LiteralPath (Join-Path $package $text) -Destination $staging -Force
    }
    if (Test-Path -LiteralPath $InstallDir) {
        # Actualizacion: se conservan la configuracion local y los datos de la instancia.
        $oldConfig = Join-Path $InstallDir "config\site_config.json"
        if (Test-Path -LiteralPath $oldConfig) { Copy-Item -LiteralPath $oldConfig -Destination (Join-Path $staging "config") -Force }
        $oldInstance = Join-Path $InstallDir "instance"
        if (Test-Path -LiteralPath $oldInstance) { Copy-Item -LiteralPath $oldInstance -Destination $staging -Recurse -Force }
        Rename-Item -LiteralPath $InstallDir -NewName (Split-Path -Leaf $previous)
    }
    Rename-Item -LiteralPath $staging -NewName (Split-Path -Leaf $InstallDir)
}
catch {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue }
    if ((Test-Path -LiteralPath $previous) -and -not (Test-Path -LiteralPath $InstallDir)) {
        Rename-Item -LiteralPath $previous -NewName (Split-Path -Leaf $InstallDir)
    }
    throw
}
if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Recurse -Force -ErrorAction SilentlyContinue }
# Evita bloqueos de "archivo descargado de Internet" heredados del ZIP.
Get-ChildItem -LiteralPath $InstallDir -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

if (-not $SkipCalibration) {
    Write-Host "Calibrando motores PDF/OCR para este equipo..."
    $calibration = Start-Process -FilePath (Join-Path $InstallDir "Folio.exe") -ArgumentList "--calibrate" `
        -WorkingDirectory $InstallDir -WindowStyle Hidden -Wait -PassThru
    if ($calibration.ExitCode -eq 0) { Write-Host "Calibracion completada." -ForegroundColor Green }
    else { Write-Warning "La calibracion fallo (codigo $($calibration.ExitCode)). Folio usara limites seguros por defecto." }
}

if (-not $NoShortcuts) {
    New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
    $launcher = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $InstallDir "Iniciar-Folio.ps1") + '"'
    New-Shortcut (Join-Path $startMenu "Folio PDF.lnk") $launcher "Iniciar Folio PDF en este equipo"
    New-Shortcut (Join-Path $startMenu "Folio PDF (compartir en LAN).lnk") "$launcher -Lan" "Iniciar Folio PDF accesible desde la red local"
    New-Shortcut (Join-Path $startMenu "Desinstalar Folio PDF.lnk") ('-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $InstallDir "Desinstalar-Folio.ps1") + '"') "Desinstalar Folio PDF"
    New-Shortcut $desktopLink $launcher "Iniciar Folio PDF en este equipo"
    Write-Host "Accesos directos creados en el Escritorio y en el menu Inicio > Folio PDF."
}

Write-Host ""
Write-Host "Folio PDF instalado en: $InstallDir" -ForegroundColor Green
Write-Host "Use el acceso directo 'Folio PDF'. Se abrira http://127.0.0.1:8090/ en el navegador."
Write-Host "Para convertir Word/Excel/PowerPoint a PDF instale LibreOffice (ver COMPLEMENTOS_ADICIONALES.txt)."
