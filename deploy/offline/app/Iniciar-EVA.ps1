param(
    [switch]$Lan,
    [ValidateRange(1, 65535)][int]$Port = 8090,
    [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$exe = Join-Path $root "EVA-PDF.exe"

function Show-Message([string]$Text, [string]$Icon = "Information") {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($Text, "EVA PDF Enterprise", "OK", $Icon) | Out-Null
}

function Get-EvaStatus([int]$Candidate) {
    # Sin proxy: la consulta es siempre al propio equipo.
    $request = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$Candidate/health")
    $request.Proxy = $null
    $request.Timeout = 2000
    try {
        $response = $request.GetResponse()
        try { $body = (New-Object IO.StreamReader($response.GetResponseStream())).ReadToEnd() }
        finally { $response.Close() }
        try { $app = ($body | ConvertFrom-Json).app } catch { $app = $null }
        if ($app -eq "pdf-lan") { return "eva" }
        return "other"
    }
    catch {
        if (Get-NetTCPConnection -State Listen -LocalPort $Candidate -ErrorAction SilentlyContinue) { return "other" }
        return "free"
    }
}

try {
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "No se encuentra EVA-PDF.exe en $root. Reinstale EVA PDF Enterprise." }
    $selected = $null
    $alreadyRunning = $false
    foreach ($candidate in $Port..([Math]::Min($Port + 9, 65535))) {
        $status = Get-EvaStatus $candidate
        if ($status -eq "eva") { $selected = $candidate; $alreadyRunning = $true; break }
        if ($status -eq "free") { $selected = $candidate; break }
    }
    if (-not $selected) { throw "Los puertos $Port a $($Port + 9) estan ocupados por otras aplicaciones." }

    if (-not $alreadyRunning) {
        $bind = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
        $server = Start-Process -FilePath $exe -ArgumentList @("--host", $bind, "--port", "$selected") `
            -WorkingDirectory $root -WindowStyle Minimized -PassThru
        $deadline = (Get-Date).AddSeconds(90)
        while ((Get-EvaStatus $selected) -ne "eva") {
            if ($server.HasExited) {
                throw "El servidor EVA PDF Enterprise se cerro al iniciar (codigo $($server.ExitCode)). Ejecute EVA-PDF.exe desde $root para ver el detalle."
            }
            if ((Get-Date) -gt $deadline) { throw "EVA PDF Enterprise no respondio en 90 segundos. Revise la ventana minimizada de EVA-PDF.exe." }
            Start-Sleep -Milliseconds 500
        }
    }

    $url = "http://127.0.0.1:$selected/"
    if (-not $NoBrowser) { Start-Process $url }
    if ($Lan) {
        $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
            $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*"
        } | ForEach-Object { "  http://$($_.IPAddress):$selected/" })
        $note = if ($alreadyRunning) { "EVA PDF Enterprise ya estaba en ejecucion; si se inicio en modo local, cierrelo y vuelva a abrir este acceso para compartirlo.`r`n`r`n" } else { "" }
        Show-Message ($note + "EVA PDF Enterprise esta compartido en la red local. Otros equipos pueden entrar con:`r`n" + ($addresses -join "`r`n") +
            "`r`n`r`nSi no conectan, autorice el puerto en el Firewall (ver COMPLEMENTOS_ADICIONALES.txt).`r`nNo cierre la ventana minimizada de EVA-PDF.exe mientras se use.")
    }
}
catch {
    Show-Message $_.Exception.Message "Error"
    exit 1
}
