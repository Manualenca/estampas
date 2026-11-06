"""Texto final de cada cuadro de una estampa: plantillas, datos del pedido y ajustes a mano.

Lo usan la vista previa y el PDF, para que los dos muestren exactamente lo mismo.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .lector_docx import ALTO_LINEA_DEFECTO, ALTO_LINEA_FUENTE
from .models import CuadroTexto, EstiloLinea, Genero, PlantillaTexto

Rol = CuadroTexto.Rol
Clave = PlantillaTexto.Clave
Elemento = EstiloLinea.Elemento

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
VARIABLE = re.compile(r"\{(\w+)\}")
NEGRITA = re.compile(r"\*\*(.+?)\*\*", re.S)

# Parte del cuadro a la que pertenece un renglón, según la primera variable que usa.
ELEMENTO_DE_VARIABLE = {
    "linea_padrinos": Elemento.PADRINOS,
    "padrino": Elemento.PADRINOS,
    "madrina": Elemento.PADRINOS,
    "linea_padres": Elemento.PADRES,
    "padre": Elemento.PADRES,
    "madre": Elemento.PADRES,
    "linea_nacimiento": Elemento.NACIMIENTO,
    "fecha_nacimiento": Elemento.NACIMIENTO,
    "fecha": Elemento.FECHA,
    "hora": Elemento.FECHA,
    "anio": Elemento.FECHA,
    "articulo": Elemento.LUGAR,
    "parroquia": Elemento.LUGAR,
    "localidad": Elemento.LOCALIDAD,
}


def formatear_fecha(fecha):
    if not fecha:
        return ""
    return f"{fecha.day:02d} de {MESES[fecha.month - 1]} de {fecha.year}"


def formatear_hora(hora):
    return f"{hora.hour}:{hora.minute:02d}" if hora else ""


def unir(valores):
    """["A"] -> "A"; ["A", "B"] -> "A y B"; ["A", "B", "C"] -> "A, B y C"."""
    valores = [v for v in valores if v]
    if len(valores) <= 1:
        return "".join(valores)
    return ", ".join(valores[:-1]) + " y " + valores[-1]


def factor_linea(fuente):
    return ALTO_LINEA_FUENTE.get((fuente or "").lower(), ALTO_LINEA_DEFECTO)


@dataclass
class Segmento:
    texto: str
    negrita: bool = False


@dataclass
class Linea:
    segmentos: list
    elemento: str | None = None
    fuente: str = ""
    tamano_pt: Decimal = Decimal("0")
    negrita: bool = False
    cursiva: bool = False
    color: str = "000000"

    @property
    def texto(self):
        return "".join(s.texto for s in self.segmentos)


@dataclass
class TextoCuadro:
    cuadro: CuadroTexto
    lineas: list
    manual: bool = False
    texto_editable: str = ""
    tamano_pt: Decimal = Decimal("0")
    escala: Decimal = Decimal("1")
    color: str = "000000"
    avisos: list = field(default_factory=list)
    x_mm: Decimal = Decimal("0")
    y_mm: Decimal = Decimal("0")
    ancho_mm: Decimal = Decimal("0")
    alto_mm: Decimal = Decimal("0")
    posicion_ajustada: bool = False

    @property
    def vacio(self):
        return not any(linea.texto.strip() for linea in self.lineas)

    @property
    def ajustado(self):
        return self.escala != 1


def separar_negrita(texto):
    """Divide un renglón según las marcas **negrita**."""
    segmentos, posicion = [], 0
    for marca in NEGRITA.finditer(texto):
        if marca.start() > posicion:
            segmentos.append(Segmento(texto[posicion : marca.start()]))
        segmentos.append(Segmento(marca.group(1), negrita=True))
        posicion = marca.end()
    if posicion < len(texto):
        segmentos.append(Segmento(texto[posicion:]))
    return segmentos


def completar(plantilla, valores):
    """Reemplaza las variables. Un renglón cuyas variables quedan todas vacías se omite."""
    renglones = []
    for renglon in plantilla.splitlines():
        variables = VARIABLE.findall(renglon)
        if variables and not any(valores.get(v) for v in variables):
            continue
        elemento = next(
            (ELEMENTO_DE_VARIABLE[v] for v in variables if v in ELEMENTO_DE_VARIABLE), None
        )
        if not variables:
            elemento = Elemento.TEXTO_FIJO
        texto = VARIABLE.sub(lambda m: str(valores.get(m.group(1), "")), renglon)
        for parte in texto.split("\n"):
            parte = re.sub(r"[ \t]{2,}", " ", parte).strip()
            if parte:
                renglones.append((parte, elemento))
    return renglones


class ContextoEstampa:
    """Datos de una estampa listos para completar plantillas."""

    def __init__(self, estampa):
        self.estampa = estampa
        self.variante = estampa.variante
        self.ninos = list(estampa.ninos.order_by("pk"))
        self.sacramentos = list(
            estampa.estampasacramento_set.select_related("sacramento").order_by("sacramento__orden")
        )
        self.avisos = []

    @property
    def cantidad(self):
        return min(len(self.ninos), 2) or 1

    def generos(self):
        return [n.genero for n in self.ninos]

    def _comun(self, campo, etiqueta):
        """Valor del dato. Si los chicos tienen datos distintos, los une y avisa."""
        distintos = list(dict.fromkeys(getattr(n, campo) for n in self.ninos if getattr(n, campo)))
        if len(distintos) > 1:
            self.avisos.append(
                f"Los chicos tienen {etiqueta} distintos: revisá el texto o editalo a mano."
            )
        return unir(distintos)

    def _sacramento(self, cuadro):
        if cuadro.sacramento_id:
            for relacion in self.sacramentos:
                if relacion.sacramento_id == cuadro.sacramento_id:
                    return relacion
        return self.sacramentos[0] if self.sacramentos else None

    def _posesivo(self):
        if len(self.ninos) >= 2 and self.sacramentos:
            return self.sacramentos[0].sacramento.posesivo_plural
        return "Mi"

    def _bautizado(self):
        generos = set(self.generos())
        plural = len(self.ninos) >= 2
        if generos == {Genero.MUJER}:
            return "Bautizadas" if plural else "Bautizada"
        if generos == {Genero.VARON} or (plural and generos <= {Genero.VARON, Genero.MUJER} and generos):
            return "Bautizados" if plural else "Bautizado"
        return ""

    def plantilla(self, clave, sacramento=None):
        return PlantillaTexto.resolver(
            clave,
            sacramento.sacramento if sacramento else None,
            self.cantidad,
            self.variante,
        )

    def valores(self, cuadro):
        relacion = self._sacramento(cuadro)
        posesivo = self._posesivo()
        fecha = relacion.fecha_efectiva if relacion else self.estampa.fecha_celebracion
        nacimientos = list(dict.fromkeys(n.fecha_nacimiento for n in self.ninos if n.fecha_nacimiento))
        if len(nacimientos) > 1:
            self.avisos.append(
                "Los chicos tienen distinta fecha de nacimiento: revisá el texto o editalo a mano."
            )
        valores = {
            "posesivo": posesivo.lower(),
            "Posesivo": posesivo,
            "sacramentos": unir(r.sacramento.nombre for r in self.sacramentos),
            "fecha": formatear_fecha(fecha),
            "hora": formatear_hora(relacion.hora if relacion else None),
            "anio": str(fecha.year) if fecha else "",
            "articulo": self.estampa.articulo_parroquia,
            "parroquia": self.estampa.parroquia,
            "localidad": self.estampa.localidad,
            "padrino": self._comun("padrino", "padrinos"),
            "madrina": self._comun("madrina", "madrinas"),
            "padre": self._comun("padre", "papás"),
            "madre": self._comun("madre", "mamás"),
            "fecha_nacimiento": unir(formatear_fecha(f) for f in nacimientos),
            "bautizado": self._bautizado(),
        }
        valores["linea_padrinos"] = self._linea(
            relacion, valores, valores["padrino"], valores["madrina"],
            Clave.PADRINOS_AMBOS, Clave.PADRINOS_SOLO_PADRINO, Clave.PADRINOS_SOLO_MADRINA,
        ) if self.variante.lleva_padrinos else ""
        valores["linea_padres"] = self._linea(
            relacion, valores, valores["padre"], valores["madre"],
            Clave.PADRES_AMBOS, Clave.PADRES_SOLO_PADRE, Clave.PADRES_SOLO_MADRE,
        )
        nacimiento = self.plantilla(Clave.NACIMIENTO, relacion) if nacimientos else None
        valores["linea_nacimiento"] = (
            "\n".join(t for t, _ in completar(nacimiento.texto, valores)) if nacimiento else ""
        )
        return relacion, valores

    def _linea(self, relacion, valores, varon, mujer, ambos, solo_varon, solo_mujer):
        if varon and mujer:
            clave = ambos
        elif varon:
            clave = solo_varon
        elif mujer:
            clave = solo_mujer
        else:
            return ""
        plantilla = self.plantilla(clave, relacion)
        return "\n".join(t for t, _ in completar(plantilla.texto, valores)) if plantilla else ""


def _renglones_automaticos(contexto, cuadro):
    """(texto, parte) de cada renglón del cuadro, sin ajustes a mano."""
    estampa = contexto.estampa
    if cuadro.rol == Rol.NOMBRE:
        return [(unir(n.nombre for n in contexto.ninos), Elemento.NOMBRE)]
    if cuadro.rol == Rol.ORACION:
        if not estampa.lleva_oracion or not contexto.variante.lleva_oracion:
            return []
        if estampa.oracion_id:
            renglones = [(t, None) for t in estampa.oracion.texto.splitlines() if t.strip()]
            if estampa.oracion.autor:
                renglones.append((estampa.oracion.autor, Elemento.AUTOR))
            return renglones
        return [(t, None) for t in estampa.oracion_libre.splitlines() if t.strip()]
    relacion, valores = contexto.valores(cuadro)
    if cuadro.rol == Rol.FECHA:
        return [(valores["fecha"], Elemento.FECHA)] if valores["fecha"] else []
    if cuadro.rol == Rol.TITULO:
        modo = contexto.variante.modo_titulo
        if modo == contexto.variante.ModoTitulo.SIN_TITULO:
            return []
        clave = Clave.TITULO_COMPLETO if modo == contexto.variante.ModoTitulo.COMPLETO else Clave.TITULO_SIN_RECUERDO
    elif cuadro.rol == Rol.CELEBRACION:
        clave = Clave.CELEBRACION
    elif cuadro.rol == Rol.FECHA_NACIMIENTO:
        clave = Clave.NACIMIENTO
    else:
        return []
    plantilla = contexto.plantilla(clave, relacion)
    if plantilla is None:
        contexto.avisos.append(f"No hay plantilla para «{PlantillaTexto.Clave(clave).label}».")
        return []
    return completar(plantilla.texto, valores)


def _renglones_manuales(texto):
    return [(t, None) for t in texto.splitlines() if t.strip()]


def texto_de_cuadro(contexto, cuadro, ajuste=None):
    contexto.avisos = []
    manual = bool(ajuste and ajuste.texto_manual.strip())
    if manual:
        renglones = _renglones_manuales(ajuste.texto_manual)
    elif cuadro.rol == Rol.SIN_ASIGNAR:
        renglones = []  # Solo se imprime si se le escribe un texto a mano.
    else:
        renglones = _renglones_automaticos(contexto, cuadro)

    base = cuadro.tamano_pt
    tamano = ajuste.tamano_pt if ajuste and ajuste.tamano_pt else base
    escala = (tamano / base) if base else Decimal("1")
    color = cuadro.color_para(contexto.generos())
    estilos = {e.elemento: e for e in cuadro.estilos.all()}

    lineas = []
    for texto, elemento in renglones:
        estilo = estilos.get(elemento)
        lineas.append(
            Linea(
                segmentos=separar_negrita(texto),
                elemento=elemento,
                fuente=(estilo.fuente if estilo and estilo.fuente else cuadro.fuente),
                tamano_pt=(estilo.tamano_pt if estilo and estilo.tamano_pt else base) * escala,
                negrita=estilo.negrita if estilo and estilo.negrita is not None else cuadro.negrita,
                cursiva=estilo.cursiva if estilo and estilo.cursiva is not None else cuadro.cursiva,
                color=(estilo.color if estilo and estilo.color else color),
            )
        )
    editable = ajuste.texto_manual if manual else "\n".join(texto for texto, _ in renglones)
    # Posición: la de esta estampa si se movió el cuadro; si no, la del modelo.
    posicion = {}
    for campo in ("x_mm", "y_mm", "ancho_mm", "alto_mm"):
        propio = getattr(ajuste, campo) if ajuste else None
        posicion[campo] = propio if propio is not None else getattr(cuadro, campo)
    return TextoCuadro(
        cuadro=cuadro,
        lineas=lineas,
        manual=manual,
        texto_editable=editable,
        tamano_pt=tamano,
        escala=escala,
        color=color,
        avisos=list(dict.fromkeys(contexto.avisos)),
        posicion_ajustada=bool(ajuste and ajuste.tiene_posicion),
        **posicion,
    )


def textos_de_estampa(estampa):
    """Texto final de todos los cuadros de la variante de la estampa."""
    contexto = ContextoEstampa(estampa)
    ajustes = {a.cuadro_id: a for a in estampa.ajustes.all()}
    cuadros = estampa.variante.cuadros.prefetch_related("estilos").order_by("pagina", "y_mm", "x_mm")
    return [texto_de_cuadro(contexto, cuadro, ajustes.get(cuadro.pk)) for cuadro in cuadros]
