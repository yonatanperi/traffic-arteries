""""Database" backed by Cloudflare R2 (S3-compatible object storage).

A :class:`Database` owns two JSON objects in an R2 bucket:

  * ``routes.json``      — the source of truth: the routes exactly as authored,
    each ``{"places": [place names], "priority": 0..3}`` (``0`` = best). A route may
    also be *branched* — a shared tail (``places``) plus ``"branches"``, a converging
    tree of alternate heads whose leaves each share the downstream tail (see
    :func:`expand_route`). The tree is flattened to one flat subroute per leaf before
    the graph is built, so a branched route and the equivalent set of flat routes
    derive identical edges. The priority is *not* copied into the derived graph
    object — it is re-attached from here on every load, so this stays the one place
    it lives.
  * ``edge_routes.json`` — the derived graph, rebuilt on every save so it can be
    loaded straight from the store without recomputation. Each record is
    ``[place_a, place_b, [authored route indices on that edge]]``: it carries both
    the topology (the adjacency is reconstructed from the edges) and the route
    provenance the router needs to find the most-concentrated path (riding one
    authored route as far as possible). Before it
    is built the routes are run through :meth:`Database.fill_missing_destinations`,
    so a route that skips stops another spells out doesn't fabricate a direct
    edge — ``routes.json`` keeps the originals, the graph sees the filled version.

All object I/O goes through the :data:`~utils.r2_storage.storage` facade; writes
are atomic per key, so no half-written object can be observed. On first access an empty store is
initialised. The move off the local filesystem is what lets the backend run on
Render's ephemeral disk (see ``build.sh`` / deployment notes).

A module-level :data:`database` singleton (no key prefix) is the instance the app
uses; construct your own :class:`Database` (e.g. in tests, against a mocked
bucket) with a ``prefix`` to namespace its keys.
"""

from utils.r2_storage import storage

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
    """The place-name chain of a stored route (its *trunk*), whichever shape it is in."""
    return list(route["places"] if isinstance(route, dict) else route)


def route_priority(route):
    """The priority of a stored route (``BEST_PRIORITY`` if it doesn't state one)."""
    return route.get("priority", BEST_PRIORITY) if isinstance(route, dict) else BEST_PRIORITY


def route_branches(route):
    """The branches (converging heads) of a stored route (``[]`` if flat)."""
    return route.get("branches", []) if isinstance(route, dict) else []


def expand_route(route):
    """Flatten one authored route (a converging tree) to its ridable subroutes.

    A route is a *shared tail* with *heads* that converge into the start of it.
    Concretely, a node is ``{"places": [stops toward the tail], "branches": [...]}``:
    its ``branches`` are upstream heads whose last stop is adjacent to this node's
    first stop (``places[0]``), and they nest — a head can itself split into
    sub-heads further upstream. There is no "primary" head: every real corridor is
    a *leaf* (a head with no further split), and it expands to one flat subroute —
    the chain from that leaf all the way down the shared tail to the destination::

        subroute(leaf) = leaf.places + parent.places + … + root.places

    A flat route (no branches) is itself the sole leaf and yields exactly
    ``[route.places]`` — identical to authoring it the old way. Emitted in the
    branches' pre-order; that ordering *is* the route-index space the derived
    graph, its priorities and the path labels all share.
    """
    leaves = []

    def walk(node, downstream):
        # `downstream` is the chain from this node's parent junction to the
        # destination; this node's own stops flow into its front.
        full = route_places(node) + downstream
        branches = route_branches(node)
        if branches:
            for branch in branches:
                walk(branch, full)
        else:
            leaves.append(full)  # a leaf head — exactly one subroute

    walk(route, [])
    return leaves


def expand_routes(routes):
    """Every authored route flattened to its subroutes, as ``{"places", "priority"}``.

    Concatenation of :func:`expand_route` over ``routes`` in order; each subroute
    inherits its route's single priority (branches carry no priority of their own).
    """
    expanded = []
    for route in routes:
        priority = route_priority(route)
        for chain in expand_route(route):
            expanded.append({"places": chain, "priority": priority})
    return expanded


def _join_key(prefix, name):
    """Namespace an object key under an optional prefix (``""`` = no prefix)."""
    prefix = (prefix or "").strip("/")
    return f"{prefix}/{name}" if prefix else name


