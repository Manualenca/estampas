import shutil
import tempfile
import zipfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from .importador import analizar_nombre, leer_banco_oraciones
from .lector_docx import leer_docx
from .models import CuadroTexto, ModeloTarjeta, Oracion, PlantillaTexto, VarianteLayout

ESPACIOS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:v="urn:schemas-microsoft-com:vml"'
)
MM = 36000  # EMU por mm
TWIP = 1440 / 25.4
SECCION = (
    f'<w:sectPr><w:pgSz w:w="{round(75 * TWIP)}" w:h="{round(125 * TWIP)}"/>'
    f'<w:pgMar w:top="{round(10 * TWIP)}" w:right="{round(5 * TWIP)}" '
    f'w:bottom="{round(5 * TWIP)}" w:left="{round(5 * TWIP)}"/></w:sectPr>'
)


def contenido(*parrafos, fuente="Abadi", tamano=20):
    texto = ""
    for parrafo in parrafos:
        texto += (
            f'<w:p><w:r><w:rPr><w:rFonts w:ascii="{fuente}"/><w:sz w:val="{tamano}"/></w:rPr>'
            f"<w:t>{parrafo}</w:t></w:r></w:p>"
        )
    return f"<wps:txbx><w:txbxContent>{texto}</w:txbxContent></wps:txbx>"


def forma(cuerpo, xfrm="", relleno=""):
    return f"<wps:wsp><wps:spPr>{xfrm}{relleno}</wps:spPr>{cuerpo}<wps:bodyPr/></wps:wsp>"


def ancla(grafico, x, y, ancho, alto, rel_h="page", rel_v="page", z=1):
    return (
        f'<w:r><w:drawing><wp:anchor relativeHeight="{z}" simplePos="0">'
        f'<wp:positionH relativeFrom="{rel_h}"><wp:posOffset>{round(x * MM)}</wp:posOffset></wp:positionH>'
        f'<wp:positionV relativeFrom="{rel_v}"><wp:posOffset>{round(y * MM)}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{round(ancho * MM)}" cy="{round(alto * MM)}"/>'
        f"<a:graphic><a:graphicData>{grafico}</a:graphicData></a:graphic>"
        "</wp:anchor></w:drawing></w:r>"
    )


def cuadro(texto, x, y, ancho=40, alto=10, xfrm="", relleno="", **extra):
    return ancla(forma(contenido(texto), xfrm, relleno), x, y, ancho, alto, **extra)


def documento(*parrafos):
    cuerpo = "".join(f"<w:p>{p}</w:p>" for p in parrafos)
    return f"<w:document {ESPACIOS}><w:body>{cuerpo}{SECCION}</w:body></w:document>"


def escribir_docx(ruta, xml):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ruta, "w") as archivo:
        archivo.writestr("word/document.xml", xml)
    return ruta


class ConCarpetaTemporal:
    def crear_carpeta(self):
        self.carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.carpeta, ignore_errors=True)

    def leer(self, *parrafos):
        return leer_docx(escribir_docx(self.carpeta / "a.docx", documento(*parrafos)))


