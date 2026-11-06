"""Convierte los .docx en modelos, variantes, cuadros y oraciones."""

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import transaction

from . import datos_importacion as datos
from .lector_docx import INSET_Y_MM, Parrafo, leer_docx, leer_parrafos_cuerpo
from .models import (
    CuadroTexto,
    EstiloLinea,
    Genero,
    ModeloTarjeta,
    Oracion,
    PlantillaTexto,
    Sacramento,
    VarianteLayout,
    normalizar_texto,
)

Rol = CuadroTexto.Rol

MESES = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"
FECHA = re.compile(rf"\b\d{{1,2}}\s+de\s+({MESES})\b", re.I)
LUGAR = re.compile(
    r"(?<!mi )\b(parroquia|pquia|capilla|iglesia|vicar[ií]a|catedral|bas[ií]lica|santuario)\b",
    re.I,
)
PADRINOS = re.compile(r"\b(padrinos?|madrina)\b", re.I)
PADRES = re.compile(r"\b(papis|pap[aá]|mam[aá])\b", re.I)
NACIMIENTO = re.compile(r"^\s*(nac[ií]|naci[oó]|nacimos)\b", re.I)
TITULO = re.compile(
    r"^(recuerdo de |invitacion a )?(mi|nuestra|nuestro)\b.*(primera comunion|confirmacion|bautismo)"
)
CITA = re.compile(r"^(salmo\b|jn\b|jn\.|mt\b|lc\b|mc\b|sal\b|san\b|santa\b|santo\b|papa\b|marcos\b|\(jes)", re.I)
CITA_AL_FINAL = re.compile(r"\s*(Salmo \d+|San Francisco de Asís)$")
ENCABEZADO_BANCO = re.compile(r"TEXTO N[°º]\s*(\d+)")
SIN_ORACION = re.compile(r"(^|[ _])(sin[ _]?or(acion)?|s[ _]?or(acion)?)($|[ _])", re.I)
ALINEACIONES = {
    "center": CuadroTexto.Alineacion.CENTRO,
    "right": CuadroTexto.Alineacion.DERECHA,
    "end": CuadroTexto.Alineacion.DERECHA,
    "both": CuadroTexto.Alineacion.JUSTIFICADO,
}
ANCLAS = {
    "ctr": CuadroTexto.AlineacionVertical.CENTRO,
    "b": CuadroTexto.AlineacionVertical.ABAJO,
}

CORRECCIONES = {normalizar_texto(o): c for o, c in datos.CORRECCIONES_ORACIONES}
SACRAMENTOS_FIJOS = {normalizar_texto(t): s for t, s in datos.SACRAMENTOS_POR_ORACION}


@dataclass
class Resultado:
    modelos_nuevos: list = field(default_factory=list)
    nuevos: list = field(default_factory=list)
    actualizados: list = field(default_factory=list)
    ya_importados: list = field(default_factory=list)
    omitidos: list = field(default_factory=list)
    errores: list = field(default_factory=list)
    sin_asignar: list = field(default_factory=list)
    descartados: list = field(default_factory=list)
    oraciones_nuevas: int = 0
    oraciones_sin_sacramento: list = field(default_factory=list)


def decimal(valor):
    return Decimal(str(round(valor, 2)))


def es_titulo(texto):
    normal = normalizar_texto(texto)
    return len(normal.split()) <= 12 and bool(TITULO.match(normal))


def es_celebracion(texto):
    return bool(
        FECHA.search(texto)
        or LUGAR.search(texto)
        or re.match(r"\s*celebrad", texto, re.I)
        or PADRINOS.search(texto)
    )


def analizar_nombre(ruta):
    """Modelo, variante y si el nombre indica "sin oración". Tarj2059_Conf_SOr -> 2059."""
    nombre = ruta.stem
    hallado = re.match(r"^Tarj(\d+)(.*)$", nombre, re.I)
    if not hallado:
        return nombre, "base", False
    sufijo = hallado.group(2).strip(" _")
    return hallado.group(1), sufijo or "base", bool(SIN_ORACION.search(sufijo))


def es_diploma(ruta):
    return "diplomas" in (p.lower() for p in ruta.parts) or ruta.stem.lower().startswith("diploma")


def _tamano_mayor(cuadro):
    return max((c.tamano or 0 for p in cuadro.parrafos for c in p.corridas if c.texto.strip()), default=0)


