import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

PREFIJO = "db_"
PATRON = f"{PREFIJO}*.sqlite3"
FORMATO = "%Y-%m-%d_%H%M%S"
REGISTRO = "backups.log"


def ultimo_backup(carpeta):
    """Fecha y hora del backup más nuevo, según su nombre. None si no hay."""
    fechas = []
    for archivo in Path(carpeta).glob(PATRON):
        try:
            fechas.append(datetime.strptime(archivo.stem[len(PREFIJO):], FORMATO))
        except ValueError:
            continue
    return max(fechas, default=None)


class Command(BaseCommand):
    help = "Copia la base a la carpeta de backups y conserva solo las últimas copias."

    def add_arguments(self, parser):
        parser.add_argument(
            "--si-hace-falta",
            action="store_true",
            help="Solo copia si el último backup tiene más de 24 horas (lo usa el lanzador).",
        )

    def handle(self, *args, si_hace_falta=False, **options):
        destino = Path(settings.BACKUP_DIR)
        destino.mkdir(parents=True, exist_ok=True)
        if si_hace_falta:
            ultimo = ultimo_backup(destino)
            if ultimo and datetime.now() - ultimo < timedelta(hours=24):
                self.stdout.write(f"No hace falta: el último backup es del {ultimo:%d/%m/%Y %H:%M}.")
                return
        try:
            archivo, conservadas = self._copiar(destino)
        except Exception as error:
            self._registrar(destino, f"ERROR: {error}")
            raise
        self._registrar(destino, f"OK {archivo.name}")
        self.stdout.write(
            self.style.SUCCESS(f"Backup creado: {archivo} ({conservadas} copias conservadas)")
        )
        self._copia_extra(archivo, destino)

    def _copia_extra(self, archivo, destino):
        """Copia el backup a BACKUP_EXTRA_DIR. Si falla, lo registra sin cortar el principal."""
        extra = settings.BACKUP_EXTRA_DIR
        if not extra:
            return
        extra = Path(extra)
        try:
            if not extra.is_dir():
                raise FileNotFoundError(f"la carpeta no existe: {extra}")
            final = extra / archivo.name
            temporal = final.with_suffix(".tmp")
            shutil.copy2(archivo, temporal)
            temporal.replace(final)  # Sin archivos a medio copiar en la carpeta sincronizada.
            copias = sorted(extra.glob(PATRON), key=lambda p: p.name, reverse=True)
            for vieja in copias[settings.BACKUPS_EXTRA_A_CONSERVAR :]:
                vieja.unlink()
        except Exception as error:  # noqa: BLE001 - la copia extra nunca corta el backup principal.
            self._registrar(destino, f"ERROR copia extra: {error}")
            self.stderr.write(self.style.WARNING(f"No se pudo hacer la copia extra: {error}"))
            return
        self._registrar(destino, f"OK copia extra {final}")
        self.stdout.write(f"Copia extra: {final}")

    def _copiar(self, destino):
        archivo = destino / f"{PREFIJO}{datetime.now().strftime(FORMATO)}.sqlite3"
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
        return archivo, min(len(copias), settings.BACKUPS_A_CONSERVAR)

    @staticmethod
    def _registrar(destino, mensaje):
        """Deja constancia en backups.log: la tarea programada corre sin ventana."""
        with open(destino / REGISTRO, "a", encoding="utf-8") as registro:
            registro.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {mensaje}\n")
