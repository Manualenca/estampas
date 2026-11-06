import json
import re
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.views.static import serve

from . import fuentes
from .forms import CalibracionForm, EstampaForm, FiltroPedidosForm, NinoFormSet, PedidoForm
from .models import AjusteCuadro, CuadroTexto, Estampa, ModeloTarjeta, Nino, Pedido, normalizar_texto
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


DIAS_DE_AVISO = 3


def alerta_de_entrega(pedido, hoy):
    """'atrasado' o 'vence' (en los próximos días) para los pedidos que todavía no se enviaron."""
    if pedido.estado == Pedido.Estado.ENVIADO:
        return ""
    if pedido.fecha_entrega < hoy:
        return "atrasado"
    if pedido.fecha_entrega <= hoy + timedelta(days=DIAS_DE_AVISO):
        return "vence"
    return ""


def _mes_elegido(texto, hoy):
    try:
        anio, mes = (int(v) for v in (texto or "").split("-"))
        return date(anio, mes, 1)
    except ValueError:
        return hoy.replace(day=1)


def _mes_siguiente(primero):
    return (primero.replace(day=28) + timedelta(days=4)).replace(day=1)


def inicio(request):
    hoy = timezone.localdate()
    filtro = FiltroPedidosForm(request.GET or None)
    busqueda, desde, hasta = "", None, None
    if filtro.is_valid():
        busqueda = filtro.cleaned_data["q"].strip()
        desde, hasta = filtro.cleaned_data["desde"], filtro.cleaned_data["hasta"]

    pedidos = Pedido.objects.annotate(
        cantidad_estampas=Count("estampas", distinct=True),
        ultimo_cambio=Max("historial__fecha_hora"),
    ).order_by("fecha_entrega", "numero_factura")
    if desde:
        pedidos = pedidos.filter(fecha_entrega__gte=desde)
    if hasta:
        pedidos = pedidos.filter(fecha_entrega__lte=hasta)
    if busqueda:
        # Sin distinguir mayúsculas ni acentos: "maria" encuentra a "María".
        clave = normalizar_texto(busqueda)
        por_numero = Pedido.objects.filter(
            Q(numero_factura__icontains=busqueda) | Q(numero_sapp__icontains=busqueda)
        ).values_list("pk", flat=True)
        por_nombre = [
            pedido_id
            for pedido_id, nombre in Nino.objects.values_list("pedido_id", "nombre")
            if clave in normalizar_texto(nombre)
        ]
        pedidos = pedidos.filter(pk__in=set(por_numero) | set(por_nombre))

    grupos = {estado: [] for estado in Pedido.Estado}
    for pedido in pedidos:
        pedido.alerta = alerta_de_entrega(pedido, hoy)
        grupos[pedido.estado].append(pedido)
    columnas = [
        {
            "estado": estado,
            "pedidos": grupos[estado],
            "atrasados": sum(1 for p in grupos[estado] if p.alerta == "atrasado"),
            "por_vencer": sum(1 for p in grupos[estado] if p.alerta == "vence"),
        }
        for estado in Pedido.Estado
    ]

    mes = _mes_elegido(request.GET.get("mes"), hoy)
    siguiente = _mes_siguiente(mes)
    del_mes = Pedido.objects.filter(fecha_entrega__gte=mes, fecha_entrega__lt=siguiente)
    conteo = {fila["estado"]: fila["cantidad"] for fila in del_mes.values("estado").annotate(cantidad=Count("pk"))}
    contador = [(estado.label, conteo.get(estado.value, 0)) for estado in Pedido.Estado]
    anterior = (mes - timedelta(days=1)).replace(day=1)

    return render(
        request,
        "tarjetas/inicio.html",
        {
            "filtro": filtro,
            "columnas": columnas,
            "hay_filtro": bool(busqueda or desde or hasta),
            "total": sum(len(c["pedidos"]) for c in columnas),
            "mes": mes,
            "mes_anterior": anterior.strftime("%Y-%m"),
            "mes_siguiente": siguiente.strftime("%Y-%m"),
            "contador": contador,
            "total_mes": sum(c for _, c in contador),
            "dias_de_aviso": DIAS_DE_AVISO,
            "hoy": hoy,
        },
    )


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
        {
            "pedido": pedido,
            "estampas": estampas,
            "ninos": ninos,
            "historial": pedido.historial.all(),
            "alerta": alerta_de_entrega(pedido, timezone.localdate()),
            "siguiente": SIGUIENTE_ESTADO.get(pedido.estado),
        },
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
    partes.append(f"text-align:{ALINEACION_CSS[linea.alineacion]}")
    if cuadro.espaciado_letras_pt:
        partes.append(f"letter-spacing:{numero(cuadro.espaciado_letras_pt)}pt")
    if linea.espacio_antes_pt:
        partes.append(f"margin-top:{numero(linea.espacio_antes_pt)}pt")
    if linea.espacio_despues_pt:
        partes.append(f"margin-bottom:{numero(linea.espacio_despues_pt)}pt")
    if linea.sangria_izquierda_mm or linea.sangria_derecha_mm:
        partes.append(
            f"padding:0 {numero(linea.sangria_derecha_mm)}mm 0 {numero(linea.sangria_izquierda_mm)}mm"
        )
    if linea.sangria_primera_mm:
        partes.append(f"text-indent:{numero(linea.sangria_primera_mm)}mm")
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
    from .pdf import componer

    no_entran_en_pdf = [t.cuadro.get_rol_display() for t in textos if not t.vacio and componer(t).desborda]

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
            "no_entran_en_pdf": no_entran_en_pdf,
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


