from django.contrib.staticfiles.management.commands.runserver import (
    Command as RunserverCommand,
)


class Command(RunserverCommand):
    """Usa el puerto 8001 por defecto: el 8000 lo ocupa otro sistema."""

    default_port = "8001"
