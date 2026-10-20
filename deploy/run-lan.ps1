param(
    [ValidateRange(1,65535)][int]$Port,
    [switch]$LocalOnly
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Falta el entorno propio .venv. Consulte README.md." }
Set-Location -LiteralPath $root
$arguments = @("-u", (Join-Path $root "server.py"))
if ($LocalOnly) { $arguments += @("--host", "127.0.0.1") }
else { $arguments += @("--host", "0.0.0.0") }
if ($Port) { $arguments += @("--port", "$Port") }
& $python @arguments
exit $LASTEXITCODE
