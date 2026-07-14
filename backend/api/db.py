"""Filesystem "database".

A :class:`Database` owns two JSON files under ``backend/data``:

  * ``routes.json``      — the source of truth: the routes exactly as authored,
    each ``{"places": [place names], "priority": 0..3}`` (``0`` = best). The
    priority is *not* copied into the derived graph file — it is re-attached from
    here on every load, so this stays the one place it lives.
  * ``edge_routes.json`` — the derived graph, rebuilt on every save so it can be
    loaded straight from disk without recomputation. Each record is
    ``[place_a, place_b, [authored route indices on that edge]]``: it carries both
    the topology (the adjacency is reconstructed from the edges) and the route
    provenance the router needs to find the most-concentrated path (riding one
    authored route as far as possible). Before it
    is built the routes are run through :meth:`Database.fill_missing_destinations`,
    so a route that skips stops another spells out doesn't fabricate a direct
    edge — ``routes.json`` keeps the originals, the graph sees the filled version.

Writes are atomic (temp file + ``os.replace``) so a crash mid-write can never
leave a half-written file. On first access an empty store is initialised.

A module-level :data:`database` singleton, wired to ``settings.DATA_DIR``, is the
instance the app uses; construct your own :class:`Database` (e.g. in tests) to
point at a different directory.
"""

import json
import os
import tempfile

from django.conf import settings

from .graph import BEST_PRIORITY, WORST_PRIORITY, Graph


# How many stops a single hop may be elaborated with when re-inserting skipped
# destinations (see :meth:`Database.fill_missing_destinations`). Two tiers, keyed
# on how strongly the direct hop is attested:
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


class ValidationError(ValueError):
    """Raised when incoming routes are malformed."""


# A route is stored as ``{"places": [...], "priority": int}``. These two readers
# also accept the bare ``[...]`` list the file used before priorities existed, so
# an un-upgraded routes.json still loads (as all-best-priority).
def route_places(route):
    """The place-name chain of a stored route, whichever shape it is in."""
    return list(route["places"] if isinstance(route, dict) else route)


def route_priority(route):
    """The priority of a stored route (``BEST_PRIORITY`` if it doesn't state one)."""
    return route.get("priority", BEST_PRIORITY) if isinstance(route, dict) else BEST_PRIORITY


