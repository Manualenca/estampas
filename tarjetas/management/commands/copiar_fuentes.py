from django.conf import settings
from django.core.management.base import BaseCommand

from tarjetas import fuentes
from tarjetas.models import CuadroTexto, EstiloLinea


class Command(BaseCommand):
    help = "Copia a fuentes/ las fuentes que usan los modelos, desde Windows y la nube de Office."

    def handle(self, *args, **options):
        familias = set(CuadroTexto.objects.values_list("fuente", flat=True))
        familias |= set(EstiloLinea.objects.exclude(fuente="").values_list("fuente", flat=True))
        copiadas, faltantes, generadas = fuentes.copiar(sorted(familias), settings.FUENTES_DIR)
        for familia, origen, ejes in generadas:
            valores = ", ".join(f"{eje}={valor:g}" for eje, valor in ejes.items())
            self.stdout.write(f"Generada desde la fuente variable {origen} ({valores}): {familia}")

        por_familia = {}
        for cara in copiadas:
            por_familia.setdefault(cara.familia, []).append(cara.estilo)
        self.stdout.write(self.style.MIGRATE_HEADING(f"Fuentes copiadas a {settings.FUENTES_DIR}"))
        for familia in sorted(por_familia):
            estilos = ", ".join(sorted(por_familia[familia]))
            self.stdout.write(f"  {familia}: {estilos}")
        sin_variantes = [f for f, e in por_familia.items() if len(e) == 1]
        if sin_variantes:
            self.stdout.write(
                "Con un solo estilo (la negrita y la cursiva se simulan): "
                + ", ".join(sorted(sin_variantes))
            )
        if faltantes:
            self.stdout.write(self.style.WARNING("No encontradas: " + ", ".join(faltantes)))
