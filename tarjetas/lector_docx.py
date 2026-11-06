"""Lee la geometría y el texto de los cuadros de un .docx, en mm desde el borde de la hoja."""

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "wp14": "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
}
EMU_A_MM = 1 / 36000
TWIP_A_MM = 25.4 / 1440
PT_A_MM = 25.4 / 72
INSET_X_MM = 2.54
INSET_Y_MM = 1.27

# Alto de renglón "sencillo" relativo al tamaño, medido en los PDF que genera Word.
ALTO_LINEA_FUENTE = {
    "abadi": 1.07,
    "algerian": 1.33,
    "arial narrow": 1.15,
    "brush script mt": 1.33,
    "calibri": 1.22,
    "cordia new": 1.235,
    "curlz mt": 1.33,
    "edwardian script itc": 1.18,
    "french script mt": 1.14,
    "georgia": 1.13,
    "harrington": 1.18,
    "monotype corsiva": 1.12,
    "times new roman": 1.15,
}
ALTO_LINEA_DEFECTO = 1.20


def q(nombre):
    prefijo, local = nombre.split(":")
    return "{%s}%s" % (NS[prefijo], local)


W = lambda local: q("w:" + local)  # noqa: E731


@dataclass
class Corrida:
    texto: str
    fuente: str | None = None
    tamano: float | None = None
    negrita: bool = False
    cursiva: bool = False
    color: str | None = None
    espaciado: float = 0


@dataclass
class Parrafo:
    corridas: list = field(default_factory=list)
    alineacion: str | None = None
    linea: int | None = None
    regla_linea: str | None = None
    despues: float = 0
    antes: float = 0
    sangria_izquierda: float = 0  # mm
    sangria_derecha: float = 0  # mm
    sangria_primera: float = 0  # mm, respecto de la izquierda (negativa = francesa)
    tamano_marca: float | None = None
    fuente_marca: str | None = None

    @property
    def texto(self):
        return "".join(c.texto for c in self.corridas)

    def alto_mm(self):
        """Alto estimado de un renglón del párrafo más el espacio posterior."""
        visibles = [c for c in self.corridas if c.texto.strip()]
        principal = max(visibles, key=lambda c: len(c.texto), default=None)
        tamano = (principal.tamano if principal else None) or self.tamano_marca or 11
        fuente = (principal.fuente if principal else None) or self.fuente_marca or ""
        factor = ALTO_LINEA_FUENTE.get(fuente.lower(), ALTO_LINEA_DEFECTO)
        natural = tamano * factor
        if self.regla_linea in ("exact", "atLeast") and self.linea:
            exacto = self.linea / 20
            alto = exacto if self.regla_linea == "exact" else max(natural, exacto)
        else:
            alto = natural * ((self.linea or 240) / 240)
        return (alto + self.antes + self.despues) * PT_A_MM


@dataclass
class Cuadro:
    indice: int
    pagina: int
    x: float
    y: float
    ancho: float
    alto: float
    parrafos: list
    ancla_vertical: str = "t"
    invertido: bool = False
    oculto: bool = False
    con_relleno: bool = False
    orden_z: int = 0

    @property
    def texto(self):
        return "\n".join(p.texto for p in self.parrafos).strip()

    def fuera_de_hoja(self, ancho_hoja, alto_hoja):
        return (
            self.y + self.alto <= 0
            or self.y >= alto_hoja
            or self.x + self.ancho <= 0
            or self.x >= ancho_hoja
        )


@dataclass
class Documento:
    ancho_mm: float
    alto_mm: float
    cuadros: list


def _activo(elemento):
    return elemento is not None and elemento.get(W("val")) not in ("0", "false", "off")