class Database:
    """Routes + derived graph persisted as JSON objects in an R2 bucket.

    ``prefix`` namespaces this instance's keys (default ``""`` = the bare keys
    ``routes.json`` etc.); tests pass a prefix to isolate their objects.
    """

    def __init__(self, prefix=""):
        self.routes_key = _join_key(prefix, "routes.json")
        # The derived graph: edges with their authored-route membership. Lets the
        # router find the route that rides one authored route as far as possible,
        # and the adjacency is reconstructed from it — no separate adjacency object.
        self.edge_routes_key = _join_key(prefix, "edge_routes.json")
        # Destinations temporarily marked unavailable, grouped (e.g. one group per
        # closure event): a list of lists of place names. Filtered out at read
        # time for routing/place-picking — routes.json/edge_routes.json never
        # change because of this.
        self.compromised_key = _join_key(prefix, "compromised.json")

    # --- persistence primitives -------------------------------------------

    @staticmethod
    def _atomic_write_json(key, data):
        # The store writes atomically per key; the name is kept for callers' intent.
        storage.upload_json(key, data)

    @staticmethod
    def _read_json(key):
        return storage.download_json(key)

    # --- validation --------------------------------------------------------

    @staticmethod
    def _clean_places(raw_places, label, minimum):
        """Trim and validate a place-name chain (shared by trunk and branches)."""
        if not isinstance(raw_places, list):
            raise ValidationError(f"{label} אינו רשימה.")
        places = []
        for place in raw_places:
            if not isinstance(place, str) or not place.strip():
                raise ValidationError(f"{label} מכיל שם מקום ריק או לא תקין.")
            places.append(place.strip())
        if len(places) < minimum:
            word = "שתי נקודות" if minimum >= 2 else "נקודה אחת"
            raise ValidationError(f"{label} חייב לכלול לפחות {word}.")
        return places

    @classmethod
    def _clean_branches(cls, raw_branches, label):
        """Recursively validate/normalise a node's branches (converging heads).

        Each branch is ``{"places": [≥1 stop], "branches": [...]}`` — its stops flow
        into this node's first stop; no join index (convergence is always at the
        tail's start). Sub-branches converge into the branch's own first stop.
        """
        if not isinstance(raw_branches, list):
            raise ValidationError(f"ההסתעפויות של {label} אינן רשימה.")
        cleaned = []
        for i, branch in enumerate(raw_branches):
            blabel = f"הסתעפות מספר {i + 1} של {label}"
            if not isinstance(branch, dict):
                raise ValidationError(f"{blabel} אינה תקינה.")
            places = cls._clean_places(branch.get("places"), blabel, minimum=1)
            entry = {"places": places}
            sub = cls._clean_branches(branch.get("branches", []), blabel)
            if sub:
                entry["branches"] = sub
            cleaned.append(entry)
        return cleaned

    @classmethod
    def validate_routes(cls, routes):
        """Validate and normalise routes. Returns cleaned routes or raises.

        Rules: ``routes`` is a list; each route is either a bare list of place
        names or ``{"places": [...], "priority": int, "branches": [...]}``. A route
        with no branches (a plain corridor) needs at least two non-empty places; a
        route that has branches is a *shared tail* whose own ``places`` needs at
        least one (the heads supply the origin side). ``priority`` is an int in
        ``[BEST_PRIORITY, WORST_PRIORITY]``; ``branches`` is optional (see
        :meth:`_clean_branches`). Place names are trimmed of surrounding whitespace.

        Both the bare-list and object shapes are accepted so a routes file written
        before priorities existed still loads — a bare list simply means
        :data:`~.graph.BEST_PRIORITY` and no branches. The output is always the
        object form, so the file is upgraded on the next save.
        """
        if not isinstance(routes, list):
            raise ValidationError("הנתונים חייבים להיות רשימה של צירים.")

        cleaned = []
        for index, route in enumerate(routes):
            label = f"ציר מספר {index + 1}"
            if isinstance(route, list):
                raw_places, raw_priority, raw_branches = route, BEST_PRIORITY, []
            elif isinstance(route, dict):
                raw_places = route.get("places")
                raw_priority = route.get("priority", BEST_PRIORITY)
                raw_branches = route.get("branches", [])
            else:
                raise ValidationError(f"{label} אינו רשימה.")

            places = cls._clean_places(raw_places, label, minimum=1)
            branches = cls._clean_branches(raw_branches, label)
            # A branchless route is a plain corridor and needs both endpoints; a
            # branched route's `places` is only the shared tail (heads add the rest).
            if not branches and len(places) < 2:
                raise ValidationError(f"{label} חייב לכלול לפחות שתי נקודות.")

            # bool is an int subclass, and True would silently become priority 1.
            if isinstance(raw_priority, bool) or not isinstance(raw_priority, int):
                raise ValidationError(f"עדיפות של {label} אינה תקינה.")
            if not BEST_PRIORITY <= raw_priority <= WORST_PRIORITY:
                raise ValidationError(
                    f"עדיפות של {label} חייבת להיות בין "
                    f"{BEST_PRIORITY} ל-{WORST_PRIORITY}."
                )

            entry = {"places": places, "priority": raw_priority}
            # Only carry `branches` when there are any, so a flat route stays the
            # exact `{"places", "priority"}` shape it had before this feature.
            if branches:
                entry["branches"] = branches
            cleaned.append(entry)
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
        if not storage.object_exists(self.routes_key):
            # Start empty; routes are added through the editor.
            self._atomic_write_json(self.routes_key, [])
            self._rebuild_graph([])
        elif not storage.object_exists(self.edge_routes_key):
            # routes exist but the derived graph is missing/stale — rebuild it.
            self._rebuild_graph(self._read_json(self.routes_key))
        if not storage.object_exists(self.compromised_key):
            self._atomic_write_json(self.compromised_key, [])

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

        Branched routes are flattened by :func:`expand_routes` first, so the graph
        is built from one flat subroute per tree node. Authoring three tail-sharing
        routes flat and authoring them as one trunk + two branches therefore derive
        the *same* edges — the expansion is the single route-index space.
        """
        expanded = expand_routes(routes)
        filled = self.fill_missing_destinations(
            [route_places(route) for route in expanded], lazy_gap, confirmed_gap
        )
        graph = Graph.from_routes(filled, [route_priority(route) for route in expanded])
        self._atomic_write_json(self.edge_routes_key, graph.edge_routes_records)
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
            {
                "places": route_places(route),
                "priority": route_priority(route),
                **({"branches": route_branches(route)} if route_branches(route) else {}),
            }
            for route in self._read_json(self.routes_key)
        ]

    def load_expanded_routes(self):
        """The authored routes flattened to one ``{"places", "priority"}`` per subroute.

        This is the flat view that lines up with the derived graph's route indices
        (each tree node is one graph route). Consumers that index a graph run back
        to a route — priorities in :meth:`load_graph`, endpoint labels in the path
        view — read *this*, not :meth:`load_routes` (which keeps the authored tree).
        """
        return expand_routes(self.load_routes())

    def load_graph(self):
        """Load the pre-built graph (edges + route membership) from disk.

        The edges come from the derived file; the priorities come from the expanded
        routes (``routes.json`` stays their single source of truth), aligned to the
        graph's route indices — one per tree node.
        """
        self._ensure_files()
        return Graph.from_edge_routes(
            self._read_json(self.edge_routes_key),
            [route["priority"] for route in self.load_expanded_routes()],
        )

    def save_routes(self, routes):
        """Validate, persist routes, and regenerate the derived graph.

        Returns the cleaned routes that were saved.
        """
        cleaned = self.validate_routes(routes)
        self._atomic_write_json(self.routes_key, cleaned)
        self._rebuild_graph(cleaned)
        return cleaned

    def load_compromised(self):
        self._ensure_files()
        return self._read_json(self.compromised_key)

    def compromised_places(self):
        """Flattened set of every destination marked unavailable, across all groups."""
        return {place for group in self.load_compromised() for place in group}

    def save_compromised(self, groups):
        """Validate against the closed list of known destinations and persist.

        Returns the cleaned groups that were saved.
        """
        known = set(self.load_graph().places())
        cleaned = self.validate_compromised(groups, known)
        self._atomic_write_json(self.compromised_key, cleaned)
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


# The instance the app uses: the bare-key store in the configured R2 bucket.
database = Database()