class Database:
    """Routes + derived graph persisted as two JSON files in ``data_dir``."""

    def __init__(self, data_dir=None):
        base = data_dir if data_dir is not None else settings.DATA_DIR
        self.routes_file = os.path.join(base, "routes.json")
        # The derived graph: edges with their authored-route membership. Lets the
        # router find the route that rides one authored route as far as possible,
        # and the adjacency is reconstructed from it — no separate adjacency file.
        self.edge_routes_file = os.path.join(base, "edge_routes.json")
        # Destinations temporarily marked unavailable, grouped (e.g. one group per
        # closure event): a list of lists of place names. Filtered out at read
        # time for routing/place-picking — routes.json/edge_routes.json never
        # change because of this.
        self.compromised_file = os.path.join(base, "compromised.json")

    # --- persistence primitives -------------------------------------------

    @staticmethod
    def _atomic_write_json(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    @staticmethod
    def _read_json(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    # --- validation --------------------------------------------------------

    @staticmethod
    def validate_routes(routes):
        """Validate and normalise routes. Returns cleaned routes or raises.

        Rules: ``routes`` is a list; each route is either a bare list of place
        names or ``{"places": [...], "priority": int}``, holding at least two
        non-empty places. Place names are trimmed of surrounding whitespace, and
        ``priority`` must be an int in ``[BEST_PRIORITY, WORST_PRIORITY]``.

        Both shapes are accepted so a routes file written before priorities existed
        still loads — a bare list simply means :data:`~.graph.BEST_PRIORITY`. The
        output is always the object form, so the file is upgraded on the next save.
        """
        if not isinstance(routes, list):
            raise ValidationError("הנתונים חייבים להיות רשימה של צירים.")

        cleaned = []
        for index, route in enumerate(routes):
            if isinstance(route, list):
                raw_places, raw_priority = route, BEST_PRIORITY
            elif isinstance(route, dict):
                raw_places = route.get("places")
                raw_priority = route.get("priority", BEST_PRIORITY)
                if not isinstance(raw_places, list):
                    raise ValidationError(f"ציר מספר {index + 1} אינו רשימה.")
            else:
                raise ValidationError(f"ציר מספר {index + 1} אינו רשימה.")

            places = []
            for place in raw_places:
                if not isinstance(place, str) or not place.strip():
                    raise ValidationError(
                        f"ציר מספר {index + 1} מכיל שם מקום ריק או לא תקין."
                    )
                places.append(place.strip())
            if len(places) < 2:
                raise ValidationError(
                    f"ציר מספר {index + 1} חייב לכלול לפחות שתי נקודות."
                )

            # bool is an int subclass, and True would silently become priority 1.
            if isinstance(raw_priority, bool) or not isinstance(raw_priority, int):
                raise ValidationError(f"עדיפות של ציר מספר {index + 1} אינה תקינה.")
            if not BEST_PRIORITY <= raw_priority <= WORST_PRIORITY:
                raise ValidationError(
                    f"עדיפות של ציר מספר {index + 1} חייבת להיות בין "
                    f"{BEST_PRIORITY} ל-{WORST_PRIORITY}."
                )

            cleaned.append({"places": places, "priority": raw_priority})
        return cleaned

    @staticmethod
    def validate_compromised(groups, known_places):
        """Validate and normalise compromised-destination groups.

        Rules: ``groups`` is a list; each group is a list of at least one
        non-empty string; every destination must be a member of
        ``known_places`` (the closed list — every place appearing in any
        route), so an editor can't mark a nonexistent place unavailable.
        """
        if not isinstance(groups, list):
            raise ValidationError("הנתונים חייבים להיות רשימה של קבוצות.")

        cleaned = []
        for index, group in enumerate(groups):
            if not isinstance(group, list):
                raise ValidationError(f"קבוצה מספר {index + 1} אינה רשימה.")
            places = []
            for place in group:
                if not isinstance(place, str) or not place.strip():
                    raise ValidationError(
                        f"קבוצה מספר {index + 1} מכילה שם יעד ריק או לא תקין."
                    )
                p = place.strip()
                if p not in known_places:
                    raise ValidationError(f'היעד "{p}" אינו קיים ברשימת היעדים.')
                places.append(p)
            if not places:
                raise ValidationError(
                    f"קבוצה מספר {index + 1} חייבת לכלול לפחות יעד אחד."
                )
            cleaned.append(places)
        return cleaned

    # --- store lifecycle ---------------------------------------------------

    def _ensure_files(self):
        if not os.path.exists(self.routes_file):
            # Start empty; routes are added through the editor.
            self._atomic_write_json(self.routes_file, [])
            self._rebuild_graph([])
        elif not os.path.exists(self.edge_routes_file):
            # routes exist but the derived graph is missing/stale — rebuild it.
            self._rebuild_graph(self._read_json(self.routes_file))
        if not os.path.exists(self.compromised_file):
            self._atomic_write_json(self.compromised_file, [])

    def _rebuild_graph(self, routes, lazy_gap=LAZY_GAP, confirmed_gap=CONFIRMED_GAP):
        """Derive and persist the graph from ``routes``.

        The routes' place chains are first passed through
        :meth:`fill_missing_destinations` so the graph is built from the *filled*
        routes, while ``routes.json`` (the caller's responsibility) keeps the
        originals. The edges are persisted with their authored-route membership;
        filled route indices match ``routes.json`` (filling preserves route order
        and endpoints).

        Only the edges are persisted — priorities are *not* derived data, so they
        stay in ``routes.json`` and are re-attached at load time.
        """
        filled = self.fill_missing_destinations(
            [route_places(route) for route in routes], lazy_gap, confirmed_gap
        )
        graph = Graph.from_routes(filled, [route_priority(route) for route in routes])
        self._atomic_write_json(self.edge_routes_file, graph.edge_routes_records)
        return graph

    @staticmethod
    def fill_missing_destinations(routes, lazy_gap=LAZY_GAP, confirmed_gap=CONFIRMED_GAP):
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

    # --- public API --------------------------------------------------------

    def load_routes(self):
        """The authored routes, always in the ``{"places", "priority"}`` shape.

        A routes file written before priorities existed holds bare lists; it is
        normalised here (as all-best-priority) so every caller sees one shape, and
        rewritten in the new shape on the next save.
        """
        self._ensure_files()
        return [
            {"places": route_places(route), "priority": route_priority(route)}
            for route in self._read_json(self.routes_file)
        ]

    def load_graph(self):
        """Load the pre-built graph (edges + route membership) from disk.

        The edges come from the derived file; the priorities come from
        ``routes.json``, which stays their single source of truth.
        """
        self._ensure_files()
        return Graph.from_edge_routes(
            self._read_json(self.edge_routes_file),
            [route["priority"] for route in self.load_routes()],
        )

    def save_routes(self, routes):
        """Validate, persist routes, and regenerate the derived graph.

        Returns the cleaned routes that were saved.
        """
        cleaned = self.validate_routes(routes)
        self._atomic_write_json(self.routes_file, cleaned)
        self._rebuild_graph(cleaned)
        return cleaned

    def load_compromised(self):
        self._ensure_files()
        return self._read_json(self.compromised_file)

    def compromised_places(self):
        """Flattened set of every destination marked unavailable, across all groups."""
        return {place for group in self.load_compromised() for place in group}

    def save_compromised(self, groups):
        """Validate against the closed list of known destinations and persist.

        Returns the cleaned groups that were saved.
        """
        known = set(self.load_graph().places())
        cleaned = self.validate_compromised(groups, known)
        self._atomic_write_json(self.compromised_file, cleaned)
        return cleaned

    def load_routable_graph(self):
        """The graph with compromised destinations (and their edges) removed.

        Used anywhere a route may actually be planned or a destination picked
        for planning — the derived graph itself (``load_graph``) stays the full
        network, unaffected by compromised state.
        """
        compromised = self.compromised_places()
        graph = self.load_graph()
        return graph.without_places(compromised) if compromised else graph


# The instance the app uses, backed by ``settings.DATA_DIR``.
database = Database()
