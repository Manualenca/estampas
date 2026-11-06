import shutil
import tempfile
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import CalibracionForm
from .models import ModeloTarjeta, Nino, Pedido
from .views import alerta_de_entrega


class PantallaPrincipalTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("prueba", password="x"))
        self.hoy = timezone.localdate()

    def pedido(self, factura, dias, estado=Pedido.Estado.INGRESADO, sapp="S"):
        pedido = Pedido.objects.create(
            numero_factura=factura, numero_sapp=sapp, fecha_entrega=self.hoy + timedelta(days=dias)
        )
        if estado != Pedido.Estado.INGRESADO:
            pedido.estado = estado
            pedido.save()
        return pedido

    def columnas(self, **parametros):
        respuesta = self.client.get(reverse("inicio"), parametros)
        self.assertEqual(respuesta.status_code, 200)
        return {c["estado"].value: c for c in respuesta.context["columnas"]}

    def test_agrupa_por_estado(self):
        self.pedido("A", 10)
        self.pedido("B", 10, Pedido.Estado.IMPRESO)
        self.pedido("C", 10, Pedido.Estado.ENVIADO)
        columnas = self.columnas()
        facturas = {estado: [p.numero_factura for p in c["pedidos"]] for estado, c in columnas.items()}
        self.assertEqual(facturas, {"ingresado": ["A"], "impreso": ["B"], "enviado": ["C"]})

    def test_atrasados_en_rojo_y_por_vencer_en_amarillo(self):
        atrasado = self.pedido("Atrasado", -1)
        hoy = self.pedido("Hoy", 0)
        tres = self.pedido("Tres", 3)
        cuatro = self.pedido("Cuatro", 4)
        enviado = self.pedido("Enviado", -5, Pedido.Estado.ENVIADO)
        self.assertEqual(alerta_de_entrega(atrasado, self.hoy), "atrasado")
        self.assertEqual(alerta_de_entrega(hoy, self.hoy), "vence")
        self.assertEqual(alerta_de_entrega(tres, self.hoy), "vence")
        self.assertEqual(alerta_de_entrega(cuatro, self.hoy), "")
        self.assertEqual(alerta_de_entrega(enviado, self.hoy), "")
        pagina = self.client.get(reverse("inicio"))
        self.assertContains(pagina, 'class="tarjeta-pedido atrasado"')
        self.assertContains(pagina, 'class="tarjeta-pedido vence"')
        self.assertEqual(self.columnas()["ingresado"]["atrasados"], 1)

    def test_busca_por_factura_sapp_y_nombre_sin_acentos(self):
        primero = self.pedido("F-100", 5, sapp="9001")
        segundo = self.pedido("F-200", 5, sapp="9002")
        Nino.objects.create(pedido=segundo, nombre="María Belén Gómez")
        encontrados = lambda q: [p.numero_factura for c in self.columnas(q=q).values() for p in c["pedidos"]]  # noqa: E731
        self.assertEqual(encontrados("f-100"), ["F-100"])
        self.assertEqual(encontrados("9002"), ["F-200"])
        self.assertEqual(encontrados("maria belen"), ["F-200"])
        self.assertEqual(encontrados("nadie"), [])
        self.assertIsNotNone(primero)

    def test_filtro_por_rango_de_entrega(self):
        self.pedido("Antes", 1)
        self.pedido("Dentro", 10)
        self.pedido("Despues", 30)
        columnas = self.columnas(
            desde=(self.hoy + timedelta(days=5)).isoformat(),
            hasta=(self.hoy + timedelta(days=15)).isoformat(),
        )
        self.assertEqual([p.numero_factura for p in columnas["ingresado"]["pedidos"]], ["Dentro"])

    def test_contador_del_mes_por_estado(self):
        mes = date(2026, 11, 1)
        for factura, dia, estado in (("A", 5, "ingresado"), ("B", 20, "impreso"), ("C", 30, "impreso")):
            pedido = Pedido.objects.create(numero_factura=factura, numero_sapp="S", fecha_entrega=mes.replace(day=dia))
            pedido.estado = estado
            pedido.save()
        Pedido.objects.create(numero_factura="D", numero_sapp="S", fecha_entrega=date(2026, 12, 1))
        respuesta = self.client.get(reverse("inicio"), {"mes": "2026-11"})
        self.assertEqual(
            respuesta.context["contador"], [("Ingresado", 1), ("Impreso", 2), ("Enviado", 0)]
        )
        self.assertEqual(respuesta.context["total_mes"], 3)
        self.assertEqual(respuesta.context["mes_siguiente"], "2026-12")
        self.assertEqual(respuesta.context["mes_anterior"], "2026-10")

    def test_historial_en_el_pedido(self):
        pedido = self.pedido("H", 5)
        self.client.post(reverse("pedido_estado", args=[pedido.pk]), {"estado": "impreso", "volver": "pedido_detalle"})
        pagina = self.client.get(reverse("pedido_detalle", args=[pedido.pk]))
        self.assertContains(pagina, "Historial de estados")
        self.assertEqual(len(pagina.context["historial"]), 2)
        self.assertContains(pagina, "Marcar como enviado")