class LectorTests(ConCarpetaTemporal, SimpleTestCase):
    def setUp(self):
        self.crear_carpeta()

    def test_tamano_de_pagina(self):
        doc = self.leer(cuadro("A", 0, 0))
        self.assertAlmostEqual(doc.ancho_mm, 75, delta=0.05)
        self.assertAlmostEqual(doc.alto_mm, 125, delta=0.05)

    def test_posicion_relativa_al_margen(self):
        c = self.leer(cuadro("A", 2, 3, rel_h="margin", rel_v="margin")).cuadros[0]
        self.assertAlmostEqual(c.x, 7, delta=0.05)
        self.assertAlmostEqual(c.y, 13, delta=0.05)

    def test_posicion_relativa_al_parrafo_y_columna(self):
        c = self.leer(cuadro("A", 2, 3, rel_h="column", rel_v="paragraph")).cuadros[0]
        self.assertAlmostEqual(c.x, 7, delta=0.05)
        self.assertAlmostEqual(c.y, 13, delta=0.05)

    def test_el_segundo_parrafo_empieza_mas_abajo(self):
        doc = self.leer("", cuadro("A", 0, 0, rel_v="paragraph"))
        self.assertGreater(doc.cuadros[0].y, 10)

    def test_ignora_el_fallback(self):
        duplicado = (
            "<w:r><mc:AlternateContent><mc:Choice>"
            f"{cuadro('A', 1, 1)}</mc:Choice><mc:Fallback>{cuadro('A', 1, 1)}</mc:Fallback>"
            "</mc:AlternateContent></w:r>"
        )
        self.assertEqual(len(self.leer(duplicado).cuadros), 1)

    def grupo(self, xfrm_grupo, ancho=60, alto=40):
        hijo = forma(
            contenido("Hijo"),
            f'<a:xfrm><a:off x="{10 * MM}" y="{5 * MM}"/><a:ext cx="{20 * MM}" cy="{10 * MM}"/></a:xfrm>',
        )
        grafico = f"<wpg:wgp><wpg:grpSpPr>{xfrm_grupo}</wpg:grpSpPr>{hijo}</wpg:wgp>"
        return ancla(grafico, 2, 3, ancho, alto)

    def test_grupo_suma_ancla_y_offset(self):
        xfrm = (
            f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{60 * MM}" cy="{40 * MM}"/>'
            f'<a:chOff x="0" y="0"/><a:chExt cx="{60 * MM}" cy="{40 * MM}"/></a:xfrm>'
        )
        c = self.leer(self.grupo(xfrm)).cuadros[0]
        self.assertAlmostEqual(c.x, 12, delta=0.01)
        self.assertAlmostEqual(c.y, 8, delta=0.01)
        self.assertAlmostEqual(c.ancho, 20, delta=0.01)

    def test_grupo_escalado_por_chext(self):
        xfrm = (
            f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{60 * MM}" cy="{40 * MM}"/>'
            f'<a:chOff x="{5 * MM}" y="0"/><a:chExt cx="{120 * MM}" cy="{80 * MM}"/></a:xfrm>'
        )
        c = self.leer(self.grupo(xfrm)).cuadros[0]
        self.assertAlmostEqual(c.x, 2 + (10 - 5) * 0.5, delta=0.01)
        self.assertAlmostEqual(c.y, 3 + 5 * 0.5, delta=0.01)
        self.assertAlmostEqual(c.ancho, 10, delta=0.01)
        self.assertAlmostEqual(c.alto, 5, delta=0.01)

    def test_grupo_espejado_mueve_los_hijos_e_invierte(self):
        xfrm = (
            f'<a:xfrm flipV="1"><a:off x="0" y="0"/><a:ext cx="{60 * MM}" cy="{40 * MM}"/>'
            f'<a:chOff x="0" y="0"/><a:chExt cx="{60 * MM}" cy="{40 * MM}"/></a:xfrm>'
        )
        c = self.leer(self.grupo(xfrm)).cuadros[0]
        self.assertAlmostEqual(c.y, 3 + 40 - 5 - 10, delta=0.01)
        self.assertTrue(c.invertido)

    def test_rotacion_y_espejo_se_cancelan(self):
        rotado = '<a:xfrm rot="10800000"/>'
        ambos = '<a:xfrm rot="10800000" flipV="1"/>'
        cuadros = self.leer(cuadro("A", 0, 0, xfrm=rotado), cuadro("B", 0, 0, xfrm=ambos)).cuadros
        self.assertTrue(cuadros[0].invertido)
        self.assertFalse(cuadros[1].invertido)

    def test_salto_de_pagina_separa_anverso_y_reverso(self):
        salto = '<w:r><w:br w:type="page"/></w:r>'
        cuadros = self.leer(
            cuadro("Anverso", 0, 5, rel_v="paragraph") + salto,
            cuadro("Reverso", 0, 5, rel_v="paragraph"),
        ).cuadros
        self.assertEqual([c.pagina for c in cuadros], [1, 2])
        self.assertAlmostEqual(cuadros[0].y, cuadros[1].y, delta=0.01)

    def test_vml_agrupado(self):
        vml = (
            '<w:r><w:pict><v:group style="position:absolute;margin-left:10mm;margin-top:20mm;'
            'width:40mm;height:40mm" coordorigin="100,0" coordsize="200,200">'
            '<v:shape style="position:absolute;left:150;top:50;width:100;height:50"><v:textbox>'
            '<w:txbxContent><w:p><w:r><w:t>Vml</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape>'
            "</v:group></w:pict></w:r>"
        )
        c = self.leer(vml).cuadros[0]
        self.assertEqual(c.texto, "Vml")
        self.assertAlmostEqual(c.x, 5 + 10 + 10, delta=0.01)
        self.assertAlmostEqual(c.y, 10 + 20 + 10, delta=0.01)
        self.assertAlmostEqual(c.ancho, 20, delta=0.01)


