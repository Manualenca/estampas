"""PDF de impresión: solo el texto, sobre la tarjeta preimpresa, del tamaño exacto de cada modelo.

El texto sale de textos.py, igual que la vista previa. Acá se reparte en renglones con las
métricas reales de cada fuente y se dibuja con ReportLab.
"""

import io
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from django.conf import settings
from reportlab.lib.colors import Color, HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont
from reportlab.pdfgen.canvas import Canvas

from . import fuentes
from .lector_docx import INSET_X_MM, INSET_Y_MM
from .models import CuadroTexto
from .textos import Linea, Segmento, TextoCuadro, factor_linea, textos_de_estampa

MM = 72 / 25.4
FUENTE_DE_RESPALDO = "Helvetica"
# Negrita y cursiva simuladas, para fuentes que no traen esas variantes (como hace Word).
TRAZO_NEGRITA = 0.03  # Ancho del contorno, en proporción al tamaño.
INCLINACION_CURSIVA = math.tan(math.radians(12))
ALINEACIONES = CuadroTexto.Alineacion
VERTICAL = CuadroTexto.AlineacionVertical


# ----- Fuentes -----


@dataclass(frozen=True)
class FuenteRegistrada:
    nombre: str
    negrita_simulada: bool = False
    cursiva_simulada: bool = False
    ascenso: float = 0.8  # Proporción del alto natural por encima de la línea base.


@lru_cache(maxsize=1)
def _caras_registradas():
    """Registra en ReportLab las fuentes de fuentes/. {familia: {(negrita, cursiva): nombre}}."""
    familias = {}
    for cara in fuentes.catalogo(settings.FUENTES_DIR):
        peso, estilo = cara.peso_y_estilo
        clave = (peso >= 600, estilo == "italic")
        nombre = re.sub(r"[^A-Za-z0-9]", "", f"{cara.familia}{cara.estilo}") or "Fuente"
        try:
            pdfmetrics.registerFont(TTFont(nombre, str(cara.ruta)))
        except TTFError:  # Por ejemplo, contornos PostScript: ReportLab no los soporta.
            continue
        familias.setdefault(cara.familia.lower(), {})[clave] = nombre
    return familias


def reiniciar_fuentes():
    """Vuelve a leer la carpeta de fuentes (por ejemplo, después de copiar_fuentes)."""
    _caras_registradas.cache_clear()


def fuente(familia, negrita, cursiva, faltantes=None):
    """La cara pedida o, si no existe, la más cercana con negrita/cursiva simuladas."""
    caras = _caras_registradas().get((familia or "").lower())
    if not caras:
        if faltantes is not None and familia:
            faltantes.add(familia)
        return FuenteRegistrada(FUENTE_DE_RESPALDO, negrita, cursiva)
    for (con_negrita, con_cursiva), simular in (
        ((negrita, cursiva), (False, False)),
        ((False, cursiva), (negrita, False)),
        ((negrita, False), (False, cursiva)),
        ((False, False), (negrita, cursiva)),
    ):
        nombre = caras.get((con_negrita, con_cursiva))
        if nombre:
            cara = pdfmetrics.getFont(nombre).face
            alto = (cara.ascent - cara.descent) or 1000
            return FuenteRegistrada(nombre, simular[0], simular[1], cara.ascent / alto)
    return FuenteRegistrada(FUENTE_DE_RESPALDO, negrita, cursiva)


# ----- Reparto en renglones -----


@dataclass
class Trozo:
    texto: str
    fuente: FuenteRegistrada
    tamano: float
    color: str
    espaciado: float

    @property
    def ancho(self):
        return pdfmetrics.stringWidth(self.texto, self.fuente.nombre, self.tamano) + self.espaciado * len(
            self.texto
        )


@dataclass
class Renglon:
    trozos: list
    alto: float  # pt, con el interlineado
    natural: float  # pt, alto del renglón sencillo
    tamano: float
    ascenso: float
    alineacion: str = CuadroTexto.Alineacion.CENTRO
    izquierda: float = 0  # pt desde el borde útil del cuadro (sangrías)
    ancho_disponible: float = 0  # pt
    ultimo_del_parrafo: bool = True
    espacio_antes: float = 0
    espacio_despues: float = 0

    @property
    def ancho(self):
        return sum(t.ancho for t in self.trozos)


@dataclass
class Composicion:
    renglones: list
    alto: float
    desborda: bool = False
    faltantes: set = field(default_factory=set)


