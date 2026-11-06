from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tarjetas.importador import Importador, aplicar_estilos
from tarjetas.models import ModeloTarjeta, VarianteLayout


class Command(BaseCommand):
    help = (
        "Importa modelos, variantes, cuadros y oraciones desde los .docx. Sin argumentos "
        "recorre modelos_docx e importa solo lo que falta."
    )

    def add_arguments(self, parser):
        parser.add_argument("ruta", nargs="?", help="Importa solo este archivo .docx.")
        parser.add_argument(
            "--actualizar",
            action="store_true",
            help=(
                "Si el modelo ya existe, actualiza sus cuadros. Conserva la calibración, las "
                "imágenes de fondo y los roles y posiciones corregidos a mano."
            ),
        )
        parser.add_argument(
            "--estilos",
            action="store_true",
            help=(
                "Lleva a las plantillas de cada variante la negrita por partes del .docx "
                '(por ejemplo "**Mi Madrina:** Eva"). Solo trabaja sobre lo ya importado.'
            ),
        )

    def handle(self, *args, ruta=None, actualizar=False, estilos=False, **options):
        if estilos:
            return self._estilos(ruta)
        importador = Importador(actualizar=actualizar)
        if ruta:
            archivo = Path(ruta)
            if not archivo.is_file():
                raise CommandError(f"No existe el archivo: {ruta}")
            importador.importar_archivo(archivo)
            resultado = importador.resultado
        else:
            resultado = importador.importar_todo()
        self._mostrar(resultado)

    def _estilos(self, ruta):
        variantes = VarianteLayout.objects.filter(modelo__tipo=ModeloTarjeta.Tipo.ESTAMPA)
        if ruta:
            origen = Importador()._ruta_relativa(Path(ruta).resolve())
            variantes = variantes.filter(archivo_origen=origen)
            if not variantes.exists():
                raise CommandError(f"El archivo no está importado: {ruta}")
        cambios, no_aplicadas = [], []
        raiz = Path(settings.MODELOS_DOCX_DIR)
        with transaction.atomic():
            for variante in variantes.order_by("modelo__codigo", "nombre"):
                archivo = raiz / variante.archivo_origen
                if not archivo.is_file():
                    no_aplicadas.append(f"{variante.archivo_origen}: no se encontró el archivo")
                    continue
                propios, pendientes = aplicar_estilos(variante, archivo)
                cambios += propios
                no_aplicadas += pendientes

        self.stdout.write(self.style.MIGRATE_HEADING("Negrita por partes"))
        self.stdout.write(f"  Plantillas cambiadas: {len(cambios)}")
        actual = None
        for cambio in cambios:
            if cambio.variante != actual:
                actual = cambio.variante
                self.stdout.write(f"\n{actual}   (en el .docx: {cambio.docx})")
            self.stdout.write(f"  {cambio.plantilla}")
            self.stdout.write(f"    antes:   {cambio.antes!r}")
            self.stdout.write(f"    después: {cambio.despues!r}")
        if no_aplicadas:
            self.stdout.write("\nNo se aplicaron (revisalas a mano):")
            for linea in no_aplicadas:
                self.stdout.write(f"  - {linea}")

    def _mostrar(self, r):
        self.stdout.write(self.style.MIGRATE_HEADING("Resumen"))
        self.stdout.write(f"  Modelos nuevos: {len(r.modelos_nuevos)}")
        self.stdout.write(f"  Archivos importados (variantes nuevas): {len(r.nuevos)}")
        self.stdout.write(f"  Archivos actualizados: {len(r.actualizados)}")
        self.stdout.write(f"  Archivos que ya estaban en la base: {len(r.ya_importados)}")
        self.stdout.write(f"  Oraciones nuevas: {r.oraciones_nuevas}")
        self.stdout.write(f"  Cuadros sin asignar: {len(r.sin_asignar)}")
        self._lista("Cuadros sin asignar (corregilos en el admin)", r.sin_asignar)
        self._lista("Cuadros descartados", r.descartados)
        self._lista("Archivos omitidos", r.omitidos)
        self._lista("Oraciones sin sacramento", r.oraciones_sin_sacramento)
        if r.errores:
            self.stderr.write(self.style.ERROR(f"Archivos con error: {len(r.errores)}"))
            for origen, error in r.errores:
                self.stderr.write(f"  {origen}: {error}")

    def _lista(self, titulo, elementos):
        if elementos:
            self.stdout.write(f"{titulo}:")
            for elemento in elementos:
                self.stdout.write(f"  - {elemento}")