class NombreDeArchivoTests(SimpleTestCase):
    def test_modelo_variante_y_sin_oracion(self):
        casos = {
            "Tarj2059_Conf_SOr": ("2059", "Conf_SOr", True),
            "Tarj2059_Conf": ("2059", "Conf", False),
            "Tarj2059": ("2059", "base", False),
            "Tarj2058 s_oracion": ("2058", "s_oracion", True),
            "Tarj2066_Sin Oracion": ("2066", "Sin Oracion", True),
            "Tarj2116_sin oracion": ("2116", "sin oracion", True),
            "Tarj3004_sin_oracion": ("3004", "sin_oracion", True),
            "Tarj2067_S_Pad": ("2067", "S_Pad", False),
            "Tarj2055_11": ("2055", "11", False),
            "Diploma Nombre1_Comunion": ("Diploma Nombre1_Comunion", "base", False),
        }
        for nombre, esperado in casos.items():
            with self.subTest(nombre=nombre):
                self.assertEqual(analizar_nombre(Path(nombre + ".docx")), esperado)


def estampa_de_prueba(y_nombre=30):
    return documento(
        cuadro("Recuerdo de mi Primera Comunión", 5, 10)
        + cuadro("Ana María Pérez", 5, y_nombre)
        + cuadro("Señor, guía mis pasos siempre.", 5, 50)
        + cuadro("Recibí la Santa Eucaristía el 14 de noviembre de 2026", 5, 70)
    )


