param()
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$packDir = Join-Path $root "addons\pack-nmt"
New-Item -ItemType Directory -Path $packDir -Force | Out-Null

$models = @(
    @{
        Pair = "en_es"
        Url = "https://argos-net.com/v1/translate-en_es-1_0.argosmodel"
        Tokenizer = "sentencepiece.model"
        MinBytes = 50000000
    },
    @{
        Pair = "es_en"
        Url = "https://argos-net.com/v1/translate-es_en-1_9.argosmodel"
        Tokenizer = "bpe.model"
        MinBytes = 200000000
    }
)

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression.FileSystem

foreach ($item in $models) {
    $pairDir = Join-Path $packDir $item.Pair
    $modelBin = Join-Path $pairDir "model\model.bin"
    $tokenizerPath = Join-Path $pairDir $item.Tokenizer
    if ((Test-Path -LiteralPath $modelBin) -and (Test-Path -LiteralPath $tokenizerPath)) {
        Write-Host "Modelo NMT existente: $($item.Pair)"
        continue
    }
    $archive = Join-Path $packDir "$($item.Pair).argosmodel"
    $stage = Join-Path $packDir "$($item.Pair).stage"
    try {
        Write-Host "Descargando modelo NMT offline ($($item.Pair))..."
        Invoke-WebRequest -UseBasicParsing -Uri $item.Url -OutFile $archive
        if ((Get-Item -LiteralPath $archive).Length -lt $item.MinBytes) {
            throw "Descarga NMT incompleta: $($item.Pair)"
        }
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
        New-Item -ItemType Directory -Path $stage -Force | Out-Null
        [System.IO.Compression.ZipFile]::ExtractToDirectory($archive, $stage)
        $inner = Get-ChildItem -LiteralPath $stage -Directory | Select-Object -First 1
        if (-not $inner) { throw "Archivo .argosmodel vacio: $($item.Pair)" }
        if (Test-Path -LiteralPath $pairDir) { Remove-Item -LiteralPath $pairDir -Recurse -Force }
        Move-Item -LiteralPath $inner.FullName -Destination $pairDir
        $stanzaDir = Join-Path $pairDir "stanza"
        if (Test-Path -LiteralPath $stanzaDir) { Remove-Item -LiteralPath $stanzaDir -Recurse -Force }
        if (-not ((Test-Path -LiteralPath $modelBin) -and (Test-Path -LiteralPath $tokenizerPath))) {
            throw "Estructura NMT invalida tras extraer: $($item.Pair)"
        }
        Write-Host "Modelo NMT instalado: $($item.Pair)"
    }
    finally {
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    }
}

$manifest = @'
{
  "name": "EVA Neural MT Offline Pack (ES<->EN)",
  "version": "1.0.0",
  "capabilities": ["ctranslate2", "nmt_offline", "es_en", "en_es"],
  "pairs": ["en_es", "es_en"]
}
'@
Set-Content -LiteralPath (Join-Path $packDir "manifest.json") -Value $manifest -Encoding UTF8
Write-Host "Traductor neuronal offline ES<->EN listo en addons\pack-nmt."