def deducir_rol(cuadro, cuadros):
    texto = cuadro.texto
    if es_titulo(texto):
        return Rol.TITULO
    if NACIMIENTO.match(texto) and len(texto.splitlines()) == 1:
        return Rol.FECHA_NACIMIENTO
    if es_celebracion(texto):
        lineas = [p for p in cuadro.parrafos if p.texto.strip()]
        if len(lineas) == 1 and FECHA.search(texto) and len(texto.split()) <= 6:
            return Rol.FECHA
        primera = {c.fuente for c in lineas[0].corridas if c.texto.strip()}
        resto = {c.fuente for p in lineas[1:] for c in p.corridas if c.texto.strip()}
        if len(lineas) > 2 and not es_celebracion(lineas[0].texto) and primera and resto and not primera & resto:
            return Rol.SIN_ASIGNAR  # Nombre y celebración en el mismo cuadro.
        return Rol.CELEBRACION
    restantes = [
        c for c in cuadros
        if c.texto and not es_titulo(c.texto) and not es_celebracion(c.texto)
    ]
    mayor = max(restantes, key=_tamano_mayor, default=None)
    sin_iniciales = re.sub(r"\b[A-ZÁÉÍÓÚÑ]\.", "", texto)
    if cuadro is mayor and len(texto.split()) <= 8 and not re.search(r'[.,;:!¡¿?"“”]', sin_iniciales):
        return Rol.NOMBRE
    if len(texto.split()) >= 3:
        return Rol.ORACION
    return Rol.SIN_ASIGNAR


def _dominante(corridas):
    """Formato con más caracteres dentro de un grupo de corridas."""
    conteo = Counter()
    for corrida in corridas:
        if corrida.texto.strip():
            clave = (
                corrida.fuente,
                corrida.tamano,
                bool(corrida.negrita),
                bool(corrida.cursiva),
                corrida.color,
                corrida.espaciado or 0,
            )
            conteo[clave] += len(corrida.texto.strip())
    return conteo.most_common(1)[0][0] if conteo else (None, None, False, False, None, 0)


def _elemento_de_linea(texto, rol):
    if rol == Rol.ORACION:
        return EstiloLinea.Elemento.AUTOR if CITA.match(texto.strip()) else None
    if NACIMIENTO.match(texto):
        return EstiloLinea.Elemento.NACIMIENTO
    if PADRES.search(texto):
        return EstiloLinea.Elemento.PADRES
    if PADRINOS.search(texto):
        return EstiloLinea.Elemento.PADRINOS
    if FECHA.search(texto):
        return EstiloLinea.Elemento.FECHA
    if LUGAR.search(texto):
        return EstiloLinea.Elemento.LUGAR
    if re.search(r"[–-]|\bcapital\b", texto, re.I):
        return EstiloLinea.Elemento.LOCALIDAD
    return EstiloLinea.Elemento.TEXTO_FIJO


def _formato_de_parrafo(parrafo, base):
    """Alineación, espacios y sangrías del párrafo que difieren del primero del cuadro."""
    alineacion = ALINEACIONES.get(parrafo.alineacion, CuadroTexto.Alineacion.IZQUIERDA)
    datos = {}
    if alineacion != ALINEACIONES.get(base.alineacion, CuadroTexto.Alineacion.IZQUIERDA):
        datos["alineacion"] = alineacion
    if parrafo.antes != base.antes:
        datos["espacio_antes_pt"] = decimal(parrafo.antes)
    if parrafo.despues != base.despues:
        datos["espacio_despues_pt"] = decimal(parrafo.despues)
    for campo, atributo in (
        ("sangria_izquierda_mm", "sangria_izquierda"),
        ("sangria_derecha_mm", "sangria_derecha"),
        ("sangria_primera_mm", "sangria_primera"),
    ):
        if getattr(parrafo, atributo):
            datos[campo] = decimal(getattr(parrafo, atributo))
    return datos