def _alto_de_renglon(cuadro, linea_fuente, tamano):
    alto = tamano * factor_linea(linea_fuente) * float(cuadro.interlineado)
    if cuadro.interlineado_minimo_pt:
        alto = max(alto, float(cuadro.interlineado_minimo_pt) * (tamano / float(cuadro.tamano_pt or tamano)))
    return alto


def _trozos_de_linea(linea, cuadro, faltantes):
    trozos = []
    for segmento in linea.segmentos:
        cara = fuente(linea.fuente, linea.negrita or segmento.negrita, linea.cursiva, faltantes)
        trozos.append(
            Trozo(segmento.texto, cara, float(linea.tamano_pt), linea.color, float(cuadro.espaciado_letras_pt))
        )
    return trozos


def _partir(trozos, ancho_primero, ancho_resto):
    """Reparte los trozos en renglones que entren en el ancho. Una palabra sola nunca se corta."""
    palabras = []  # Cada palabra es una lista de trozos; los espacios van al final.
    actual = []
    for trozo in trozos:
        for parte in re.split(r"(\s+)", trozo.texto):
            if not parte:
                continue
            pieza = Trozo(parte, trozo.fuente, trozo.tamano, trozo.color, trozo.espaciado)
            if parte.isspace():
                actual.append(pieza)
                palabras.append(actual)
                actual = []
            else:
                actual.append(pieza)
    if actual:
        palabras.append(actual)

    renglones, renglon, ancho = [], [], 0.0
    for palabra in palabras:
        limite = ancho_primero if not renglones else ancho_resto
        sin_espacio = sum(p.ancho for p in palabra if not p.texto.isspace())
        if renglon and ancho + sin_espacio > limite + 0.01:
            renglones.append(renglon)
            renglon, ancho = [], 0.0
        renglon.extend(palabra)
        ancho += sum(p.ancho for p in palabra)
    if renglon or not renglones:
        renglones.append(renglon)
    # Sin espacios al final de cada renglón (Word no los cuenta para centrar).
    for renglon in renglones:
        while renglon and renglon[-1].texto.isspace():
            renglon.pop()
        if renglon:
            renglon[-1].texto = renglon[-1].texto.rstrip()
    return renglones


def componer(texto: TextoCuadro):
    """Renglones del cuadro y si el texto entra en él."""
    cuadro = texto.cuadro
    faltantes = set()
    ancho_util = (float(texto.ancho_mm) - 2 * INSET_X_MM) * MM
    renglones = []
    desborda = False
    for linea in texto.lineas:
        trozos = _trozos_de_linea(linea, cuadro, faltantes)
        tamano = float(linea.tamano_pt)
        izquierda = float(linea.sangria_izquierda_mm) * MM
        derecha = float(linea.sangria_derecha_mm) * MM
        primera = float(linea.sangria_primera_mm) * MM
        resto = ancho_util - izquierda - derecha
        partes = _partir(trozos, resto - primera, resto)
        alto = _alto_de_renglon(cuadro, linea.fuente, tamano)
        natural = tamano * factor_linea(linea.fuente)
        ascenso = trozos[0].fuente.ascenso if trozos else 0.8
        for i, parte in enumerate(partes):
            margen = izquierda + (primera if i == 0 else 0)
            renglon = Renglon(
                parte, alto, natural, tamano, ascenso,
                alineacion=linea.alineacion,
                izquierda=margen,
                ancho_disponible=ancho_util - margen - derecha,
                ultimo_del_parrafo=i == len(partes) - 1,
                espacio_antes=float(linea.espacio_antes_pt) * float(texto.escala) if i == 0 else 0,
            )
            if renglon.ancho > renglon.ancho_disponible + 0.5:
                desborda = True  # Una palabra sola más ancha que el cuadro.
            renglones.append(renglon)
        if renglones:
            renglones[-1].espacio_despues = float(linea.espacio_despues_pt) * float(texto.escala)
    alto_total = sum(r.espacio_antes + r.alto + r.espacio_despues for r in renglones)
    if renglones:
        alto_total -= renglones[-1].espacio_despues
    # Como Word: el texto puede ocupar el margen interno, pero no pasar del borde.
    if alto_total > float(texto.alto_mm) * MM + 0.5:
        desborda = True
    return Composicion(renglones, alto_total, desborda, faltantes)


# ----- Dibujo -----


def _color(hexa):
    try:
        return HexColor("#" + hexa)
    except (ValueError, TypeError):
        return Color(0, 0, 0)


