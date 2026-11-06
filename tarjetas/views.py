import json
import re
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.static import serve

from . import fuentes
from .forms import EstampaForm, NinoFormSet, PedidoForm
from .models import AjusteCuadro, CuadroTexto, Estampa, Pedido
from .textos import ContextoEstampa, factor_linea, texto_de_cuadro, textos_de_estampa

ALINEACION_CSS = {
    CuadroTexto.Alineacion.IZQUIERDA: "left",
    CuadroTexto.Alineacion.CENTRO: "center",
    CuadroTexto.Alineacion.DERECHA: "right",
    CuadroTexto.Alineacion.JUSTIFICADO: "justify",
}
VERTICAL_CSS = {
    CuadroTexto.AlineacionVertical.ARRIBA: "flex-start",
    CuadroTexto.AlineacionVertical.CENTRO: "center",
    CuadroTexto.AlineacionVertical.ABAJO: "flex-end",
}


def css_fuente(nombre):
    """Nombre de fuente seguro para usar dentro de un atributo style."""
    return re.sub(r"[\"'`;{}<>\\]", "", nombre or "")


def numero(valor):
    return f"{float(valor):.2f}".rstrip("0").rstrip(".")


# ----- Pedidos -----


def inicio(request):
    pedidos = Pedido.objects.annotate(cantidad_estampas=Count("estampas")).order_by(
        "fecha_entrega", "numero_factura"
    )
    return render(request, "tarjetas/inicio.html", {"pedidos": pedidos})


