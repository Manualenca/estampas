import shutil
import struct
import tempfile
from datetime import date, time
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import fuentes
from .models import (
    AjusteCuadro,
    CuadroTexto,
    Estampa,
    EstampaSacramento,
    EstiloLinea,
    Genero,
    ModeloTarjeta,
    Nino,
    Oracion,
    Pedido,
    PlantillaTexto,
    Sacramento,
    VarianteLayout,
)
from .textos import completar, formatear_fecha, separar_negrita, textos_de_estampa

Rol = CuadroTexto.Rol


def sacramento(codigo):
    return Sacramento.objects.get(codigo=codigo)


class Base(TestCase):
    """Una estampa con un cuadro por rol, lista para completar."""

    def setUp(self):
        self.pedido = Pedido.objects.create(
            numero_factura="F1", numero_sapp="S1", fecha_entrega=date(2026, 12, 1)
        )
        modelo = ModeloTarjeta.objects.create(
            codigo="2059", tipo=ModeloTarjeta.Tipo.ESTAMPA, ancho_mm=75, alto_mm=125
        )
        self.variante = VarianteLayout.objects.create(modelo=modelo, nombre="base")
        self.cuadros = {}
        for indice, rol in enumerate(
            [Rol.TITULO, Rol.NOMBRE, Rol.ORACION, Rol.CELEBRACION, Rol.SIN_ASIGNAR]
        ):
            self.cuadros[rol] = CuadroTexto.objects.create(
                variante=self.variante, indice_origen=indice, rol=rol, x_mm=5,
                y_mm=10 + 20 * indice, ancho_mm=60, alto_mm=15, fuente="Abadi", tamano_pt=10,
                color="806000",
            )
        self.ana = Nino.objects.create(pedido=self.pedido, nombre="Ana Pérez", genero=Genero.MUJER)
        self.estampa = Estampa.objects.create(
            pedido=self.pedido, variante=self.variante, fecha_celebracion=date(2026, 11, 14),
            parroquia="Parroquia San Pablo", localidad="Chicoana – Salta",
        )
        self.estampa.ninos.add(self.ana)

    def con(self, *codigos, **fechas):
        for codigo in codigos:
            EstampaSacramento.objects.create(
                estampa=self.estampa, sacramento=sacramento(codigo), **fechas.get(codigo, {})
            )
        return self

    def texto(self, rol):
        textos = {t.cuadro.rol: t for t in textos_de_estampa(self.estampa)}
        return [linea.texto for linea in textos[rol].lineas]


