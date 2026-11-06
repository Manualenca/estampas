import re
import unicodedata
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

MAX_NINOS_POR_ESTAMPA = 2

validar_color = RegexValidator(
    r"^[0-9A-Fa-f]{6}$", "Color hexadecimal de 6 dígitos, sin #. Ejemplo: 806000."
)

# Palabras iniciales de un lugar que llevan "el". El resto lleva "la".
LUGARES_MASCULINOS = {
    "colegio",
    "convento",
    "hospital",
    "instituto",
    "monasterio",
    "oratorio",
    "santuario",
    "seminario",
    "templo",
}


def normalizar_texto(texto):
    """Clave de comparación: ignora mayúsculas, acentos, puntuación y espacios."""
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", texto))
    return texto.strip()


def deducir_articulo(lugar):
    palabras = lugar.split()
    if not palabras:
        return ""
    return "el" if palabras[0].strip(".,").lower() in LUGARES_MASCULINOS else "la"


class Genero(models.TextChoices):
    MUJER = "F", "Mujer"
    VARON = "M", "Varón"


class Sacramento(models.Model):
    """Bautismo, Primera Comunión y Confirmación. Se cargan en una migración."""

    BAUTISMO = "bautismo"
    COMUNION = "comunion"
    CONFIRMACION = "confirmacion"

    codigo = models.SlugField("código", unique=True)
    nombre = models.CharField("nombre", max_length=60, unique=True)
    posesivo_plural = models.CharField(
        "posesivo para 2 chicos",
        max_length=20,
        help_text="Nuestro o Nuestra, según el sacramento.",
    )
    orden = models.PositiveSmallIntegerField(
        "orden", default=0, help_text="Orden en que aparece dentro del título."
    )

    class Meta:
        ordering = ["orden"]
        verbose_name = "sacramento"
        verbose_name_plural = "sacramentos"

    def __str__(self):
        return self.nombre


class OracionQuerySet(models.QuerySet):
    def priorizar_sacramentos(self, sacramentos):
        """Todas las oraciones, primero las de los sacramentos indicados."""
        afines = self.filter(sacramentos__in=sacramentos).values("pk")
        return self.annotate(
            afin=models.Case(
                models.When(pk__in=afines, then=models.Value(0)),
                default=models.Value(1),
                output_field=models.IntegerField(),
            )
        ).order_by("afin", "numero", "texto")


class Oracion(models.Model):
    numero = models.PositiveIntegerField(
        "n.º", null=True, blank=True, help_text="N.º de texto en el banco de oraciones."
    )
    texto = models.TextField("texto")
    autor = models.CharField("autor o cita", max_length=120, blank=True)
    sacramentos = models.ManyToManyField(
        Sacramento, verbose_name="sacramentos", related_name="oraciones", blank=True
    )
    clave = models.CharField(max_length=1000, unique=True, editable=False)

    objects = OracionQuerySet.as_manager()

    class Meta:
        ordering = ["numero", "texto"]
        verbose_name = "oración"
        verbose_name_plural = "oraciones"

    def __str__(self):
        prefijo = f"{self.numero}. " if self.numero else ""
        return f"{prefijo}{self.texto[:70]}"

    def clean(self):
        clave = normalizar_texto(self.texto or "")
        if Oracion.objects.exclude(pk=self.pk).filter(clave=clave).exists():
            raise ValidationError({"texto": "Esta oración ya está en el banco."})

    def save(self, *args, **kwargs):
        self.clave = normalizar_texto(self.texto)
        super().save(*args, **kwargs)


