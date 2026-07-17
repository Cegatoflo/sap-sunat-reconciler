<#
.SINOPSIS
    Registra la tarea programada que precalienta la caché de propuestas RCE de SUNAT
    todas las madrugadas, para que los analistas nunca esperen a SUNAT en horario laboral.

    Usa los cmdlets New-ScheduledTaskAction/Register-ScheduledTask en vez de `schtasks`:
    schtasks corta mal la ruta cuando el usuario de Windows tiene espacios en el nombre
    (ej. "C:\Users\Cesar Torres\...") y la tarea queda mal creada sin avisar.

    También fuerza -AllowStartIfOnBatteries y -DontStopIfGoingOnBatteries: por defecto el
    Programador de tareas de Windows NO ejecuta nada si el equipo está con batería (en un
    laptop) — la tarea aparece como "correcta" en el historial pero no hizo nada.

.USO (PowerShell como Administrador)
    cd deploy
    .\instalar_tarea_refrescar.ps1
    .\instalar_tarea_refrescar.ps1 -Hora "03:30"
#>
param(
    [string]$RutaProyecto = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$Hora = "03:00",
    [string]$NombreTarea = "Conciliador_RefrescarSUNAT"
)

$ErrorActionPreference = "Stop"

$backend = Join-Path $RutaProyecto "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$script = Join-Path $backend "refrescar_propuestas.py"

if (-not (Test-Path $python)) {
    Write-Host "No encuentro el entorno virtual en $python" -ForegroundColor Yellow
    Write-Host "Creal primero:  cd backend; python -m venv .venv; .venv\Scripts\pip install -r ..\requirements.txt"
    exit 1
}

$accion = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $backend
$disparador = New-ScheduledTaskTrigger -Daily -At $Hora
$config = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $NombreTarea `
    -Action $accion -Trigger $disparador -Settings $config `
    -Description "Precalienta la cache de propuestas RCE de SUNAT (Conciliador SAP-SUNAT)" `
    -RunLevel Highest -Force | Out-Null

Write-Host "Tarea '$NombreTarea' creada — corre todos los días a las $Hora." -ForegroundColor Green
Write-Host "Verificar con:   Get-ScheduledTask -TaskName $NombreTarea"
Write-Host "Probar ya con:   Start-ScheduledTask -TaskName $NombreTarea"