def _estilos_de_linea(cuadro, rol, principal):
    """Partes del cuadro cuyo formato (de letra o de párrafo) difiere del principal."""
    if rol not in (Rol.CELEBRACION, Rol.ORACION):
        return []
    visibles = [p for p in cuadro.parrafos if p.texto.strip()]
    if not visibles:
        return []
    base = visibles[0]
    estilos = {}
    for parrafo in visibles:
        elemento = _elemento_de_linea(parrafo.texto, rol)
        if elemento is None or elemento in estilos:
            continue
        propio = _dominante(parrafo.corridas)
        formato = _formato_de_parrafo(parrafo, base) if parrafo is not base else {}
        # Las sangrías del primer párrafo también cuentan: el cuadro no las guarda.
        if parrafo is base:
            formato = {k: v for k, v in _formato_de_parrafo(parrafo, Parrafo()).items() if k.startswith("sangria")}
        if propio[:5] == principal[:5] and not formato:
            continue
        estilos[elemento] = EstiloLinea(
            elemento=elemento,
            fuente=propio[0] if propio[0] != principal[0] else "",
            tamano_pt=decimal(propio[1]) if propio[1] and propio[1] != principal[1] else None,
            negrita=propio[2] if propio[2] != principal[2] else None,
            cursiva=propio[3] if propio[3] != principal[3] else None,
            color=propio[4] if propio[4] and propio[4] != principal[4] else "",
            **formato,
        )
    return list(estilos.values())


def tapado_por_otro(cuadro, cuadros):
    """El cuadro queda detrás de otro con fondo de la misma página."""
    area = cuadro.ancho * cuadro.alto
    if not area:
        return False
    for otro in cuadros:
        if otro is cuadro or otro.pagina != cuadro.pagina or not otro.con_relleno:
            continue
        if otro.orden_z <= cuadro.orden_z:
            continue
        ancho = min(cuadro.x + cuadro.ancho, otro.x + otro.ancho) - max(cuadro.x, otro.x)
        alto = min(cuadro.y + cuadro.alto, otro.y + otro.alto) - max(cuadro.y, otro.y)
        if ancho > 0 and alto > 0 and ancho * alto / area > 0.5:
            return True
    return False


def sacramentos_del_ejemplo(cuadros):
    """Sacramentos según el texto del título y la celebración del pedido de ejemplo."""
    texto = normalizar_texto(
        " ".join(c.texto for c, rol in cuadros if rol in (Rol.TITULO, Rol.CELEBRACION))
    )
    codigos = []
    if "bautism" in texto or "bautiz" in texto:
        codigos.append(datos.BAUTISMO)
    if "comunion" in texto or "eucaristia" in texto:
        codigos.append(datos.COMUNION)
    # Los padrinos solo indican Confirmación cuando no hay bautismo: ahí también los hay.
    if "confirmacion" in texto or (PADRINOS.search(texto) and datos.BAUTISMO not in codigos):
        codigos.append(datos.CONFIRMACION)
    return codigos


def separar_cita(texto, cita=None):
    texto = re.sub(r"\s+", " ", texto).strip()
    hallada = CITA_AL_FINAL.search(texto)
    if hallada and not cita:
        cita, texto = hallada.group(1), texto[: hallada.start()].strip()
    return texto, cita


def leer_banco_oraciones(ruta):
    """(número, texto, cita) de cada oración de un archivo del banco."""
    parrafos = leer_parrafos_cuerpo(ruta)
    oraciones = []
    numerado = any(ENCABEZADO_BANCO.match(p) for p in parrafos)
    i = 0
    while i < len(parrafos):
        encabezado = ENCABEZADO_BANCO.match(parrafos[i])
        if numerado and not encabezado:
            i += 1
            continue
        numero = int(encabezado.group(1)) if encabezado else None
        if encabezado:
            i += 1
        # Un título suelto (sin puntuación final y corto) no es una oración.
        if not encabezado and len(parrafos[i].split()) <= 6 and parrafos[i][-1] not in ".!?”\"":
            i += 1
            continue
        texto = parrafos[i]
        i += 1
        cita = None
        if i < len(parrafos) and CITA.match(parrafos[i]):
            cita = parrafos[i]
            i += 1
        oraciones.append((numero, *separar_cita(texto, cita)))
    return oraciones


