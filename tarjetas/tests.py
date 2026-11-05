from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import get_commands, load_command_class
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import (
    CuadroTexto,
    Estampa,
    EstampaSacramento,
    Genero,
    ModeloTarjeta,
    Nino,
    Oracion,
    Pedido,
    PlantillaTexto,
    Sacramento,
    VarianteLayout,
    deducir_articulo,
)


def crear_variante(codigo="Tarj1", nombre="base", tipo=ModeloTarjeta.Tipo.ESTAMPA, **extra):
    modelo, _ = ModeloTarjeta.objects.get_or_create(
        codigo=codigo, defaults={"tipo": tipo, "ancho_mm": 75, "alto_mm": 125}
    )
    return VarianteLayout.objects.create(modelo=modelo, nombre=nombre, **extra)


def crear_pedido():
    return Pedido.objects.create(
        numero_factura="F1", numero_sapp="S1", fecha_entrega=date(2026, 12, 1)
    )


def crear_cuadro(variante, **extra):
    datos = dict(x_mm=1, y_mm=2, ancho_mm=30, alto_mm=10, fuente="Abadi", tamano_pt=10)
    datos.update(extra)
    return CuadroTexto.objects.create(variante=variante, **datos)


class EntornoTests(TestCase):
    def test_runserver_usa_el_puerto_8001(self):
        self.assertEqual(get_commands()["runserver"], "tarjetas")
        comando = load_command_class("tarjetas", "runserver")
        self.assertEqual(comando.default_port, "8001")


class DatosInicialesTests(TestCase):
    def test_sacramentos_en_orden(self):
        self.assertEqual(
            list(Sacramento.objects.values_list("nombre", "posesivo_plural")),
            [
                ("Bautismo", "Nuestro"),
                ("Primera Comunión", "Nuestra"),
                ("Confirmación", "Nuestra"),
            ],
        )

    def test_frases_de_padres_son_plantillas(self):
        casos = {
            PlantillaTexto.Clave.PADRES_AMBOS: "Mis Papis: {madre} y {padre}",
            PlantillaTexto.Clave.PADRES_SOLO_MADRE: "Mi Mamá: {madre}",
            PlantillaTexto.Clave.PADRES_SOLO_PADRE: "Mi Papá: {padre}",
        }
        for clave, texto in casos.items():
            self.assertEqual(PlantillaTexto.resolver(clave).texto, texto)

    def test_celebracion_de_comunion_segun_cantidad(self):
        comunion = Sacramento.objects.get(codigo=Sacramento.COMUNION)
        uno = PlantillaTexto.resolver(PlantillaTexto.Clave.CELEBRACION, comunion, 1)
        dos = PlantillaTexto.resolver(PlantillaTexto.Clave.CELEBRACION, comunion, 2)
        self.assertTrue(uno.texto.startswith("Recibí "))
        self.assertTrue(dos.texto.startswith("Recibimos "))


class PlantillaTests(TestCase):
    def test_la_variante_le_gana_a_la_general(self):
        bautismo = Sacramento.objects.get(codigo=Sacramento.BAUTISMO)
        variante = crear_variante(codigo="Tarj3087")
        propia = PlantillaTexto.objects.create(
            clave=PlantillaTexto.Clave.CELEBRACION,
            variante=variante,
            texto="Te invitamos el {fecha}",
        )
        clave = PlantillaTexto.Clave.CELEBRACION
        self.assertEqual(PlantillaTexto.resolver(clave, bautismo, 1, variante), propia)
        self.assertNotEqual(PlantillaTexto.resolver(clave, bautismo, 1), propia)

    def test_no_permite_dos_para_el_mismo_caso(self):
        repetida = PlantillaTexto(clave=PlantillaTexto.Clave.TITULO_COMPLETO, texto="x")
        with self.assertRaises(ValidationError):
            repetida.full_clean()


class PedidoTests(TestCase):
    def test_historial_guarda_alta_y_cada_cambio(self):
        pedido = crear_pedido()
        pedido.estado = Pedido.Estado.IMPRESO
        pedido.save()
        pedido.save()
        cambios = list(
            pedido.historial.order_by("pk").values_list("estado_anterior", "estado_nuevo")
        )
        self.assertEqual(cambios, [("", "ingresado"), ("ingresado", "impreso")])