class Estilos:
    """Resuelve fuente y formato heredados de estilos, valores por defecto y tema."""

    def __init__(self, archivo):
        self.por_defecto = {}
        self.parrafo_defecto = {}
        self.estilos = {}
        self.estilo_base = None
        self.tema = {}
        if "word/theme/theme1.xml" in archivo.namelist():
            tema = ET.fromstring(archivo.read("word/theme/theme1.xml"))
            for clave, etiqueta in (("minor", "a:minorFont"), ("major", "a:majorFont")):
                latin = tema.find(".//" + q(etiqueta) + "/" + q("a:latin"))
                if latin is not None:
                    self.tema[clave] = latin.get("typeface")
        if "word/styles.xml" not in archivo.namelist():
            return
        raiz = ET.fromstring(archivo.read("word/styles.xml"))
        defaults = raiz.find(W("docDefaults"))
        if defaults is not None:
            run = defaults.find(W("rPrDefault") + "/" + W("rPr"))
            parrafo = defaults.find(W("pPrDefault") + "/" + W("pPr"))
            if run is not None:
                self.por_defecto = self.leer_run(run)
            if parrafo is not None:
                self.parrafo_defecto = self.leer_parrafo(parrafo)
        for estilo in raiz.findall(W("style")):
            identificador = estilo.get(W("styleId"))
            base = estilo.find(W("basedOn"))
            run = estilo.find(W("rPr"))
            parrafo = estilo.find(W("pPr"))
            self.estilos[identificador] = {
                "base": base.get(W("val")) if base is not None else None,
                "run": self.leer_run(run) if run is not None else {},
                "parrafo": self.leer_parrafo(parrafo) if parrafo is not None else {},
            }
            if estilo.get(W("default")) == "1" and estilo.get(W("type")) == "paragraph":
                self.estilo_base = identificador

    def _fuente(self, fuentes):
        if fuentes is None:
            return None
        directa = fuentes.get(W("ascii")) or fuentes.get(W("hAnsi"))
        if directa:
            return directa
        tema = fuentes.get(W("asciiTheme")) or fuentes.get(W("hAnsiTheme"))
        if tema:
            return self.tema.get("major" if tema.startswith("major") else "minor")
        return None

    def leer_run(self, elemento):
        datos = {}
        fuente = self._fuente(elemento.find(W("rFonts")))
        if fuente:
            datos["fuente"] = fuente
        tamano = elemento.find(W("sz"))
        if tamano is not None:
            datos["tamano"] = float(tamano.get(W("val"))) / 2
        for etiqueta, clave in (("b", "negrita"), ("i", "cursiva")):
            valor = elemento.find(W(etiqueta))
            if valor is not None:
                datos[clave] = _activo(valor)
        color = elemento.find(W("color"))
        if color is not None and color.get(W("val")) != "auto":
            datos["color"] = color.get(W("val"))
        espaciado = elemento.find(W("spacing"))
        if espaciado is not None:
            datos["espaciado"] = int(espaciado.get(W("val"))) / 20
        estilo = elemento.find(W("rStyle"))
        if estilo is not None:
            datos["estilo_run"] = estilo.get(W("val"))
        return datos

    def leer_parrafo(self, elemento):
        datos = {}
        alineacion = elemento.find(W("jc"))
        if alineacion is not None:
            datos["alineacion"] = alineacion.get(W("val"))
        espacio = elemento.find(W("spacing"))
        if espacio is not None:
            if espacio.get(W("after")) is not None:
                datos["despues"] = int(espacio.get(W("after"))) / 20
            if espacio.get(W("before")) is not None:
                datos["antes"] = int(espacio.get(W("before"))) / 20
            if espacio.get(W("line")) is not None:
                datos["linea"] = int(espacio.get(W("line")))
            datos["regla_linea"] = espacio.get(W("lineRule")) or datos.get("regla_linea")
        sangria = elemento.find(W("ind"))
        if sangria is not None:
            valor = lambda *claves: next(  # noqa: E731
                (int(sangria.get(W(c))) for c in claves if sangria.get(W(c)) is not None), None
            )
            izquierda, derecha = valor("left", "start"), valor("right", "end")
            primera, francesa = valor("firstLine"), valor("hanging")
            if izquierda is not None:
                datos["sangria_izquierda"] = izquierda * TWIP_A_MM
            if derecha is not None:
                datos["sangria_derecha"] = derecha * TWIP_A_MM
            if francesa is not None:
                datos["sangria_primera"] = -francesa * TWIP_A_MM
            elif primera is not None:
                datos["sangria_primera"] = primera * TWIP_A_MM
        estilo = elemento.find(W("pStyle"))
        if estilo is not None:
            datos["estilo"] = estilo.get(W("val"))
        return datos

    def _cadena(self, identificador):
        cadena, vistos = [], set()
        while identificador in self.estilos and identificador not in vistos:
            vistos.add(identificador)
            cadena.append(self.estilos[identificador])
            identificador = self.estilos[identificador]["base"]
        return list(reversed(cadena))

    def parrafo_efectivo(self, propios):
        datos = dict(self.parrafo_defecto)
        for estilo in self._cadena(propios.get("estilo") or self.estilo_base):
            datos.update({k: v for k, v in estilo["parrafo"].items() if v is not None})
        datos.update({k: v for k, v in propios.items() if v is not None})
        return datos

    def run_efectivo(self, estilo_parrafo, propios):
        datos = dict(self.por_defecto)
        for estilo in self._cadena(estilo_parrafo or self.estilo_base):
            datos.update(estilo["run"])
        if propios.get("estilo_run"):
            for estilo in self._cadena(propios["estilo_run"]):
                datos.update(estilo["run"])
        datos.update(propios)
        datos.pop("estilo_run", None)
        return datos