class CalibracionProbadaTests(TestCase):
    def setUp(self):
        self.modelo = ModeloTarjeta.objects.create(
            codigo="2059", tipo=ModeloTarjeta.Tipo.ESTAMPA, ancho_mm=75, alto_mm=125
        )

    def guardar(self, **datos):
        base = {"offset_x": "0", "offset_y": "0", "offset_x_reverso": "0", "offset_y_reverso": "0"}
        base.update(datos)
        formulario = CalibracionForm(base, instance=self.modelo)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        formulario.save()
        self.modelo.refresh_from_db()

    def test_estados_de_calibracion(self):
        estados = ModeloTarjeta.EstadoCalibracion
        self.assertEqual(self.modelo.estado_calibracion, estados.SIN_CALIBRAR)
        self.guardar(offset_x="1.5")
        self.assertEqual(self.modelo.estado_calibracion, estados.SIN_PROBAR)
        self.guardar(offset_x="1.5", calibracion_probada="on")
        self.assertEqual(self.modelo.estado_calibracion, estados.PROBADA)
        self.assertIsNotNone(self.modelo.calibracion_probada_el)

    def test_cambiar_el_ajuste_vuelve_a_falta_probar(self):
        self.guardar(offset_x="1.5", calibracion_probada="on")
        self.guardar(offset_x="2", calibracion_probada="on")  # Casilla que ya venía marcada.
        self.assertFalse(self.modelo.calibracion_probada)
        self.assertIsNone(self.modelo.calibracion_probada_el)

    def test_lista_de_modelos_filtra_los_que_faltan(self):
        otro = ModeloTarjeta.objects.create(
            codigo="2060", tipo=ModeloTarjeta.Tipo.ESTAMPA, ancho_mm=75, alto_mm=125,
            offset_x=1, calibracion_probada=True,
        )
        self.client.force_login(get_user_model().objects.create_superuser("p", password="x"))
        respuesta = self.client.get(reverse("modelos"), {"calibracion": "sin_calibrar"})
        self.assertEqual([m.codigo for m in respuesta.context["modelos"]], ["2059"])
        self.assertContains(self.client.get(reverse("modelos")), "Probada en impresora")
        self.assertTrue(otro.calibracion_probada)


class BackupSiHaceFaltaTests(TestCase):
    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.carpeta, ignore_errors=True)

    def backup(self, *argumentos):
        with override_settings(BACKUP_DIR=self.carpeta):
            call_command("backup_db", *argumentos, stdout=StringIO())
        return sorted(p.name for p in self.carpeta.glob("db_*.sqlite3"))

    def test_no_copia_si_hay_uno_reciente(self):
        reciente = datetime.now() - timedelta(hours=2)
        (self.carpeta / f"db_{reciente:%Y-%m-%d_%H%M%S}.sqlite3").write_text("x")
        self.assertEqual(len(self.backup("--si-hace-falta")), 1)

    def test_copia_si_el_ultimo_es_viejo_y_lo_registra(self):
        viejo = datetime.now() - timedelta(hours=30)
        (self.carpeta / f"db_{viejo:%Y-%m-%d_%H%M%S}.sqlite3").write_text("x")
        self.assertEqual(len(self.backup("--si-hace-falta")), 2)
        self.assertIn(" OK db_", (self.carpeta / "backups.log").read_text(encoding="utf-8"))


