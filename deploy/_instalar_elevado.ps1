<#
Bootstrap interno: instala y arranca el servicio, y deja transcripcion en logs/
para poder verificar el resultado desde una sesion sin privilegios de administrador.
No lo ejecutes directamente - lo invoca instalar_servicio_backend.ps1 via elevacion.
#>
param([string]$Nssm)

$ErrorActionPreference = "Stop"
$raiz = Resolve-Path "$PSScriptRoot\.."
$logDir = Join-Path $raiz "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$transcript = Join-Path $logDir "instalacion_servicio.log"

Start-Transcript -Path $transcript -Force | Out-Null
try {
    & (Join-Path $PSScriptRoot "instalar_servicio_backend.ps1") -Nssm $Nssm
    Start-Service ConciliadorBackend
    Get-Service ConciliadorBackend | Format-List *
}
catch {
    Write-Host "ERROR: $_"
    throw
}
finally {
    Stop-Transcript | Out-Null
}