class ImportarModelosTests(ConCarpetaTemporal, TestCase):
    def setUp(self):
        self.crear_carpeta()
        patron = override_settings(MODELOS_DOCX_DIR=self.carpeta)
        patron.enable()
        self.addCleanup(patron.disable)

    def importar(self, *args, **kwargs):
        salida = StringIO()
        call_command("importar_modelos", *args, stdout=salida, stderr=salida, **kwargs)
        return salida.getvalue()

    def estampa(self, nombre="estampas/Tarj1.docx", xml=None):
        return escribir_docx(self.carpeta / nombre, xml or estampa_de_prueba())

    def test_importa_y_deduce_roles(self):
        self.estampa()
        salida = self.importar()
        roles = set(CuadroTexto.objects.values_list("rol", flat=True))
        self.assertEqual(roles, {"titulo", "nombre", "oracion", "celebracion"})
        self.assertIn("Modelos nuevos: 1", salida)
        self.assertIn("Cuadros sin asignar: 0", salida)
        self.assertEqual(ModeloTarjeta.objects.get().codigo, "1")

    def test_recorre_subcarpetas_y_no_repite(self):
        self.estampa()
        self.estampa("estampas/bautismo/Tarj2.docx")
        self.importar()
        self.assertEqual(VarianteLayout.objects.count(), 2)
        salida = self.importar()
        self.assertEqual(VarianteLayout.objects.count(), 2)
        self.assertIn("Archivos que ya estaban en la base: 2", salida)
        self.assertEqual(
            VarianteLayout.objects.get(modelo__codigo="2").sacramentos.get().codigo, "bautismo"
        )

    def test_con_una_ruta_importa_solo_ese_archivo(self):
        self.estampa()
        otra = self.estampa("estampas/Tarj2.docx")
        self.importar(str(otra))
        self.assertEqual(ModeloTarjeta.objects.get().codigo, "2")

    def test_variantes_del_mismo_modelo(self):
        self.estampa("estampas/Tarj1.docx")
        self.estampa(
            "estampas/Tarj1_Sin Oracion.docx",
            documento(cuadro("Ana Pérez", 5, 30) + cuadro("Parroquia X, 14 de mayo de 2026", 5, 70)),
        )
        self.importar()
        modelo = ModeloTarjeta.objects.get()
        self.assertEqual(modelo.variantes.count(), 2)
        self.assertEqual(modelo.variante_adecuada(con_oracion=False).nombre, "Sin Oracion")

    def test_sin_cuadros_se_omite(self):
        self.estampa(xml=documento(""))
        salida = self.importar()
        self.assertFalse(ModeloTarjeta.objects.exists())
        self.assertIn("no tiene cuadros de texto", salida)

    def test_rol_desconocido_queda_sin_asignar(self):
        self.estampa(xml=documento(cuadro("Ana Pérez", 5, 30) + cuadro("Hola", 5, 50)))
        salida = self.importar()
        self.assertTrue(CuadroTexto.objects.filter(rol="sin_asignar").exists())
        self.assertIn("Cuadros sin asignar: 1", salida)

    def test_cuadro_fuera_de_hoja_se_descarta(self):
        self.estampa(xml=documento(cuadro("Ana Pérez", 5, 30) + cuadro("Mi Confirmación", 5, -60)))
        salida = self.importar()
        self.assertEqual(CuadroTexto.objects.count(), 1)
        self.assertIn("fuera de la hoja", salida)

    def test_cuadro_tapado_se_descarta(self):
        fondo = "<a:solidFill/>"
        tapado = cuadro("Parroquia X, 14 de mayo de 2026", 5, 30, z=1)
        encima = cuadro("Parroquia Y, 20 de mayo de 2026", 5, 30, relleno=fondo, z=2)
        self.estampa(xml=documento(tapado + encima))
        salida = self.importar()
        self.assertEqual(CuadroTexto.objects.get().indice_origen, 1)
        self.assertEqual(CuadroTexto.objects.get().rol, "celebracion")
        self.assertIn("tapado por otro cuadro", salida)

    def test_archivo_danado_no_frena_a_los_demas(self):
        ruta = self.carpeta / "estampas" / "Tarj9.docx"
        ruta.parent.mkdir(parents=True)
        ruta.write_bytes(b"no es un docx")
        self.estampa()
        salida = self.importar()
        self.assertEqual(ModeloTarjeta.objects.get().codigo, "1")
        self.assertIn("Tarj9.docx", salida)

    def test_actualizar_conserva_calibracion_fondo_y_rol_corregido(self):
        ruta = self.estampa()
        self.importar()
        modelo = ModeloTarjeta.objects.get()
        modelo.offset_x, modelo.offset_y_reverso = 2, 3
        modelo.imagen_fondo = "fondos/a.png"
        modelo.save()
        corregido = CuadroTexto.objects.get(rol="oracion")
        corregido.rol, corregido.rol_corregido = "sin_asignar", True
        corregido.color_mujer = "C00070"
        corregido.save()

        self.estampa(xml=estampa_de_prueba(y_nombre=33))
        salida = self.importar(str(ruta), actualizar=True)

        self.assertIn("Archivos actualizados: 1", salida)
        modelo.refresh_from_db()
        self.assertEqual((modelo.offset_x, modelo.offset_y_reverso), (2, 3))
        self.assertEqual(modelo.imagen_fondo.name, "fondos/a.png")
        corregido.refresh_from_db()
        self.assertEqual(corregido.rol, "sin_asignar")
        self.assertEqual(corregido.color_mujer, "C00070")
        self.assertAlmostEqual(float(CuadroTexto.objects.get(rol="nombre").y_mm), 33, delta=0.05)

    def test_sin_actualizar_no_modifica(self):
        ruta = self.estampa()
        self.importar()
        self.estampa(xml=estampa_de_prueba(y_nombre=33))
        self.importar(str(ruta))
        self.assertAlmostEqual(float(CuadroTexto.objects.get(rol="nombre").y_mm), 30, delta=0.05)

    def test_titulo_en_dos_lineas_crea_plantilla_de_la_variante(self):
        titulo = ancla(
            forma(contenido("Recuerdo de mi", "Confirmación")), 5, 10, 40, 15
        )
        self.estampa(xml=documento(titulo + cuadro("Ana Pérez", 5, 30)))
        self.importar()
        plantilla = PlantillaTexto.objects.get(variante__isnull=False)
        self.assertEqual(plantilla.texto, "Recuerdo de {Posesivo}\n{sacramentos}")
        self.assertTrue(CuadroTexto.objects.get(rol="titulo").respeta_saltos)

    def test_diploma_importa_solo_el_nombre(self):
        escribir_docx(
            self.carpeta / "diplomas" / "Diploma_Bautismo_fem.docx",
            documento(cuadro("Recuerdo de Mi Bautismo", 5, 10) + cuadro("Ana Pérez", 5, 30)),
        )
        self.importar()
        unico = CuadroTexto.objects.get()
        self.assertEqual(unico.rol, "nombre")
        self.assertAlmostEqual(float(unico.y_mm), 30, delta=0.05)
        variante = unico.variante
        self.assertEqual(variante.modelo.tipo, "diploma")
        self.assertEqual(variante.genero, "F")
        self.assertEqual(variante.sacramentos.get().codigo, "bautismo")

    def test_diploma_con_titulo_y_nombre_en_el_mismo_cuadro(self):
        junto = ancla(forma(contenido("Mi Bautismo", "Ana Pérez")), 5, 10, 100, 30)
        escribir_docx(self.carpeta / "diplomas" / "Diploma_Bautismo_masc.docx", documento(junto))
        self.importar()
        unico = CuadroTexto.objects.get()
        self.assertEqual(unico.rol, "nombre")
        self.assertGreater(float(unico.y_mm), 10)
        self.assertLess(float(unico.alto_mm), 30)


