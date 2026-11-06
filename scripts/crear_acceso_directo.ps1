# Crea en el menú Inicio un acceso directo a Estampas.bat (no en el escritorio: está en OneDrive compartido).
$proyecto = Split-Path -Parent $PSScriptRoot
$destino = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Estampas.lnk"
$acceso = (New-Object -ComObject WScript.Shell).CreateShortcut($destino)
$acceso.TargetPath = Join-Path $proyecto "Estampas.bat"
$acceso.WorkingDirectory = $proyecto
$acceso.WindowStyle = 7  # Minimizado: la ventana del lanzador no molesta.
$acceso.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
$acceso.Description = "Abre el sistema de estampas"
$acceso.Save()
Write-Output "Acceso directo creado: $destino"