class Importador:
    def __init__(self, actualizar=False):
        self.actualizar = actualizar
        self.resultado = Resultado()
        self.sacramentos = {s.codigo: s for s in Sacramento.objects.all()}
        self.raiz = Path(settings.MODELOS_DOCX_DIR)

    # ----- Recorrido -----

    def importar_todo(self):
        self.importar_banco_oraciones()
        for carpeta in ("estampas", "diplomas"):
            for ruta in sorted((self.raiz / carpeta).rglob("*.docx")):
                if not ruta.name.startswith("~$"):
                    self.importar_archivo(ruta)
        return self.resultado

    def importar_archivo(self, ruta):
        ruta = Path(ruta).resolve()
        origen = self._ruta_relativa(ruta)
        existente = VarianteLayout.objects.filter(archivo_origen=origen).first()
        if existente and not self.actualizar:
            self.resultado.ya_importados.append(origen)
            return
        try:
            with transaction.atomic():
                self._importar(ruta, origen, existente)
        except Exception as error:  # Un archivo dañado no debe frenar a los demás.
            self.resultado.errores.append((origen, f"{type(error).__name__}: {error}"))

    def _ruta_relativa(self, ruta):
        try:
            return ruta.relative_to(self.raiz.resolve()).as_posix()
        except ValueError:
            return ruta.as_posix()

    # ----- Modelos -----

    def _importar(self, ruta, origen, existente):
        documento = leer_docx(ruta)
        if not any(c.texto for c in documento.cuadros):
            self.resultado.omitidos.append(f"{origen}: no tiene cuadros de texto")
            return
        diploma = es_diploma(ruta)
        cuadros = self._preparar_diploma(documento, origen) if diploma else self._preparar_estampa(documento, origen)
        codigo, nombre, sin_oracion = analizar_nombre(ruta)
        # Calibración e imágenes de fondo no se tocan: solo el tipo y el tamaño de la hoja.
        modelo, modelo_creado = ModeloTarjeta.objects.update_or_create(
            codigo=codigo,
            defaults={
                "tipo": ModeloTarjeta.Tipo.DIPLOMA if diploma else ModeloTarjeta.Tipo.ESTAMPA,
                "ancho_mm": decimal(documento.ancho_mm),
                "alto_mm": decimal(documento.alto_mm),
            },
        )
        if modelo_creado:
            self.resultado.modelos_nuevos.append(codigo)
        roles = [rol for _, rol in cuadros]
        lleva_oracion = Rol.ORACION in roles and not sin_oracion
        if existente:
            variante = existente
            variante.lleva_oracion = lleva_oracion
            variante.save(update_fields=["lleva_oracion"])
        else:
            variante = VarianteLayout.objects.create(
                modelo=modelo,
                nombre=nombre,
                archivo_origen=origen,
                lleva_oracion=lleva_oracion,
                lleva_padrinos=self._lleva_padrinos(nombre, cuadros, diploma, ruta),
                modo_titulo=self._modo_titulo(cuadros),
                genero=self._genero(ruta) if diploma else "",
            )
            variante.sacramentos.set(self._sacramentos_de_variante(ruta, nombre, diploma))
        self._guardar_cuadros(variante, cuadros, origen)
        if not diploma:
            self._crear_plantillas(variante, ruta, cuadros)
            if not existente:
                self._agregar_oraciones_de_estampa(cuadros, origen)
        lista = self.resultado.actualizados if existente else self.resultado.nuevos
        lista.append(origen)

    def _preparar_estampa(self, documento, origen):
        visibles = []
        for cuadro in documento.cuadros:
            if not cuadro.texto:
                continue
            if cuadro.fuera_de_hoja(documento.ancho_mm, documento.alto_mm):
                self.resultado.descartados.append(f"{origen}: fuera de la hoja: {cuadro.texto[:40]!r}")
                continue
            if cuadro.oculto:
                self.resultado.descartados.append(f"{origen}: oculto: {cuadro.texto[:40]!r}")
                continue
            visibles.append(cuadro)
        # Un cuadro tapado por otro con fondo es un resto de un pedido anterior.
        tapados = [c for c in visibles if tapado_por_otro(c, visibles)]
        for cuadro in tapados:
            self.resultado.descartados.append(f"{origen}: tapado por otro cuadro: {cuadro.texto[:40]!r}")
        visibles = [c for c in visibles if c not in tapados]
        return [(c, self._rol_de_estampa(c, visibles)) for c in visibles]

    def _rol_de_estampa(self, cuadro, visibles):
        rol = deducir_rol(cuadro, visibles)
        if rol == Rol.SIN_ASIGNAR:
            cuadro.nota = "No se pudo deducir el rol."
        return rol

    def _preparar_diploma(self, documento, origen):
        """De un diploma solo se importa el nombre: lo demás viene preimpreso."""
        visibles = [
            c for c in documento.cuadros
            if c.texto and not c.oculto and not c.fuera_de_hoja(documento.ancho_mm, documento.alto_mm)
        ]
        propios = [c for c in visibles if not es_titulo(c.texto)]
        candidatos = [c for c in propios if not es_celebracion(c.texto)]
        if candidatos:
            return [(max(candidatos, key=_tamano_mayor), Rol.NOMBRE)]
        # Título y nombre en el mismo cuadro: el nombre es el último párrafo.
        for cuadro in visibles:
            lineas = [p for p in cuadro.parrafos if p.texto.strip()]
            if len(lineas) >= 2 and es_titulo(" ".join(p.texto for p in lineas[:-1])):
                return [(self._aislar_ultimo_parrafo(cuadro), Rol.NOMBRE)]
        for cuadro in visibles:
            cuadro.nota = "No se encontró el nombre del diploma."
        return [(c, Rol.SIN_ASIGNAR) for c in visibles]

    @staticmethod
    def _aislar_ultimo_parrafo(cuadro):
        ultimo = max(i for i, p in enumerate(cuadro.parrafos) if p.texto.strip())
        alto_previo = sum(p.alto_mm() for p in cuadro.parrafos[:ultimo])
        cuadro.y += alto_previo
        cuadro.alto = cuadro.parrafos[ultimo].alto_mm() + 2 * INSET_Y_MM
        cuadro.parrafos = [cuadro.parrafos[ultimo]]
        cuadro.nota = "Posición calculada: en el .docx el nombre comparte cuadro con el título."
        return cuadro

    @staticmethod
    def _lleva_padrinos(nombre, cuadros, diploma, ruta):
        if diploma or "s_pad" in nombre.lower():
            return False
        celebracion = " ".join(c.texto for c, rol in cuadros if rol == Rol.CELEBRACION)
        sacramentos = sacramentos_del_ejemplo(cuadros)
        solo_con_padrinos = datos.COMUNION not in sacramentos and sacramentos
        return not solo_con_padrinos or bool(PADRINOS.search(celebracion))

    @staticmethod
    def _modo_titulo(cuadros):
        titulos = [normalizar_texto(c.texto) for c, rol in cuadros if rol == Rol.TITULO]
        if not titulos:
            return VarianteLayout.ModoTitulo.SIN_TITULO
        if titulos[0].startswith(("recuerdo", "invitacion")):
            return VarianteLayout.ModoTitulo.COMPLETO
        return VarianteLayout.ModoTitulo.SIN_RECUERDO

    @staticmethod
    def _genero(ruta):
        nombre = ruta.stem.lower()
        if "fem" in nombre:
            return Genero.MUJER
        if "masc" in nombre:
            return Genero.VARON
        return ""

    def _sacramentos_de_variante(self, ruta, nombre, diploma):
        """Para qué sacramentos sirve. Vacío (cualquiera) si el archivo no lo limita."""
        carpetas = [p.lower() for p in ruta.parts]
        if diploma:
            normal = normalizar_texto(ruta.stem)
            codigos = [
                codigo
                for clave, codigo in (
                    ("bautismo", datos.BAUTISMO),
                    ("comunion", datos.COMUNION),
                    ("confirmacion", datos.CONFIRMACION),
                )
                if clave in normal
            ]
        elif nombre.lower() == "bautismo":
            codigos = [datos.BAUTISMO, datos.COMUNION, datos.CONFIRMACION]
        elif "bautismo" in carpetas:
            codigos = [datos.BAUTISMO]
        elif re.search(r"(^|[ _])conf($|[ _])", nombre, re.I):
            codigos = [datos.CONFIRMACION]
        else:
            codigos = []
        return [self.sacramentos[c] for c in codigos if c in self.sacramentos]

    # ----- Cuadros -----

    def _sacramento_de_cuadro(self, cuadro, rol, cuadros):
        """Solo cuando el modelo tiene varios cuadros del mismo rol, como Tarj2052."""
        if rol not in (Rol.TITULO, Rol.CELEBRACION):
            return None
        if sum(1 for _, otro in cuadros if otro == rol) < 2:
            return None
        normal = normalizar_texto(cuadro.texto)
        if "bautism" in normal or "bautiz" in normal:
            return self.sacramentos.get(datos.BAUTISMO)
        if "confirmacion" in normal:
            return self.sacramentos.get(datos.CONFIRMACION)
        return None

    def _datos_de_cuadro(self, cuadro, rol, cuadros):
        visibles = [c for p in cuadro.parrafos for c in p.corridas]
        principal = _dominante(visibles)
        parrafo = next((p for p in cuadro.parrafos if p.texto.strip()), cuadro.parrafos[0])
        renglones = sum(1 for p in cuadro.parrafos if p.texto.strip())
        minimo = None
        interlineado = Decimal("1")
        if parrafo.regla_linea in ("atLeast", "exact") and parrafo.linea:
            minimo = decimal(parrafo.linea / 20)
        elif parrafo.linea:
            interlineado = decimal(parrafo.linea / 240)
        respeta = (rol in (Rol.TITULO, Rol.NOMBRE) and renglones > 1) or (
            rol == Rol.CELEBRACION and not cuadro.texto.lower().startswith("recib")
        )
        return principal, {
            "pagina": cuadro.pagina,
            "x_mm": decimal(cuadro.x),
            "y_mm": decimal(cuadro.y),
            "ancho_mm": decimal(cuadro.ancho),
            "alto_mm": decimal(cuadro.alto),
            "fuente": principal[0] or "Calibri",
            "tamano_pt": decimal(principal[1] or 11),
            "negrita": principal[2],
            "cursiva": principal[3],
            "color": principal[4] or "000000",
            "alineacion": ALINEACIONES.get(parrafo.alineacion, CuadroTexto.Alineacion.IZQUIERDA),
            "alineacion_vertical": ANCLAS.get(
                cuadro.ancla_vertical, CuadroTexto.AlineacionVertical.ARRIBA
            ),
            "interlineado": interlineado,
            "interlineado_minimo_pt": minimo,
            "espacio_despues_pt": decimal(parrafo.despues or 0),
            "espacio_antes_pt": decimal(parrafo.antes or 0),
            "espaciado_letras_pt": decimal(principal[5] or 0),
            "rotacion": CuadroTexto.Rotacion.INVERTIDO if cuadro.invertido else CuadroTexto.Rotacion.NORMAL,
            "respeta_saltos": respeta,
            "nota_importacion": getattr(cuadro, "nota", ""),
        }

    def _guardar_cuadros(self, variante, cuadros, origen):
        actuales = {c.indice_origen: c for c in variante.cuadros.all()}
        indices = set()
        for cuadro, rol in cuadros:
            indices.add(cuadro.indice)
            principal, campos = self._datos_de_cuadro(cuadro, rol, cuadros)
            guardado = actuales.get(cuadro.indice)
            if guardado:
                if guardado.posicion_corregida:  # Movido a mano: no se pisa.
                    for campo in ("x_mm", "y_mm", "ancho_mm", "alto_mm"):
                        campos.pop(campo)
                for campo, valor in campos.items():
                    setattr(guardado, campo, valor)
                if not guardado.rol_corregido:
                    guardado.rol = rol
                guardado.save()
                guardado.estilos.all().delete()
            else:
                guardado = variante.cuadros.create(
                    indice_origen=cuadro.indice,
                    rol=rol,
                    sacramento=self._sacramento_de_cuadro(cuadro, rol, cuadros),
                    **campos,
                )
            for estilo in _estilos_de_linea(cuadro, rol, principal):
                estilo.cuadro = guardado
                estilo.save()
            if guardado.rol == Rol.SIN_ASIGNAR:
                self.resultado.sin_asignar.append(f"{origen}: {cuadro.texto[:50]!r}")
        for indice, sobrante in actuales.items():
            if indice not in indices:
                sobrante.delete()

    # ----- Plantillas -----

    def _crear_plantillas(self, variante, ruta, cuadros):
        """Solo agrega las que faltan: las editadas en el admin no se pisan."""
        propias = list(datos.PLANTILLAS_POR_ARCHIVO.get(ruta.stem, []))
        ya_definidas = {(p[0], p[1]) for p in propias}
        titulo = next((c for c, rol in cuadros if rol == Rol.TITULO), None)
        if titulo is not None and ("titulo_completo", None) not in ya_definidas:
            lineas = [normalizar_texto(p.texto) for p in titulo.parrafos if p.texto.strip()]
            if len(lineas) == 2 and lineas[0] == "recuerdo de mi":
                propias.append(("titulo_completo", None, None, "Recuerdo de {Posesivo}\n{sacramentos}"))
            elif len(lineas) == 2 and lineas[0] == "recuerdo de":
                propias.append(("titulo_completo", None, None, "Recuerdo de\n{Posesivo} {sacramentos}"))
        for clave, sacramento, cantidad, texto in propias:
            PlantillaTexto.objects.get_or_create(
                clave=clave,
                sacramento=self.sacramentos.get(sacramento),
                cantidad_ninos=cantidad,
                variante=variante,
                defaults={"texto": texto},
            )

    # ----- Oraciones -----

    def importar_banco_oraciones(self):
        for ruta in sorted((self.raiz / "oraciones").glob("*.docx")):
            if ruta.name.startswith("~$"):
                continue
            codigos = (
                [datos.BAUTISMO]
                if "bautismo" in ruta.stem.lower()
                else [datos.COMUNION, datos.CONFIRMACION]
            )
            for numero, texto, cita in leer_banco_oraciones(ruta):
                self._cargar_oracion(texto, cita, numero, codigos, solo_si_es_nueva=True)

    def _agregar_oraciones_de_estampa(self, cuadros, origen):
        codigos = sacramentos_del_ejemplo(cuadros)
        for cuadro, rol in cuadros:
            if rol != Rol.ORACION:
                continue
            lineas = [p.texto.strip() for p in cuadro.parrafos if p.texto.strip()]
            cita = lineas.pop() if len(lineas) > 1 and CITA.match(lineas[-1]) else None
            texto, cita = separar_cita(" ".join(lineas), cita)
            oracion = self._cargar_oracion(texto, cita, None, codigos, solo_si_es_nueva=False)
            if oracion is not None and not oracion.sacramentos.exists():
                self.resultado.oraciones_sin_sacramento.append(f"{origen}: {oracion.texto[:50]!r}")

    def _cargar_oracion(self, texto, cita, numero, codigos, solo_si_es_nueva):
        original = normalizar_texto(texto)
        corregido = CORRECCIONES.get(original, texto)
        clave = normalizar_texto(corregido)
        if not clave:
            return None
        oracion = Oracion.objects.filter(clave=clave).first()
        creada = oracion is None
        if creada:
            oracion = Oracion.objects.create(
                numero=numero,
                texto=corregido,
                autor=datos.CORRECCIONES_CITAS.get(cita, cita) if cita else "",
            )
            self.resultado.oraciones_nuevas += 1
        elif solo_si_es_nueva:
            return oracion
        fijos = SACRAMENTOS_FIJOS.get(original)
        elegidos = fijos if fijos is not None else codigos
        oracion.sacramentos.add(*[self.sacramentos[c] for c in elegidos if c in self.sacramentos])
        return oracion