class ModeloTarjeta(models.Model):
    """Diseño físico de la tarjeta o del diploma."""

    class Tipo(models.TextChoices):
        ESTAMPA = "estampa", "Estampa"
        DIPLOMA = "diploma", "Diploma"

    codigo = models.CharField("código", max_length=80, unique=True)
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices)
    ancho_mm = models.DecimalField("ancho (mm)", max_digits=6, decimal_places=2)
    alto_mm = models.DecimalField("alto (mm)", max_digits=6, decimal_places=2)
    imagen_fondo = models.ImageField(
        "fondo del anverso",
        upload_to="fondos/",
        blank=True,
        help_text="Solo para la vista previa. No se imprime.",
    )
    imagen_fondo_reverso = models.ImageField(
        "fondo del reverso",
        upload_to="fondos/",
        blank=True,
        help_text="Solo para la vista previa. No se imprime.",
    )
    offset_x = models.DecimalField(
        "ajuste X anverso (mm)", max_digits=5, decimal_places=2, default=0
    )
    offset_y = models.DecimalField(
        "ajuste Y anverso (mm)", max_digits=5, decimal_places=2, default=0
    )
    offset_x_reverso = models.DecimalField(
        "ajuste X reverso (mm)", max_digits=5, decimal_places=2, default=0
    )
    offset_y_reverso = models.DecimalField(
        "ajuste Y reverso (mm)", max_digits=5, decimal_places=2, default=0
    )
    calibracion_probada = models.BooleanField(
        "calibración probada en impresora",
        default=False,
        help_text="Se imprimió la hoja de prueba con este ajuste y coincide con la tarjeta.",
    )
    calibracion_probada_el = models.DateTimeField("probada el", null=True, blank=True)

    CAMPOS_AJUSTE = ("offset_x", "offset_y", "offset_x_reverso", "offset_y_reverso")

    class EstadoCalibracion(models.TextChoices):
        PROBADA = "probada", "Probada en impresora"
        SIN_PROBAR = "sin_probar", "Ajuste cargado, falta probar"
        SIN_CALIBRAR = "sin_calibrar", "Sin calibrar"

    class Meta:
        ordering = ["tipo", "codigo"]
        verbose_name = "modelo de tarjeta"
        verbose_name_plural = "modelos de tarjeta"

    def __str__(self):
        return self.codigo

    @property
    def tiene_ajuste(self):
        return any(getattr(self, campo) for campo in self.CAMPOS_AJUSTE)

    @property
    def estado_calibracion(self):
        if self.calibracion_probada:
            return self.EstadoCalibracion.PROBADA
        if self.tiene_ajuste:
            return self.EstadoCalibracion.SIN_PROBAR
        return self.EstadoCalibracion.SIN_CALIBRAR

    def offset(self, pagina):
        """Ajuste de impresora (x, y) en mm para una página."""
        if pagina == CuadroTexto.Pagina.REVERSO:
            return self.offset_x_reverso, self.offset_y_reverso
        return self.offset_x, self.offset_y

    def variante_adecuada(self, con_oracion):
        """Variante según lleve oración o no. Si no existe, la que haya."""
        variantes = self.variantes.all()
        return (
            variantes.filter(lleva_oracion=con_oracion).first() or variantes.first()
        )


class VarianteLayout(models.Model):
    """Cada .docx de un modelo, con sus cuadros."""

    class ModoTitulo(models.TextChoices):
        COMPLETO = "completo", "Completo: «Recuerdo de mi ...»"
        SIN_RECUERDO = (
            "sin_recuerdo",
            "Sin «Recuerdo de»: viene impreso, solo «Mi ...»",
        )
        SIN_TITULO = "sin_titulo", "Sin título: todo viene impreso"

    modelo = models.ForeignKey(
        ModeloTarjeta,
        on_delete=models.CASCADE,
        related_name="variantes",
        verbose_name="modelo",
    )
    nombre = models.CharField(
        "nombre", max_length=60, help_text="Ejemplo: base, Conf, Sin oración, S_Pad."
    )
    archivo_origen = models.CharField(
        "archivo de origen",
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Ruta del .docx dentro de modelos_docx.",
    )
    lleva_oracion = models.BooleanField("lleva oración", default=True)
    lleva_padrinos = models.BooleanField("lleva línea de padrinos", default=True)
    modo_titulo = models.CharField(
        "título",
        max_length=15,
        choices=ModoTitulo.choices,
        default=ModoTitulo.COMPLETO,
    )
    sacramentos = models.ManyToManyField(
        Sacramento,
        verbose_name="sacramentos",
        related_name="variantes",
        blank=True,
        help_text="Para qué sacramentos sirve. Vacío: para cualquiera.",
    )
    genero = models.CharField(
        "género del diploma",
        max_length=1,
        choices=Genero.choices,
        blank=True,
        help_text="Solo diplomas. Vacío: para cualquiera.",
    )

    class Meta:
        ordering = ["modelo", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["modelo", "nombre"], name="variante_unica_por_modelo"
            )
        ]
        verbose_name = "variante de layout"
        verbose_name_plural = "variantes de layout"

    def __str__(self):
        return f"{self.modelo.codigo} · {self.nombre}"


