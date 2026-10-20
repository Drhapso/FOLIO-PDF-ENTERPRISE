param(
    [ValidateSet("Menu", "Diagnose", "Scan", "Print", "Printers")]
    [string]$Action = "Menu"
)
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Este complemento requiere Windows." }

if ($Action -eq "Diagnose") {
    $manager = New-Object -ComObject WIA.DeviceManager
    $scanners = @($manager.DeviceInfos | Where-Object { $_.Type -eq 1 })
    $printerService = Get-Service -Name Spooler -ErrorAction Stop
    [pscustomobject]@{
        Windows = $true
        WiaScanners = $scanners.Count
        PrintSpoolerRunning = ($printerService.Status -eq "Running")
        MicrosoftPrintToPdf = [bool](Get-CimInstance Win32_Printer -Filter "Name='Microsoft Print to PDF'")
        NetworkListener = $false
        UploadsDocuments = $false
    } | ConvertTo-Json
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
function Show-Notice([string]$Text) {
    [System.Windows.Forms.MessageBox]::Show($Text, "Folio Desktop", "OK", "Information") | Out-Null
}
function Invoke-Scan {
    $manager = New-Object -ComObject WIA.DeviceManager
    $scanners = @($manager.DeviceInfos | Where-Object { $_.Type -eq 1 })
    if ($scanners.Count -eq 0) { throw "No hay escaner WIA disponible. Instale su controlador desde el fabricante o importe un archivo ya escaneado." }
    $dialog = New-Object -ComObject WIA.CommonDialog
    # El dialogo nativo deja elegir dispositivo; no accede al escaner del servidor.
    $image = $dialog.ShowAcquireImage(1, 1, 0, "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}", $true, $true, $false)
    if ($null -eq $image) { return }
    $save = New-Object System.Windows.Forms.SaveFileDialog
    $save.Title = "Guardar escaneo en su equipo"
    $save.Filter = "PNG (*.png)|*.png"
    $save.FileName = "escaneo.png"
    $save.OverwritePrompt = $true
    try {
        if ($save.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }
        $target = [IO.Path]::GetFullPath($save.FileName)
        # WIA no sobrescribe: se pide elegir otro nombre y no se borra ningun archivo existente.
        if (Test-Path -LiteralPath $target) { throw "El archivo ya existe. Elija un nombre nuevo para no reemplazarlo." }
        $image.SaveFile($target)
        Show-Notice "Escaneo guardado localmente. Abra Folio en su navegador y seleccione Imagenes a PDF. El complemento no envia ni guarda copias adicionales."
    }
    finally { $save.Dispose() }
}
function Invoke-Print {
    $open = New-Object System.Windows.Forms.OpenFileDialog
    $open.Title = "Seleccione un PDF local para imprimir"
    $open.Filter = "PDF (*.pdf)|*.pdf"
    try {
        if ($open.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }
        $path = [IO.Path]::GetFullPath($open.FileName)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "El PDF seleccionado ya no existe." }
        $confirm = [System.Windows.Forms.MessageBox]::Show(
            "Se solicitara imprimir con la aplicacion PDF asociada y su impresora configurada. Esto puede imprimir directamente. Para elegir impresora y opciones, cancele y abra el PDF con Ctrl+P. La cola de Windows puede conservar datos. Continuar?",
            "Confirmar impresion", "YesNo", "Question")
        if ($confirm -ne [System.Windows.Forms.DialogResult]::Yes) { return }
        $start = New-Object System.Diagnostics.ProcessStartInfo
        $start.FileName = $path
        $start.UseShellExecute = $true
        $start.Verb = "Print"
        [System.Diagnostics.Process]::Start($start) | Out-Null
        Show-Notice "Solicitud enviada a la aplicacion PDF asociada de Windows. Folio no puede confirmar que se imprimio. Revise la cola y la impresora. Si no hay asociacion para Print, abra el PDF y use Ctrl+P. La cola de impresion puede conservar datos segun la politica de Windows."
    }
    finally { $open.Dispose() }
}

try {
    switch ($Action) {
        "Scan" { Invoke-Scan; exit 0 }
        "Print" { Invoke-Print; exit 0 }
        "Printers" { Start-Process "ms-settings:printers"; exit 0 }
    }
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Folio - complemento local Windows"
    $form.ClientSize = New-Object System.Drawing.Size(520, 340)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $label = New-Object System.Windows.Forms.Label
    $label.Text = "Se ejecuta en SU equipo, sin servicio ni puerto abierto.`r`nNo sube archivos ni instala controladores. Los escaneos que guarde y la cola de impresion permanecen bajo su control."
    $label.Location = New-Object System.Drawing.Point(24, 20)
    $label.Size = New-Object System.Drawing.Size(470, 70)
    $form.Controls.Add($label)
    $scan = New-Object System.Windows.Forms.Button
    $scan.Text = "Escanear con WIA y guardar PNG"
    $scan.Location = New-Object System.Drawing.Point(24, 100)
    $scan.Size = New-Object System.Drawing.Size(470, 42)
    $scan.Add_Click({ try { Invoke-Scan } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "No se pudo escanear", "OK", "Error") | Out-Null } })
    $form.Controls.Add($scan)
    $print = New-Object System.Windows.Forms.Button
    $print.Text = "Imprimir PDF con la aplicacion asociada"
    $print.Location = New-Object System.Drawing.Point(24, 152)
    $print.Size = New-Object System.Drawing.Size(470, 42)
    $print.Add_Click({ try { Invoke-Print } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "No se pudo imprimir", "OK", "Error") | Out-Null } })
    $form.Controls.Add($print)
    $settings = New-Object System.Windows.Forms.Button
    $settings.Text = "Abrir impresoras y escaneres de Windows"
    $settings.Location = New-Object System.Drawing.Point(24, 204)
    $settings.Size = New-Object System.Drawing.Size(470, 42)
    $settings.Add_Click({ try { Start-Process "ms-settings:printers" } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "No se pudo abrir configuracion", "OK", "Error") | Out-Null } })
    $form.Controls.Add($settings)
    $help = New-Object System.Windows.Forms.Label
    $help.Text = "Crear PDF desde cualquier programa: Ctrl+P > Microsoft Print to PDF.`r`nNo necesita permisos de administrador. Cierre esta ventana al terminar."
    $help.Location = New-Object System.Drawing.Point(24, 265)
    $help.Size = New-Object System.Drawing.Size(470, 55)
    $form.Controls.Add($help)
    [System.Windows.Forms.Application]::Run($form)
    $form.Dispose()
}
catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Folio Desktop - error", "OK", "Error") | Out-Null
    exit 1
}