def _leer_parrafo(elemento, estilos):
    propiedades = elemento.find(W("pPr"))
    propios = estilos.leer_parrafo(propiedades) if propiedades is not None else {}
    efectivo = estilos.parrafo_efectivo(propios)
    estilo = propios.get("estilo")
    marca = {}
    if propiedades is not None and propiedades.find(W("rPr")) is not None:
        marca = estilos.leer_run(propiedades.find(W("rPr")))
    marca = estilos.run_efectivo(estilo, marca)
    parrafo = Parrafo(
        alineacion=efectivo.get("alineacion"),
        linea=efectivo.get("linea"),
        regla_linea=efectivo.get("regla_linea"),
        despues=efectivo.get("despues", 0) or 0,
        antes=efectivo.get("antes", 0) or 0,
        sangria_izquierda=efectivo.get("sangria_izquierda", 0) or 0,
        sangria_derecha=efectivo.get("sangria_derecha", 0) or 0,
        sangria_primera=efectivo.get("sangria_primera", 0) or 0,
        tamano_marca=marca.get("tamano"),
        fuente_marca=marca.get("fuente"),
    )
    for run in elemento.iter(W("r")):
        texto = ""
        for hijo in run:
            if hijo.tag == W("t"):
                texto += hijo.text or ""
            elif hijo.tag in (W("br"), W("cr")):
                texto += "\n"
            elif hijo.tag == W("tab"):
                texto += "\t"
        if not texto:
            continue
        propiedades_run = run.find(W("rPr"))
        datos = estilos.run_efectivo(
            estilo, estilos.leer_run(propiedades_run) if propiedades_run is not None else {}
        )
        parrafo.corridas.append(Corrida(texto=texto, **datos))
    return parrafo


def _leer_contenido(contenedor, estilos):
    return [_leer_parrafo(p, estilos) for p in contenedor.findall(W("p"))]


def _quitar_fallback(raiz):
    for padre in raiz.iter():
        for hijo in list(padre):
            if hijo.tag == q("mc:Fallback"):
                padre.remove(hijo)


def _medida(estilo, clave):
    """Valor en mm de una propiedad de estilo VML. Sin unidad devuelve el número crudo."""
    hallado = re.search(r"(?:^|;)" + clave + r":(-?[\d.]+)(pt|in|mm|cm)?", estilo)
    if not hallado:
        return None
    valor = float(hallado.group(1))
    unidades = {"pt": PT_A_MM, "in": 25.4, "mm": 1, "cm": 10}
    return valor * unidades[hallado.group(2)] if hallado.group(2) else valor


def _propiedad(estilo, clave):
    hallado = re.search(r"(?:^|;)" + clave + r":([^;]+)", estilo)
    return hallado.group(1) if hallado else None


class _Hoja:
    def __init__(self, seccion):
        tamano = seccion.find(W("pgSz"))
        margenes = seccion.find(W("pgMar"))
        self.ancho = int(tamano.get(W("w"))) * TWIP_A_MM
        self.alto = int(tamano.get(W("h"))) * TWIP_A_MM
        medida = lambda k: int(margenes.get(W(k), 0)) * TWIP_A_MM  # noqa: E731
        self.izquierda = medida("left")
        self.derecha = medida("right")
        self.arriba = medida("top")
        self.abajo = medida("bottom")

    def referencia_horizontal(self, relativo):
        if relativo == "page":
            return 0, self.ancho
        if relativo in ("leftMargin", "insideMargin"):
            return 0, self.izquierda
        if relativo in ("rightMargin", "outsideMargin"):
            return self.ancho - self.derecha, self.derecha
        return self.izquierda, self.ancho - self.izquierda - self.derecha

    def referencia_vertical(self, relativo, y_parrafo):
        if relativo == "page":
            return 0, self.alto
        if relativo == "topMargin":
            return 0, self.arriba
        if relativo == "bottomMargin":
            return self.alto - self.abajo, self.abajo
        if relativo == "margin":
            return self.arriba, self.alto - self.arriba - self.abajo
        return y_parrafo, None