class CuadroTexto(models.Model):
    class Pagina(models.IntegerChoices):
        ANVERSO = 1, "Anverso"
        REVERSO = 2, "Reverso"

    class Rol(models.TextChoices):
        TITULO = "titulo", "Título"
        NOMBRE = "nombre", "Nombre"
        ORACION = "oracion", "Oración"
        CELEBRACION = "celebracion", "Celebración"
        FECHA = "fecha", "Fecha"
        FECHA_NACIMIENTO = "fecha_nacimiento", "Fecha de nacimiento"
        SIN_ASIGNAR = "sin_asignar", "Sin asignar"

    class Alineacion(models.TextChoices):
        IZQUIERDA = "izquierda", "Izquierda"
        CENTRO = "centro", "Centro"
        DERECHA = "derecha", "Derecha"
        JUSTIFICADO = "justificado", "Justificado"

    class AlineacionVertical(models.TextChoices):
        ARRIBA = "arriba", "Arriba"
        CENTRO = "centro", "Centro"
        ABAJO = "abajo", "Abajo"

    class Rotacion(models.IntegerChoices):
        NORMAL = 0, "Normal"
        INVERTIDO = 180, "Invertido (180°)"

    variante = models.ForeignKey(
        VarianteLayout,
        on_delete=models.CASCADE,
        related_name="cuadros",
        verbose_name="variante",
    )
    indice_origen = models.PositiveSmallIntegerField(
        "orden en el .docx",
        default=0,
        help_text="Identifica el cuadro al volver a importar el archivo.",
    )
    pagina = models.PositiveSmallIntegerField(
        "página", choices=Pagina.choices, default=Pagina.ANVERSO
    )
    rol = models.CharField(
        "rol", max_length=20, choices=Rol.choices, default=Rol.SIN_ASIGNAR
    )
    rol_corregido = models.BooleanField(
        "rol corregido a mano",
        default=False,
        editable=False,
        help_text="El importador con --actualizar no cambia este rol.",
    )
    posicion_corregida = models.BooleanField(
        "posición corregida a mano",
        default=False,
        editable=False,
        help_text="El importador con --actualizar no cambia la posición ni el tamaño.",
    )
    sacramento = models.ForeignKey(
        Sacramento,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cuadros",
        verbose_name="sacramento",
        help_text="Solo si el cuadro corresponde a un sacramento puntual.",
    )
    x_mm = models.DecimalField("x (mm)", max_digits=7, decimal_places=2)
    y_mm = models.DecimalField("y (mm)", max_digits=7, decimal_places=2)
    ancho_mm = models.DecimalField("ancho (mm)", max_digits=7, decimal_places=2)
    alto_mm = models.DecimalField("alto (mm)", max_digits=7, decimal_places=2)
    fuente = models.CharField("fuente", max_length=80)
    tamano_pt = models.DecimalField("tamaño (pt)", max_digits=5, decimal_places=2)
    negrita = models.BooleanField("negrita", default=False)
    cursiva = models.BooleanField("cursiva", default=False)
    color = models.CharField(
        "color", max_length=6, default="000000", validators=[validar_color]
    )
    color_varon = models.CharField(
        "color para varón",
        max_length=6,
        blank=True,
        validators=[validar_color],
        help_text="Opcional. Si está vacío, se usa el color general.",
    )
    color_mujer = models.CharField(
        "color para mujer",
        max_length=6,
        blank=True,
        validators=[validar_color],
        help_text="Opcional. Si está vacío, se usa el color general.",
    )
    alineacion = models.CharField(
        "alineación",
        max_length=12,
        choices=Alineacion.choices,
        default=Alineacion.CENTRO,
    )
    alineacion_vertical = models.CharField(
        "alineación vertical",
        max_length=10,
        choices=AlineacionVertical.choices,
        default=AlineacionVertical.ARRIBA,
    )
    interlineado = models.DecimalField(
        "interlineado",
        max_digits=4,
        decimal_places=2,
        default=1,
        help_text="Múltiplo del alto de línea. 1 = sencillo.",
    )
    interlineado_minimo_pt = models.DecimalField(
        "interlineado mínimo (pt)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Si se completa, el renglón nunca es más bajo que este valor.",
    )
    espacio_despues_pt = models.DecimalField(
        "espacio tras cada párrafo (pt)", max_digits=5, decimal_places=2, default=0
    )
    espacio_antes_pt = models.DecimalField(
        "espacio antes de cada párrafo (pt)", max_digits=5, decimal_places=2, default=0
    )
    espaciado_letras_pt = models.DecimalField(
        "espaciado entre letras (pt)", max_digits=5, decimal_places=2, default=0
    )
    rotacion = models.PositiveSmallIntegerField(
        "rotación", choices=Rotacion.choices, default=Rotacion.NORMAL
    )
    respeta_saltos = models.BooleanField(
        "respeta los saltos de la plantilla",
        default=False,
        help_text="Si está apagado, el texto se ajusta solo al ancho del cuadro.",
    )
    nota_importacion = models.CharField(
        "nota de importación", max_length=200, blank=True
    )

    class Meta:
        ordering = ["variante", "pagina", "y_mm"]
        constraints = [
            models.UniqueConstraint(
                fields=["variante", "indice_origen"],
                name="cuadro_unico_por_indice_de_variante",
            ),
            models.CheckConstraint(
                condition=Q(pagina__in=[1, 2]),
                name="cuadro_pagina_valida",
            ),
        ]
        verbose_name = "cuadro de texto"
        verbose_name_plural = "cuadros de texto"

    def __str__(self):
        return f"{self.variante} · {self.get_rol_display()}"

    def color_para(self, generos):
        """Color según los chicos: el alternativo solo si todos son del mismo género."""
        distintos = set(generos)
        if distintos == {Genero.VARON} and self.color_varon:
            return self.color_varon
        if distintos == {Genero.MUJER} and self.color_mujer:
            return self.color_mujer
        return self.color


