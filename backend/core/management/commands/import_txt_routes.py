import json
import os
import re

from django.conf import settings
from django.core.management.base import BaseCommand

from api.db import _rebuild_graph


# Labels that name a region/polygon rather than a concrete junction, so they
# must not be injected into the route as an ordinary stop.
POLYGONS = ['רמה"ג']

# How many stops a single hop may be elaborated with when re-inserting skipped
# destinations (see fill_missing_destinations). Two tiers, keyed on how strongly
# the direct hop is attested:
#   * A hop that several routes take directly is a *real* road; we only refine it
#     with a tiny skip (CONFIRMED_GAP), to avoid splicing in a long scenic loop
#     that some grand-tour route happens to connect the same two junctions with.
#   * A hop only one route takes directly is likely a *lazy* shortcut, so we
#     allow a much longer elaboration (LAZY_GAP) — e.g. the Arava corridor, where
#     a single route hops straight past a dozen stops another route spells out.
CONFIRMED_GAP = 2
LAZY_GAP = 8
# A hop is treated as "confirmed" once at least this many routes take it directly.
CONFIRMED_MIN_ROUTES = 2

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

    @staticmethod
    def fill_missing_destinations(
        routes, lazy_gap=LAZY_GAP, confirmed_gap=CONFIRMED_GAP
    ):
        """Fill stops that a route skipped on a segment detailed elsewhere.

        A hand-written route may hop straight from ``D`` to ``B`` while another
        route spells the same segment out as ``D, E, F, B``. Taken literally the
        first route asserts a direct ``D``–``B`` edge that doesn't exist, so we
        splice the skipped stops back in.

        The elaboration used for a hop ``(u, v)`` is the *shortest* contiguous
        subpath between them seen in any route. Preferring the shortest (over the
        longest) avoids grabbing a long unrelated loop that merely happens to
        connect the two junctions.

        How long an elaboration we accept depends on how strongly the direct hop
        is attested (see the ``*_GAP`` constants): a hop taken directly by
        several routes is a real road we barely touch (``confirmed_gap``); a hop
        only one route takes directly is a likely lazy shortcut we fill
        generously (``lazy_gap``). ``lazy_gap == 0`` disables filling entirely.

        Two invariants are guaranteed, so the derived graph never gains a
        connection that isn't in the source:

        * **Only add, never remove.** Each result is a supersequence of its
          original route — no stop is dropped, only skipped ones inserted.
        * **No invented edges.** A hop is only elaborated when every inserted
          stop is *fresh* (not already elsewhere on the route). Inserting a stop
          that also sits elsewhere would force a de-duplication that welds two
          non-adjacent stops together, fabricating an edge; instead we leave such
          a hop alone. Every consecutive pair in a result is therefore a real
          adjacency drawn straight from some route.
        """
        if lazy_gap <= 0:
            return [list(route) for route in routes]

        # How many routes take each undirected pair as a *direct* hop.
        direct = {}
        for route in routes:
            for a, b in zip(route, route[1:]):
                if a != b:
                    direct[frozenset((a, b))] = direct.get(frozenset((a, b)), 0) + 1

        def gap_budget(a, b):
            confirmed = direct.get(frozenset((a, b)), 0) >= CONFIRMED_MIN_ROUTES
            return confirmed_gap if confirmed else lazy_gap

        # detail[(u, v)] = shortest contiguous u..v subpath whose intermediate
        # count is within the pair's gap budget, across all routes (both ways).
        detail = {}

        def index(route):
            n = len(route)
            for i in range(n):
                for j in range(i + 2, min(i + 2 + lazy_gap, n)):
                    u, w = route[i], route[j]
                    if j - i - 1 > gap_budget(u, w):
                        continue
                    sub = route[i : j + 1]
                    if (u, w) not in detail or len(sub) < len(detail[(u, w)]):
                        detail[(u, w)] = sub

        for route in routes:
            index(route)
            index(list(reversed(route)))

        def fill_pass(route):
            """One collision-safe pass: insert each hop's skipped stops when they
            are all fresh, otherwise leave the hop untouched."""
            stops = set(route)
            out = [route[0]]
            placed = {route[0]}
            for u, v in zip(route, route[1:]):
                seg = detail.get((u, v))
                if seg:
                    intermediates = seg[1:-1]
                    if all(m not in placed and m not in stops for m in intermediates):
                        for m in intermediates:
                            out.append(m)
                            placed.add(m)
                out.append(v)
                placed.add(v)
            return out

        # A single pass only fills one level: an inserted chain can itself contain
        # a lazy sub-hop (D→B filled to D,E,B where E→B was also skipped
        # elsewhere). Re-run to a fixed point so those get detailed too. Each pass
        # only *adds* fresh stops, so the invariants hold and length is bounded —
        # the loop always terminates.
        filled = []
        for route in routes:
            while True:
                nxt = fill_pass(route)
                if nxt == route:
                    break
                route = nxt
            filled.append(route)
        return filled

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

        # Fill stops skipped on segments the author detailed elsewhere.
        routes = self.fill_missing_destinations(
            routes, options["lazy_gap"], options["confirmed_gap"]
        )

        os.makedirs(os.path.dirname(ROUTES_JSON), exist_ok=True)
        with open(ROUTES_JSON, "w", encoding="utf-8") as f:
            json.dump(routes, f, ensure_ascii=False, indent=2)

        _rebuild_graph(routes)

        self.stdout.write(self.style.SUCCESS(f"Imported {len(routes)} routes."))