# ----- PDF e impresión -----

ORDENES = {"intercalado": True, "por_cara": False}


def _respuesta_pdf(resultado, nombre):
    respuesta = HttpResponse(resultado.contenido, content_type="application/pdf")
    respuesta["Content-Disposition"] = f'inline; filename="{nombre}"'
    return respuesta


def _estampas_del_pedido(pedido):
    return pedido.estampas.select_related("variante__modelo", "oracion").prefetch_related(
        "ninos", "ajustes", "estampasacramento_set__sacramento"
    ).order_by("pk")


def avisos_de_impresion(estampas):
    """Lo que no entra según las métricas reales de las fuentes, como saldrá en el PDF."""
    from .pdf import componer

    avisos = []
    for estampa in estampas:
        for texto in textos_de_estampa(estampa):
            if not texto.vacio and componer(texto).desborda:
                avisos.append((estampa, texto.cuadro.get_rol_display()))
    return avisos


def pedido_imprimir(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    estampas = list(_estampas_del_pedido(pedido))
    ninos = list(pedido.ninos.filter(lleva_diploma=True))
    for nino in ninos:
        nino.diploma_elegido = nino.diploma_que_corresponde()
    modelos = sorted({e.variante.modelo for e in estampas} | {n.diploma_elegido.modelo for n in ninos if n.diploma_elegido}, key=lambda m: m.codigo)
    for estampa in estampas:
        reverso = estampa.variante.cuadros.filter(pagina=CuadroTexto.Pagina.REVERSO).exists()
        estampa.caras = 2 if reverso else 1
    paginas = sum(e.cantidad * e.caras for e in estampas)
    return render(
        request,
        "tarjetas/pedido_imprimir.html",
        {
            "pedido": pedido,
            "estampas": estampas,
            "ninos": ninos,
            "modelos": modelos,
            "paginas": paginas,
            "avisos": avisos_de_impresion(estampas),
            "historial": pedido.historial.all(),
            "siguiente": SIGUIENTE_ESTADO.get(pedido.estado),
        },
    )


def pdf_pedido(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    from .pdf import pdf_de_estampas

    intercalado = ORDENES.get(request.GET.get("orden", "intercalado"), True)
    resultado = pdf_de_estampas(
        _estampas_del_pedido(pedido), f"Estampas · Pedido {pedido.numero_factura}", intercalado
    )
    return _respuesta_pdf(resultado, f"estampas_{pedido.numero_factura}.pdf")


def pdf_diplomas(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    from .pdf import pdf_de_diplomas

    return _respuesta_pdf(pdf_de_diplomas(pedido), f"diplomas_{pedido.numero_factura}.pdf")


def pdf_estampa(request, pk):
    estampa = get_object_or_404(Estampa.objects.select_related("pedido", "variante__modelo"), pk=pk)
    from .pdf import pdf_de_estampas

    copias = None if request.GET.get("copias") == "todas" else 1
    resultado = pdf_de_estampas([estampa], f"Estampa · {estampa.variante}", copias=copias)
    return _respuesta_pdf(resultado, f"estampa_{estampa.pk}.pdf")


SIGUIENTE_ESTADO = {
    Pedido.Estado.INGRESADO: Pedido.Estado.IMPRESO,
    Pedido.Estado.IMPRESO: Pedido.Estado.ENVIADO,
}


@require_POST
def pedido_estado(request, pk):
    """Avanza el estado un paso (Ingresado -> Impreso -> Enviado). El historial lo guarda el modelo."""
    pedido = get_object_or_404(Pedido, pk=pk)
    pedido_nuevo = request.POST.get("estado")
    if SIGUIENTE_ESTADO.get(pedido.estado) != pedido_nuevo:
        messages.error(request, "Ese cambio de estado no corresponde.")
    else:
        pedido.estado = pedido_nuevo
        pedido.save()
        messages.success(request, f"Pedido marcado como {pedido.get_estado_display().lower()}.")
    destino = request.POST.get("volver")
    if destino not in ("pedido_detalle", "pedido_imprimir"):
        destino = "pedido_imprimir"
    return redirect(destino, pk=pedido.pk)


# ----- Calibración -----


def modelos_lista(request):
    """Modelos con su estado de calibración, para ver cuáles faltan probar."""
    modelos = list(
        ModeloTarjeta.objects.annotate(cantidad_variantes=Count("variantes")).order_by("tipo", "codigo")
    )
    estados = ModeloTarjeta.EstadoCalibracion
    resumen = [
        (estado, sum(1 for m in modelos if m.estado_calibracion == estado)) for estado in estados
    ]
    elegido = request.GET.get("calibracion")
    if elegido in estados.values:
        modelos = [m for m in modelos if m.estado_calibracion == elegido]
    return render(
        request,
        "tarjetas/modelos.html",
        {"modelos": modelos, "resumen": resumen, "elegido": elegido},
    )


def calibracion(request, pk):
    modelo = get_object_or_404(ModeloTarjeta, pk=pk)
    if request.method == "POST":
        form = CalibracionForm(request.POST, instance=modelo)
        if form.is_valid():
            form.save()
            messages.success(request, "Calibración guardada. Reimprimí la hoja de prueba para comprobarla.")
            return redirect("calibracion", pk=modelo.pk)
    else:
        form = CalibracionForm(instance=modelo)
    variantes = modelo.variantes.order_by("nombre")
    tiene_reverso = CuadroTexto.objects.filter(
        variante__modelo=modelo, pagina=CuadroTexto.Pagina.REVERSO
    ).exists()
    return render(
        request,
        "tarjetas/calibracion.html",
        {"modelo": modelo, "form": form, "variantes": variantes, "tiene_reverso": tiene_reverso},
    )


def pdf_calibracion(request, pk):
    modelo = get_object_or_404(ModeloTarjeta, pk=pk)
    from .pdf import pdf_de_calibracion

    variante = modelo.variantes.filter(pk=request.GET.get("variante")).first() if request.GET.get("variante") else None
    return _respuesta_pdf(pdf_de_calibracion(modelo, variante), f"calibracion_{modelo.codigo}.pdf")
