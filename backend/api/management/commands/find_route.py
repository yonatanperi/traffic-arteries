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

        compromised = database.compromised_places()
        graph = database.load_graph()
        routes = database.load_expanded_routes()

        known = set(graph.places())
        unknown = [p for p in [start, end, *via] if p not in known]
        if unknown:
            raise CommandError(f"unknown place(s): {', '.join(unknown)}")

        def run_endpoints(run):
            places = (
                routes[run.route_id]["places"]
                if isinstance(run.route_id, int) and 0 <= run.route_id < len(routes)
                else None
            )
            if not places:
                return run.start, run.end
            order = {name: i for i, name in enumerate(places)}
            start_i, end_i = order.get(run.start), order.get(run.end)
            if start_i is not None and end_i is not None and start_i > end_i:
                return places[-1], places[0]
            return places[0], places[-1]

        def run_meta(run, total_hops, start_index):
            origin, dest = run_endpoints(run)
            return {
                "id": run.route_id if isinstance(run.route_id, int) else -1,
                "label": f"{origin} - {dest}",
                "share": round(run.hops / total_hops * 100) if total_hops else 100,
                "priority": run.priority,
                "startIndex": start_index,
                "endIndex": start_index + run.hops,
            }

        def routes_meta(runs, total_hops):
            metas = []
            offset = 0
            for run in runs:
                metas.append(run_meta(run, total_hops, offset))
                offset += run.hops
            return metas

        # Same pipeline as views.path: rank once, select twice (natural vs.
        # compromised-free) over the one ranked pool, then truncate to TOP_N.
        finder = RouteFinder(graph)
        ranked, stretch = finder.rank_candidates(start, end, via=via)
        natural = finder.select_diverse(ranked, k=None, max_stretch=stretch)
        detour = (
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
        paths = [r.stops for r in top]
        meta = [
            {
                "routeCount": r.route_count,
                "match": round(r.hhi * 100),
                "priority": r.priority,
                "routes": routes_meta(r.runs, r.total_hops),
            }
            for r in top
        ]
        payload = {"paths": paths, "meta": meta, "compromisedDetour": detour if paths else []}

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
            for run in m["routes"]:
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
