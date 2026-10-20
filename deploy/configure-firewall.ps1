param(
    [Parameter(Mandatory=$true)][string]$AuthorizedSubnet,
    [ValidateRange(1,65535)][int]$Port = 8090,
    [switch]$Apply
)
$ErrorActionPreference = "Stop"
if ($AuthorizedSubnet -notmatch '^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$') {
    throw "Indique una subred IPv4 CIDR explicita."
}
$parts = $AuthorizedSubnet.Split("/")
$address = $null
if (-not [System.Net.IPAddress]::TryParse($parts[0], [ref]$address) -or [int]$parts[1] -lt 1 -or [int]$parts[1] -gt 32) {
    throw "Subred IPv4 no valida."
}
if (-not $Apply) {
    Write-Host "Diagnostico: TCP $Port para $AuthorizedSubnet, perfiles Domain/Private. No se modifica el firewall."
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess
    return
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Se requieren permisos administrativos." }
$name = "Folio-PDF-LAN-$Port"
$existing = Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
if ($existing) { throw "La regla $name ya existe. Revisela antes de sustituirla." }
New-NetFirewallRule -Name $name -DisplayName "Folio PDF LAN ($Port)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress $AuthorizedSubnet -Profile Domain,Private | Out-Null
Write-Host "Regla creada. No se modificaron otros puertos, IP, DNS ni servicios."
