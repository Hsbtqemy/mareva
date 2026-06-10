"""
Sauvegarde complète de l'étude : base de données + médias, dans une archive
.zip horodatée.

  python manage.py sauvegarde
  python manage.py sauvegarde --sortie /chemin/vers/sauvegardes

Restauration : voir README (section « Sauvegardes »).
"""
from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Crée une sauvegarde horodatée (base + médias) dans un fichier .zip."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sortie", default="sauvegardes",
            help="Dossier de destination de l'archive (défaut : sauvegardes/).",
        )

    def handle(self, *args, **options):
        dossier = Path(options["sortie"])
        dossier.mkdir(parents=True, exist_ok=True)
        horodatage = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        archive = dossier / f"sauvegarde_{horodatage}.zip"

        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            self._sauver_base(z)
            self._sauver_medias(z)

        self.stdout.write(self.style.SUCCESS(f"Sauvegarde créée : {archive}"))

    def _sauver_base(self, z):
        if connection.vendor == "sqlite":
            # Copie COHÉRENTE de la base en cours via l'API backup de SQLite
            # (sûre même si l'application tourne).
            connection.ensure_connection()
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d) / "db.sqlite3"
                dst = sqlite3.connect(str(tmp))
                try:
                    with dst:
                        connection.connection.backup(dst)
                finally:
                    dst.close()
                z.write(tmp, "base/db.sqlite3")  # dossier temp supprimé à la sortie du with
        else:
            # Autre moteur (ex. PostgreSQL) : export JSON portable et rechargeable.
            buf = StringIO()
            call_command(
                "dumpdata", indent=2, natural_foreign=True,
                exclude=["contenttypes", "auth.permission"], stdout=buf,
            )
            z.writestr("base/dumpdata.json", buf.getvalue())

    def _sauver_medias(self, z):
        media = Path(settings.MEDIA_ROOT)
        if not media.exists():
            return
        for f in media.rglob("*"):
            if f.is_file():
                arcname = (Path("media") / f.relative_to(media)).as_posix()
                z.write(f, arcname)