class TextosTests(Base):
    def test_titulo_con_mi_mayuscula(self):
        self.con("comunion")
        self.assertEqual(self.texto(Rol.TITULO), ["Recuerdo de Mi Primera Comunión"])

    def test_titulo_con_varios_sacramentos_y_plural(self):
        self.con("bautismo", "comunion", "confirmacion")
        self.assertEqual(
            self.texto(Rol.TITULO), ["Recuerdo de Mi Bautismo, Primera Comunión y Confirmación"]
        )
        self.estampa.ninos.add(Nino.objects.create(pedido=self.pedido, nombre="Luis"))
        self.assertEqual(
            self.texto(Rol.TITULO),
            ["Recuerdo de Nuestro Bautismo, Primera Comunión y Confirmación"],
        )

    def test_titulo_sin_recuerdo_y_sin_titulo(self):
        self.con("confirmacion")
        self.variante.modo_titulo = VarianteLayout.ModoTitulo.SIN_RECUERDO
        self.variante.save()
        self.assertEqual(self.texto(Rol.TITULO), ["Mi Confirmación"])
        self.variante.modo_titulo = VarianteLayout.ModoTitulo.SIN_TITULO
        self.variante.save()
        self.assertEqual(self.texto(Rol.TITULO), [])

    def test_nombres_unidos_con_y(self):
        self.con("comunion")
        self.estampa.ninos.add(Nino.objects.create(pedido=self.pedido, nombre="Luis Gómez"))
        self.assertEqual(self.texto(Rol.NOMBRE), ["Ana Pérez y Luis Gómez"])

    def test_celebracion_de_comunion_singular_y_plural(self):
        self.con("comunion")
        self.assertEqual(
            self.texto(Rol.CELEBRACION),
            [
                "Recibí la Santa Eucaristía el 14 de noviembre de 2026 en la Parroquia San Pablo.",
                "Chicoana – Salta",
            ],
        )
        self.estampa.ninos.add(Nino.objects.create(pedido=self.pedido, nombre="Luis"))
        self.assertTrue(self.texto(Rol.CELEBRACION)[0].startswith("Recibimos la Santa Eucaristía"))

    def test_articulo_del_lugar(self):
        self.con("comunion")
        self.estampa.parroquia = "Colegio José Manuel Estrada"
        self.estampa.articulo_parroquia = ""
        self.estampa.save()
        self.assertIn("en el Colegio José Manuel Estrada.", self.texto(Rol.CELEBRACION)[0])

    def celebracion_de_confirmacion(self, padrino="", madrina=""):
        self.ana.padrino, self.ana.madrina = padrino, madrina
        self.ana.save()
        return self.texto(Rol.CELEBRACION)

    def test_confirmacion_lineas_de_padrinos(self):
        self.con("confirmacion")
        resto = ["14 de noviembre de 2026", "Parroquia San Pablo", "Chicoana – Salta"]
        self.assertEqual(self.celebracion_de_confirmacion(madrina="Eva"), ["Mi Madrina: Eva", *resto])
        self.assertEqual(self.celebracion_de_confirmacion(padrino="Juan"), ["Mi Padrino: Juan", *resto])
        self.assertEqual(
            self.celebracion_de_confirmacion("Juan", "Eva"), ["Mis Padrinos: Juan", "Eva", *resto]
        )
        self.assertEqual(self.celebracion_de_confirmacion(), resto)

    def test_modelo_sin_linea_de_padrinos(self):
        self.con("confirmacion")
        self.variante.lleva_padrinos = False
        self.variante.save()
        self.assertEqual(
            self.celebracion_de_confirmacion("Juan", "Eva"),
            ["14 de noviembre de 2026", "Parroquia San Pablo", "Chicoana – Salta"],
        )

    def test_bautismo_con_padres_y_nacimiento(self):
        self.con("bautismo")
        self.ana.fecha_nacimiento = date(2025, 1, 21)
        self.ana.madre, self.ana.padre = "Romina", "Oscar"
        self.ana.madrina, self.ana.padrino = "Brenda", "Rodrigo"
        self.ana.save()
        self.assertEqual(
            self.texto(Rol.CELEBRACION),
            [
                "Nací el 21 de enero de 2025",
                "Mis Papis: Romina y Oscar",
                "Mis Padrinos: Brenda y Rodrigo",
                "14 de noviembre de 2026",
                "Parroquia San Pablo",
                "Chicoana – Salta",
            ],
        )

    def test_solo_mama_y_frase_editable(self):
        self.con("bautismo")
        self.ana.madre = "Sol"
        self.ana.save()
        self.assertIn("Mi Mamá: Sol", self.texto(Rol.CELEBRACION))
        plantilla = PlantillaTexto.resolver(PlantillaTexto.Clave.PADRES_SOLO_MADRE)
        plantilla.texto = "Mamá: {madre}"
        plantilla.save()
        self.assertIn("Mamá: Sol", self.texto(Rol.CELEBRACION))

    def test_fecha_y_hora_propias_del_sacramento(self):
        self.con("confirmacion", confirmacion={"fecha": date(2026, 8, 2), "hora": time(9, 0)})
        cuadro = self.cuadros[Rol.CELEBRACION]
        cuadro.sacramento = sacramento("confirmacion")
        cuadro.save()
        PlantillaTexto.objects.create(
            clave=PlantillaTexto.Clave.CELEBRACION, variante=self.variante,
            sacramento=sacramento("confirmacion"), texto="el {fecha} a las {hora} hs.",
        )
        self.assertEqual(self.texto(Rol.CELEBRACION), ["el 02 de agosto de 2026 a las 9:00 hs."])

    def test_oracion_con_autor_sin_oracion_y_libre(self):
        self.con("comunion")
        self.estampa.oracion = Oracion.objects.create(texto="Señor, haz de mí.", autor="San Francisco")
        self.estampa.save()
        self.assertEqual(self.texto(Rol.ORACION), ["Señor, haz de mí.", "San Francisco"])
        self.estampa.oracion = None
        self.estampa.oracion_libre = "Jesús, guíame."
        self.estampa.save()
        self.assertEqual(self.texto(Rol.ORACION), ["Jesús, guíame."])
        self.estampa.oracion_libre = ""
        self.estampa.save()
        self.assertEqual(self.texto(Rol.ORACION), [])

    def test_sin_asignar_solo_se_imprime_con_texto_a_mano(self):
        self.con("comunion")
        self.assertEqual(self.texto(Rol.SIN_ASIGNAR), [])
        AjusteCuadro.objects.create(
            estampa=self.estampa, cuadro=self.cuadros[Rol.SIN_ASIGNAR], texto_manual="Renzo\nSalta"
        )
        self.assertEqual(self.texto(Rol.SIN_ASIGNAR), ["Renzo", "Salta"])

    def test_texto_a_mano_reemplaza_al_automatico(self):
        self.con("comunion")
        AjusteCuadro.objects.create(
            estampa=self.estampa, cuadro=self.cuadros[Rol.NOMBRE], texto_manual="Anita"
        )
        texto = next(t for t in textos_de_estampa(self.estampa) if t.cuadro.rol == Rol.NOMBRE)
        self.assertTrue(texto.manual)
        self.assertEqual([l.texto for l in texto.lineas], ["Anita"])

    def test_tamano_ajustado_escala_todas_las_lineas(self):
        self.con("bautismo")
        cuadro = self.cuadros[Rol.CELEBRACION]
        EstiloLinea.objects.create(cuadro=cuadro, elemento=EstiloLinea.Elemento.FECHA, tamano_pt=12)
        AjusteCuadro.objects.create(estampa=self.estampa, cuadro=cuadro, tamano_pt=Decimal("8"))
        texto = next(t for t in textos_de_estampa(self.estampa) if t.cuadro.rol == Rol.CELEBRACION)
        self.assertEqual(texto.escala, Decimal("0.8"))
        tamanos = {l.elemento: l.tamano_pt for l in texto.lineas}
        self.assertEqual(tamanos[EstiloLinea.Elemento.FECHA], Decimal("9.6"))
        self.assertEqual(tamanos[EstiloLinea.Elemento.LUGAR], Decimal("8"))

    def test_estilo_de_una_parte_y_color_por_genero(self):
        self.con("confirmacion")
        cuadro = self.cuadros[Rol.CELEBRACION]
        cuadro.color_mujer = "C00070"
        cuadro.save()
        EstiloLinea.objects.create(cuadro=cuadro, elemento=EstiloLinea.Elemento.PADRINOS, negrita=True)
        self.ana.madrina = "Eva"
        self.ana.save()
        texto = next(t for t in textos_de_estampa(self.estampa) if t.cuadro.rol == Rol.CELEBRACION)
        padrinos, fecha = texto.lineas[0], texto.lineas[1]
        self.assertTrue(padrinos.negrita)
        self.assertFalse(fecha.negrita)
        self.assertEqual(fecha.color, "C00070")

    def test_avisa_si_los_chicos_tienen_padrinos_distintos(self):
        self.con("confirmacion")
        self.ana.madrina = "Eva"
        self.ana.save()
        self.estampa.ninos.add(Nino.objects.create(pedido=self.pedido, nombre="Luis", madrina="Sol"))
        texto = next(t for t in textos_de_estampa(self.estampa) if t.cuadro.rol == Rol.CELEBRACION)
        self.assertTrue(any("distintos" in a for a in texto.avisos))


