import json
import os
import re

from django.conf import settings
from django.core.management.base import BaseCommand

from api.db import CONFIRMED_GAP, LAZY_GAP, database


# Labels that name a region/polygon rather than a concrete junction, so they
# must not be injected into the route as an ordinary stop.
POLYGONS = ['רמה"ג']

TXT_FILE = os.path.join(settings.BASE_DIR, "core", "data", "routes.txt")
ROUTES_JSON = os.path.join(settings.DATA_DIR, "routes.json")


def _normalize(name):
    """Trim and collapse internal whitespace so ``צ.  השריון`` and
    ``צ. השריון`` resolve to the same node."""
    return re.sub(r"\s+", " ", name).strip()


class Command(BaseCommand):
    help = "Import routes from core/data/routes.txt into data/routes.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lazy-gap",
            type=int,
            default=LAZY_GAP,
            help="Max stops filled into a hop only one route takes directly "
            "(0 disables filling).",
        )
        parser.add_argument(
            "--confirmed-gap",
            type=int,
            default=CONFIRMED_GAP,
            help="Max stops filled into a hop several routes take directly.",
        )

    def handle(self, *args, **options):
        routes = []
        with open(TXT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                displacement, route = line.split(": ", 1)
                displacement = [_normalize(p) for p in displacement.split(" - ")]
                route = [_normalize(p) for p in route.split(",")]

                # The displacement endpoints name the start/end of the route.
                # Add them only when the route body doesn't already start/end
                # there and they aren't a region label.
                if displacement[0] != route[0] and displacement[0] not in POLYGONS:
                    route.insert(0, displacement[0])
                if displacement[1] != route[-1] and displacement[1] not in POLYGONS:
                    route.append(displacement[1])

                routes.append(route)

        # Unify a bare place name with its military-post spelling: if "מ. X"
        # appears anywhere, every bare "X" becomes "מ. X".
        places = {place for route in routes for place in route}
        for route in routes:
            for j, place in enumerate(route):
                camp_label = f"מ. {place}"
                if camp_label in places:
                    route[j] = camp_label

        # Drop consecutive duplicates, e.g. a bare "אליקים" right after
        # "מ. אליקים" that the camp unification above just made identical.
        routes = [
            [place for k, place in enumerate(route) if k == 0 or place != route[k - 1]]
            for route in routes
        ]

        # Persist the routes exactly as authored; the derived graph is built from
        # the *filled* routes inside _rebuild_graph, so stops skipped on segments
        # detailed elsewhere don't fabricate a direct edge.
        os.makedirs(os.path.dirname(ROUTES_JSON), exist_ok=True)
        with open(ROUTES_JSON, "w", encoding="utf-8") as f:
            json.dump(routes, f, ensure_ascii=False, indent=2)

        database._rebuild_graph(
            routes,
            lazy_gap=options["lazy_gap"],
            confirmed_gap=options["confirmed_gap"],
        )

        self.stdout.write(self.style.SUCCESS(f"Imported {len(routes)} routes."))
