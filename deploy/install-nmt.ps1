param()
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$packDir = Join-Path $root "addons\pack-nmt"
New-Item -ItemType Directory -Path $packDir -Force | Out-Null

# 1. Instalar/verificar paquetes Python requeridos por el motor neuronal CTranslate2 + SentencePiece + BPE
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$pythonCmd = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
Write-Host "Verificando runtime Python NMT ($pythonCmd)..."
& $pythonCmd -c "import ctranslate2, sentencepiece, subword_nmt, sacremoses" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando dependencias de traduccion neuronal offline (ctranslate2, sentencepiece, subword-nmt, sacremoses)..."
    & $pythonCmd -m pip install "ctranslate2>=4.6,<5" "sentencepiece>=0.2,<1" "subword-nmt>=0.3.8,<1" "sacremoses>=0.1.1,<1"
    if ($LASTEXITCODE -ne 0) {
        throw "Error instalando dependencias Python para NMT offline."
    }
}

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
  "id": "pack-nmt",
  "name": "EVA Neural MT Offline Pack (ES<->EN)",
  "version": "1.0.0",
  "engine": "ctranslate2",
  "capabilities": ["ctranslate2", "nmt_offline", "translate_layout", "es_en", "en_es"],
  "pairs": ["en_es", "es_en"],
  "models": {
    "en_es": {
      "source_lang": "en",
      "target_lang": "es",
      "tokenizer": "sentencepiece.model",
      "model_bin": "en_es/model/model.bin"
    },
    "es_en": {
      "source_lang": "es",
      "target_lang": "en",
      "tokenizer": "bpe.model",
      "model_bin": "es_en/model/model.bin"
    }
  }
}
'@
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $packDir "manifest.json"), $manifest, $utf8NoBom)

Push-Location $root
try {
    & $pythonCmd -c "from pathlib import Path; from settings import load_settings; from engines.addons import addons_status; st = addons_status(load_settings(Path('.')), Path('.')); print('Estado NMT:', {'nmt_offline': st['nmt_offline'], 'nmt_pairs': st['nmt_pairs']})"
}
finally {
    Pop-Location
}
Write-Host "Traductor neuronal offline ES<->EN listo en addons\pack-nmt."