class EstiloLinea(models.Model):
    """Estilo propio de una parte del cuadro. Lo vacío hereda del cuadro."""

    class Elemento(models.TextChoices):
        TEXTO_FIJO = "texto_fijo", "Texto fijo de la plantilla"
        NACIMIENTO = "nacimiento", "Fecha de nacimiento"
        PADRES = "padres", "Padres"
        PADRINOS = "padrinos", "Padrinos"
        FECHA = "fecha", "Fecha"
        LUGAR = "lugar", "Lugar"
        LOCALIDAD = "localidad", "Localidad"
        AUTOR = "autor", "Autor de la oración"
        NOMBRE = "nombre", "Nombre"

    cuadro = models.ForeignKey(
        CuadroTexto,
        on_delete=models.CASCADE,
        related_name="estilos",
        verbose_name="cuadro",
    )
    elemento = models.CharField("parte", max_length=15, choices=Elemento.choices)
    fuente = models.CharField("fuente", max_length=80, blank=True)
    tamano_pt = models.DecimalField(
        "tamaño (pt)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    negrita = models.BooleanField("negrita", null=True, blank=True)
    cursiva = models.BooleanField("cursiva", null=True, blank=True)
    color = models.CharField(
        "color", max_length=6, blank=True, validators=[validar_color]
    )
    alineacion = models.CharField(
        "alineación", max_length=12, choices=CuadroTexto.Alineacion.choices, blank=True
    )
    espacio_antes_pt = models.DecimalField(
        "espacio antes (pt)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    espacio_despues_pt = models.DecimalField(
        "espacio después (pt)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    sangria_izquierda_mm = models.DecimalField(
        "sangría izquierda (mm)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    sangria_derecha_mm = models.DecimalField(
        "sangría derecha (mm)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    sangria_primera_mm = models.DecimalField(
        "sangría de la primera línea (mm)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Respecto de la izquierda. Negativa: sangría francesa.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cuadro", "elemento"], name="estilo_unico_por_parte"
            )
        ]
        verbose_name = "estilo de línea"
        verbose_name_plural = "estilos de línea"

    def __str__(self):
        return f"{self.cuadro} · {self.get_elemento_display()}"