# ----- Negrita por partes (importar_modelos --estilos) -----

CLAVES_POR_ELEMENTO = {
    EstiloLinea.Elemento.PADRINOS: [
        PlantillaTexto.Clave.PADRINOS_AMBOS,
        PlantillaTexto.Clave.PADRINOS_SOLO_PADRINO,
        PlantillaTexto.Clave.PADRINOS_SOLO_MADRINA,
    ],
    EstiloLinea.Elemento.PADRES: [
        PlantillaTexto.Clave.PADRES_AMBOS,
        PlantillaTexto.Clave.PADRES_SOLO_PADRE,
        PlantillaTexto.Clave.PADRES_SOLO_MADRE,
    ],
    EstiloLinea.Elemento.NACIMIENTO: [PlantillaTexto.Clave.NACIMIENTO],
}


@dataclass
class EtiquetaEnNegrita:
    """Etiqueta en negrita al comienzo de un renglón del .docx: "**Mi Madrina**: Eva"."""

    palabras: int
    con_dos_puntos: bool
    texto_docx: str


def etiqueta_en_negrita(parrafo):
    """La etiqueta en negrita del comienzo del párrafo, completando palabras cortadas."""
    corridas = [c for c in parrafo.corridas if c.texto]
    if not corridas or not corridas[0].negrita:
        return None
    if len({bool(c.negrita) for c in corridas if c.texto.strip()}) < 2:
        return None
    texto = "".join(c.texto for c in corridas)
    largo = 0
    for corrida in corridas:
        if not corrida.negrita:
            break
        largo += len(corrida.texto)
    # "Mis Padrino" + "s:" -> se completa la palabra cortada: "Mis Padrinos".
    while largo < len(texto) and texto[largo].isalpha():
        largo += 1
    negrita = texto[:largo].strip()
    if not negrita:
        return None
    return EtiquetaEnNegrita(
        palabras=len(negrita.rstrip(":").split()),
        con_dos_puntos=negrita.endswith(":"),
        texto_docx="".join(f"**{c.texto}**" if c.negrita else c.texto for c in corridas).strip(),
    )


