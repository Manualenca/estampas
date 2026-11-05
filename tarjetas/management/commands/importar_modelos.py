from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tarjetas.importador import Importador


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
                "imágenes de fondo y los roles corregidos a mano."
            ),
        )

    def handle(self, *args, ruta=None, actualizar=False, **options):
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