class PlantillaTexto(models.Model):
    """Texto editable. Se elige la más específica para cada caso."""

    class Clave(models.TextChoices):
        TITULO_COMPLETO = "titulo_completo", "Título completo"
        TITULO_SIN_RECUERDO = "titulo_sin_recuerdo", "Título sin «Recuerdo de»"
        CELEBRACION = "celebracion", "Celebración"
        PADRINOS_AMBOS = "padrinos_ambos", "Padrinos: los dos"
        PADRINOS_SOLO_PADRINO = "padrinos_solo_padrino", "Padrinos: solo padrino"
        PADRINOS_SOLO_MADRINA = "padrinos_solo_madrina", "Padrinos: solo madrina"
        PADRES_AMBOS = "padres_ambos", "Padres: los dos"
        PADRES_SOLO_PADRE = "padres_solo_padre", "Padres: solo papá"
        PADRES_SOLO_MADRE = "padres_solo_madre", "Padres: solo mamá"
        NACIMIENTO = "nacimiento", "Fecha de nacimiento"

    clave = models.CharField("texto de", max_length=25, choices=Clave.choices)
    sacramento = models.ForeignKey(
        Sacramento,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="plantillas",
        verbose_name="sacramento",
        help_text="Vacío: cualquier sacramento.",
    )
    cantidad_ninos = models.PositiveSmallIntegerField(
        "cantidad de chicos",
        null=True,
        blank=True,
        choices=[(1, "1 chico"), (2, "2 chicos")],
        help_text="Vacío: cualquier cantidad.",
    )
    variante = models.ForeignKey(
        VarianteLayout,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="plantillas",
        verbose_name="variante",
        help_text="Solo para reemplazar el texto general en una variante.",
    )
    texto = models.TextField(
        "texto",
        help_text=(
            "Una línea por renglón. Variables: {posesivo} {Posesivo} {sacramentos} {fecha} {hora} "
            "{articulo} {parroquia} {localidad} {padrino} {madrina} {padre} {madre} "
            "{linea_padrinos} {linea_padres} {linea_nacimiento} {fecha_nacimiento} "
            "{bautizado} {anio}. Una línea cuyas variables queden vacías no se imprime."
        ),
    )

    class Meta:
        ordering = ["clave", "sacramento", "cantidad_ninos"]
        verbose_name = "plantilla de texto"
        verbose_name_plural = "plantillas de texto"

    def __str__(self):
        partes = [self.get_clave_display()]
        if self.sacramento:
            partes.append(self.sacramento.nombre)
        if self.cantidad_ninos:
            partes.append(self.get_cantidad_ninos_display())
        if self.variante:
            partes.append(str(self.variante))
        return " · ".join(partes)

    def clean(self):
        repetida = PlantillaTexto.objects.exclude(pk=self.pk).filter(
            clave=self.clave,
            sacramento=self.sacramento,
            cantidad_ninos=self.cantidad_ninos,
            variante=self.variante,
        )
        if repetida.exists():
            raise ValidationError("Ya existe una plantilla para este mismo caso.")

    @classmethod
    def resolver(cls, clave, sacramento=None, cantidad_ninos=None, variante=None):
        """Plantilla más específica que aplica. Prioridad: variante, sacramento, cantidad."""
        candidatas = cls.objects.filter(clave=clave).filter(
            Q(variante__isnull=True) | Q(variante=variante),
            Q(sacramento__isnull=True) | Q(sacramento=sacramento),
            Q(cantidad_ninos__isnull=True) | Q(cantidad_ninos=cantidad_ninos),
        )
        return max(
            candidatas,
            key=lambda p: (
                p.variante_id is not None,
                p.sacramento_id is not None,
                p.cantidad_ninos is not None,
            ),
            default=None,
        )


