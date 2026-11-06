# Crea la tarea "Estampas - backup diario" en el Programador de tareas de Windows.
# Corre todos los días a las 13:00 con tu usuario, sin ventana. Si la PC estaba apagada a esa hora,
# se ejecuta apenas se pueda. El resultado queda en C:\EstampasDatos\backups\backups.log.
$proyecto = Split-Path -Parent $PSScriptRoot
$python = Join-Path $env:USERPROFILE ".virtualenvs\estampas\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { throw "No se encontró $python. Creá el entorno siguiendo el README." }

$accion = New-ScheduledTaskAction -Execute $python -Argument "`"$proyecto\manage.py`" backup_db" -WorkingDirectory $proyecto
$disparador = New-ScheduledTaskTrigger -Daily -At "13:00"
$opciones = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "Estampas - backup diario" -Action $accion -Trigger $disparador -Settings $opciones `
    -Description "Copia la base de Estampas a C:\EstampasDatos\backups (conserva 30 copias)." -Force | Out-Null
Write-Output "Tarea creada. Para probarla ahora: Start-ScheduledTask -TaskName 'Estampas - backup diario'"