def _dibujar_trozo(lienzo, trozo, x, y_base, espacio_extra=0.0):
    lienzo.saveState()
    lienzo.setFillColor(_color(trozo.color))
    if trozo.fuente.cursiva_simulada:
        lienzo.transform(1, 0, INCLINACION_CURSIVA, 1, x - INCLINACION_CURSIVA * y_base, 0)
    else:
        lienzo.translate(x, 0)
    objeto = lienzo.beginText(0, y_base)
    objeto.setFont(trozo.fuente.nombre, trozo.tamano)
    if trozo.espaciado:
        objeto.setCharSpace(trozo.espaciado)
    if espacio_extra:
        objeto.setWordSpace(espacio_extra)
    if trozo.fuente.negrita_simulada:
        lienzo.setStrokeColor(_color(trozo.color))
        lienzo.setLineWidth(trozo.tamano * TRAZO_NEGRITA)
        objeto.setTextRenderMode(2)  # Relleno y contorno.
    objeto.textOut(trozo.texto)
    lienzo.drawText(objeto)
    lienzo.restoreState()


def dibujar_cuadro(lienzo, texto, alto_hoja_mm, desplazamiento):
    """Dibuja el texto de un cuadro. desplazamiento = (x, y) en mm; y positivo baja."""
    composicion = componer(texto)
    if not composicion.renglones:
        return composicion
    cuadro = texto.cuadro
    dx, dy = (float(v) for v in desplazamiento)
    izquierda = (float(texto.x_mm) + dx) * MM
    arriba = (alto_hoja_mm - float(texto.y_mm) - dy) * MM  # ReportLab mide desde abajo.
    ancho = float(texto.ancho_mm) * MM
    alto = float(texto.alto_mm) * MM
    util_izquierda = izquierda + INSET_X_MM * MM

    lienzo.saveState()
    if cuadro.rotacion == CuadroTexto.Rotacion.INVERTIDO:
        centro_x, centro_y = izquierda + ancho / 2, arriba - alto / 2
        lienzo.translate(centro_x, centro_y)
        lienzo.rotate(180)
        lienzo.translate(-centro_x, -centro_y)

    alto_util = alto - 2 * INSET_Y_MM * MM
    if cuadro.alineacion_vertical == VERTICAL.CENTRO:
        tope = arriba - INSET_Y_MM * MM - (alto_util - composicion.alto) / 2
    elif cuadro.alineacion_vertical == VERTICAL.ABAJO:
        tope = arriba - alto + INSET_Y_MM * MM + composicion.alto
    else:
        tope = arriba - INSET_Y_MM * MM

    for renglon in composicion.renglones:
        tope -= renglon.espacio_antes
        # Como Word: con interlineado mayor que sencillo, el espacio extra queda debajo del
        # texto; con menor, se recorta arriba y la línea base sube.
        base = tope - min(renglon.alto, renglon.natural) * renglon.ascenso
        sobra = renglon.ancho_disponible - renglon.ancho
        inicio = util_izquierda + renglon.izquierda
        espacio_extra = 0.0
        if renglon.alineacion == ALINEACIONES.CENTRO:
            x = inicio + sobra / 2
        elif renglon.alineacion == ALINEACIONES.DERECHA:
            x = inicio + sobra
        else:
            x = inicio
            if renglon.alineacion == ALINEACIONES.JUSTIFICADO and not renglon.ultimo_del_parrafo:
                espacios = sum(t.texto.count(" ") for t in renglon.trozos)
                if espacios and sobra > 0:
                    espacio_extra = sobra / espacios
        for trozo in renglon.trozos:
            _dibujar_trozo(lienzo, trozo, x, base, espacio_extra)
            x += trozo.ancho + espacio_extra * trozo.texto.count(" ")
        tope -= renglon.alto + renglon.espacio_despues
    lienzo.restoreState()
    return composicion


def _lienzo(destino, titulo):
    lienzo = Canvas(destino, pageCompression=1)
    lienzo.setTitle(titulo)
    lienzo.setCreator("Estampas")
    # Que el visor sugiera imprimir al 100 %, sin "ajustar a la página".
    lienzo.setViewerPreference("PrintScaling", "None")
    return lienzo


@dataclass
class Resultado:
    contenido: bytes
    paginas: int
    avisos: list


