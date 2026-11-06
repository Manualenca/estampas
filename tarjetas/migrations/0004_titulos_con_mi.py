from django.db import migrations

CLAVES_TITULO = ("titulo_completo", "titulo_sin_recuerdo")


def usar_mi_mayuscula(apps, schema_editor):
    """En los títulos va "Mi" con mayúscula: "Recuerdo de Mi Primera Comunión"."""
    PlantillaTexto = apps.get_model("tarjetas", "PlantillaTexto")
    for plantilla in PlantillaTexto.objects.filter(clave__in=CLAVES_TITULO):
        texto = plantilla.texto.replace("{posesivo}", "{Posesivo}")
        if texto != plantilla.texto:
            plantilla.texto = texto
            plantilla.save(update_fields=["texto"])


class Migration(migrations.Migration):
    dependencies = [("tarjetas", "0003_ayuda_variable_anio")]

    operations = [migrations.RunPython(usar_mi_mayuscula, migrations.RunPython.noop)]
