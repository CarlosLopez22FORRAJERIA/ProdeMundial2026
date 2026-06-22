$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

if (-not $env:PORT) {
    $env:PORT = "5000"
}

$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$Addresses = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.PrefixOrigin -ne "WellKnown"
    } |
    Sort-Object InterfaceMetric, InterfaceAlias

Write-Host ""
Write-Host "Prode Mundial 2026 local"
Write-Host "PC:   http://127.0.0.1:$env:PORT"
foreach ($Address in $Addresses) {
    Write-Host ("LAN:  http://{0}:{1}  ({2})" -f $Address.IPAddress, $env:PORT, $Address.InterfaceAlias)
}
Write-Host ""
Write-Host "Si el celular no abre, revisa que este en la misma red Wi-Fi y que Windows Firewall permita el puerto $env:PORT."
Write-Host ""

& $Python app.py
