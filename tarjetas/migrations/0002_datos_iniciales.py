from django.db import migrations

SACRAMENTOS = [
    ("bautismo", "Bautismo", "Nuestro", 1),
    ("comunion", "Primera Comunión", "Nuestra", 2),
    ("confirmacion", "Confirmación", "Nuestra", 3),
]

# (clave, código de sacramento, cantidad de chicos, texto). None = cualquiera.
PLANTILLAS = [
    ("titulo_completo", None, None, "Recuerdo de {Posesivo} {sacramentos}"),
    ("titulo_sin_recuerdo", None, None, "{Posesivo} {sacramentos}"),
    (
        "celebracion",
        "comunion",
        1,
        "Recibí la Santa Eucaristía el {fecha} en {articulo} {parroquia}.\n{localidad}",
    ),
    (
        "celebracion",
        "comunion",
        2,
        "Recibimos la Santa Eucaristía el {fecha} en {articulo} {parroquia}.\n{localidad}",
    ),
    ("celebracion", "confirmacion", None, "{linea_padrinos}\n{fecha}\n{parroquia}\n{localidad}"),
    (
        "celebracion",
        "bautismo",
        None,
        "{linea_nacimiento}\n{linea_padres}\n{linea_padrinos}\n{fecha}\n{parroquia}\n{localidad}",
    ),
    ("padrinos_ambos", None, None, "Mis Padrinos: {padrino}\n{madrina}"),
    ("padrinos_ambos", "bautismo", None, "Mis Padrinos: {madrina} y {padrino}"),
    ("padrinos_solo_padrino", None, None, "Mi Padrino: {padrino}"),
    ("padrinos_solo_madrina", None, None, "Mi Madrina: {madrina}"),
    ("padres_ambos", None, None, "Mis Papis: {madre} y {padre}"),
    ("padres_solo_padre", None, None, "Mi Papá: {padre}"),
    ("padres_solo_madre", None, None, "Mi Mamá: {madre}"),
    ("nacimiento", None, 1, "Nací el {fecha_nacimiento}"),
]


def cargar(apps, schema_editor):
    Sacramento = apps.get_model("tarjetas", "Sacramento")
    PlantillaTexto = apps.get_model("tarjetas", "PlantillaTexto")
    por_codigo = {}
    for codigo, nombre, posesivo, orden in SACRAMENTOS:
        por_codigo[codigo], _ = Sacramento.objects.get_or_create(
            codigo=codigo,
            defaults={"nombre": nombre, "posesivo_plural": posesivo, "orden": orden},
        )
    for clave, sacramento, cantidad, texto in PLANTILLAS:
        PlantillaTexto.objects.get_or_create(
            clave=clave,
            sacramento=por_codigo.get(sacramento),
            cantidad_ninos=cantidad,
            variante=None,
            defaults={"texto": texto},
        )


class Migration(migrations.Migration):
    dependencies = [("tarjetas", "0001_initial")]

    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