def _posicion(elemento, base, area, total, extension, etiqueta_porcentaje):
    desplazamiento = elemento.find(q("wp:posOffset"))
    alineacion = elemento.find(q("wp:align"))
    porcentaje = elemento.find(q(etiqueta_porcentaje))
    if porcentaje is not None and porcentaje.text:
        return base + (area or total) * int(porcentaje.text) / 100000
    if desplazamiento is not None and desplazamiento.text is not None:
        return base + int(desplazamiento.text) * EMU_A_MM
    if alineacion is not None:
        disponible = area if area is not None else total
        return base + {
            "center": (disponible - extension) / 2,
            "right": disponible - extension,
            "bottom": disponible - extension,
            "outside": disponible - extension,
        }.get(alineacion.text, 0)
    return base


def _rot_180(xfrm):
    return xfrm is not None and int(xfrm.get("rot", 0)) % 21600000 == 10800000


def _flip_v(xfrm):
    return xfrm is not None and xfrm.get("flipV") == "1"


class _Lector:
    def __init__(self, ruta):
        with zipfile.ZipFile(ruta) as archivo:
            self.estilos = Estilos(archivo)
            self.raiz = ET.fromstring(archivo.read("word/document.xml"))
        _quitar_fallback(self.raiz)
        cuerpo = self.raiz.find(W("body"))
        self.hoja = _Hoja(self.raiz.findall(".//" + W("sectPr"))[-1])
        self.cuerpo = cuerpo
        self.cuadros = []
        self.pagina = 1
        self.y_parrafo = self.hoja.arriba

    def leer(self):
        for elemento in self.cuerpo:
            if elemento.tag != W("p"):
                continue
            self.salto_pagina = False
            self.alto_en_linea = 0
            self._recorrer(elemento)
            if self.salto_pagina:
                self.y_parrafo = self.hoja.arriba
            else:
                parrafo = _leer_parrafo_cuerpo(elemento, self.estilos)
                self.y_parrafo += max(parrafo.alto_mm(), self.alto_en_linea)
        return Documento(self.hoja.ancho, self.hoja.alto, self.cuadros)

    def _recorrer(self, elemento):
        for hijo in elemento:
            if hijo.tag == q("wp:anchor"):
                self._leer_ancla(hijo)
            elif hijo.tag == q("wp:inline"):
                extension = hijo.find(q("wp:extent"))
                self.alto_en_linea += int(extension.get("cy")) * EMU_A_MM
            elif hijo.tag == W("pict"):
                self._leer_vml(hijo)
            elif hijo.tag == W("br") and hijo.get(W("type")) == "page":
                self.pagina += 1
                self.salto_pagina = True
            elif hijo.tag != W("txbxContent"):
                self._recorrer(hijo)

    def _agregar(self, x, y, ancho, alto, contenido, **extra):
        self.cuadros.append(
            Cuadro(
                indice=len(self.cuadros),
                pagina=self.pagina,
                x=x,
                y=y,
                ancho=ancho,
                alto=alto,
                parrafos=_leer_contenido(contenido, self.estilos),
                **extra,
            )
        )

    def _leer_ancla(self, ancla):
        extension = ancla.find(q("wp:extent"))
        ancho, alto = (int(extension.get(k)) * EMU_A_MM for k in ("cx", "cy"))
        if ancla.get("simplePos") == "1":
            simple = ancla.find(q("wp:simplePos"))
            x, y = int(simple.get("x")) * EMU_A_MM, int(simple.get("y")) * EMU_A_MM
        else:
            horizontal = ancla.find(q("wp:positionH"))
            vertical = ancla.find(q("wp:positionV"))
            base, area = self.hoja.referencia_horizontal(horizontal.get("relativeFrom"))
            x = _posicion(horizontal, base, area, self.hoja.ancho, ancho, "wp14:pctPosHOffset")
            base, area = self.hoja.referencia_vertical(vertical.get("relativeFrom"), self.y_parrafo)
            y = _posicion(vertical, base, area, self.hoja.alto, alto, "wp14:pctPosVOffset")

        datos = ancla.find(q("a:graphic") + "/" + q("a:graphicData"))
        if datos is None:
            return
        propiedades = ancla.find(q("wp:docPr"))
        comunes = {
            "oculto": propiedades is not None and propiedades.get("hidden") in ("1", "true"),
            "orden_z": int(ancla.get("relativeHeight", 0)),
        }
        forma = datos.find(q("wps:wsp"))
        grupo = datos.find(q("wpg:wgp"))
        if forma is not None:
            self._agregar_forma(forma, x, y, ancho, alto, False, comunes)
        elif grupo is not None:
            xfrm = grupo.find(q("wpg:grpSpPr") + "/" + q("a:xfrm"))
            externo = xfrm.find(q("a:ext"))
            ancho_grupo, alto_grupo = int(externo.get("cx")), int(externo.get("cy"))
            escala_ancla = (
                (int(extension.get("cx")) / ancho_grupo) if ancho_grupo else 1,
                (int(extension.get("cy")) / alto_grupo) if alto_grupo else 1,
            )
            self._leer_grupo(
                grupo, xfrm, x, y, ancho, alto, escala_ancla, False, False, False, comunes
            )

    def _leer_grupo(
        self, grupo, xfrm, x, y, ancho, alto, escala_padre, espejo_h, espejo_v, invertido, comunes
    ):
        """Hijos con offset relativo al grupo, escalado por chOff/chExt y espejado si hace falta."""
        origen = xfrm.find(q("a:chOff"))
        interno = xfrm.find(q("a:chExt"))
        externo = xfrm.find(q("a:ext"))
        origen_x, origen_y = int(origen.get("x")), int(origen.get("y"))
        escala_x = int(externo.get("cx")) / int(interno.get("cx")) if int(interno.get("cx")) else 1
        escala_y = int(externo.get("cy")) / int(interno.get("cy")) if int(interno.get("cy")) else 1
        escala_x *= escala_padre[0]
        escala_y *= escala_padre[1]
        media_vuelta = _rot_180(xfrm)
        espejo_h = espejo_h ^ (xfrm.get("flipH") == "1") ^ media_vuelta
        espejo_v = espejo_v ^ _flip_v(xfrm) ^ media_vuelta
        invertido = invertido ^ _flip_v(xfrm) ^ media_vuelta

        for hijo in grupo:
            if hijo.tag == q("wps:wsp"):
                forma_xfrm = hijo.find(q("wps:spPr") + "/" + q("a:xfrm"))
                if forma_xfrm is None or forma_xfrm.find(q("a:off")) is None:
                    continue
                desplazado = forma_xfrm.find(q("a:off"))
                medida = forma_xfrm.find(q("a:ext"))
                hijo_x = (int(desplazado.get("x")) - origen_x) * escala_x * EMU_A_MM
                hijo_y = (int(desplazado.get("y")) - origen_y) * escala_y * EMU_A_MM
                hijo_ancho = int(medida.get("cx")) * escala_x * EMU_A_MM
                hijo_alto = int(medida.get("cy")) * escala_y * EMU_A_MM
                if espejo_h:
                    hijo_x = ancho - hijo_x - hijo_ancho
                if espejo_v:
                    hijo_y = alto - hijo_y - hijo_alto
                self._agregar_forma(
                    hijo, x + hijo_x, y + hijo_y, hijo_ancho, hijo_alto, invertido, comunes
                )
            elif hijo.tag == q("wpg:grpSp"):
                self._leer_grupo_anidado(
                    hijo, x, y, ancho, alto, origen_x, origen_y, escala_x, escala_y,
                    espejo_h, espejo_v, invertido, comunes,
                )

    def _leer_grupo_anidado(
        self, grupo, x, y, ancho, alto, origen_x, origen_y, escala_x, escala_y,
        espejo_h, espejo_v, invertido, comunes,
    ):
        xfrm = grupo.find(q("wpg:grpSpPr") + "/" + q("a:xfrm"))
        desplazado = xfrm.find(q("a:off"))
        medida = xfrm.find(q("a:ext"))
        hijo_x = (int(desplazado.get("x")) - origen_x) * escala_x * EMU_A_MM
        hijo_y = (int(desplazado.get("y")) - origen_y) * escala_y * EMU_A_MM
        hijo_ancho = int(medida.get("cx")) * escala_x * EMU_A_MM
        hijo_alto = int(medida.get("cy")) * escala_y * EMU_A_MM
        if espejo_h:
            hijo_x = ancho - hijo_x - hijo_ancho
        if espejo_v:
            hijo_y = alto - hijo_y - hijo_alto
        self._leer_grupo(
            grupo, xfrm, x + hijo_x, y + hijo_y, hijo_ancho, hijo_alto,
            (escala_x, escala_y), espejo_h, espejo_v, invertido, comunes,
        )

    def _agregar_forma(self, forma, x, y, ancho, alto, invertido_grupo, comunes):
        contenido = forma.find(q("wps:txbx") + "/" + W("txbxContent"))
        if contenido is None:
            return
        propiedades = forma.find(q("wps:spPr"))
        xfrm = propiedades.find(q("a:xfrm")) if propiedades is not None else None
        cuerpo = forma.find(q("wps:bodyPr"))
        self._agregar(
            x, y, ancho, alto, contenido,
            ancla_vertical=cuerpo.get("anchor", "t") if cuerpo is not None else "t",
            invertido=invertido_grupo ^ _rot_180(xfrm) ^ _flip_v(xfrm),
            con_relleno=propiedades is not None
            and propiedades.find(q("a:solidFill")) is not None,
            **comunes,
        )

    def _leer_vml(self, pict):
        v = lambda local: "{%s}%s" % (NS["v"], local)  # noqa: E731
        for forma in pict:
            if forma.tag not in (v("group"), v("shape"), v("rect")):
                continue
            estilo = forma.get("style", "")
            relativo_h = _propiedad(estilo, "mso-position-horizontal-relative") or "text"
            relativo_v = _propiedad(estilo, "mso-position-vertical-relative") or "text"
            base_x = 0 if relativo_h == "page" else self.hoja.izquierda
            if relativo_v == "page":
                base_y = 0
            elif relativo_v == "margin":
                base_y = self.hoja.arriba
            else:
                base_y = self.y_parrafo
            x = base_x + (_medida(estilo, "margin-left") or 0)
            y = base_y + (_medida(estilo, "margin-top") or 0)
            ancho = _medida(estilo, "width") or 0
            alto = _medida(estilo, "height") or 0
            if forma.tag == v("group"):
                origen = [float(n) for n in (forma.get("coordorigin") or "0,0").split(",")]
                tamano = [float(n) for n in (forma.get("coordsize") or "1000,1000").split(",")]
                escala_x, escala_y = ancho / tamano[0], alto / tamano[1]
                for hijo in forma:
                    if hijo.tag not in (v("shape"), v("rect")):
                        continue
                    propio = hijo.get("style", "")
                    izquierda = _medida(propio, "left") or 0
                    arriba = _medida(propio, "top") or 0
                    self._agregar_vml(
                        hijo,
                        x + (izquierda - origen[0]) * escala_x,
                        y + (arriba - origen[1]) * escala_y,
                        (_medida(propio, "width") or 0) * escala_x,
                        (_medida(propio, "height") or 0) * escala_y,
                    )
            else:
                self._agregar_vml(forma, x, y, ancho, alto)

    def _agregar_vml(self, forma, x, y, ancho, alto):
        caja = forma.find("{%s}textbox" % NS["v"])
        contenido = caja.find(W("txbxContent")) if caja is not None else None
        if contenido is None:
            return
        estilo = forma.get("style", "")
        self._agregar(
            x, y, ancho, alto, contenido,
            invertido=_propiedad(estilo, "rotation") == "180"
            or (_propiedad(estilo, "flip") or "").strip() == "y",
            oculto=_propiedad(estilo, "visibility") == "hidden",
        )


