"""Push the local ``data/*.json`` files to R2, overriding whatever is there.

The inverse of :mod:`seed_r2`: that command seeds an *empty* bucket from local
JSON; this one overwrites a *live* bucket with the current local files. Because
that's destructive, every push first downloads each key's existing R2 object
into a timestamped backup directory (skipped only for keys R2 doesn't have yet),
and asks for confirmation before uploading::

    python manage.py push_r2                 # from settings.DATA_DIR
    python manage.py push_r2 --source /path   # push a different local directory
    python manage.py push_r2 --yes            # skip the confirmation prompt

Requires R2 credentials in the environment (``R2_ACCOUNT_ID``/``R2_ENDPOINT_URL``,
``R2_ACCESS_KEY_ID``, ``R2_SECRET_ACCESS_KEY``, ``R2_BUCKET_NAME`` — see
``.env.example``); it talks to :class:`~utils.r2_storage.R2Storage` directly
rather than through the :data:`~utils.r2_storage.storage` facade, so it fails
loudly instead of silently falling back to the local store when R2 isn't
configured.
"""

import json
import os
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.management.commands.seed_r2 import SEED_FILES
from utils.r2_storage import ObjectNotFound, R2Storage


class Command(BaseCommand):
    help = "Push local data/*.json files to R2, backing up the previous R2 objects first."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=settings.DATA_DIR,
            help="Local directory holding the JSON files to push (default: settings.DATA_DIR).",
        )
        parser.add_argument(
            "--backup-dir",
            default=None,
            help="Where to save the pre-push R2 backup (default: <source>/r2_backups/<timestamp>).",
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip the confirmation prompt before overriding R2.",
        )

    def handle(self, *args, **options):
        if not R2Storage.is_configured():
            missing = [
                name
                for name in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME")
                if not os.environ.get(name)
            ]
            if not (os.environ.get("R2_ENDPOINT_URL") or os.environ.get("R2_ACCOUNT_ID")):
                missing.append("R2_ENDPOINT_URL or R2_ACCOUNT_ID")
            raise CommandError(
                "R2 is not configured — missing: " + ", ".join(missing) + ". "
                "Set these in backend/.env (see .env.example) before pushing."
            )

        source = options["source"]
        r2 = R2Storage()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = options["backup_dir"] or os.path.join(source, "r2_backups", timestamp)

        # Load the local files up front so a missing/invalid one aborts before
        # anything is backed up or touched on R2.
        local_data = {}
        for name in SEED_FILES:
            path = os.path.join(source, name)
            if not os.path.exists(path):
                self.stdout.write(self.style.WARNING(f"skip {name} (not found in {source})"))
                continue
            with open(path, "r", encoding="utf-8") as fh:
                local_data[name] = json.load(fh)

        if not local_data:
            raise CommandError(f"no seed files found in {source}; nothing to push.")

        if not options["yes"]:
            bucket = os.environ["R2_BUCKET_NAME"]
            confirm = input(
                f"This will overwrite {len(local_data)} object(s) in R2 bucket "
                f"'{bucket}' with the contents of {source}. Continue? [y/N] "
            )
            if confirm.strip().lower() not in ("y", "yes"):
                self.stdout.write("Aborted.")
                return

        # Back up whatever R2 currently holds before overriding anything.
        os.makedirs(backup_dir, exist_ok=True)
        backed_up = []
        for name in SEED_FILES:
            try:
                existing = r2.download_json(name)
            except ObjectNotFound:
                self.stdout.write(self.style.WARNING(f"no existing R2 object for {name}, skipping backup"))
                continue
            backup_path = os.path.join(backup_dir, name)
            with open(backup_path, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, ensure_ascii=False, indent=2)
            backed_up.append(name)
        if backed_up:
            self.stdout.write(self.style.SUCCESS(f"backed up {len(backed_up)} object(s) to {backup_dir}"))

        # Now override R2 with the local files.
        for name, data in local_data.items():
            r2.upload_json(name, data)
            self.stdout.write(self.style.SUCCESS(f"pushed {name} -> r2://{name}"))