def marcar_etiqueta(plantilla, etiqueta):
    """Pone en negrita las primeras palabras del primer renglón de la plantilla."""
    renglones = plantilla.split("\n")
    primero = renglones[0]
    if "**" in primero:
        return plantilla
    hallado = re.match(r"^(\s*(?:[^\s{]+\s+){%d})" % (etiqueta.palabras - 1) + r"([^\s{]+)", primero)
    if not hallado:
        return plantilla
    etiqueta_texto = hallado.group(1) + hallado.group(2)
    resto = primero[len(etiqueta_texto):]
    if etiqueta_texto.endswith(":") and not etiqueta.con_dos_puntos:
        etiqueta_texto, resto = etiqueta_texto[:-1], ":" + resto
    renglones[0] = f"**{etiqueta_texto.strip()}**{resto}"
    return "\n".join(renglones)


@dataclass
class CambioDeEstilo:
    variante: str
    plantilla: str
    antes: str
    despues: str
    docx: str


def aplicar_estilos(variante, ruta):
    """Lleva a las plantillas de la variante la negrita por partes del .docx.

    Devuelve (cambios, no_aplicadas). No toca plantillas que ya tengan marcas de negrita.
    """
    documento = leer_docx(ruta)
    por_indice = {c.indice: c for c in documento.cuadros}
    cambios, no_aplicadas = [], []
    for cuadro in variante.cuadros.filter(rol=Rol.CELEBRACION):
        original = por_indice.get(cuadro.indice_origen)
        if original is None:
            continue
        for parrafo in original.parrafos:
            etiqueta = etiqueta_en_negrita(parrafo)
            if etiqueta is None:
                if len({bool(c.negrita) for c in parrafo.corridas if c.texto.strip()}) > 1:
                    no_aplicadas.append(f"{variante.archivo_origen}: {parrafo.texto.strip()!r}")
                continue
            elemento = _elemento_de_linea(parrafo.texto, Rol.CELEBRACION)
            claves = CLAVES_POR_ELEMENTO.get(elemento)
            if not claves:
                no_aplicadas.append(f"{variante.archivo_origen}: {etiqueta.texto_docx!r}")
                continue
            for clave in claves:
                cambios += _marcar_plantillas(variante, clave, etiqueta)
            # El renglón queda sin negrita de base: la negrita va solo en la etiqueta.
            estilo, _ = EstiloLinea.objects.get_or_create(cuadro=cuadro, elemento=elemento)
            if estilo.negrita is not False:
                estilo.negrita = False
                estilo.save()
    return cambios, no_aplicadas


def _marcar_plantillas(variante, clave, etiqueta):
    """Crea o actualiza, para la variante, la plantilla de cada caso general de esa clave."""
    cambios = []
    generales = PlantillaTexto.objects.filter(clave=clave, variante__isnull=True)
    for general in generales:
        propia, creada = PlantillaTexto.objects.get_or_create(
            clave=clave,
            sacramento=general.sacramento,
            cantidad_ninos=general.cantidad_ninos,
            variante=variante,
            defaults={"texto": general.texto},
        )
        antes = propia.texto
        despues = marcar_etiqueta(antes, etiqueta)
        if despues == antes:
            if creada:  # No se pudo marcar: no hace falta una copia igual a la general.
                propia.delete()
            continue
        propia.texto = despues
        propia.save()
        cambios.append(
            CambioDeEstilo(
                variante=str(variante),
                plantilla=str(propia),
                antes=general.texto if creada else antes,
                despues=despues,
                docx=etiqueta.texto_docx,
            )
        )
    return cambios