class Pedido(models.Model):
    class Estado(models.TextChoices):
        INGRESADO = "ingresado", "Ingresado"
        IMPRESO = "impreso", "Impreso"
        ENVIADO = "enviado", "Enviado"

    numero_factura = models.CharField("n.º de factura", max_length=40, db_index=True)
    numero_sapp = models.CharField("n.º de SAPP", max_length=40, db_index=True)
    fecha_entrega = models.DateField("fecha de entrega", db_index=True)
    observaciones = models.TextField("observaciones", blank=True)
    estado = models.CharField(
        "estado", max_length=10, choices=Estado.choices, default=Estado.INGRESADO
    )
    creado = models.DateTimeField("creado", auto_now_add=True)

    class Meta:
        ordering = ["fecha_entrega", "numero_factura"]
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"

    def __str__(self):
        return f"Factura {self.numero_factura} · SAPP {self.numero_sapp}"

    def save(self, *args, **kwargs):
        anterior = None
        if self.pk:
            anterior = (
                Pedido.objects.filter(pk=self.pk)
                .values_list("estado", flat=True)
                .first()
            )
        super().save(*args, **kwargs)
        if anterior != self.estado:
            self.historial.create(estado_anterior=anterior or "", estado_nuevo=self.estado)


class HistorialEstado(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name="historial",
        verbose_name="pedido",
    )
    estado_anterior = models.CharField(
        "estado anterior", max_length=10, choices=Pedido.Estado.choices, blank=True
    )
    estado_nuevo = models.CharField(
        "estado nuevo", max_length=10, choices=Pedido.Estado.choices
    )
    fecha_hora = models.DateTimeField("fecha y hora", auto_now_add=True)

    class Meta:
        ordering = ["-fecha_hora", "-pk"]
        verbose_name = "cambio de estado"
        verbose_name_plural = "historial de estados"

    def __str__(self):
        return f"{self.pedido}: {self.get_estado_nuevo_display()}"


