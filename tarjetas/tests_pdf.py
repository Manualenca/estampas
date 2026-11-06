import re
import shutil
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import fuentes, pdf
from .importador import EtiquetaEnNegrita, aplicar_estilos, etiqueta_en_negrita, marcar_etiqueta
from .lector_docx import Corrida, Parrafo
from .models import (
    CuadroTexto,
    EstampaSacramento,
    EstiloLinea,
    Genero,
    ModeloTarjeta,
    Nino,
    Pedido,
    PlantillaTexto,
    Sacramento,
    VarianteLayout,
)
from .tests_importacion import ESPACIOS, SECCION, ancla, escribir_docx
from .tests_vista_previa import Base
from .textos import textos_de_estampa

Rol = CuadroTexto.Rol


def tamanos_de_pagina(contenido):
    """[(ancho, alto)] en mm de cada página, en orden."""
    cajas = re.findall(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", contenido)
    return [(round(float(a) * 25.4 / 72, 1), round(float(b) * 25.4 / 72, 1)) for a, b in cajas]


class PdfEstampasTests(Base):
    def setUp(self):
        super().setUp()
        self.con("comunion")
        self.reverso = CuadroTexto.objects.create(
            variante=self.variante, indice_origen=9, pagina=CuadroTexto.Pagina.REVERSO, rol=Rol.NOMBRE,
            x_mm=5, y_mm=5, ancho_mm=60, alto_mm=12, fuente="Abadi", tamano_pt=10,
        )
        self.estampa.cantidad = 3
        self.estampa.save()

    def test_paginas_del_tamano_de_la_tarjeta_con_anverso_y_reverso(self):
        resultado = pdf.pdf_de_estampas([self.estampa], "prueba")
        self.assertTrue(resultado.contenido.startswith(b"%PDF"))
        self.assertEqual(resultado.paginas, 6)  # 3 copias x 2 caras
        self.assertEqual(set(tamanos_de_pagina(resultado.contenido)), {(75.0, 125.0)})

    def test_el_visor_sugiere_imprimir_al_100(self):
        contenido = pdf.pdf_de_estampas([self.estampa], "prueba").contenido
        self.assertIn(b"/PrintScaling /None", contenido)

    def orden_de_caras(self, intercalado):
        caras = []
        original = pdf._dibujar_pagina

        def anotar(lienzo, modelo, pagina, textos, avisos, faltantes):
            caras.append(pagina)
            return original(lienzo, modelo, pagina, textos, avisos, faltantes)

        with mock.patch.object(pdf, "_dibujar_pagina", anotar):
            pdf.pdf_de_estampas([self.estampa], "prueba", intercalado=intercalado)
        return caras

    def test_orden_intercalado_o_por_cara(self):
        self.assertEqual(self.orden_de_caras(True), [1, 2, 1, 2, 1, 2])
        self.assertEqual(self.orden_de_caras(False), [1, 1, 1, 2, 2, 2])

    def test_una_copia_si_se_pide(self):
        self.assertEqual(pdf.pdf_de_estampas([self.estampa], "prueba", copias=1).paginas, 2)

    def posiciones_dibujadas(self):
        posiciones = []
        with mock.patch.object(pdf, "_dibujar_trozo", lambda lienzo, trozo, x, y, extra=0: posiciones.append((trozo.texto, x, y))):
            pdf.pdf_de_estampas([self.estampa], "prueba", copias=1)
        primeras = {}
        for texto, x, y in posiciones:  # La primera es la del anverso.
            primeras.setdefault(texto, (x, y))
        return primeras

    def test_la_calibracion_corre_cada_pagina(self):
        antes = self.posiciones_dibujadas()["Ana"]
        modelo = self.variante.modelo
        modelo.offset_x, modelo.offset_y = Decimal("2"), Decimal("1")
        modelo.save()
        despues = self.posiciones_dibujadas()["Ana"]
        self.assertAlmostEqual(despues[0] - antes[0], 2 * pdf.MM, places=3)
        self.assertAlmostEqual(despues[1] - antes[1], -1 * pdf.MM, places=3)  # Y positivo baja.

    def test_usa_la_posicion_ajustada_de_la_estampa(self):
        from .models import AjusteCuadro

        antes = self.posiciones_dibujadas()["Ana"]
        AjusteCuadro.objects.create(
            estampa=self.estampa, cuadro=self.cuadros[Rol.NOMBRE], x_mm=Decimal("15")
        )
        despues = self.posiciones_dibujadas()["Ana"]
        self.assertAlmostEqual(despues[0] - antes[0], 10 * pdf.MM, places=3)

    def test_avisa_si_el_texto_no_entra(self):
        nombre = self.cuadros[Rol.NOMBRE]
        nombre.alto_mm = Decimal("2")
        nombre.save()
        resultado = pdf.pdf_de_estampas([self.estampa], "prueba", copias=1)
        self.assertTrue(any("Nombre" in a for a in resultado.avisos))

    def test_cuadro_invertido_no_falla(self):
        CuadroTexto.objects.filter(variante=self.variante).update(rotacion=180)
        self.assertEqual(pdf.pdf_de_estampas([self.estampa], "prueba", copias=1).paginas, 2)


class ComponerTests(Base):
    def componer(self, rol, **cambios):
        self.con("comunion")
        CuadroTexto.objects.filter(pk=self.cuadros[rol].pk).update(**cambios)
        texto = next(t for t in textos_de_estampa(self.estampa) if t.cuadro.rol == rol)
        return pdf.componer(texto)

    def test_reparte_en_renglones_sin_cortar_palabras(self):
        composicion = self.componer(Rol.CELEBRACION, ancho_mm=40, alto_mm=80)
        textos = [" ".join(t.texto for t in r.trozos) for r in composicion.renglones]
        self.assertGreater(len(textos), 2)
        self.assertFalse(composicion.desborda)
        for renglon in composicion.renglones:
            self.assertLessEqual(renglon.ancho, renglon.ancho_disponible + 0.5)

    def test_sangria_y_alineacion_por_parte(self):
        self.ana.madrina = "Eva"
        self.ana.save()
        cuadro = self.cuadros[Rol.CELEBRACION]
        EstiloLinea.objects.create(
            cuadro=cuadro, elemento=EstiloLinea.Elemento.PADRINOS,
            alineacion=CuadroTexto.Alineacion.IZQUIERDA, sangria_izquierda_mm=Decimal("5"),
            espacio_antes_pt=Decimal("4"),
        )
        EstampaSacramento.objects.filter(estampa=self.estampa).delete()
        self.con("confirmacion")
        texto = next(t for t in textos_de_estampa(self.estampa) if t.cuadro.rol == Rol.CELEBRACION)
        padrinos = pdf.componer(texto).renglones[0]
        self.assertEqual(padrinos.alineacion, CuadroTexto.Alineacion.IZQUIERDA)
        self.assertAlmostEqual(padrinos.izquierda, 5 * pdf.MM, places=3)
        self.assertEqual(padrinos.espacio_antes, 4)

    def test_fuente_sin_negrita_la_simula(self):
        cara = pdf.fuente("Fuente Inexistente", True, True)
        self.assertEqual(cara.nombre, pdf.FUENTE_DE_RESPALDO)
        self.assertTrue(cara.negrita_simulada and cara.cursiva_simulada)


class DiplomasYCalibracionTests(Base):
    def setUp(self):
        super().setUp()
        self.con("bautismo")
        bautismo = Sacramento.objects.get(codigo="bautismo")
        for genero, codigo in ((Genero.MUJER, "dip_fem"), (Genero.VARON, "dip_masc")):
            modelo = ModeloTarjeta.objects.create(
                codigo=codigo, tipo=ModeloTarjeta.Tipo.DIPLOMA, ancho_mm=210, alto_mm=297
            )
            variante = VarianteLayout.objects.create(modelo=modelo, nombre="base", genero=genero)
            variante.sacramentos.add(bautismo)
            CuadroTexto.objects.create(
                variante=variante, rol=Rol.NOMBRE, x_mm=20, y_mm=60, ancho_mm=170, alto_mm=20,
                fuente="Harrington", tamano_pt=32,
            )

    def test_un_diploma_por_chico_segun_su_genero(self):
        luis = Nino.objects.create(pedido=self.pedido, nombre="Luis", genero=Genero.VARON)
        self.estampa.ninos.add(luis)
        Nino.objects.create(pedido=self.pedido, nombre="Sin diploma", lleva_diploma=False)
        resultado = pdf.pdf_de_diplomas(self.pedido)
        self.assertEqual(resultado.paginas, 2)
        self.assertEqual(tamanos_de_pagina(resultado.contenido), [(210.0, 297.0)] * 2)

    def test_chico_sin_genero_se_avisa(self):
        self.ana.genero = ""
        self.ana.save()
        resultado = pdf.pdf_de_diplomas(self.pedido)
        self.assertEqual(resultado.paginas, 0)
        self.assertTrue(any("Ana Pérez" in a for a in resultado.avisos))

    def test_hoja_de_calibracion_con_reverso(self):
        modelo = self.variante.modelo
        self.assertEqual(pdf.pdf_de_calibracion(modelo).paginas, 1)
        CuadroTexto.objects.create(
            variante=self.variante, indice_origen=20, pagina=CuadroTexto.Pagina.REVERSO, x_mm=1, y_mm=1,
            ancho_mm=10, alto_mm=10, fuente="Abadi", tamano_pt=9,
        )
        resultado = pdf.pdf_de_calibracion(modelo)
        self.assertEqual(resultado.paginas, 2)
        self.assertEqual(tamanos_de_pagina(resultado.contenido), [(75.0, 125.0)] * 2)


class PantallasDeImpresionTests(Base):
    def setUp(self):
        super().setUp()
        self.con("comunion")
        self.client.force_login(get_user_model().objects.create_superuser("prueba", password="x"))

    def test_pantalla_de_impresion_con_aviso_de_escala(self):
        pagina = self.client.get(reverse("pedido_imprimir", args=[self.pedido.pk]))
        self.assertContains(pagina, "Imprimir en tamaño real / 100 %, sin «Ajustar a la página»")
        self.assertContains(pagina, "Marcar como impreso")

    def test_los_pdf_salen_y_no_cambian_el_estado(self):
        for nombre, args in (
            ("pdf_pedido", [self.pedido.pk]),
            ("pdf_diplomas", [self.pedido.pk]),
            ("pdf_estampa", [self.estampa.pk]),
            ("pdf_calibracion", [self.variante.modelo.pk]),
        ):
            with self.subTest(nombre=nombre):
                respuesta = self.client.get(reverse(nombre, args=args))
                self.assertEqual(respuesta["Content-Type"], "application/pdf")
                self.assertTrue(respuesta.content.startswith(b"%PDF"))
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.INGRESADO)
        self.assertEqual(self.pedido.historial.count(), 1)

    def test_marcar_impreso_y_despues_enviado(self):
        url = reverse("pedido_estado", args=[self.pedido.pk])
        self.client.post(url, {"estado": "enviado"})  # Salteado: no corresponde.
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.INGRESADO)
        self.client.post(url, {"estado": "impreso"})
        self.client.post(url, {"estado": "enviado"})
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.ENVIADO)
        cambios = list(self.pedido.historial.order_by("pk").values_list("estado_nuevo", flat=True))
        self.assertEqual(cambios, ["ingresado", "impreso", "enviado"])
        self.assertNotContains(self.client.get(reverse("pedido_imprimir", args=[self.pedido.pk])), "Marcar como")

    def test_calibracion_por_pagina(self):
        modelo = self.variante.modelo
        url = reverse("calibracion", args=[modelo.pk])
        self.assertContains(self.client.get(url), "Hoja de prueba")
        self.client.post(url, {"offset_x": "1.5", "offset_y": "-0.5", "offset_x_reverso": "0", "offset_y_reverso": "2"})
        modelo.refresh_from_db()
        self.assertEqual(modelo.offset(1), (Decimal("1.5"), Decimal("-0.5")))
        self.assertEqual(modelo.offset(2), (Decimal("0"), Decimal("2")))
        self.assertContains(self.client.get(reverse("modelos")), "Calibrar")