class OracionesTests(ConCarpetaTemporal, TestCase):
    def setUp(self):
        self.crear_carpeta()
        patron = override_settings(MODELOS_DOCX_DIR=self.carpeta)
        patron.enable()
        self.addCleanup(patron.disable)

    def banco(self, nombre, *parrafos):
        cuerpo = "".join(f"<w:r><w:t>{p}</w:t></w:r></w:p><w:p>" for p in parrafos)
        ruta = self.carpeta / "oraciones" / nombre
        return escribir_docx(ruta, documento(cuerpo))

    def cargar(self):
        call_command("importar_modelos", stdout=StringIO())

    def sacramentos(self, fragmento):
        oracion = Oracion.objects.get(texto__contains=fragmento)
        return set(oracion.sacramentos.values_list("codigo", flat=True))

    def test_banco_numerado_con_cita_y_correccion(self):
        ruta = self.banco(
            "Oraciones Nuevas.docx",
            "TEXTO N° 308",
            "Señor haz de mí un instrumento de tu paz. San Francisco de Asís",
            "TEXTO Nº 326",
            "¡Abre mis ojos, Señor para que vea la luz de tu verdad!",
            "Salmo N° 8",
        )
        self.assertEqual(len(leer_banco_oraciones(ruta)), 2)
        self.cargar()
        primera = Oracion.objects.get(numero=308)
        self.assertEqual(primera.texto, "Señor, haz de mí un instrumento de tu paz.")
        self.assertEqual(primera.autor, "San Francisco de Asís")
        segunda = Oracion.objects.get(numero=326)
        self.assertEqual(segunda.autor, "Salmo 8")
        self.assertEqual(self.sacramentos("instrumento"), {"comunion", "confirmacion"})

    def test_la_314_queda_como_estaba(self):
        original = "Fortalece mi alma, dirígeme por el buen camino, por amor de su nombre."
        self.banco("Oraciones Nuevas.docx", "TEXTO Nº 314", original)
        self.cargar()
        self.assertEqual(Oracion.objects.get().texto, original)

    def test_banco_de_bautismo_y_clasificacion_a_mano(self):
        self.banco(
            "Oraciones_Bautismo.docx",
            "Reflexiones en formato de oración",
            "Señor, en este día en que nada podéis negarme, bendíceme y bendice a todos los "
            "que me enseñaron a amarte.",
            "Oh buen Jesús, has venido a mi corazón por primera vez en este día y yo te adoraré "
            "por aquellos que se olvidan de ti.",
            "Ven a mí, Jesús querido, y úname a tu corazón; que tú siempre estés conmigo es lo "
            "que más deseo.",
        )
        self.cargar()
        self.assertEqual(Oracion.objects.count(), 3)
        self.assertEqual(self.sacramentos("nada puedes negarme"), {"bautismo"})
        self.assertEqual(self.sacramentos("primera vez"), {"comunion"})
        self.assertEqual(self.sacramentos("Ven a mí"), {"bautismo", "comunion"})

    def test_estampa_suma_su_sacramento_sin_repetir(self):
        self.banco("Oraciones_Bautismo.docx", "Oh Jesús mío, haz que siempre te ame con la inocencia de este día.")
        escribir_docx(
            self.carpeta / "estampas" / "Tarj1.docx",
            documento(
                cuadro("Mi Primera Comunión", 5, 10)
                + cuadro("Ana Pérez", 5, 30)
                + cuadro("¡Oh Jesús! Mío; haz que siempre te ame con la inocencia de este día.", 5, 50)
            ),
        )
        self.cargar()
        self.assertEqual(Oracion.objects.count(), 1)
        self.assertEqual(self.sacramentos("inocencia"), {"bautismo", "comunion"})

    def test_cambios_del_admin_no_se_pisan_al_reimportar(self):
        self.banco("Oraciones_Bautismo.docx", "Ya nada anhelo, ya soy feliz; el Rey del cielo ya vive en mí.")
        self.cargar()
        oracion = Oracion.objects.get()
        oracion.sacramentos.clear()
        self.cargar()
        self.assertFalse(oracion.sacramentos.exists())