class FuncionesTests(SimpleTestCase):
    def test_fecha_con_dia_de_dos_digitos(self):
        self.assertEqual(formatear_fecha(date(2026, 6, 7)), "07 de junio de 2026")

    def test_renglon_con_variables_vacias_se_omite(self):
        renglones = completar("{linea_padrinos}\n{fecha}\nFijo", {"fecha": "hoy", "linea_padrinos": ""})
        self.assertEqual([t for t, _ in renglones], ["hoy", "Fijo"])

    def test_marca_de_negrita(self):
        segmentos = separar_negrita("**Mi Madrina:** Eva")
        self.assertEqual([(s.texto, s.negrita) for s in segmentos], [("Mi Madrina:", True), (" Eva", False)])


class PantallasTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser("prueba", password="x"))

    def test_sin_usuario_pide_entrar(self):
        self.client.logout()
        respuesta = self.client.get(reverse("inicio"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("admin:login"), respuesta["Location"])

    def test_pantallas_abren(self):
        self.con("comunion")
        for url in (
            reverse("inicio"),
            reverse("pedido_nuevo"),
            reverse("pedido_detalle", args=[self.pedido.pk]),
            reverse("pedido_editar", args=[self.pedido.pk]),
            reverse("estampa_nueva", args=[self.pedido.pk]),
            reverse("estampa_editar", args=[self.estampa.pk]),
            reverse("vista_previa", args=[self.estampa.pk]),
            reverse("fuentes_css"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_crear_pedido_con_chicos(self):
        respuesta = self.client.post(
            reverse("pedido_nuevo"),
            {
                "numero_factura": "F9", "numero_sapp": "S9", "fecha_entrega": "2026-12-10",
                "observaciones": "",
                "ninos-TOTAL_FORMS": 2, "ninos-INITIAL_FORMS": 0,
                "ninos-0-nombre": "Juan", "ninos-0-genero": "M", "ninos-0-lleva_diploma": "on",
                "ninos-1-nombre": "", "ninos-1-lleva_diploma": "on",
            },
        )
        pedido = Pedido.objects.get(numero_factura="F9")
        self.assertRedirects(respuesta, reverse("pedido_detalle", args=[pedido.pk]))
        self.assertEqual(list(pedido.ninos.values_list("nombre", flat=True)), ["Juan"])

    def datos_estampa(self, **extra):
        datos = {
            "variante": self.variante.pk, "ninos": [self.ana.pk], "cantidad": 10,
            "sacramentos": [sacramento("comunion").pk], "fecha_celebracion": "2026-11-14",
            "parroquia": "Parroquia San Pablo", "articulo_parroquia": "", "localidad": "Salta",
            "modo_oracion": "ninguna",
        }
        datos.update(extra)
        return datos

    def test_crear_estampa_y_ver_la_vista_previa(self):
        respuesta = self.client.post(reverse("estampa_nueva", args=[self.pedido.pk]), self.datos_estampa())
        estampa = Estampa.objects.exclude(pk=self.estampa.pk).get()
        self.assertRedirects(respuesta, reverse("vista_previa", args=[estampa.pk]))
        pagina = self.client.get(reverse("vista_previa", args=[estampa.pk]))
        self.assertContains(pagina, "Recuerdo de Mi Primera Comunión")
        self.assertContains(pagina, "Ana Pérez")

    def test_validaciones_de_la_estampa(self):
        otro = [Nino.objects.create(pedido=self.pedido, nombre=n).pk for n in ("B", "C")]
        respuesta = self.client.post(
            reverse("estampa_nueva", args=[self.pedido.pk]),
            self.datos_estampa(ninos=[self.ana.pk, *otro], sacramentos=[], modo_oracion="banco"),
        )
        self.assertContains(respuesta, "como máximo 2 chicos")
        self.assertContains(respuesta, "Elegí una oración del banco")
        self.assertEqual(Estampa.objects.count(), 1)

    def test_sin_oracion_usa_la_variante_sin_oracion(self):
        sin = VarianteLayout.objects.create(
            modelo=self.variante.modelo, nombre="Sin oración", lleva_oracion=False
        )
        self.client.post(reverse("estampa_nueva", args=[self.pedido.pk]), self.datos_estampa())
        self.assertEqual(Estampa.objects.exclude(pk=self.estampa.pk).get().variante, sin)

    def test_modelo_de_otro_sacramento_no_se_acepta(self):
        self.variante.sacramentos.add(sacramento("bautismo"))
        respuesta = self.client.post(reverse("estampa_nueva", args=[self.pedido.pk]), self.datos_estampa())
        self.assertContains(respuesta, "Este modelo es para Bautismo")

    def ajustar(self, cuadro, **datos):
        return self.client.post(reverse("ajuste_cuadro", args=[self.estampa.pk, cuadro.pk]), datos)

    def test_editar_a_mano_y_volver_al_automatico(self):
        self.con("comunion")
        nombre = self.cuadros[Rol.NOMBRE]
        self.ajustar(nombre, accion="texto", texto="Anita")
        self.assertEqual(AjusteCuadro.objects.get().texto_manual, "Anita")
        self.assertContains(self.client.get(reverse("vista_previa", args=[self.estampa.pk])), "Anita")
        self.ajustar(nombre, accion="texto_auto")
        self.assertFalse(AjusteCuadro.objects.exists())

    def test_guardar_el_texto_automatico_no_lo_vuelve_manual(self):
        self.con("comunion")
        self.ajustar(self.cuadros[Rol.NOMBRE], accion="texto", texto="Ana Pérez")
        self.assertFalse(AjusteCuadro.objects.exists())

    def test_tamano_solo_para_esta_estampa(self):
        self.con("comunion")
        nombre = self.cuadros[Rol.NOMBRE]
        self.ajustar(nombre, accion="tamano", tamano="8,5")
        self.assertEqual(AjusteCuadro.objects.get().tamano_pt, Decimal("8.5"))
        nombre.refresh_from_db()
        self.assertEqual(nombre.tamano_pt, Decimal("10"))
        self.ajustar(nombre, accion="tamano", tamano="1")
        self.assertEqual(AjusteCuadro.objects.get().tamano_pt, Decimal("8.5"))
        self.ajustar(nombre, accion="tamano_auto")
        self.assertFalse(AjusteCuadro.objects.exists())

    def test_no_se_ajusta_un_cuadro_de_otra_variante(self):
        ajeno = VarianteLayout.objects.create(modelo=self.variante.modelo, nombre="otra")
        cuadro = CuadroTexto.objects.create(
            variante=ajeno, x_mm=0, y_mm=0, ancho_mm=1, alto_mm=1, fuente="A", tamano_pt=1
        )
        self.assertEqual(self.ajustar(cuadro, accion="texto", texto="x").status_code, 404)

    def test_contorno_y_aviso_de_desborde_en_la_pagina(self):
        self.con("comunion")
        pagina = self.client.get(reverse("vista_previa", args=[self.estampa.pk]))
        self.assertContains(pagina, 'id="contorno"')
        self.assertContains(pagina, "data-achicar")
        self.assertContains(pagina, 'data-rol="Nombre"')


def fuente_minima(familia, estilo):
    """Archivo TTF con solo la tabla "name", suficiente para leer familia y estilo."""
    registros, cadenas = [], b""
    for identificador, texto in ((1, familia), (2, estilo)):
        crudo = texto.encode("utf-16-be")
        registros.append(struct.pack(">HHHHHH", 3, 1, 0x409, identificador, len(crudo), len(cadenas)))
        cadenas += crudo
    tabla = struct.pack(">HHH", 0, len(registros), 6 + 12 * len(registros)) + b"".join(registros) + cadenas
    cabecera = struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
    registro = struct.pack(">4sIII", b"name", 0, 12 + 16, len(tabla))
    return cabecera + registro + tabla


class FuentesTests(SimpleTestCase):
    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.carpeta, ignore_errors=True)
        self.origen = self.carpeta / "nube" / "Abadi"
        self.origen.mkdir(parents=True)
        (self.origen / "184992.ttf").write_bytes(fuente_minima("Abadi", "Italic"))
        (self.origen / "236434.ttf").write_bytes(fuente_minima("Abadi", "Regular"))
        (self.origen / "otra.ttf").write_bytes(fuente_minima("Otra", "Regular"))

    def test_lee_familia_y_estilo(self):
        self.assertEqual(fuentes.leer_nombres(self.origen / "184992.ttf"), ("Abadi", "Italic"))

    def test_copia_con_nombre_estable_y_lista_faltantes(self):
        destino = self.carpeta / "fuentes"
        copiadas, faltantes = fuentes.copiar(["Abadi", "Bierstadt"], destino, [self.carpeta / "nube"])
        nombres = sorted(c.ruta.name for c in copiadas)
        self.assertEqual(nombres, ["Abadi - Italic.ttf", "Abadi - Regular.ttf"])
        self.assertEqual(faltantes, ["Bierstadt"])
        caras = {c.estilo: c.peso_y_estilo for c in fuentes.catalogo(destino)}
        self.assertEqual(caras, {"Italic": (400, "italic"), "Regular": (400, "normal")})

    def test_copiar_dos_veces_no_duplica(self):
        destino = self.carpeta / "fuentes"
        fuentes.copiar(["Abadi"], destino, [self.carpeta / "nube"])
        fuentes.copiar(["Abadi"], destino, [self.carpeta / "nube"])
        self.assertEqual(len(list((destino / "Abadi").iterdir())), 2)


class FuentesVistaTests(TestCase):
    def test_hoja_de_estilos_y_archivo(self):
        carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, carpeta, ignore_errors=True)
        (carpeta / "Abadi").mkdir()
        (carpeta / "Abadi" / "Abadi - Italic.ttf").write_bytes(fuente_minima("Abadi", "Italic"))
        self.client.force_login(get_user_model().objects.create_superuser("p", password="x"))
        with override_settings(FUENTES_DIR=carpeta):
            css = self.client.get(reverse("fuentes_css")).content.decode()
            self.assertIn("font-family:'Abadi'", css)
            self.assertIn("font-style:italic", css)
            archivo = self.client.get(reverse("fuente", args=["Abadi/Abadi - Italic.ttf"]))
            self.assertEqual(archivo.status_code, 200)
            fuera = self.client.get(reverse("fuente", args=["../.env"]))
            self.assertIn(fuera.status_code, (400, 404))


class PosicionesTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser("prueba", password="x"))
        self.con("comunion")
        self.nombre = self.cuadros[Rol.NOMBRE]

    def enviar(self, accion, *cuadros, **valores):
        import json

        datos = {"accion": accion, "cuadros": []}
        for cuadro in cuadros:
            posicion = {"x_mm": 7, "y_mm": 31.5, "ancho_mm": 60, "alto_mm": 15}
            posicion.update(valores)
            datos["cuadros"].append({"id": cuadro.pk, **posicion})
        return self.client.post(
            reverse("posiciones", args=[self.estampa.pk]), json.dumps(datos), content_type="application/json"
        )

    def geometria(self):
        texto = next(t for t in textos_de_estampa(self.estampa) if t.cuadro.pk == self.nombre.pk)
        return texto.x_mm, texto.y_mm, texto.ancho_mm, texto.alto_mm, texto.posicion_ajustada

    def test_guardar_solo_en_esta_estampa(self):
        self.assertEqual(self.enviar("estampa", self.nombre).status_code, 200)
        self.assertEqual(self.geometria(), (Decimal("7"), Decimal("31.5"), Decimal("60"), Decimal("15"), True))
        ajuste = AjusteCuadro.objects.get()
        self.assertIsNone(ajuste.ancho_mm)  # Igual que el modelo: no se guarda como propio.
        self.nombre.refresh_from_db()
        self.assertEqual(self.nombre.x_mm, Decimal("5"))
        self.assertFalse(self.nombre.posicion_corregida)

    def test_volver_a_la_posicion_del_modelo(self):
        self.enviar("estampa", self.nombre)
        self.enviar("restablecer", self.nombre)
        self.assertFalse(AjusteCuadro.objects.exists())
        self.assertEqual(self.geometria()[:2], (Decimal("5"), Decimal("30")))

    def test_restablecer_conserva_el_texto_a_mano(self):
        AjusteCuadro.objects.create(estampa=self.estampa, cuadro=self.nombre, texto_manual="Anita")
        self.enviar("estampa", self.nombre)
        self.enviar("restablecer", self.nombre)
        ajuste = AjusteCuadro.objects.get()
        self.assertEqual(ajuste.texto_manual, "Anita")
        self.assertFalse(ajuste.tiene_posicion)

    def test_guardar_en_el_modelo(self):
        self.enviar("estampa", self.nombre, x_mm=9)
        self.enviar("modelo", self.nombre, x_mm=8)
        self.nombre.refresh_from_db()
        self.assertEqual((self.nombre.x_mm, self.nombre.y_mm), (Decimal("8"), Decimal("31.5")))
        self.assertTrue(self.nombre.posicion_corregida)
        self.assertFalse(AjusteCuadro.objects.exists())

    def test_datos_invalidos(self):
        self.assertEqual(self.enviar("estampa", self.nombre, ancho_mm=0.5).status_code, 400)
        self.assertEqual(self.enviar("otra", self.nombre).status_code, 400)
        ajeno = VarianteLayout.objects.create(modelo=self.variante.modelo, nombre="otra")
        cuadro = CuadroTexto.objects.create(
            variante=ajeno, x_mm=0, y_mm=0, ancho_mm=1, alto_mm=1, fuente="A", tamano_pt=1
        )
        self.assertEqual(self.enviar("estampa", cuadro).status_code, 400)
        self.assertFalse(AjusteCuadro.objects.exists())

    def test_la_pagina_trae_el_panel_y_las_posiciones(self):
        self.enviar("estampa", self.nombre)
        pagina = self.client.get(reverse("vista_previa", args=[self.estampa.pk]))
        self.assertContains(pagina, 'id="mover"')
        self.assertContains(pagina, 'data-x="7"')
        self.assertContains(pagina, 'data-modelo-x="5"')
        self.assertContains(pagina, "left:7mm")
        self.assertContains(pagina, "posición propia")

    def test_editar_la_posicion_en_el_admin_la_protege(self):
        from .admin import CuadroTextoForm

        datos = {campo: getattr(self.nombre, campo) for campo in (
            "variante", "indice_origen", "pagina", "rol", "x_mm", "y_mm", "ancho_mm", "alto_mm", "fuente",
            "tamano_pt", "color", "alineacion", "alineacion_vertical", "interlineado",
            "espacio_despues_pt", "espaciado_letras_pt", "rotacion",
        )}
        datos["variante"] = self.variante.pk
        datos["x_mm"] = 12
        formulario = CuadroTextoForm(datos, instance=self.nombre)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        formulario.save()
        self.nombre.refresh_from_db()
        self.assertTrue(self.nombre.posicion_corregida)