def _paginas_de_estampa(estampa):
    """[(página, [textos])] con anverso siempre y reverso si el modelo lo tiene."""
    textos = textos_de_estampa(estampa)
    paginas = []
    for pagina in (CuadroTexto.Pagina.ANVERSO, CuadroTexto.Pagina.REVERSO):
        propios = [t for t in textos if t.cuadro.pagina == pagina]
        if propios or pagina == CuadroTexto.Pagina.ANVERSO:
            paginas.append((pagina, propios))
    return paginas


def _dibujar_pagina(lienzo, modelo, pagina, textos, avisos, faltantes):
    ancho, alto = float(modelo.ancho_mm), float(modelo.alto_mm)
    lienzo.setPageSize((ancho * MM, alto * MM))
    for texto in textos:
        if texto.vacio:
            continue
        composicion = dibujar_cuadro(lienzo, texto, alto, modelo.offset(pagina))
        faltantes |= composicion.faltantes
        if composicion.desborda:
            avisos.append(f"{modelo.codigo}: el texto no entra en el cuadro {texto.cuadro.get_rol_display()}.")
    lienzo.showPage()


def pdf_de_estampas(estampas, titulo, intercalado=True, copias=None):
    """PDF con las estampas. Cada copia es anverso y, si hay, reverso.

    intercalado=True: anverso, reverso, anverso, reverso... (impresión a doble faz o a mano).
    intercalado=False: todos los anversos y después todos los reversos.
    copias: None usa la cantidad de cada estampa.
    """
    salida = io.BytesIO()
    lienzo = _lienzo(salida, titulo)
    avisos, faltantes, total = [], set(), 0
    for estampa in estampas:
        modelo = estampa.variante.modelo
        paginas = _paginas_de_estampa(estampa)
        cantidad = copias if copias is not None else estampa.cantidad
        orden = (
            [p for _ in range(cantidad) for p in paginas]
            if intercalado
            else [p for p in paginas for _ in range(cantidad)]
        )
        for pagina, textos in orden:
            _dibujar_pagina(lienzo, modelo, pagina, textos, avisos, faltantes)
            total += 1
    lienzo.save()
    avisos += [f"Falta la fuente {f}: se usó {FUENTE_DE_RESPALDO}." for f in sorted(faltantes)]
    return Resultado(salida.getvalue(), total, list(dict.fromkeys(avisos)))


def texto_de_diploma(nino, cuadro):
    """Solo el nombre del chico, con el formato del cuadro del diploma."""
    color = cuadro.color_para([nino.genero])
    linea = Linea(
        segmentos=[Segmento(nino.nombre)],
        fuente=cuadro.fuente,
        tamano_pt=cuadro.tamano_pt,
        negrita=cuadro.negrita,
        cursiva=cuadro.cursiva,
        color=color,
        alineacion=cuadro.alineacion,
        espacio_antes_pt=cuadro.espacio_antes_pt,
        espacio_despues_pt=cuadro.espacio_despues_pt,
    )
    return TextoCuadro(
        cuadro=cuadro, lineas=[linea], tamano_pt=cuadro.tamano_pt, color=color,
        x_mm=cuadro.x_mm, y_mm=cuadro.y_mm, ancho_mm=cuadro.ancho_mm, alto_mm=cuadro.alto_mm,
    )


def pdf_de_diplomas(pedido):
    """Un diploma por chico que lo lleva, según su sacramento y género."""
    salida = io.BytesIO()
    lienzo = _lienzo(salida, f"Diplomas · Pedido {pedido.numero_factura}")
    avisos, faltantes, total = [], set(), 0
    for nino in pedido.ninos.filter(lleva_diploma=True).order_by("pk"):
        variante = nino.diploma_que_corresponde()
        if variante is None:
            avisos.append(f"{nino.nombre}: sin diploma (falta el género o elegirlo a mano).")
            continue
        cuadros = variante.cuadros.filter(rol=CuadroTexto.Rol.NOMBRE)
        textos = [texto_de_diploma(nino, c) for c in cuadros]
        _dibujar_pagina(lienzo, variante.modelo, CuadroTexto.Pagina.ANVERSO, textos, avisos, faltantes)
        total += 1
    lienzo.save()
    avisos += [f"Falta la fuente {f}: se usó {FUENTE_DE_RESPALDO}." for f in sorted(faltantes)]
    return Resultado(salida.getvalue(), total, list(dict.fromkeys(avisos)))


# ----- Hoja de calibración -----