class EstampaTests(TestCase):
    def setUp(self):
        self.pedido = crear_pedido()
        self.estampa = Estampa.objects.create(
            pedido=self.pedido,
            variante=crear_variante(),
            fecha_celebracion=date(2026, 11, 14),
            parroquia="Colegio José Manuel Estrada",
        )

    def nino(self, nombre, pedido=None):
        return Nino.objects.create(pedido=pedido or self.pedido, nombre=nombre)

    def test_articulo_se_deduce_y_se_puede_cambiar(self):
        self.assertEqual(self.estampa.articulo_parroquia, "el")
        self.assertEqual(deducir_articulo("Parroquia San Pablo"), "la")
        self.estampa.articulo_parroquia = "la"
        self.estampa.save()
        self.estampa.refresh_from_db()
        self.assertEqual(self.estampa.articulo_parroquia, "la")

    def test_maximo_dos_chicos(self):
        self.estampa.ninos.add(self.nino("A"), self.nino("B"))
        with self.assertRaises(ValidationError):
            self.estampa.ninos.add(self.nino("C"))

    def test_maximo_dos_chicos_desde_el_chico(self):
        self.estampa.ninos.add(self.nino("A"), self.nino("B"))
        with self.assertRaises(ValidationError):
            self.nino("C").estampas.add(self.estampa)

    def test_chicos_del_mismo_pedido(self):
        otro = Pedido.objects.create(
            numero_factura="F2", numero_sapp="S2", fecha_entrega=date(2026, 12, 2)
        )
        with self.assertRaises(ValidationError):
            self.estampa.ninos.add(self.nino("Ajeno", otro))

    def test_oracion_del_banco_o_libre_pero_no_ambas(self):
        self.estampa.oracion = Oracion.objects.create(texto="Señor, guíame.")
        self.estampa.oracion_libre = "Otra"
        with self.assertRaises(ValidationError):
            self.estampa.clean()

    def test_fecha_por_sacramento_o_la_general(self):
        comunion, confirmacion = Sacramento.objects.filter(
            codigo__in=[Sacramento.COMUNION, Sacramento.CONFIRMACION]
        )
        general = EstampaSacramento.objects.create(estampa=self.estampa, sacramento=comunion)
        propia = EstampaSacramento.objects.create(
            estampa=self.estampa, sacramento=confirmacion, fecha=date(2026, 8, 2)
        )
        self.assertEqual(general.fecha_efectiva, date(2026, 11, 14))
        self.assertEqual(propia.fecha_efectiva, date(2026, 8, 2))


class OracionTests(TestCase):
    def test_sin_repetidas_ignorando_acentos_y_puntuacion(self):
        Oracion.objects.create(texto="Señor, haz de mí un instrumento.")
        repetida = Oracion(texto="senor haz de mi un instrumento")
        with self.assertRaises(ValidationError):
            repetida.full_clean()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            repetida.save()

    def test_primero_las_del_sacramento_elegido(self):
        bautismo = Sacramento.objects.get(codigo=Sacramento.BAUTISMO)
        otra = Oracion.objects.create(texto="A otra", numero=1)
        propia = Oracion.objects.create(texto="B propia", numero=2)
        propia.sacramentos.add(bautismo)
        lista = list(Oracion.objects.priorizar_sacramentos([bautismo]))
        self.assertEqual(lista, [propia, otra])


class ModeloTests(TestCase):
    def test_offset_por_pagina(self):
        modelo = ModeloTarjeta.objects.create(
            codigo="T",
            tipo=ModeloTarjeta.Tipo.ESTAMPA,
            ancho_mm=75,
            alto_mm=125,
            offset_x=1,
            offset_y=2,
            offset_x_reverso=3,
            offset_y_reverso=4,
        )
        self.assertEqual(modelo.offset(CuadroTexto.Pagina.ANVERSO), (1, 2))
        self.assertEqual(modelo.offset(CuadroTexto.Pagina.REVERSO), (3, 4))

    def test_variante_sin_oracion_si_existe(self):
        con = crear_variante(codigo="Tarj2059", nombre="base")
        sin = crear_variante(codigo="Tarj2059", nombre="Sin oración", lleva_oracion=False)
        self.assertEqual(con.modelo.variante_adecuada(con_oracion=False), sin)
        self.assertEqual(con.modelo.variante_adecuada(con_oracion=True), con)

    def test_sin_variante_sin_oracion_usa_la_que_hay(self):
        unica = crear_variante(codigo="Tarj2060")
        self.assertEqual(unica.modelo.variante_adecuada(con_oracion=False), unica)

    def test_color_segun_genero(self):
        cuadro = crear_cuadro(
            crear_variante(), color="806000", color_varon="0070C0", color_mujer="C00070"
        )
        self.assertEqual(cuadro.color_para([Genero.VARON]), "0070C0")
        self.assertEqual(cuadro.color_para([Genero.MUJER]), "C00070")
        self.assertEqual(cuadro.color_para([Genero.VARON, Genero.MUJER]), "806000")
        self.assertEqual(cuadro.color_para([""]), "806000")

    def test_color_sin_alternativo_usa_el_general(self):
        cuadro = crear_cuadro(crear_variante(), color="806000")
        self.assertEqual(cuadro.color_para([Genero.VARON]), "806000")


