# Crea en el escritorio un acceso directo a Estampas.bat.
$proyecto = Split-Path -Parent $PSScriptRoot
$escritorio = [Environment]::GetFolderPath("Desktop")
$acceso = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $escritorio "Estampas.lnk"))
$acceso.TargetPath = Join-Path $proyecto "Estampas.bat"
$acceso.WorkingDirectory = $proyecto
$acceso.WindowStyle = 7  # Minimizado: la ventana del lanzador no molesta.
$acceso.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
$acceso.Description = "Abre el sistema de estampas"
$acceso.Save()
Write-Output "Acceso directo creado: $(Join-Path $escritorio 'Estampas.lnk')"
