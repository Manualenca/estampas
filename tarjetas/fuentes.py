"""Ubica las fuentes de los modelos en esta PC y las copia a la carpeta fuentes/ del proyecto.

Algunas fuentes (Abadi, Bierstadt) están en la caché de nube de Office y no las ve el
navegador ni ReportLab. Copiarlas con nombres estables las deja disponibles para los dos.
"""

import os
import re
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

EXTENSIONES = {".ttf", ".otf"}
ESTILOS = {
    "regular": (400, "normal"),
    "normal": (400, "normal"),
    "bold": (700, "normal"),
    "italic": (400, "italic"),
    "oblique": (400, "italic"),
    "bold italic": (700, "italic"),
    "bold oblique": (700, "italic"),
}


@dataclass(frozen=True)
class Cara:
    familia: str
    estilo: str
    ruta: Path

    @property
    def peso_y_estilo(self):
        return ESTILOS.get(self.estilo.lower(), (400, "normal"))


def carpetas_del_sistema():
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return [
        windows / "Fonts",
        local / "Microsoft" / "Windows" / "Fonts",
        local / "Microsoft" / "FontCache" / "4" / "CloudFonts",
    ]


def leer_nombres(ruta):
    """(familia, estilo) según la tabla "name" del archivo. None si no se puede leer."""
    try:
        with open(ruta, "rb") as archivo:
            datos = archivo.read()
        if datos[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            return None
        cantidad = struct.unpack(">H", datos[4:6])[0]
        for i in range(cantidad):
            etiqueta, _, inicio, _ = struct.unpack(">4sIII", datos[12 + 16 * i : 28 + 16 * i])
            if etiqueta == b"name":
                return _tabla_nombres(datos, inicio)
    except (OSError, struct.error):
        return None
    return None


def _tabla_nombres(datos, inicio):
    _, cantidad, base = struct.unpack(">HHH", datos[inicio : inicio + 6])
    nombres = {}
    for i in range(cantidad):
        registro = datos[inicio + 6 + 12 * i : inicio + 18 + 12 * i]
        plataforma, codificacion, idioma, nombre, largo, desde = struct.unpack(">HHHHHH", registro)
        if nombre not in (1, 2):
            continue
        crudo = datos[inicio + base + desde : inicio + base + desde + largo]
        if plataforma == 3:
            texto = crudo.decode("utf-16-be", errors="ignore")
            prioridad = 0 if idioma == 0x409 else 1
        elif plataforma == 1:
            texto = crudo.decode("mac_roman", errors="ignore")
            prioridad = 2
        else:
            continue
        actual = nombres.get(nombre)
        if actual is None or prioridad < actual[0]:
            nombres[nombre] = (prioridad, texto.strip())
    if 1 not in nombres:
        return None
    return nombres[1][1], nombres.get(2, (0, "Regular"))[1]


def buscar(familias, carpetas=None):
    """Caras encontradas por familia (sin distinguir mayúsculas)."""
    buscadas = {f.lower(): f for f in familias if f}
    encontradas = {}
    for carpeta in carpetas or carpetas_del_sistema():
        if not carpeta.is_dir():
            continue
        for ruta in carpeta.rglob("*"):
            if ruta.suffix.lower() not in EXTENSIONES:
                continue
            nombres = leer_nombres(ruta)
            if not nombres or nombres[0].lower() not in buscadas:
                continue
            familia = buscadas[nombres[0].lower()]
            caras = encontradas.setdefault(familia, {})
            caras.setdefault(nombres[1].lower(), Cara(familia, nombres[1], ruta))
    return {familia: list(caras.values()) for familia, caras in encontradas.items()}


def nombre_de_archivo(cara):
    limpio = lambda t: re.sub(r'[<>:"/\\|?*]', "", t).strip()  # noqa: E731
    return f"{limpio(cara.familia)} - {limpio(cara.estilo)}{cara.ruta.suffix.lower()}"


def buscar_instancias_variables(familias, carpetas=None):
    """Familias pedidas que son una instancia de una fuente variable, como "Bahnschrift SemiLight".

    Devuelve {familia: (ruta de la fuente variable, coordenadas de los ejes)}.
    """
    from fontTools.ttLib import TTFont

    buscadas = {f.lower(): f for f in familias if f}
    halladas = {}
    for carpeta in carpetas or carpetas_del_sistema():
        if not carpeta.is_dir():
            continue
        for ruta in carpeta.rglob("*"):
            if ruta.suffix.lower() not in EXTENSIONES:
                continue
            nombres = leer_nombres(ruta)
            if not nombres or not any(b.startswith(nombres[0].lower() + " ") for b in buscadas):
                continue
            try:
                fuente = TTFont(ruta, lazy=True)
            except Exception:  # noqa: BLE001 - archivo de fuente ilegible: se ignora.
                continue
            if "fvar" not in fuente:
                continue
            for instancia in fuente["fvar"].instances:
                estilo = fuente["name"].getDebugName(instancia.subfamilyNameID) or ""
                completo = f"{nombres[0]} {estilo}".lower()
                if completo in buscadas and buscadas[completo] not in halladas:
                    halladas[buscadas[completo]] = (ruta, dict(instancia.coordinates))
    return halladas


def generar_instancia(origen, coordenadas, familia, destino):
    """Crea un TTF estático de una instancia de fuente variable, con el nombre de la familia."""
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    variable = TTFont(origen)
    fija = instancer.instantiateVariableFont(variable, coordenadas)
    nombre_ps = re.sub(r"[^A-Za-z0-9-]", "", familia.replace(" ", "-"))
    tabla = fija["name"]
    for identificador in (16, 17, 21, 22, 25):
        tabla.removeNames(nameID=identificador)
    for identificador, texto in ((1, familia), (2, "Regular"), (3, f"{nombre_ps};estampas"),
                                 (4, familia), (6, nombre_ps)):
        tabla.setName(texto, identificador, 3, 1, 0x409)
        tabla.setName(texto, identificador, 1, 0, 0)
    final = Path(destino) / familia / f"{familia} - Regular.ttf"
    final.parent.mkdir(parents=True, exist_ok=True)
    fija.save(final)
    return Cara(familia, "Regular", final)


def copiar(familias, destino, carpetas=None):
    """Copia las caras encontradas a destino/<familia>/. Devuelve (copiadas, faltantes, generadas).

    Las familias que solo existen como instancia de una fuente variable se generan con fontTools.
    """
    encontradas = buscar(familias, carpetas)
    copiadas = []
    for familia, caras in encontradas.items():
        carpeta = Path(destino) / familia
        carpeta.mkdir(parents=True, exist_ok=True)
        for cara in caras:
            final = carpeta / nombre_de_archivo(cara)
            if not final.exists() or final.stat().st_size != cara.ruta.stat().st_size:
                shutil.copyfile(cara.ruta, final)
            copiadas.append(Cara(familia, cara.estilo, final))
    pendientes = [f for f in familias if f and f not in encontradas]
    generadas = []
    for familia, (origen, coordenadas) in buscar_instancias_variables(pendientes, carpetas).items():
        cara = generar_instancia(origen, coordenadas, familia, destino)
        copiadas.append(cara)
        generadas.append((familia, origen.name, coordenadas))
    hechas = {c.familia for c in copiadas}
    faltantes = sorted(f for f in pendientes if f not in hechas)
    return copiadas, faltantes, generadas


def alto_de_linea_de_archivo(ruta):
    """Alto de renglón sencillo según la tabla hhea de la fuente, relativo al tamaño."""
    from fontTools.ttLib import TTFont

    try:
        fuente = TTFont(ruta, lazy=True)
        cabecera = fuente["hhea"]
        return (cabecera.ascent - cabecera.descent + cabecera.lineGap) / fuente["head"].unitsPerEm
    except Exception:  # noqa: BLE001 - sin métricas legibles: que decida quien llama.
        return None


def catalogo(carpeta):
    """Caras disponibles en la carpeta del proyecto."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return []
    caras = []
    for ruta in sorted(carpeta.rglob("*")):
        if ruta.suffix.lower() in EXTENSIONES:
            nombres = leer_nombres(ruta)
            if nombres:
                caras.append(Cara(nombres[0], nombres[1], ruta))
    return caras