def _reglas(lienzo, ancho, alto):
    """Reglas en mm en los cuatro bordes: marca cada 1 mm, más larga cada 5 y número cada 10."""
    lienzo.setLineWidth(0.25)
    lienzo.setFont(FUENTE_DE_RESPALDO, 5)
    for mm in range(0, int(ancho) + 1):
        largo = 3 if mm % 10 == 0 else 2 if mm % 5 == 0 else 1
        x = mm * MM
        lienzo.line(x, alto * MM, x, (alto - largo) * MM)
        lienzo.line(x, 0, x, largo * MM)
        if mm % 10 == 0 and 0 < mm < ancho:
            lienzo.drawCentredString(x, (alto - 5) * MM, str(mm))
            lienzo.drawCentredString(x, 3.5 * MM, str(mm))
    for mm in range(0, int(alto) + 1):
        largo = 3 if mm % 10 == 0 else 2 if mm % 5 == 0 else 1
        y = (alto - mm) * MM
        lienzo.line(0, y, largo * MM, y)
        lienzo.line(ancho * MM, y, (ancho - largo) * MM, y)
        if mm % 10 == 0 and 0 < mm < alto:
            lienzo.drawString(3.5 * MM, y - 1.5, str(mm))
            lienzo.drawRightString((ancho - 3.5) * MM, y - 1.5, str(mm))


def _cruz(lienzo, x, y, largo=4):
    lienzo.line((x - largo) * MM, y * MM, (x + largo) * MM, y * MM)
    lienzo.line(x * MM, (y - largo) * MM, x * MM, (y + largo) * MM)
    lienzo.circle(x * MM, y * MM, 1 * MM)


def pdf_de_calibracion(modelo, variante=None):
    """Hoja de prueba del tamaño de la tarjeta, con la calibración actual aplicada.

    Se imprime sobre papel común y se superpone a la tarjeta para ver cuánto se corre.
    """
    variante = variante or modelo.variantes.order_by("nombre").first()
    cuadros = list(variante.cuadros.order_by("pagina", "y_mm")) if variante else []
    paginas = sorted({c.pagina for c in cuadros} | {CuadroTexto.Pagina.ANVERSO})
    ancho, alto = float(modelo.ancho_mm), float(modelo.alto_mm)
    salida = io.BytesIO()
    lienzo = _lienzo(salida, f"Calibración · {modelo.codigo}")
    for pagina in paginas:
        dx, dy = (float(v) for v in modelo.offset(pagina))
        lienzo.setPageSize((ancho * MM, alto * MM))
        lienzo.saveState()
        lienzo.translate(dx * MM, -dy * MM)
        lienzo.setStrokeColor(Color(0, 0, 0))
        _reglas(lienzo, ancho, alto)
        lienzo.setLineWidth(0.4)
        for x, y in ((6, 6), (ancho - 6, 6), (6, alto - 6), (ancho - 6, alto - 6)):
            _cruz(lienzo, x, y)
        lienzo.setFont(FUENTE_DE_RESPALDO, 6)
        etiqueta = "Anverso" if pagina == CuadroTexto.Pagina.ANVERSO else "Reverso"
        lienzo.drawCentredString(
            ancho / 2 * MM, (alto - 9) * MM,
            f"{modelo.codigo} · {etiqueta} · ajuste x {dx:+.1f} mm, y {dy:+.1f} mm",
        )
        lienzo.drawCentredString(ancho / 2 * MM, 7 * MM, "Imprimir al 100 %, sin ajustar a la página")
        lienzo.setStrokeColor(Color(0.1, 0.35, 0.8))
        lienzo.setFillColor(Color(0.1, 0.35, 0.8))
        lienzo.setLineWidth(0.5)
        lienzo.setDash(2, 1.5)
        for cuadro in (c for c in cuadros if c.pagina == pagina):
            x, y = float(cuadro.x_mm) * MM, (alto - float(cuadro.y_mm) - float(cuadro.alto_mm)) * MM
            lienzo.rect(x, y, float(cuadro.ancho_mm) * MM, float(cuadro.alto_mm) * MM)
            lienzo.setFont(FUENTE_DE_RESPALDO, 5)
            girado = " (180°)" if cuadro.rotacion == CuadroTexto.Rotacion.INVERTIDO else ""
            lienzo.drawString(x + 1, y + float(cuadro.alto_mm) * MM - 6, cuadro.get_rol_display() + girado)
        lienzo.restoreState()
        lienzo.showPage()
    lienzo.save()
    return Resultado(salida.getvalue(), len(paginas), [])