def corrida(texto, negrita=False):
    return Corrida(texto=texto, negrita=negrita)


class NegritaPorPartesTests(SimpleTestCase):
    def test_etiqueta_completa_la_palabra_cortada(self):
        etiqueta = etiqueta_en_negrita(Parrafo(corridas=[corrida("Mis Padrino", True), corrida("s: Ana y Juan")]))
        self.assertEqual((etiqueta.palabras, etiqueta.con_dos_puntos), (2, False))

    def test_etiqueta_con_dos_puntos(self):
        etiqueta = etiqueta_en_negrita(Parrafo(corridas=[corrida("Mis Papis:", True), corrida(" Ana")]))
        self.assertTrue(etiqueta.con_dos_puntos)

    def test_sin_negrita_al_comienzo_no_hay_etiqueta(self):
        self.assertIsNone(etiqueta_en_negrita(Parrafo(corridas=[corrida("Ana "), corrida("Pérez", True)])))

    def test_marcar_respeta_los_dos_puntos(self):
        self.assertEqual(
            marcar_etiqueta("Mi Madrina: {madrina}", EtiquetaEnNegrita(2, False, "")),
            "**Mi Madrina**: {madrina}",
        )
        self.assertEqual(
            marcar_etiqueta("Mis Papis: {madre} y {padre}", EtiquetaEnNegrita(2, True, "")),
            "**Mis Papis:** {madre} y {padre}",
        )
        self.assertEqual(
            marcar_etiqueta("Nací el {fecha_nacimiento}", EtiquetaEnNegrita(1, False, "")),
            "**Nací** el {fecha_nacimiento}",
        )