class Nino(models.Model):
    pedido = models.ForeignKey(
        Pedido, on_delete=models.CASCADE, related_name="ninos", verbose_name="pedido"
    )
    nombre = models.CharField("nombre", max_length=120)
    genero = models.CharField(
        "género", max_length=1, choices=Genero.choices, blank=True
    )
    fecha_nacimiento = models.DateField("fecha de nacimiento", null=True, blank=True)
    padrino = models.CharField("padrino", max_length=120, blank=True)
    madrina = models.CharField("madrina", max_length=120, blank=True)
    padre = models.CharField("papá", max_length=120, blank=True)
    madre = models.CharField("mamá", max_length=120, blank=True)
    lleva_diploma = models.BooleanField("lleva diploma", default=True)
    diploma = models.ForeignKey(
        VarianteLayout,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ninos",
        limit_choices_to={"modelo__tipo": ModeloTarjeta.Tipo.DIPLOMA},
        verbose_name="diploma",
        help_text="Vacío: se elige según el sacramento y el género.",
    )

    class Meta:
        ordering = ["pedido", "nombre"]
        verbose_name = "chico"
        verbose_name_plural = "chicos"

    def __str__(self):
        return self.nombre

    def sacramentos(self):
        return Sacramento.objects.filter(
            estampasacramento__estampa__ninos=self
        ).distinct()

    def diploma_que_corresponde(self):
        """Diploma elegido a mano o, si no hay, el que mejor coincide."""
        if self.diploma_id:
            return self.diploma
        propios = set(self.sacramentos().values_list("pk", flat=True))
        if not propios:
            return None
        candidatos = (
            VarianteLayout.objects.filter(modelo__tipo=ModeloTarjeta.Tipo.DIPLOMA)
            .filter(Q(genero="") | Q(genero=self.genero))
            .select_related("modelo")
            .prefetch_related("sacramentos")
            .order_by("modelo__codigo", "nombre")
        )

        def puntaje(variante):
            suyos = {s.pk for s in variante.sacramentos.all()}
            coincidencia = 2 if suyos == propios else int(not suyos or bool(suyos & propios))
            genero_exacto = bool(variante.genero and variante.genero == self.genero)
            return coincidencia, genero_exacto

        mejor = max(candidatos, key=puntaje, default=None)
        return mejor if mejor is not None and puntaje(mejor)[0] else None


class Estampa(models.Model):
    class Articulo(models.TextChoices):
        LA = "la", "la"
        EL = "el", "el"

    pedido = models.ForeignKey(
        Pedido, on_delete=models.CASCADE, related_name="estampas", verbose_name="pedido"
    )
    variante = models.ForeignKey(
        VarianteLayout,
        on_delete=models.PROTECT,
        related_name="estampas",
        limit_choices_to={"modelo__tipo": ModeloTarjeta.Tipo.ESTAMPA},
        verbose_name="variante",
    )
    sacramentos = models.ManyToManyField(
        Sacramento,
        through="EstampaSacramento",
        related_name="estampas",
        verbose_name="sacramentos",
    )
    ninos = models.ManyToManyField(Nino, related_name="estampas", verbose_name="chicos")
    fecha_celebracion = models.DateField("fecha de celebración")
    parroquia = models.CharField("parroquia o lugar", max_length=200)
    articulo_parroquia = models.CharField(
        "artículo",
        max_length=2,
        choices=Articulo.choices,
        blank=True,
        help_text="Vacío: se deduce del lugar (el Colegio, la Parroquia).",
    )
    localidad = models.CharField("localidad", max_length=120, blank=True)
    oracion = models.ForeignKey(
        Oracion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="estampas",
        verbose_name="oración del banco",
    )
    oracion_libre = models.TextField("oración libre", blank=True)
    cantidad = models.PositiveIntegerField(
        "cantidad", default=1, validators=[MinValueValidator(1), MaxValueValidator(100000)]
    )

    class Meta:
        ordering = ["pedido", "pk"]
        verbose_name = "estampa"
        verbose_name_plural = "estampas"

    def __str__(self):
        return f"{self.variante} · {self.pedido}"

    def clean(self):
        if self.oracion_id and self.oracion_libre.strip():
            raise ValidationError(
                "Elegí una oración del banco o escribí una libre, no las dos."
            )

    def save(self, *args, **kwargs):
        if not self.articulo_parroquia:
            self.articulo_parroquia = deducir_articulo(self.parroquia)
        super().save(*args, **kwargs)

    @property
    def lleva_oracion(self):
        return bool(self.oracion_id or self.oracion_libre.strip())