class BackupTests(TestCase):
    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.carpeta, ignore_errors=True)

    def test_crea_copia_y_conserva_las_ultimas(self):
        for i in range(32):
            (self.carpeta / f"db_2020-01-{i + 1:02d}_000000.sqlite3").write_text("x")
        ajeno = self.carpeta / "otro.sqlite3"
        ajeno.write_text("x")
        with override_settings(BACKUP_DIR=self.carpeta, BACKUPS_A_CONSERVAR=30):
            call_command("backup_db", stdout=StringIO())
        copias = sorted(p.name for p in self.carpeta.glob("db_*.sqlite3"))
        self.assertEqual(len(copias), 30)
        self.assertNotIn("db_2020-01-01_000000.sqlite3", copias)
        self.assertNotIn("db_2020-01-03_000000.sqlite3", copias)
        self.assertIn("db_2020-01-04_000000.sqlite3", copias)
        self.assertTrue(ajeno.exists())
        self.assertEqual(list(self.carpeta.glob("*.tmp")), [])

    def test_la_copia_es_una_base_valida(self):
        import sqlite3

        with override_settings(BACKUP_DIR=self.carpeta):
            call_command("backup_db", stdout=StringIO())
        copia = next(self.carpeta.glob("db_*.sqlite3"))
        conexion = sqlite3.connect(copia)
        try:
            cantidad = conexion.execute("select count(*) from tarjetas_sacramento").fetchone()[0]
        finally:
            conexion.close()
        self.assertEqual(cantidad, 3)


class PosicionCorregidaTests(ConCarpetaTemporal, TestCase):
    def setUp(self):
        self.crear_carpeta()
        patron = override_settings(MODELOS_DOCX_DIR=self.carpeta)
        patron.enable()
        self.addCleanup(patron.disable)

    def test_actualizar_no_pisa_una_posicion_movida_a_mano(self):
        ruta = escribir_docx(self.carpeta / "estampas" / "Tarj1.docx", estampa_de_prueba())
        call_command("importar_modelos", stdout=StringIO())
        nombre = CuadroTexto.objects.get(rol="nombre")
        nombre.y_mm, nombre.posicion_corregida = 40, True
        nombre.save()
        escribir_docx(ruta, estampa_de_prueba(y_nombre=33))
        call_command("importar_modelos", str(ruta), actualizar=True, stdout=StringIO())
        nombre.refresh_from_db()
        self.assertEqual(nombre.y_mm, 40)
