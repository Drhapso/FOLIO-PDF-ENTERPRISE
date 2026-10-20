param()
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$models = Join-Path $root "models"
New-Item -ItemType Directory -Path $models -Force | Out-Null
$revision = "65727574dfcd264acbb0c3e07860e4e9e9b22185"
$hashes = @{
    spa = "6F2E04D02774A18F01BED44B1111F2CD7F3BA7AC9DC4373CD3F898A40EA6B464"
    eng = "7D4322BD2A7749724879683FC3912CB542F19906C83BCC1A52132556427170B2"
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
foreach ($language in @("spa", "eng")) {
    $destination = Join-Path $models "$language.traineddata"
    if (Test-Path -LiteralPath $destination) {
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $hashes[$language]) {
            throw "Modelo existente no coincide con la revision fijada: $language"
        }
        Write-Host "Modelo existente: $language"
        continue
    }
    $temporary = Join-Path $models "$language.download"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/$revision/$language.traineddata" -OutFile $temporary
        if ((Get-Item -LiteralPath $temporary).Length -lt 100000) {
            throw "Descarga OCR incompleta: $language"
        }
        if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash -ne $hashes[$language]) {
            throw "Verificacion SHA256 fallida: $language"
        }
        Move-Item -LiteralPath $temporary -Destination $destination
        Write-Host "Modelo instalado: $language"
        Get-FileHash -LiteralPath $destination -Algorithm SHA256 | Select-Object Hash
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}
Write-Host "OCR listo. Los documentos nunca se envian a Internet."
