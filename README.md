# Estampas

Sistema local para gestionar e imprimir estampas personalizadas de Bautismo, Primera Comunión y Confirmación, y sus diplomas. Corre solo en esta PC (Windows), con SQLite, porque usa las fuentes instaladas acá.

## Uso diario

### 1. Abrir el sistema

Botón de Inicio de Windows → **Estampas**. Se abre el navegador con la lista de pedidos. Si pide usuario y contraseña, son los de siempre.

Aparece también una ventana negra llamada «Estampas - servidor», minimizada abajo. **No la cierres mientras trabajás**: es la que hace andar el sistema.

### 2. Cargar un pedido

1. Arriba, **Nuevo pedido**.
2. Completá el número de factura, el número de SAPP y la fecha de entrega.
3. En «Chicos», escribí el nombre de cada chico. Marcá si es mujer o varón: sirve para elegir el diploma. Padrinos, papás y fecha de nacimiento van solo si se imprimen en la estampa.
4. **Agregar chico** suma otro renglón. Al terminar, **Guardar**.

### 3. Cargar las estampas

1. Dentro del pedido, **Agregar estampa**.
2. Elegí el **modelo** (el número de la tarjeta) y el chico. Pueden ser dos, por ejemplo hermanos.
3. Marcá el sacramento: Bautismo, Primera Comunión, Confirmación o varios.
4. Completá la fecha, la parroquia y la localidad.
5. Elegí la **oración**: «Del banco» muestra primero las de ese sacramento (con «Ver todas» aparecen las demás). También podés escribirla a mano o elegir «Sin oración».
6. Poné la **cantidad** y tocá **Guardar y ver la vista previa**.

### 4. Revisar la vista previa

- Mirá que la tarjeta diga lo que tiene que decir.
- **Mostrar contornos** dibuja el espacio de cada texto.
- **Si algo aparece en rojo, el texto no entra.** Tocá «Achicar hasta que entre», o cambiá el texto en el recuadro de abajo y tocá **Guardar texto**. Para deshacer lo escrito a mano, **Volver al texto automático**.
- **Para mover un texto**, con los contornos activados: hacé clic en el texto y arrastralo, o usá las flechas del teclado. Después tocá **Guardar en esta estampa**. Ctrl+Z deshace. «Guardar en el modelo» cambia la tarjeta para siempre: usalo solo si estás segura.

### 5. Imprimir

1. En el pedido, **Imprimir**.
2. Abrí el **PDF de estampas**.
3. En la ventana de imprimir elegí **«Tamaño real» o escala 100 %**. Nunca «Ajustar a la página», porque el texto queda corrido.
4. Si la tarjeta tiene **reverso**, el PDF trae las caras en orden: anverso, reverso, anverso, reverso… Si la impresora imprime de los dos lados, mandalo así. Si no, imprimí de a una hoja y dala vuelta antes de imprimir la siguiente página.
5. Los diplomas salen aparte, con **PDF de diplomas**.

### 6. Marcar el pedido

Cuando lo imprimiste, **Marcar como impreso**. Cuando lo entregaste, **Marcar como enviado**. Generar el PDF no cambia nada: hay que marcarlo a mano.

En la lista de pedidos, **amarillo** quiere decir que la entrega vence en los próximos 3 días y **rojo** que está atrasado.

### 7. Si algo falla

Cerrá la ventana negra «Estampas - servidor» y volvé a abrir **Estampas** desde el menú Inicio. No se pierde nada: todo queda guardado.

### Dónde está cada cosa

| Qué | Dónde |
|---|---|
| El sistema, en el navegador | <http://127.0.0.1:8001/> |
| Código del programa | `C:\Users\FIX\OneDrive\Proyectos\estampas` |
| Base de datos (pedidos, modelos, oraciones) | `C:\EstampasDatos\db.sqlite3` |
| Backups (últimos 30) | `C:\EstampasDatos\backups\` (el registro, en `backups.log`) |
| Copia extra de los backups (últimos 7) | La carpeta de `BACKUP_EXTRA_DIR` en `.env` |
| Entorno de Python | `%USERPROFILE%\.virtualenvs\estampas` |
| Configuración y clave secreta | `.env`, en la carpeta del programa (no se sube a GitHub) |
| Fuentes de las tarjetas | `fuentes\`, en la carpeta del programa (no se sube a GitHub) |
| Modelos de Word originales | `modelos_docx\`, en la carpeta del programa (no se sube a GitHub) |

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
