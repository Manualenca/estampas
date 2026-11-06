from django import forms
from django.contrib import admin
from django.db.models import Count, Q

from .models import (
    MAX_NINOS_POR_ESTAMPA,
    CuadroTexto,
    Estampa,
    EstampaSacramento,
    EstiloLinea,
    HistorialEstado,
    ModeloTarjeta,
    Nino,
    Oracion,
    Pedido,
    PlantillaTexto,
    Sacramento,
    VarianteLayout,
)

admin.site.site_header = "Estampas"
admin.site.site_title = "Estampas"
admin.site.index_title = "Administración"


class SoloLecturaMixin:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CuadroTextoForm(forms.ModelForm):
    """Recuerda qué roles y posiciones se corrigieron a mano para que el importador los respete."""

    class Meta:
        model = CuadroTexto
        fields = "__all__"

    def save(self, commit=True):
        if self.instance.pk and "rol" in self.changed_data:
            self.instance.rol_corregido = True
        if self.instance.pk and set(self.changed_data) & {"x_mm", "y_mm", "ancho_mm", "alto_mm"}:
            self.instance.posicion_corregida = True
        return super().save(commit)


class EstiloLineaInline(admin.TabularInline):
    model = EstiloLinea
    extra = 0


class CuadroTextoInline(admin.TabularInline):
    model = CuadroTexto
    form = CuadroTextoForm
    extra = 0
    show_change_link = True
    fields = (
        "pagina",
        "rol",
        "sacramento",
        "x_mm",
        "y_mm",
        "ancho_mm",
        "alto_mm",
        "fuente",
        "tamano_pt",
        "color",
        "rotacion",
    )


class VarianteLayoutInline(admin.TabularInline):
    model = VarianteLayout
    extra = 0
    show_change_link = True
    fields = ("nombre", "lleva_oracion", "lleva_padrinos", "modo_titulo", "archivo_origen")


@admin.register(ModeloTarjeta)
class ModeloTarjetaAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "tipo",
        "ancho_mm",
        "alto_mm",
        "cantidad_variantes",
        "cuadros_sin_asignar",
        "offset_x",
        "offset_y",
        "offset_x_reverso",
        "offset_y_reverso",
    )
    list_filter = ("tipo",)
    search_fields = ("codigo",)
    inlines = [VarianteLayoutInline]
    fieldsets = (
        (None, {"fields": ("codigo", "tipo", "ancho_mm", "alto_mm")}),
        ("Fondos para la vista previa", {"fields": ("imagen_fondo", "imagen_fondo_reverso")}),
        (
            "Calibración de la impresora",
            {"fields": (("offset_x", "offset_y"), ("offset_x_reverso", "offset_y_reverso"))},
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                _variantes=Count("variantes", distinct=True),
                _sin_asignar=Count(
                    "variantes__cuadros",
                    filter=Q(variantes__cuadros__rol=CuadroTexto.Rol.SIN_ASIGNAR),
                    distinct=True,
                ),
            )
        )

    @admin.display(description="variantes", ordering="_variantes")
    def cantidad_variantes(self, obj):
        return obj._variantes

    @admin.display(description="cuadros sin asignar", ordering="_sin_asignar")
    def cuadros_sin_asignar(self, obj):
        return obj._sin_asignar


@admin.register(VarianteLayout)
class VarianteLayoutAdmin(admin.ModelAdmin):
    list_display = (
        "modelo",
        "nombre",
        "lleva_oracion",
        "lleva_padrinos",
        "modo_titulo",
        "genero",
        "archivo_origen",
    )
    list_filter = ("modelo__tipo", "modo_titulo", "lleva_oracion", "sacramentos", "genero")
    search_fields = ("modelo__codigo", "nombre", "archivo_origen")
    autocomplete_fields = ("modelo",)
    filter_horizontal = ("sacramentos",)
    inlines = [CuadroTextoInline]