def _leer_parrafo_cuerpo(elemento, estilos):
    """Párrafo del cuerpo, sin el texto de los cuadros que tiene anclados."""
    propiedades = elemento.find(W("pPr"))
    propios = estilos.leer_parrafo(propiedades) if propiedades is not None else {}
    efectivo = estilos.parrafo_efectivo(propios)
    marca = {}
    if propiedades is not None and propiedades.find(W("rPr")) is not None:
        marca = estilos.leer_run(propiedades.find(W("rPr")))
    marca = estilos.run_efectivo(propios.get("estilo"), marca)
    return Parrafo(
        linea=efectivo.get("linea"),
        regla_linea=efectivo.get("regla_linea"),
        despues=efectivo.get("despues", 0) or 0,
        tamano_marca=marca.get("tamano"),
        fuente_marca=marca.get("fuente"),
    )


def leer_docx(ruta):
    return _Lector(ruta).leer()


def leer_parrafos_cuerpo(ruta):
    """Textos de los párrafos del cuerpo, para los bancos de oraciones."""
    with zipfile.ZipFile(ruta) as archivo:
        raiz = ET.fromstring(archivo.read("word/document.xml"))
    textos = []
    for parrafo in raiz.find(W("body")).iter(W("p")):
        texto = "".join(
            hijo.text or ""
            for run in parrafo.iter(W("r"))
            for hijo in run
            if hijo.tag == W("t")
        ).strip()
        if texto:
            textos.append(texto)
    return textos
