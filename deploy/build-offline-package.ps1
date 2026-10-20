param(
    [string]$ParametersFile = (Join-Path $PSScriptRoot "release.local.json")
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $ParametersFile)) { $ParametersFile = Join-Path $PSScriptRoot "release.example.json" }
$version = (Get-Content -LiteralPath $ParametersFile -Raw | ConvertFrom-Json).version
$payload = Join-Path $root "dist\release-$version\EVA-PDF"
if (-not (Test-Path -LiteralPath (Join-Path $payload "SHA256SUMS.txt"))) {
    throw "No existe un build verificado en $payload. Ejecute antes build-executable.ps1 -Build."
}
foreach ($path in @("runtime", "instance", ".git", ".venv", "config\site_config.json")) {
    if (Test-Path -LiteralPath (Join-Path $payload $path)) { throw "Contenido local prohibido en el payload: $path" }
}
$name = "EVA-PDF-Enterprise-Offline-$version-win-x64"
$stage = Join-Path $root "dist\$name"
$zip = "$stage.zip"
foreach ($output in @($stage, $zip)) {
    if (Test-Path -LiteralPath $output) { throw "La salida ya existe y no se sobrescribe: $output" }
}
$kit = Join-Path $PSScriptRoot "offline"
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item -LiteralPath $payload -Destination (Join-Path $stage "EVA-PDF") -Recurse
Copy-Item -LiteralPath (Join-Path $kit "app") -Destination (Join-Path $stage "app") -Recurse
New-Item -ItemType Directory -Path (Join-Path $stage "app\herramientas") | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "configure-firewall.ps1") -Destination (Join-Path $stage "app\herramientas")
foreach ($file in @("INSTALAR.bat", "INSTALAR.ps1", "LEEME.txt", "COMPLEMENTOS_ADICIONALES.txt")) {
    Copy-Item -LiteralPath (Join-Path $kit $file) -Destination $stage
}
$app = Join-Path $stage "app"
Get-ChildItem -LiteralPath $app -File -Recurse | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash, $_.FullName.Substring($app.Length + 1)
} | Set-Content -LiteralPath (Join-Path $app "APP-SHA256SUMS.txt") -Encoding UTF8

$build = [regex]::Match((Get-Content -LiteralPath (Join-Path $root "server.py") -Raw), 'CLIENT_BUILD\s*=\s*"([^"]+)"').Groups[1].Value
$exeHash = (Get-FileHash -LiteralPath (Join-Path $stage "EVA-PDF\EVA-PDF.exe") -Algorithm SHA256).Hash
$sumsHash = (Get-FileHash -LiteralPath (Join-Path $stage "EVA-PDF\SHA256SUMS.txt") -Algorithm SHA256).Hash
@(
    "EVA PDF Enterprise offline $version (Windows x64)",
    "Build web: $build",
    "Generado: $((Get-Date).ToString('yyyy-MM-dd HH:mm'))",
    "Python embebido: 3.13 x64 (PyInstaller onedir)",
    "SHA256 EVA-PDF.exe:      $exeHash",
    "SHA256 SHA256SUMS.txt:   $sumsHash",
    "Binarios sin firma Authenticode: verifique las huellas antes de distribuir."
) | Set-Content -LiteralPath (Join-Path $stage "PAQUETE-INFO.txt") -Encoding UTF8

Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, [IO.Compression.CompressionLevel]::Optimal, $true)
$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
"$zipHash  $name.zip" | Set-Content -LiteralPath "$zip.sha256.txt" -Encoding ASCII
Write-Host ("Paquete: {0} ({1:N0} MB)" -f $zip, ((Get-Item -LiteralPath $zip).Length / 1MB))
Write-Host "SHA256:  $zipHash"