def pedido_detalle(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    estampas = pedido.estampas.select_related("variante__modelo").prefetch_related(
        "ninos", "estampasacramento_set__sacramento"
    )
    ninos = list(pedido.ninos.all())
    for nino in ninos:
        nino.diploma_elegido = nino.diploma_que_corresponde() if nino.lleva_diploma else None
    return render(
        request,
        "tarjetas/pedido_detalle.html",
        {"pedido": pedido, "estampas": estampas, "ninos": ninos},
    )


def pedido_form(request, pk=None):
    pedido = get_object_or_404(Pedido, pk=pk) if pk else Pedido()
    if request.method == "POST":
        form = PedidoForm(request.POST, instance=pedido)
        chicos = NinoFormSet(request.POST, instance=pedido, prefix="ninos")
        if form.is_valid() and chicos.is_valid():
            with transaction.atomic():
                pedido = form.save()
                chicos.instance = pedido
                chicos.save()
            messages.success(request, "Pedido guardado.")
            return redirect("pedido_detalle", pk=pedido.pk)
    else:
        form = PedidoForm(instance=pedido)
        chicos = NinoFormSet(instance=pedido, prefix="ninos")
    return render(
        request, "tarjetas/pedido_form.html", {"form": form, "chicos": chicos, "pedido": pedido}
    )


# ----- Estampas -----


def estampa_form(request, pedido_pk=None, pk=None):
    if pk:
        estampa = get_object_or_404(Estampa.objects.select_related("pedido"), pk=pk)
        pedido = estampa.pedido
    else:
        pedido = get_object_or_404(Pedido, pk=pedido_pk)
        estampa = Estampa(pedido=pedido)
    if request.method == "POST":
        form = EstampaForm(request.POST, instance=estampa, pedido=pedido)
        if form.is_valid():
            with transaction.atomic():
                estampa = form.save()
            if form.variante_cambiada:
                messages.info(
                    request,
                    f"Sin oración: se usó la variante «{form.variante_cambiada}» del mismo modelo.",
                )
            messages.success(request, "Estampa guardada.")
            return redirect("vista_previa", pk=estampa.pk)
    else:
        inicial = {}
        if not pk:
            anterior = pedido.estampas.order_by("-pk").first()
            if anterior:  # Lo habitual es que se repitan en el mismo pedido.
                inicial = {
                    "fecha_celebracion": anterior.fecha_celebracion,
                    "parroquia": anterior.parroquia,
                    "localidad": anterior.localidad,
                }
        form = EstampaForm(instance=estampa, pedido=pedido, initial=inicial)
    return render(
        request,
        "tarjetas/estampa_form.html",
        {"form": form, "pedido": pedido, "estampa": estampa},
    )


@require_POST
def estampa_borrar(request, pk):
    estampa = get_object_or_404(Estampa, pk=pk)
    pedido = estampa.pedido
    estampa.delete()
    messages.success(request, "Estampa borrada.")
    return redirect("pedido_detalle", pk=pedido.pk)


# ----- Vista previa -----


def _css_cuadro(texto):
    cuadro = texto.cuadro
    partes = [
        f"left:{numero(texto.x_mm)}mm",
        f"top:{numero(texto.y_mm)}mm",
        f"width:{numero(texto.ancho_mm)}mm",
        f"height:{numero(texto.alto_mm)}mm",
        f"justify-content:{VERTICAL_CSS[cuadro.alineacion_vertical]}",
        f"text-align:{ALINEACION_CSS[cuadro.alineacion]}",
        f"--escala:{numero(texto.escala)}",
    ]
    if cuadro.rotacion == CuadroTexto.Rotacion.INVERTIDO:
        partes.append("transform:rotate(180deg)")
    return ";".join(partes)


def _css_linea(linea, texto):
    cuadro = texto.cuadro
    base = linea.tamano_pt / texto.escala if texto.escala else linea.tamano_pt
    alto = f"{numero(cuadro.interlineado * Decimal(str(factor_linea(linea.fuente))))}em"
    if cuadro.interlineado_minimo_pt:
        alto = f"max({alto}, calc(var(--escala) * {numero(cuadro.interlineado_minimo_pt)}pt))"
    partes = [
        f"font-family:'{css_fuente(linea.fuente)}'",
        f"font-size:calc(var(--escala) * {numero(base)}pt)",
        f"line-height:{alto}",
        f"color:#{linea.color}",
        f"font-weight:{'bold' if linea.negrita else 'normal'}",
        f"font-style:{'italic' if linea.cursiva else 'normal'}",
        # Como en Word: los saltos de la plantilla se respetan y las líneas largas se acomodan.
        "white-space:pre-wrap",
    ]
    if cuadro.espaciado_letras_pt:
        partes.append(f"letter-spacing:{numero(cuadro.espaciado_letras_pt)}pt")
    if cuadro.espacio_despues_pt:
        partes.append(f"margin-bottom:{numero(cuadro.espacio_despues_pt)}pt")
    return ";".join(partes)


def vista_previa(request, pk):
    estampa = get_object_or_404(
        Estampa.objects.select_related("pedido", "variante__modelo", "oracion"), pk=pk
    )
    modelo = estampa.variante.modelo
    textos = textos_de_estampa(estampa)
    for texto in textos:
        texto.css = _css_cuadro(texto)
        # Números con punto: el navegador no entiende la coma decimal.
        texto.base_txt = numero(texto.cuadro.tamano_pt)
        texto.escala_txt = numero(texto.escala)
        texto.tamano_txt = numero(texto.tamano_pt)
        texto.geometria = {
            campo: numero(getattr(texto, campo)) for campo in ("x_mm", "y_mm", "ancho_mm", "alto_mm")
        }
        texto.geometria_modelo = {
            campo: numero(getattr(texto.cuadro, campo))
            for campo in ("x_mm", "y_mm", "ancho_mm", "alto_mm")
        }
        for linea in texto.lineas:
            linea.css = _css_linea(linea, texto)

    paginas = []
    for numero_pagina, etiqueta, fondo in (
        (CuadroTexto.Pagina.ANVERSO, "Anverso", modelo.imagen_fondo),
        (CuadroTexto.Pagina.REVERSO, "Reverso", modelo.imagen_fondo_reverso),
    ):
        propios = [t for t in textos if t.cuadro.pagina == numero_pagina]
        if propios or numero_pagina == CuadroTexto.Pagina.ANVERSO:
            paginas.append(
                {
                    "etiqueta": etiqueta,
                    "fondo": fondo.url if fondo else "",
                    "textos": propios,
                }
            )

    disponibles = {c.familia.lower() for c in fuentes.catalogo(settings.FUENTES_DIR)}
    usadas = {linea.fuente for t in textos for linea in t.lineas} | {t.cuadro.fuente for t in textos}
    faltantes = sorted(f for f in usadas if f and f.lower() not in disponibles)
    avisos = list(dict.fromkeys(a for t in textos for a in t.avisos))

    return render(
        request,
        "tarjetas/vista_previa.html",
        {
            "estampa": estampa,
            "modelo": modelo,
            "paginas": paginas,
            "textos": textos,
            "ancho": numero(modelo.ancho_mm),
            "alto": numero(modelo.alto_mm),
            "fuentes_faltantes": faltantes,
            "avisos": avisos,
        },
    )


@require_POST
def ajuste_cuadro(request, pk, cuadro_pk):
    estampa = get_object_or_404(Estampa.objects.select_related("variante"), pk=pk)
    cuadro = get_object_or_404(CuadroTexto, pk=cuadro_pk, variante=estampa.variante)
    ajuste, _ = AjusteCuadro.objects.get_or_create(estampa=estampa, cuadro=cuadro)
    accion = request.POST.get("accion")

    if accion == "texto":
        texto = request.POST.get("texto", "").replace("\r\n", "\n").strip()
        automatico = texto_de_cuadro(ContextoEstampa(estampa), cuadro).texto_editable
        # Guardar el mismo texto automático no lo convierte en manual.
        ajuste.texto_manual = "" if texto == automatico.strip() else texto
        mensaje = "Texto guardado." if ajuste.texto_manual else "El cuadro usa el texto automático."
    elif accion == "texto_auto":
        ajuste.texto_manual = ""
        mensaje = "El cuadro volvió al texto automático."
    elif accion == "tamano":
        try:
            tamano = Decimal(request.POST.get("tamano", "").replace(",", "."))
        except InvalidOperation:
            tamano = None
        if tamano is None or not Decimal("2") <= tamano <= Decimal("200"):
            messages.error(request, "El tamaño tiene que ser un número entre 2 y 200.")
            return redirect(reverse("vista_previa", args=[estampa.pk]) + f"#cuadro-{cuadro.pk}")
        tamano = tamano.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        ajuste.tamano_pt = None if tamano == cuadro.tamano_pt else tamano
        mensaje = f"Tamaño guardado: {numero(tamano)} pt."
    elif accion == "tamano_auto":
        ajuste.tamano_pt = None
        mensaje = "El cuadro volvió al tamaño del modelo."
    else:
        raise Http404("Acción desconocida.")

    if ajuste.vacio:
        ajuste.delete()
    else:
        ajuste.save()
    messages.success(request, mensaje)
    return redirect(reverse("vista_previa", args=[estampa.pk]) + f"#cuadro-{cuadro.pk}")


LIMITE_MM = Decimal("2000")
CAMPOS_POSICION = ("x_mm", "y_mm", "ancho_mm", "alto_mm")


def _leer_posicion(dato):
    """Posición validada de un cuadro, en mm con dos decimales."""
    valores = {}
    for campo in CAMPOS_POSICION:
        valor = Decimal(str(dato[campo])).quantize(Decimal("0.01"))
        if not -LIMITE_MM <= valor <= LIMITE_MM:
            raise ValueError(f"{campo} fuera de rango")
        valores[campo] = valor
    if valores["ancho_mm"] < 1 or valores["alto_mm"] < 1:
        raise ValueError("El ancho y el alto tienen que ser de al menos 1 mm.")
    return valores


@require_POST
def posiciones(request, pk):
    """Guarda posiciones movidas en la vista previa: en esta estampa, en el modelo, o las borra."""
    estampa = get_object_or_404(Estampa.objects.select_related("variante"), pk=pk)
    try:
        datos = json.loads(request.body)
        accion = datos["accion"]
        pedidos = {int(c["id"]): c for c in datos["cuadros"]}
        if accion not in ("estampa", "modelo", "restablecer"):
            raise ValueError("Acción desconocida.")
        nuevas = {} if accion == "restablecer" else {i: _leer_posicion(c) for i, c in pedidos.items()}
    except (KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError) as error:
        return JsonResponse({"error": f"Datos inválidos: {error}"}, status=400)

    cuadros = {
        c.pk: c for c in CuadroTexto.objects.filter(pk__in=pedidos, variante=estampa.variante)
    }
    if len(cuadros) != len(pedidos):
        return JsonResponse({"error": "Algún cuadro no es de esta estampa."}, status=400)

    with transaction.atomic():
        for cuadro_id, cuadro in cuadros.items():
            ajuste = AjusteCuadro.objects.filter(estampa=estampa, cuadro=cuadro).first()
            if accion == "modelo":
                for campo, valor in nuevas[cuadro_id].items():
                    setattr(cuadro, campo, valor)
                cuadro.posicion_corregida = True  # importar_modelos --actualizar no lo pisa.
                cuadro.save()
                if ajuste:
                    ajuste.quitar_posicion()
            elif accion == "estampa":
                ajuste = ajuste or AjusteCuadro(estampa=estampa, cuadro=cuadro)
                for campo, valor in nuevas[cuadro_id].items():
                    # Igual que el modelo: no hace falta guardarlo como propio.
                    setattr(ajuste, campo, None if valor == getattr(cuadro, campo) else valor)
            elif ajuste:
                ajuste.quitar_posicion()
            if ajuste is None:
                continue
            if ajuste.vacio:
                if ajuste.pk:
                    ajuste.delete()
            else:
                ajuste.save()
    return JsonResponse({"ok": True, "cuadros": len(cuadros)})


# ----- Fuentes -----


def fuentes_css(request):
    reglas = []
    for cara in fuentes.catalogo(settings.FUENTES_DIR):
        peso, estilo = cara.peso_y_estilo
        ruta = cara.ruta.relative_to(settings.FUENTES_DIR).as_posix()
        url = reverse("fuente", args=[ruta])
        reglas.append(
            "@font-face{"
            f"font-family:'{css_fuente(cara.familia)}';"
            f"src:url('{url}');"
            f"font-weight:{peso};font-style:{estilo};font-display:block"
            "}"
        )
    return HttpResponse("\n".join(reglas), content_type="text/css")


def fuente(request, ruta):
    return serve(request, ruta, document_root=settings.FUENTES_DIR)
