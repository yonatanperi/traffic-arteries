"""One-time migration: convert ``routes.json``/``compromised.json`` from
name-string storage to id-based storage, populating the new ``places.json``
registry along the way.

Every place currently appears as a full display-name string (e.g. ``"מ.
אלפורן"``, ``"צ. גומא"``) baked directly into ``routes.json``/``compromised.json``.
This command assigns each one a numeric id (:mod:`api.place_groups` classifies
it by its prefix, defaulting to ``"other"`` when none matches) and rewrites
both files to reference places by id — exactly what an ordinary
:meth:`~api.db.Database.save_routes` call already does for *any* payload, so
this is really just that call applied once to everything currently stored::

    python manage.py migrate_place_groups --dry-run   # report only, writes nothing
    python manage.py migrate_place_groups              # the real run

No collision detection is needed (unlike an earlier design that tried to key
the registry by base name alone): ids are minted per currently-distinct
*string*, which is trivially already unique — that's the status quo identity.
Two places that share a base name after stripping their prefix (e.g. "מ. גולני"
and "מחלף גולני", both real, distinct places in this network) simply get
distinct ids, same as they're already distinct strings today.

Idempotent, and safe to re-run whenever ``api.place_groups.PREFIX_PATTERNS``
gains a new group: once ``places.json`` is populated, this command switches
from "convert strings to ids" to "reclassify" — any place still parked in
``"other"`` whose name matches a prefix that wasn't recognized when it was
first classified (e.g. a brand-new group) gets its group corrected in place.
This never touches ``routes.json``/``edge_routes.json`` — a place's id is its
real identity, so recoloring its group is a pure registry edit.
"""

import json
import os
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand

from api.db import database, expand_routes
from api.place_groups import DEFAULT_GROUP, parse_prefixed_name
from utils.r2_storage import ObjectNotFound, storage


class Command(BaseCommand):
    help = "One-time migration: convert routes.json/compromised.json to id-based storage, populating places.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change (group counts, a sample of assignments) without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        registry = database.load_place_registry()
        if registry:
            self._reclassify_other_places(registry, dry_run)
            return

        routes = database._normalised_routes()  # raw, untranslated — registry is empty at this point
        try:
            raw_compromised = storage.download_json(database.compromised_key)
        except ObjectNotFound:
            raw_compromised = []

        all_places = sorted({p for leaf in expand_routes(routes) for p in leaf["places"]})

        counts = {}
        for name in all_places:
            parsed = parse_prefixed_name(name)
            group = parsed[0] if parsed else DEFAULT_GROUP
            counts[group] = counts.get(group, 0) + 1

        self.stdout.write(self.style.MIGRATE_HEADING(f"{len(all_places)} place(s) to migrate:"))
        for group, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"  {group}: {count}")

        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("dry run — nothing written. Sample:"))
            for name in all_places[:20]:
                parsed = parse_prefixed_name(name)
                group, base = parsed if parsed else (DEFAULT_GROUP, name)
                self.stdout.write(f'  "{name}" -> group={group}, base="{base}"')
            if len(all_places) > 20:
                self.stdout.write(f"  ... and {len(all_places) - 20} more")
            return

        self._backup(routes, raw_compromised)

        database.save_routes(routes)
        if raw_compromised:
            database.save_compromised(raw_compromised)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"migrated {len(all_places)} place(s) to id-based storage.")
        )

    def _reclassify_other_places(self, registry, dry_run):
        """Correct any place still in ``"other"`` whose name now matches a
        prefix ``PREFIX_PATTERNS`` didn't recognize when it was first
        classified — the path a store already on the id-registry scheme takes
        when a new group is added later. A pure registry edit: ids, and so
        every reference to them in routes.json/edge_routes.json, are untouched.
        """
        by_group_base = {(e["group"], e["name"]): pid for pid, e in registry.items()}
        changes = []
        for place_id, entry in registry.items():
            if entry["group"] != DEFAULT_GROUP:
                continue
            parsed = parse_prefixed_name(entry["name"])
            if not parsed:
                continue
            new_group, new_base = parsed
            existing = by_group_base.get((new_group, new_base))
            if existing is not None and existing != place_id:
                self.stdout.write(
                    self.style.WARNING(
                        f'skip "{entry["name"]}" (id {place_id}) -> {new_group}:"{new_base}" '
                        f"— collides with existing id {existing}"
                    )
                )
                continue
            changes.append((place_id, entry["name"], new_group, new_base))

        if not changes:
            self.stdout.write(
                self.style.SUCCESS("nothing to reclassify — every place's group is up to date.")
            )
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"{len(changes)} place(s) to reclassify:"))
        for place_id, old_name, new_group, new_base in changes:
            self.stdout.write(f'  "{old_name}" (id {place_id}) -> group={new_group}, base="{new_base}"')

        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("dry run — nothing written."))
            return

        self._backup_places(registry)
        for place_id, _old_name, new_group, new_base in changes:
            registry[place_id] = {"name": new_base, "group": new_group}
        database._atomic_write_json(database.places_key, {str(k): v for k, v in registry.items()})

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"reclassified {len(changes)} place(s)."))

    def _backup_places(self, registry):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = os.path.join(settings.DATA_DIR, "migration_backups", timestamp)
        os.makedirs(backup_dir, exist_ok=True)
        with open(os.path.join(backup_dir, "places.json"), "w", encoding="utf-8") as fh:
            json.dump(registry, fh, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(f"backed up current places.json to {backup_dir}"))

    def _backup(self, routes, compromised):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = os.path.join(settings.DATA_DIR, "migration_backups", timestamp)
        os.makedirs(backup_dir, exist_ok=True)
        for name, data in (("routes.json", routes), ("compromised.json", compromised)):
            with open(os.path.join(backup_dir, name), "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(f"backed up current data to {backup_dir}"))
