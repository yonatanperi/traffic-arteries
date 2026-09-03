"""Find and print routes between two places from the console.

Mirrors the exact pipeline behind ``POST /api/path/`` (see ``api.views.path``,
which is what the home page's search form hits via ``findPaths``): rank the
candidate pool once, then select twice — the natural best and the
compromised-free best — and truncate to the top-N. Useful for inspecting a
route's stats (match/tier/merged sub-routes) without going through the UI::

    python manage.py find_route "אילת" "ירושלים"
    python manage.py find_route "אילת" "ירושלים" --via "מ. אלפורן" "באר שבע"
    python manage.py find_route "אילת" "ירושלים" --json
"""

import json

from django.core.management.base import BaseCommand, CommandError

from api.db import database
from api.graph import RouteFinder
from api.path_meta import route_meta

TOP_N = 3


class Command(BaseCommand):
    help = "Find the top routes between two places (optionally via required stops)."

    def add_arguments(self, parser):
        parser.add_argument("start", help="Origin place name.")
        parser.add_argument("end", help="Destination place name.")
        parser.add_argument(
            "--via",
            nargs="+",
            default=[],
            metavar="PLACE",
            help="Required intermediate stop(s), visited in an optimised order.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the raw {paths, meta, compromisedDetour} payload as JSON instead of a human-readable report.",
        )

    def handle(self, *args, **options):
        start = options["start"].strip()
        end = options["end"].strip()
        via = [v.strip() for v in options["via"] if v.strip()]

        if not start or not end:
            raise CommandError("start and end must be non-empty place names.")

        registry = database.load_place_registry()
        compromised = database.compromised_places()
        graph = database.load_graph()
        routes = database.load_expanded_routes()  # id-based, like the graph itself

        start_id, end_id, *via_ids = database.resolve_places([start, end, *via])
        unknown = [
            p for p, p_id in zip([start, end, *via], [start_id, end_id, *via_ids]) if p_id is None
        ]
        if unknown:
            raise CommandError(f"unknown place(s): {', '.join(unknown)}")

        # Same pipeline as views.path: rank once, select twice (natural vs.
        # compromised-free) over the one ranked pool, then truncate to TOP_N.
        finder = RouteFinder(graph)
        ranked, stretch = finder.rank_candidates(start_id, end_id, via=via_ids)
        natural = finder.select_diverse(ranked, k=None, max_stretch=stretch)
        detour_ids = (
            sorted({stop for r in natural[:TOP_N] for stop in r.stops} & compromised)
            if compromised
            else []
        )
        clean = (
            finder.select_diverse(ranked, k=None, max_stretch=stretch, exclude=compromised)
            if compromised
            else natural
        )
        top = clean[:TOP_N]
        paths = [database.translate_stops(r.stops, registry) for r in top]
        meta = [route_meta(r, registry, routes) for r in top]
        detour = sorted(database.translate_stops(detour_ids, registry)) if paths else []
        payload = {"paths": paths, "meta": meta, "compromisedDetour": detour}

        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self._print_report(start, end, via, payload)

    def _print_report(self, start, end, via, payload):
        header = f"{start} -> {end}"
        if via:
            header += f" (via {', '.join(via)})"
        self.stdout.write(self.style.MIGRATE_HEADING(header))

        paths, meta = payload["paths"], payload["meta"]
        if not paths:
            self.stdout.write(self.style.WARNING("no route found"))
            return

        for i, (stops, m) in enumerate(zip(paths, meta), start=1):
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    f"#{i}  match={m['match']}%  tier={m['priority']}  "
                    f"hops={len(stops) - 1}  merges={m['routeCount']} route(s)"
                )
            )
            self.stdout.write("  " + " -> ".join(stops))
            # A required stop splits the trip into legs; print each one under its own
            # heading so the console report shows the same division the UI draws. With
            # no `via` there is exactly one leg and the heading is skipped, leaving the
            # report as it always looked.
            legs = m["legs"]
            for j, leg in enumerate(legs, start=1):
                if len(legs) > 1:
                    self.stdout.write(
                        f"    leg {j}: {leg['start']} -> {leg['end']}"
                        f"  [{leg['startIndex']}-{leg['endIndex']}]"
                        f"  match={leg['match']}%  tier={leg['priority']}"
                    )
                for run in leg["routes"]:
                    self.stdout.write(
                        f"    [{run['startIndex']}-{run['endIndex']}] "
                        f"{run['label']}  (priority={run['priority']}, share={run['share']}%)"
                    )

        if payload["compromisedDetour"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "compromised detour avoided: " + ", ".join(payload["compromisedDetour"])
                )
            )
