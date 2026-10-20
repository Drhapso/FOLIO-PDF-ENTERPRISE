param(
    [string]$ParametersFile = (Join-Path $PSScriptRoot "release.example.json"),
    [string]$Python,
    [switch]$Build,
    [switch]$Installer,
    [switch]$LicensesReviewed
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $root ".venv\Scripts\python.exe" }
$parameters = Get-Content -LiteralPath $ParametersFile -Raw | ConvertFrom-Json
if ($parameters.version -notmatch '^\d+\.\d+\.\d+$') { throw "Version no valida: use tres numeros." }
if ($parameters.python_version -ne "3.13" -or $parameters.architecture -ne "AMD64") {
    throw "Esta receta esta preparada para CPython 3.13 Windows x64."
}
if ($Installer -and -not $Build) { throw "-Installer requiere -Build." }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "No existe el interprete de construccion: $Python" }
# Windows PowerShell 5.1 elimina comillas dobles incrustadas en argumentos nativos.
& $Python -c "import sys,struct,os; assert os.name=='nt' and sys.version_info[:2]==(3,13) and struct.calcsize('P')==8, 'Se requiere CPython 3.13 Windows x64'"
if ($LASTEXITCODE -ne 0) { throw "Interprete no compatible." }
& $Python -m pip check
if ($LASTEXITCODE -ne 0) { throw "Dependencias incompatibles." }
& $Python -c "import PyInstaller; from packaging.version import Version; assert Version('6.16') <= Version(PyInstaller.__version__) < Version('7')"
if ($LASTEXITCODE -ne 0) { throw "Prepare requirements-build.txt en un entorno de construccion dedicado." }
foreach ($language in @("spa", "eng")) {
    $model = Join-Path $root "models\$language.traineddata"
    $expected = $parameters.ocr_sha256.$language
    if ($expected -notmatch '^[A-Fa-f0-9]{64}$') { throw "Falta SHA256 OCR: $language" }
    if (-not (Test-Path -LiteralPath $model -PathType Leaf)) { throw "Falta el modelo OCR: $language" }
    if ((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash -ne $expected) {
        throw "El modelo OCR no coincide: $language"
    }
}
if ($Installer -and -not (Test-Path -LiteralPath $parameters.installer_compiler -PathType Leaf)) {
    throw "Falta el compilador Inno Setup configurado."
}
if (-not $Build) {
    Write-Host "Prevalidacion correcta. No se han generado ejecutables ni instaladores."
    exit 0
}
if (-not $LicensesReviewed) { throw "Revise licencias y permisos de redistribucion; confirme con -LicensesReviewed." }
$release = Join-Path $root ("dist\release-" + $parameters.version)
if (Test-Path -LiteralPath $release) { throw "La salida ya existe. No se sobrescribe: $release" }
New-Item -ItemType Directory -Path $release | Out-Null
Push-Location $root
try {
    & $Python -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallaron; no se construira." }
    & $Python -m PyInstaller --noconfirm --distpath $release --workpath (Join-Path $root "build") (Join-Path $PSScriptRoot "folio.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo." }
    $payload = Join-Path $release "Folio"
    $prohibited = @("runtime", "instance", ".git", ".venv", "config\site_config.json")
    foreach ($path in $prohibited) {
        if (Test-Path -LiteralPath (Join-Path $payload $path)) { throw "Contenido local prohibido en paquete: $path" }
    }
    & $Python -m pip list --format=freeze | Set-Content -LiteralPath (Join-Path $payload "BUILD-DEPENDENCIES.txt") -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { throw "No se pudo registrar dependencias." }
    & (Join-Path $payload "Folio.exe") --calibrate
    if ($LASTEXITCODE -ne 0) { throw "El ejecutable no pudo calibrar sus motores." }
    # El perfil de esta maquina nunca debe viajar al equipo de destino.
    foreach ($name in @("instance", "runtime")) {
        $local = Join-Path $payload $name
        if (Test-Path -LiteralPath $local) { Remove-Item -LiteralPath $local -Recurse -Force }
    }
    $checksums = Get-ChildItem -LiteralPath $payload -File -Recurse | ForEach-Object {
        "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash, $_.FullName.Substring($payload.Length + 1)
    }
    $checksums | Set-Content -LiteralPath (Join-Path $payload "SHA256SUMS.txt") -Encoding UTF8
    if ($Installer) {
        & $parameters.installer_compiler "/DReleaseVersion=$($parameters.version)" "/DPayloadDir=$payload" "/DOutputDir=$release" (Join-Path $PSScriptRoot "installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo." }
        Get-ChildItem -LiteralPath $release -Filter "*.exe" -File | Get-FileHash -Algorithm SHA256 |
            ForEach-Object { "{0}  {1}" -f $_.Hash, (Split-Path -Leaf $_.Path) } |
            Set-Content -LiteralPath (Join-Path $release "INSTALLER-SHA256SUMS.txt") -Encoding UTF8
    }
    Write-Host "Construccion terminada. Antes de distribuir, complete la validacion offline de docs\DISTRIBUCION_OFFLINE.md."
}
finally { Pop-Location }