class EstilosDelImportadorTests(TestCase):
    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.carpeta, ignore_errors=True)
        patron = override_settings(MODELOS_DOCX_DIR=self.carpeta)
        patron.enable()
        self.addCleanup(patron.disable)

    def docx(self, parrafos_xml):
        cuerpo = f"<wps:txbx><w:txbxContent>{parrafos_xml}</w:txbxContent></wps:txbx>"
        forma = f"<wps:wsp><wps:spPr/>{cuerpo}<wps:bodyPr/></wps:wsp>"
        nombre = ancla(
            "<wps:wsp><wps:spPr/><wps:txbx><w:txbxContent><w:p><w:r><w:rPr><w:sz w:val='40'/></w:rPr>"
            "<w:t>Ana Pérez</w:t></w:r></w:p></w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>",
            5, 10, 60, 12,
        )
        xml = f"<w:document {ESPACIOS}><w:body><w:p>{nombre}{ancla(forma, 5, 40, 60, 40)}</w:p>{SECCION}</w:body></w:document>"
        return escribir_docx(self.carpeta / "estampas" / "Tarj1.docx", xml)

    def test_formato_por_parrafo_y_negrita_por_partes(self):
        ruta = self.docx(
            '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>Mi Madrina</w:t></w:r>'
            "<w:r><w:t xml:space='preserve'>: Eva</w:t></w:r></w:p>"
            '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:t>14 de mayo de 2026</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:spacing w:before="80"/><w:ind w:left="567"/><w:jc w:val="right"/></w:pPr>'
            "<w:r><w:t>Salta – Capital</w:t></w:r></w:p>"
        )
        call_command("importar_modelos", stdout=StringIO())
        cuadro = CuadroTexto.objects.get(rol=Rol.CELEBRACION)
        localidad = cuadro.estilos.get(elemento=EstiloLinea.Elemento.LOCALIDAD)
        self.assertEqual(localidad.alineacion, CuadroTexto.Alineacion.DERECHA)
        self.assertEqual(localidad.espacio_antes_pt, Decimal("4"))
        self.assertEqual(localidad.sangria_izquierda_mm, Decimal("10"))

        salida = StringIO()
        call_command("importar_modelos", estilos=True, stdout=salida)
        variante = cuadro.variante
        propia = PlantillaTexto.objects.get(
            variante=variante, clave=PlantillaTexto.Clave.PADRINOS_SOLO_MADRINA
        )
        self.assertEqual(propia.texto, "**Mi Madrina**: {madrina}")
        self.assertIn("Plantillas cambiadas: 4", salida.getvalue())
        self.assertIs(cuadro.estilos.get(elemento=EstiloLinea.Elemento.PADRINOS).negrita, False)
        # Una segunda pasada no cambia nada.
        otra = StringIO()
        call_command("importar_modelos", ruta, estilos=True, stdout=otra)
        self.assertIn("Plantillas cambiadas: 0", otra.getvalue())


BAHNSCHRIFT = Path(r"C:\Windows\Fonts\bahnschrift.ttf")


class InstanciaVariableTests(SimpleTestCase):
    @unittest.skipUnless(BAHNSCHRIFT.exists(), "Bahnschrift no está instalada")
    def test_genera_bahnschrift_semilight(self):
        destino = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, destino, ignore_errors=True)
        copiadas, faltantes, generadas = fuentes.copiar(
            ["Bahnschrift SemiLight"], destino, [BAHNSCHRIFT.parent]
        )
        self.assertEqual(faltantes, [])
        self.assertEqual(generadas[0][2]["wght"], 350)
        archivo = destino / "Bahnschrift SemiLight" / "Bahnschrift SemiLight - Regular.ttf"
        self.assertEqual(fuentes.leer_nombres(archivo), ("Bahnschrift SemiLight", "Regular"))
        from fontTools.ttLib import TTFont

        self.assertNotIn("fvar", TTFont(archivo))