class EstampaSacramento(models.Model):
    """Sacramento de una estampa. Fecha y hora solo si difieren de la general."""

    estampa = models.ForeignKey(
        Estampa, on_delete=models.CASCADE, verbose_name="estampa"
    )
    sacramento = models.ForeignKey(
        Sacramento, on_delete=models.PROTECT, verbose_name="sacramento"
    )
    fecha = models.DateField(
        "fecha",
        null=True,
        blank=True,
        help_text="Vacío: se usa la fecha de celebración de la estampa.",
    )
    hora = models.TimeField("hora", null=True, blank=True)

    class Meta:
        ordering = ["sacramento__orden"]
        constraints = [
            models.UniqueConstraint(
                fields=["estampa", "sacramento"], name="sacramento_unico_por_estampa"
            )
        ]
        verbose_name = "sacramento de la estampa"
        verbose_name_plural = "sacramentos de la estampa"

    def __str__(self):
        return f"{self.estampa} · {self.sacramento}"

    @property
    def fecha_efectiva(self):
        return self.fecha or self.estampa.fecha_celebracion


class AjusteCuadro(models.Model):
    """Cambio a mano de un cuadro en una estampa puntual. El modelo no se toca."""

    estampa = models.ForeignKey(
        Estampa, on_delete=models.CASCADE, related_name="ajustes", verbose_name="estampa"
    )
    cuadro = models.ForeignKey(
        CuadroTexto, on_delete=models.CASCADE, related_name="ajustes", verbose_name="cuadro"
    )
    texto_manual = models.TextField(
        "texto a mano",
        blank=True,
        help_text="Reemplaza al texto automático. **texto** va en negrita.",
    )
    tamano_pt = models.DecimalField(
        "tamaño (pt)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("2"))],
        help_text="Vacío: el tamaño del modelo.",
    )
    x_mm = models.DecimalField("x (mm)", max_digits=7, decimal_places=2, null=True, blank=True)
    y_mm = models.DecimalField("y (mm)", max_digits=7, decimal_places=2, null=True, blank=True)
    ancho_mm = models.DecimalField(
        "ancho (mm)", max_digits=7, decimal_places=2, null=True, blank=True
    )
    alto_mm = models.DecimalField(
        "alto (mm)", max_digits=7, decimal_places=2, null=True, blank=True
    )

    CAMPOS_POSICION = ("x_mm", "y_mm", "ancho_mm", "alto_mm")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["estampa", "cuadro"], name="ajuste_unico_por_cuadro"
            )
        ]
        verbose_name = "ajuste de cuadro"
        verbose_name_plural = "ajustes de cuadro"

    def __str__(self):
        return f"{self.estampa} · {self.cuadro.get_rol_display()}"

    def clean(self):
        if self.cuadro_id and self.estampa_id and self.cuadro.variante_id != self.estampa.variante_id:
            raise ValidationError("El cuadro no es de la variante de esta estampa.")

    @property
    def tiene_posicion(self):
        return any(getattr(self, campo) is not None for campo in self.CAMPOS_POSICION)

    def quitar_posicion(self):
        for campo in self.CAMPOS_POSICION:
            setattr(self, campo, None)

    @property
    def vacio(self):
        return not self.texto_manual.strip() and self.tamano_pt is None and not self.tiene_posicion


@receiver(m2m_changed, sender=Estampa.ninos.through)
def validar_ninos_de_estampa(sender, instance, action, reverse, pk_set, **kwargs):
    """Una estampa lleva 1 o 2 chicos, siempre del mismo pedido."""
    if action != "pre_add":
        return
    if reverse:
        pares = [(estampa, {instance.pk}) for estampa in Estampa.objects.filter(pk__in=pk_set)]
    else:
        pares = [(instance, pk_set)]
    for estampa, ninos in pares:
        if Nino.objects.filter(pk__in=ninos).exclude(pedido_id=estampa.pedido_id).exists():
            raise ValidationError(
                "Los chicos tienen que ser del mismo pedido que la estampa."
            )
        actuales = set(estampa.ninos.values_list("pk", flat=True))
        if len(actuales | set(ninos)) > MAX_NINOS_POR_ESTAMPA:
            raise ValidationError(
                f"Una estampa lleva como máximo {MAX_NINOS_POR_ESTAMPA} chicos."
            )
