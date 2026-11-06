@echo off
rem Lanzador de Estampas: levanta el servidor en el puerto 8001 (si no esta corriendo) y abre el navegador.
setlocal
cd /d "%~dp0"
set "VENV=%USERPROFILE%\.virtualenvs\estampas"
rem ESTAMPAS_PUERTO permite probar el lanzador en otro puerto; lo normal es 8001.
if not defined ESTAMPAS_PUERTO set "ESTAMPAS_PUERTO=8001"
set "URL=http://127.0.0.1:%ESTAMPAS_PUERTO%/"

if not exist "%VENV%\Scripts\activate.bat" (
    echo No se encontro el entorno de Python en %VENV%.
    echo Crealo siguiendo los pasos del README.md.
    pause
    exit /b 1
)

rem Si el servidor ya responde, solo se abre el navegador.
call :responde
if not errorlevel 1 goto abrir

call "%VENV%\Scripts\activate.bat"

rem Backup si el ultimo tiene mas de 24 horas.
python manage.py backup_db --si-hace-falta

rem El servidor queda en una ventana minimizada: cerrarla lo detiene.
start "Estampas - servidor (cerrar esta ventana detiene el sistema)" /min cmd /k python manage.py runserver %ESTAMPAS_PUERTO%

rem Esperar hasta 30 segundos a que el servidor responda.
for /l %%i in (1,1,30) do (
    call :responde
    if not errorlevel 1 goto abrir
    rem Pausa de 1 segundo (ping funciona aunque la entrada este redirigida, timeout no).
    ping -n 2 127.0.0.1 >nul
)
echo El servidor no respondio. Revisa la ventana "Estampas - servidor".
pause
exit /b 1

:abrir
rem ESTAMPAS_SIN_NAVEGADOR=1 sirve para probar el lanzador sin abrir el navegador.
if defined ESTAMPAS_SIN_NAVEGADOR exit /b 0
start "" "%URL%"
exit /b 0

:responde
rem Devuelve 0 si en el puerto responde Estampas (y no otro sistema).
curl.exe -s -m 2 "%URL%admin/login/" 2>nul | findstr /c:"Estampas" >nul
exit /b %errorlevel%