@admin.register(CuadroTexto)
class CuadroTextoAdmin(admin.ModelAdmin):
    form = CuadroTextoForm
    list_display = (
        "variante",
        "pagina",
        "rol",
        "x_mm",
        "y_mm",
        "ancho_mm",
        "alto_mm",
        "fuente",
        "tamano_pt",
        "nota_importacion",
    )
    list_editable = ("rol",)
    list_filter = ("rol", "pagina", "rotacion", "variante__modelo__tipo", "fuente")
    search_fields = ("variante__modelo__codigo", "variante__nombre", "fuente")
    autocomplete_fields = ("variante",)
    readonly_fields = ("rol_corregido", "posicion_corregida")
    inlines = [EstiloLineaInline]

    def get_changelist_form(self, request, **kwargs):
        kwargs.setdefault("form", CuadroTextoForm)
        return super().get_changelist_form(request, **kwargs)


@admin.register(Sacramento)
class SacramentoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "posesivo_plural", "orden")
    readonly_fields = ("codigo",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Oracion)
class OracionAdmin(admin.ModelAdmin):
    list_display = ("numero", "texto", "autor", "lista_sacramentos")
    list_display_links = ("texto",)
    list_filter = ("sacramentos",)
    search_fields = ("texto", "autor")
    filter_horizontal = ("sacramentos",)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("sacramentos")

    @admin.display(description="sacramentos")
    def lista_sacramentos(self, obj):
        return ", ".join(s.nombre for s in obj.sacramentos.all())


@admin.register(PlantillaTexto)
class PlantillaTextoAdmin(admin.ModelAdmin):
    list_display = ("clave", "sacramento", "cantidad_ninos", "variante", "texto")
    list_filter = ("clave", "sacramento", "cantidad_ninos")
    search_fields = ("texto", "variante__modelo__codigo")
    autocomplete_fields = ("variante",)


class NinoInline(admin.StackedInline):
    model = Nino
    extra = 0
    show_change_link = True
    autocomplete_fields = ("diploma",)


class EstampaInline(admin.TabularInline):
    """Vista resumida. Cada estampa se edita en su propia pantalla."""

    model = Estampa
    extra = 0
    show_change_link = True
    fields = readonly_fields = ("variante", "fecha_celebracion", "parroquia", "cantidad")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class HistorialEstadoInline(SoloLecturaMixin, admin.TabularInline):
    model = HistorialEstado
    extra = 0
    fields = readonly_fields = ("fecha_hora", "estado_anterior", "estado_nuevo")


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("numero_factura", "numero_sapp", "fecha_entrega", "estado", "creado")
    list_filter = ("estado", "fecha_entrega")
    search_fields = ("numero_factura", "numero_sapp")
    date_hierarchy = "fecha_entrega"
    inlines = [NinoInline, EstampaInline, HistorialEstadoInline]


@admin.register(Nino)
class NinoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "pedido", "genero", "lleva_diploma", "diploma")
    list_filter = ("genero", "lleva_diploma")
    search_fields = ("nombre", "pedido__numero_factura", "pedido__numero_sapp")
    autocomplete_fields = ("pedido", "diploma")


class EstampaForm(forms.ModelForm):
    class Meta:
        model = Estampa
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        pedido_id = self.instance.pedido_id or self.initial.get("pedido")
        if pedido_id and "ninos" in self.fields:
            self.fields["ninos"].queryset = Nino.objects.filter(pedido_id=pedido_id)

    def clean(self):
        datos = super().clean()
        ninos = datos.get("ninos")
        pedido = datos.get("pedido")
        if ninos is not None:
            if len(ninos) > MAX_NINOS_POR_ESTAMPA:
                self.add_error(
                    "ninos", f"Una estampa lleva como máximo {MAX_NINOS_POR_ESTAMPA} chicos."
                )
            if pedido and any(n.pedido_id != pedido.pk for n in ninos):
                self.add_error("ninos", "Los chicos tienen que ser del mismo pedido.")
        return datos


class EstampaSacramentoInline(admin.TabularInline):
    model = EstampaSacramento
    extra = 0
    min_num = 1
    validate_min = True


@admin.register(Estampa)
class EstampaAdmin(admin.ModelAdmin):
    form = EstampaForm
    list_display = ("variante", "pedido", "fecha_celebracion", "parroquia", "cantidad")
    list_filter = ("pedido__estado", "sacramentos")
    search_fields = (
        "pedido__numero_factura",
        "pedido__numero_sapp",
        "variante__modelo__codigo",
        "ninos__nombre",
    )
    autocomplete_fields = ("pedido", "variante", "oracion")
    filter_horizontal = ("ninos",)
    inlines = [EstampaSacramentoInline]
