<#
.SINOPSIS
    Instala el backend (FastAPI/uvicorn) como servicio de Windows usando NSSM,
    para que arranque solo con el equipo y sobreviva reinicios / cierres de sesión.

.REQUISITOS
    - NSSM (https://nssm.cc/download) — descomprime nssm.exe en una carpeta del PATH,
      o pasa su ruta completa con -Nssm.
    - Haber creado el entorno virtual e instalado dependencias:
        cd backend
        python -m venv .venv
        .venv\Scripts\pip install -r ..\requirements.txt
    - Un `.env` real y completo en la raíz del proyecto (ver .env.example), con
      APP_ENV=production y SAP_VERIFY_SSL=true.

.USO (PowerShell como Administrador)
    cd deploy
    .\instalar_servicio_backend.ps1
    .\instalar_servicio_backend.ps1 -Puerto 18450 -Nssm "C:\herramientas\nssm.exe"
#>
param(
    [string]$NombreServicio = "ConciliadorBackend",
    [string]$RutaProyecto = (Resolve-Path "$PSScriptRoot\..").Path,
    [int]$Puerto = 18450,
    [string]$Nssm = "nssm"
)

$ErrorActionPreference = "Stop"

$backend = Join-Path $RutaProyecto "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$logs = Join-Path $RutaProyecto "logs"

if (-not (Test-Path $python)) {
    Write-Host "No encuentro el entorno virtual en $python" -ForegroundColor Yellow
    Write-Host "Creal primero:  cd backend; python -m venv .venv; .venv\Scripts\pip install -r ..\requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $RutaProyecto ".env"))) {
    Write-Host "No encuentro $RutaProyecto\.env — cópialo desde .env.example y complétalo antes de instalar el servicio." -ForegroundColor Yellow
    exit 1
}
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$argumentos = "-m uvicorn app.main:app --host 0.0.0.0 --port $Puerto"

& $Nssm install $NombreServicio $python $argumentos
& $Nssm set $NombreServicio AppDirectory $backend
& $Nssm set $NombreServicio AppStdout (Join-Path $logs "backend.log")
& $Nssm set $NombreServicio AppStderr (Join-Path $logs "backend-error.log")
& $Nssm set $NombreServicio AppRotateFiles 1
& $Nssm set $NombreServicio AppRotateBytes 10485760
& $Nssm set $NombreServicio Start SERVICE_AUTO_START
& $Nssm set $NombreServicio Description "Conciliador SAP-SUNAT - API (FastAPI/uvicorn)"

Write-Host "`nServicio '$NombreServicio' instalado (aún no iniciado)." -ForegroundColor Green
Write-Host "Iniciar ahora con:   Start-Service $NombreServicio"
Write-Host "Ver estado con:      Get-Service $NombreServicio"
Write-Host "Logs en:             $logs"
Write-Host "`nRecuerda: el frontend debe estar compilado (npm run build en frontend/) para que"
Write-Host "el backend lo sirva — ver README, sección 'Despliegue en producción'."
