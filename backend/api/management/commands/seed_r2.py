"""Upload the local ``data/*.json`` seed files into the R2 bucket.

The route/graph store now lives in R2 (see :mod:`api.db`). A fresh bucket has no
objects, so :meth:`Database._ensure_files` would initialise an *empty* store and
the authored routes would be missing. Run this once (with prod R2 credentials) to
seed the bucket from the JSON that used to live on disk::

    python manage.py seed_r2                 # from settings.DATA_DIR
    python manage.py seed_r2 --source /path  # from another directory
"""

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from utils import r2_storage

# The three objects the store owns. Each local filename maps 1:1 to its R2 key
# (the app uses bare, unprefixed keys — see api/db.py).
SEED_FILES = ["routes.json", "edge_routes.json", "compromised.json"]


class Command(BaseCommand):
    help = "Upload the local data/*.json seed files into the R2 bucket."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=settings.DATA_DIR,
            help="Local directory holding the seed JSON files (default: settings.DATA_DIR).",
        )

    def handle(self, *args, **options):
        source = options["source"]
        for name in SEED_FILES:
            path = os.path.join(source, name)
            if not os.path.exists(path):
                self.stdout.write(self.style.WARNING(f"skip {name} (not found in {source})"))
                continue
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            r2_storage.upload_json(name, data)
            self.stdout.write(self.style.SUCCESS(f"uploaded {name} -> r2://{name}"))