class LanzadorTests(TestCase):
    def test_lanzador_usa_el_puerto_8001_y_el_entorno(self):
        lanzador = (Path(settings.BASE_DIR) / "Estampas.bat").read_bytes()
        self.assertIn(b"\r\n", lanzador)  # cmd necesita finales de línea de Windows.
        texto = lanzador.decode("ascii")
        self.assertIn('set "ESTAMPAS_PUERTO=8001"', texto)
        self.assertIn(r"%USERPROFILE%\.virtualenvs\estampas", texto)
        self.assertIn("backup_db --si-hace-falta", texto)


class CopiaExtraTests(TestCase):
    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.carpeta, ignore_errors=True)
        self.principal = self.carpeta / "backups"
        self.extra = self.carpeta / "onedrive"

    def backup(self, extra):
        salida, errores = StringIO(), StringIO()
        with override_settings(BACKUP_DIR=self.principal, BACKUP_EXTRA_DIR=extra, BACKUPS_EXTRA_A_CONSERVAR=7):
            call_command("backup_db", stdout=salida, stderr=errores)
        return errores.getvalue()

    def test_copia_y_conserva_las_ultimas_7(self):
        self.extra.mkdir()
        for i in range(8):
            (self.extra / f"db_2020-01-0{i + 1}_000000.sqlite3").write_text("x")
        (self.extra / "mio.txt").write_text("no tocar")
        self.backup(self.extra)
        copias = sorted(p.name for p in self.extra.glob("db_*.sqlite3"))
        self.assertEqual(len(copias), 7)
        self.assertNotIn("db_2020-01-01_000000.sqlite3", copias)
        self.assertEqual(copias[-1], next(self.principal.glob("db_*.sqlite3")).name)
        self.assertTrue((self.extra / "mio.txt").exists())
        self.assertEqual(list(self.extra.glob("*.tmp")), [])

    def test_si_la_carpeta_no_existe_registra_y_sigue(self):
        errores = self.backup(self.carpeta / "no_existe")
        self.assertEqual(len(list(self.principal.glob("db_*.sqlite3"))), 1)
        registro = (self.principal / "backups.log").read_text(encoding="utf-8")
        self.assertIn(" OK db_", registro)
        self.assertIn("ERROR copia extra: la carpeta no existe", registro)
        self.assertIn("No se pudo hacer la copia extra", errores)
        self.assertFalse((self.carpeta / "no_existe").exists())

    def test_sin_configurar_no_copia(self):
        self.backup(None)
        self.assertNotIn("copia extra", (self.principal / "backups.log").read_text(encoding="utf-8"))


class BackupSinConsolaTests(TestCase):
    """La tarea programada corre con pythonw.exe: sys.stdout y sys.stderr son None."""

    def test_sin_consola_hace_la_copia_extra(self):
        from unittest import mock

        from .management.commands.backup_db import Command

        carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, carpeta, ignore_errors=True)
        extra = carpeta / "onedrive"
        extra.mkdir()
        with override_settings(BACKUP_DIR=carpeta / "backups", BACKUP_EXTRA_DIR=extra), \
                mock.patch("sys.stdout", None), mock.patch("sys.stderr", None):
            Command().handle(si_hace_falta=False)
        self.assertEqual(len(list(extra.glob("db_*.sqlite3"))), 1)
        self.assertIn("OK copia extra", (carpeta / "backups" / "backups.log").read_text(encoding="utf-8"))
