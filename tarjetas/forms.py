from django import forms
from django.db.models import Q

from .models import (
    MAX_NINOS_POR_ESTAMPA,
    Estampa,
    EstampaSacramento,
    ModeloTarjeta,
    Nino,
    Oracion,
    Pedido,
    Sacramento,
    VarianteLayout,
)

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
HORA = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class PedidoForm(forms.ModelForm):
    class Meta:
        model = Pedido
        fields = ["numero_factura", "numero_sapp", "fecha_entrega", "observaciones"]
        widgets = {"fecha_entrega": FECHA, "observaciones": forms.Textarea(attrs={"rows": 3})}


class CalibracionForm(forms.ModelForm):
    class Meta:
        model = ModeloTarjeta
        fields = ["offset_x", "offset_y", "offset_x_reverso", "offset_y_reverso"]
        labels = {
            "offset_x": "Anverso: corrimiento X (mm)",
            "offset_y": "Anverso: corrimiento Y (mm)",
            "offset_x_reverso": "Reverso: corrimiento X (mm)",
            "offset_y_reverso": "Reverso: corrimiento Y (mm)",
        }
        widgets = {campo: forms.NumberInput(attrs={"step": "0.1"}) for campo in fields}


class DiplomaChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, variante):
        return variante.modelo.codigo


class NinoForm(forms.ModelForm):
    diploma = DiplomaChoiceField(
        queryset=VarianteLayout.objects.filter(modelo__tipo=ModeloTarjeta.Tipo.DIPLOMA)
        .select_related("modelo")
        .order_by("modelo__codigo"),
        required=False,
        empty_label="Automático",
    )

    class Meta:
        model = Nino
        fields = [
            "nombre",
            "genero",
            "fecha_nacimiento",
            "padrino",
            "madrina",
            "padre",
            "madre",
            "lleva_diploma",
            "diploma",
        ]
        widgets = {"fecha_nacimiento": FECHA}


NinoFormSet = forms.inlineformset_factory(
    Pedido, Nino, form=NinoForm, extra=1, can_delete=True
)


class VarianteChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, variante):
        partes = [variante.modelo.codigo]
        if variante.nombre != "base":
            partes.append(variante.nombre)
        etiqueta = " · ".join(partes)
        if not variante.lleva_oracion:
            etiqueta += " (sin oración)"
        return etiqueta