class DiplomaTests(TestCase):
    def setUp(self):
        self.bautismo = Sacramento.objects.get(codigo=Sacramento.BAUTISMO)
        self.comunion = Sacramento.objects.get(codigo=Sacramento.COMUNION)
        self.pedido = crear_pedido()
        self.estampa = Estampa.objects.create(
            pedido=self.pedido,
            variante=crear_variante(),
            fecha_celebracion=date(2026, 11, 14),
            parroquia="Parroquia X",
        )
        tipo = ModeloTarjeta.Tipo.DIPLOMA
        self.fem = crear_variante("dip_fem", tipo=tipo, genero=Genero.MUJER)
        self.masc = crear_variante("dip_masc", tipo=tipo, genero=Genero.VARON)
        self.fem.sacramentos.add(self.bautismo)
        self.masc.sacramentos.add(self.bautismo)
        self.dip_comunion = crear_variante("dip_com", tipo=tipo)
        self.dip_comunion.sacramentos.add(self.comunion)

    def chico(self, genero, sacramento):
        nino = Nino.objects.create(pedido=self.pedido, nombre="N", genero=genero)
        EstampaSacramento.objects.get_or_create(estampa=self.estampa, sacramento=sacramento)
        self.estampa.ninos.set([nino])
        return nino

    def test_elige_por_genero_y_sacramento(self):
        self.assertEqual(
            self.chico(Genero.MUJER, self.bautismo).diploma_que_corresponde(), self.fem
        )
        self.assertEqual(
            self.chico(Genero.VARON, self.bautismo).diploma_que_corresponde(), self.masc
        )

    def test_diploma_sin_genero_sirve_para_cualquiera(self):
        self.assertEqual(
            self.chico(Genero.VARON, self.comunion).diploma_que_corresponde(),
            self.dip_comunion,
        )

    def test_el_elegido_a_mano_tiene_prioridad(self):
        nino = self.chico(Genero.MUJER, self.bautismo)
        nino.diploma = self.masc
        self.assertEqual(nino.diploma_que_corresponde(), self.masc)

    def test_sin_genero_no_adivina_entre_fem_y_masc(self):
        self.assertIsNone(self.chico("", self.bautismo).diploma_que_corresponde())


class AdminTests(TestCase):
    def setUp(self):
        self.client.force_login(
            get_user_model().objects.create_superuser("prueba", password="x")
        )
        self.pedido = crear_pedido()
        self.variante = crear_variante()
        self.cuadro = crear_cuadro(self.variante)
        self.nino = Nino.objects.create(pedido=self.pedido, nombre="Ana")
        self.estampa = Estampa.objects.create(
            pedido=self.pedido,
            variante=self.variante,
            fecha_celebracion=date(2026, 11, 14),
            parroquia="Parroquia X",
        )

    def test_todas_las_pantallas_abren(self):
        objetos = {
            "modelotarjeta": self.variante.modelo,
            "variantelayout": self.variante,
            "cuadrotexto": self.cuadro,
            "oracion": Oracion.objects.create(texto="Señor"),
            "plantillatexto": PlantillaTexto.objects.first(),
            "pedido": self.pedido,
            "nino": self.nino,
            "estampa": self.estampa,
            "sacramento": Sacramento.objects.first(),
        }
        for modelo, objeto in objetos.items():
            for url in (
                reverse(f"admin:tarjetas_{modelo}_changelist"),
                reverse(f"admin:tarjetas_{modelo}_change", args=[objeto.pk]),
            ):
                with self.subTest(url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)
            if modelo != "sacramento":
                url = reverse(f"admin:tarjetas_{modelo}_add")
                with self.subTest(url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_corregir_el_rol_queda_registrado(self):
        url = reverse("admin:tarjetas_cuadrotexto_changelist")
        respuesta = self.client.post(
            url,
            {
                "form-TOTAL_FORMS": 1,
                "form-INITIAL_FORMS": 1,
                "form-0-id": self.cuadro.pk,
                "form-0-rol": CuadroTexto.Rol.NOMBRE,
                "_save": "Guardar",
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        self.cuadro.refresh_from_db()
        self.assertEqual(self.cuadro.rol, CuadroTexto.Rol.NOMBRE)
        self.assertTrue(self.cuadro.rol_corregido)

    def test_mas_de_dos_chicos_es_error_de_formulario(self):
        ninos = [Nino.objects.create(pedido=self.pedido, nombre=n) for n in "BCD"]
        comunion = Sacramento.objects.get(codigo=Sacramento.COMUNION)
        respuesta = self.client.post(
            reverse("admin:tarjetas_estampa_change", args=[self.estampa.pk]),
            {
                "pedido": self.pedido.pk,
                "variante": self.variante.pk,
                "ninos": [n.pk for n in ninos],
                "fecha_celebracion": "2026-11-14",
                "parroquia": "Parroquia X",
                "cantidad": 1,
                "estampasacramento_set-TOTAL_FORMS": 1,
                "estampasacramento_set-INITIAL_FORMS": 0,
                "estampasacramento_set-MIN_NUM_FORMS": 1,
                "estampasacramento_set-MAX_NUM_FORMS": 1000,
                "estampasacramento_set-0-sacramento": comunion.pk,
            },
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "como máximo 2 chicos")
