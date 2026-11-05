# Estampas

Sistema local para gestionar e imprimir estampas personalizadas de Bautismo, Primera Comunión y Confirmación, y sus diplomas. Corre solo en esta PC (Windows), con SQLite, porque usa las fuentes instaladas acá.

## Requisitos

- Python 3.12
- Las carpetas `modelos_docx/` y `fuentes/` no están en el repositorio: tienen datos personales y fuentes comerciales. Hay que copiarlas a mano.

## Instalación

El entorno virtual va en `%USERPROFILE%\.virtualenvs\estampas`, fuera de OneDrive, para que no se sincronicen sus miles de archivos. Desde la carpeta del proyecto, en PowerShell:

```powershell
python -m venv "$env:USERPROFILE\.virtualenvs\estampas"
& "$env:USERPROFILE\.virtualenvs\estampas\Scripts\Activate.ps1"
python -m pip install -r requirements.txt
```

Si `.env` no existe, crealo con una clave nueva:

```powershell
python -c "from django.core.management.utils import get_random_secret_key as g; open('.env','w',newline=chr(10)).write('SECRET_KEY=' + chr(39) + g() + chr(39) + chr(10))"
```

Después creá las tablas y tu usuario:

```powershell
python manage.py migrate
python manage.py createsuperuser
```

## Uso

```powershell
& "$env:USERPROFILE\.virtualenvs\estampas\Scripts\Activate.ps1"
python manage.py runserver
```

El sistema queda en http://127.0.0.1:8001/admin/. Usa el puerto 8001 por defecto porque el 8000 lo ocupa otro sistema.

## Pruebas

```powershell
python manage.py test
```