class OracionSelect(forms.Select):
    """Cada opción lleva sus sacramentos, para filtrarlas en el navegador."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(name, value, label, selected, index, subindex, attrs)
        oracion = getattr(value, "instance", None)
        if oracion is not None:
            codigos = " ".join(s.codigo for s in oracion.sacramentos.all())
            opcion["attrs"]["data-sacramentos"] = codigos
        return opcion


class OracionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, oracion):
        texto = oracion.texto if len(oracion.texto) <= 110 else oracion.texto[:107] + "…"
        return f"{oracion.numero}. {texto}" if oracion.numero else texto


class EstampaForm(forms.ModelForm):
    MODOS = [
        ("banco", "Del banco"),
        ("libre", "Escrita a mano"),
        ("ninguna", "Sin oración"),
    ]

    variante = VarianteChoiceField(
        queryset=VarianteLayout.objects.filter(modelo__tipo=ModeloTarjeta.Tipo.ESTAMPA)
        .select_related("modelo")
        .order_by("modelo__codigo", "nombre"),
        label="Modelo",
    )
    sacramentos = forms.ModelMultipleChoiceField(
        queryset=Sacramento.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        label="Sacramentos",
    )
    modo_oracion = forms.ChoiceField(
        choices=MODOS, widget=forms.RadioSelect, initial="banco", label="Oración"
    )
    oracion = OracionChoiceField(
        queryset=Oracion.objects.prefetch_related("sacramentos").order_by("numero", "texto"),
        widget=OracionSelect,
        required=False,
        label="Oración del banco",
    )

    class Meta:
        model = Estampa
        fields = [
            "variante",
            "ninos",
            "fecha_celebracion",
            "parroquia",
            "articulo_parroquia",
            "localidad",
            "oracion",
            "oracion_libre",
            "cantidad",
        ]
        widgets = {
            "ninos": forms.CheckboxSelectMultiple,
            "fecha_celebracion": FECHA,
            "oracion_libre": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"ninos": "Chicos"}

    def __init__(self, *args, pedido, **kwargs):
        super().__init__(*args, **kwargs)
        self.pedido = pedido
        self.variante_cambiada = None
        self.fields["ninos"].queryset = pedido.ninos.all()
        self.sacramentos_por_codigo = {s.codigo: s for s in Sacramento.objects.all()}
        for codigo, sacramento in self.sacramentos_por_codigo.items():
            self.fields[f"fecha_{codigo}"] = forms.DateField(
                required=False, widget=FECHA, label=f"Fecha de {sacramento.nombre}"
            )
            self.fields[f"hora_{codigo}"] = forms.TimeField(
                required=False, widget=HORA, label=f"Hora de {sacramento.nombre}"
            )
        if self.instance.pk:
            relaciones = self.instance.estampasacramento_set.select_related("sacramento")
            self.initial["sacramentos"] = [r.sacramento_id for r in relaciones]
            for relacion in relaciones:
                self.initial[f"fecha_{relacion.sacramento.codigo}"] = relacion.fecha
                self.initial[f"hora_{relacion.sacramento.codigo}"] = relacion.hora
            if self.instance.oracion_id:
                self.initial["modo_oracion"] = "banco"
            elif self.instance.oracion_libre.strip():
                self.initial["modo_oracion"] = "libre"
            else:
                self.initial["modo_oracion"] = "ninguna"

    def campos_de_sacramento(self):
        """(sacramento, elegido, campo fecha, campo hora) para la plantilla."""
        elegidos = {str(v) for v in (self["sacramentos"].value() or [])}
        return [
            (s, str(s.pk) in elegidos, self[f"fecha_{codigo}"], self[f"hora_{codigo}"])
            for codigo, s in self.sacramentos_por_codigo.items()
        ]

    def clean(self):
        datos = super().clean()
        ninos = datos.get("ninos")
        if ninos is not None:
            if not ninos:
                self.add_error("ninos", "Elegí al menos un chico.")
            elif len(ninos) > MAX_NINOS_POR_ESTAMPA:
                self.add_error("ninos", f"Una estampa lleva como máximo {MAX_NINOS_POR_ESTAMPA} chicos.")

        modo = datos.get("modo_oracion")
        if modo == "banco":
            datos["oracion_libre"] = ""
            if not datos.get("oracion"):
                self.add_error("oracion", "Elegí una oración del banco.")
        elif modo == "libre":
            datos["oracion"] = None
            if not (datos.get("oracion_libre") or "").strip():
                self.add_error("oracion_libre", "Escribí la oración.")
        else:
            datos["oracion"] = None
            datos["oracion_libre"] = ""
        self.instance.oracion = datos.get("oracion")
        self.instance.oracion_libre = datos.get("oracion_libre", "")

        variante = datos.get("variante")
        elegidos = set(datos.get("sacramentos") or [])
        if variante and elegidos:
            propios = set(variante.sacramentos.all())
            if propios and not propios & elegidos:
                nombres = ", ".join(s.nombre for s in propios)
                self.add_error("variante", f"Este modelo es para {nombres}.")
        return datos

    def _variante_sin_oracion(self, variante, elegidos):
        """Variante sin oración del mismo modelo, si existe y sirve para el sacramento."""
        candidatas = (
            variante.modelo.variantes.filter(lleva_oracion=False)
            .filter(Q(sacramentos__isnull=True) | Q(sacramentos__in=elegidos))
            .distinct()
            .order_by("nombre")
        )
        return candidatas.first()

    def save(self, commit=True):
        estampa = super().save(commit=False)
        estampa.pedido = self.pedido
        elegidos = list(self.cleaned_data["sacramentos"])
        if not estampa.lleva_oracion and estampa.variante.lleva_oracion:
            alternativa = self._variante_sin_oracion(estampa.variante, elegidos)
            if alternativa:
                estampa.variante = alternativa
                self.variante_cambiada = alternativa
        cambio_de_variante = "variante" in self.changed_data or self.variante_cambiada
        estampa.save()
        if cambio_de_variante:
            estampa.ajustes.exclude(cuadro__variante=estampa.variante).delete()
        self.save_m2m()
        self._guardar_sacramentos(estampa, elegidos)
        return estampa

    def _guardar_sacramentos(self, estampa, elegidos):
        estampa.estampasacramento_set.exclude(sacramento__in=elegidos).delete()
        for sacramento in elegidos:
            EstampaSacramento.objects.update_or_create(
                estampa=estampa,
                sacramento=sacramento,
                defaults={
                    "fecha": self.cleaned_data.get(f"fecha_{sacramento.codigo}"),
                    "hora": self.cleaned_data.get(f"hora_{sacramento.codigo}"),
                },
            )
