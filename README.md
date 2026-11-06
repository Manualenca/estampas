# Estampas

Sistema local para gestionar e imprimir estampas personalizadas de Bautismo, Primera Comunión y Confirmación, y sus diplomas. Corre solo en esta PC (Windows), con SQLite, porque usa las fuentes instaladas acá.

## Requisitos

- Python 3.12
- Las carpetas `modelos_docx/` y `fuentes/` no están en el repositorio: tienen datos personales y fuentes comerciales. Hay que copiarlas a mano.

## Instalación

El entorno virtual va en `%USERPROFILE%\.virtualenvs\estampas` y la base en `C:\EstampasDatos`, ambos fuera de OneDrive. Desde la carpeta del proyecto, en PowerShell:

```powershell
python -m venv "$env:USERPROFILE\.virtualenvs\estampas"
& "$env:USERPROFILE\.virtualenvs\estampas\Scripts\Activate.ps1"
python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force C:\EstampasDatos
```

Si `.env` no existe, crealo a partir de `.env.example` con una clave nueva:

```powershell
python -c "from pathlib import Path as P; from django.core.management.utils import get_random_secret_key as g; P('.env').write_text(P('.env.example').read_text(encoding='utf-8').replace('poner-aca-una-clave-larga-y-aleatoria', g()), encoding='utf-8')"
```

Después creá las tablas, tu usuario, cargá los modelos y copiá sus fuentes:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py importar_modelos
python manage.py copiar_fuentes
```

`copiar_fuentes` busca en Windows, en tu carpeta de fuentes y en la caché de nube de Office (Abadi, Bierstadt) y las copia a `fuentes/` con nombres estables. Si una fuente solo existe como instancia de una fuente variable (por ejemplo, Bahnschrift SemiLight), genera un archivo fijo con fontTools. Hay que volver a correrlo si un modelo nuevo usa otra fuente.

## Uso

Doble clic en **Estampas** (en el menú Inicio, o `Estampas.bat` en la carpeta del proyecto). Hace el backup si el último tiene más de 24 horas, levanta el servidor en una ventana minimizada y abre el navegador. Si el servidor ya está corriendo, solo abre el navegador. Para detener el sistema, cerrá la ventana «Estampas - servidor».

Para volver a crear el acceso directo del menú Inicio: `powershell -ExecutionPolicy Bypass -File scripts\crear_acceso_directo.ps1`.

A mano, sin el lanzador:

```powershell
& "$env:USERPROFILE\.virtualenvs\estampas\Scripts\Activate.ps1"
python manage.py runserver
```

El sistema queda en <http://127.0.0.1:8001/> y el admin en <http://127.0.0.1:8001/admin/>. Usa el puerto 8001 por defecto porque el 8000 lo ocupa otro sistema.

## Importar modelos

| Comando | Qué hace |
|---|---|
| `python manage.py importar_modelos` | Recorre `modelos_docx/` (con subcarpetas) e importa lo que todavía no está en la base. |
| `python manage.py importar_modelos "ruta\Tarj2059.docx"` | Importa solo ese archivo. |
| `python manage.py importar_modelos --actualizar` | Actualiza los cuadros de lo ya importado. Conserva la calibración, las imágenes de fondo, los colores por género y los roles corregidos a mano. |

| `python manage.py importar_modelos --estilos` | Lleva a las plantillas de cada variante la negrita por partes del .docx (por ejemplo, "**Mi Madrina:** Eva") y muestra qué cambió. |

Al terminar muestra un resumen. Los cuadros marcados "sin asignar" se corrigen desde el admin y no se imprimen hasta tener un rol.

Después de `--actualizar`, volvé a correr `--estilos`: la actualización rehace los estilos por parte de cada cuadro.

## Imprimir

Desde el pedido, «Imprimir» da el PDF de estampas (cada página del tamaño exacto de la tarjeta, con anverso, reverso y copias) y el PDF de diplomas. Imprimí siempre en **tamaño real / 100 %, sin «Ajustar a la página»**. Generar el PDF no cambia el estado: usá «Marcar como impreso» y después «Marcar como enviado».

Para calibrar la impresora, en «Modelos y calibración» imprimí la hoja de prueba del modelo en papel común, superponela a la tarjeta y cargá cuánto se corre (X positivo mueve a la derecha; Y positivo, hacia abajo). Cada cara tiene su propio ajuste.

## Copias de seguridad

```powershell
python manage.py backup_db
```

Copia la base a `C:\EstampasDatos\backups\` con fecha y hora en el nombre, y conserva las últimas 30 copias. Cada backup queda anotado en `C:\EstampasDatos\backups\backups.log`. Con `--si-hace-falta` solo copia si el último tiene más de 24 horas (lo usa el lanzador).

Si en `.env` completás `BACKUP_EXTRA_DIR` (por ejemplo, una carpeta de tu OneDrive personal), cada backup se copia también ahí y se conservan los últimos 7. Si esa carpeta no existe o la copia falla, el backup principal se hace igual y el problema queda anotado en `backups.log`.

Para que se haga solo todos los días (a las 13:00, o apenas se prenda la PC si estaba apagada), creá la tarea del Programador de tareas una vez:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\crear_tarea_backup.ps1
```

## Pruebas

```powershell
python manage.py test
```
