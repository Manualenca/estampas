import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

PREFIJO = "db_"
PATRON = f"{PREFIJO}*.sqlite3"


class Command(BaseCommand):
    help = "Copia la base a la carpeta de backups y conserva solo las últimas copias."

    def handle(self, *args, **options):
        destino = Path(settings.BACKUP_DIR)
        destino.mkdir(parents=True, exist_ok=True)
        marca = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        archivo = destino / f"{PREFIJO}{marca}.sqlite3"
        temporal = archivo.with_suffix(".tmp")

        # Copia con la API de SQLite: es consistente aunque el sistema esté en uso.
        try:
            connection.ensure_connection()
            copia = sqlite3.connect(temporal)
            try:
                connection.connection.backup(copia)
                resultado = copia.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                copia.close()
            if resultado != "ok":
                raise CommandError(f"La copia salió dañada: {resultado}")
            temporal.replace(archivo)
        finally:
            temporal.unlink(missing_ok=True)

        copias = sorted(destino.glob(PATRON), key=lambda p: p.name, reverse=True)
        for vieja in copias[settings.BACKUPS_A_CONSERVAR :]:
            vieja.unlink()

        conservadas = min(len(copias), settings.BACKUPS_A_CONSERVAR)
        self.stdout.write(
            self.style.SUCCESS(f"Backup creado: {archivo} ({conservadas} copias conservadas)")
        )
