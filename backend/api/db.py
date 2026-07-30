""""Database" backed by Cloudflare R2 (S3-compatible object storage).

A :class:`Database` owns two JSON objects in an R2 bucket:

  * ``routes.json``      — the source of truth: the routes exactly as authored,
    each ``{"places": [place names], "priority": 0..3}`` (``0`` = best). A route may
    also be *branched* — a shared tail (``places``) plus ``"branches"``, a converging
    tree of alternate heads whose leaves each share the downstream tail (see
    :func:`expand_route`). The tree is flattened to one flat subroute per leaf before
    the graph is built, so a branched route and the equivalent set of flat routes
    derive identical edges. **Any head may state a ``priority`` of its own**, which
    rates the whole corridor it generates (that head, down the shared tail, to the
    destination) without touching its sibling heads; a head that states none inherits
    its parent's, so the root's priority is the tree-wide default. The priority is
    *not* copied into the derived graph object — it is re-attached from here on every
    load, so this stays the one place it lives.
  * ``edge_routes.json`` — the derived graph, rebuilt on every save so it can be
    loaded straight from the store without recomputation. It is accompanied by
    ``edge_routes.fingerprint.json``, recording which routes it was derived from and
    under which :data:`DERIVATION_VERSION`; a load whose fingerprint doesn't match
    rebuilds rather than trusting the object (see :meth:`Database._derived_is_stale`).
    Without that check a ``routes.json`` changed out of band — or a change to the
    derivation itself — leaves the store serving edges no route asserts, and nothing
    ever notices. Each record is
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

import hashlib
import json

from utils.r2_storage import ObjectNotFound, storage

from .graph import BEST_PRIORITY, WORST_PRIORITY, Graph

# Version of the *derivation* — the pipeline that turns ``routes.json`` into
# ``edge_routes.json`` (:func:`expand_route`, :meth:`Database.fill_missing_destinations`,
# :meth:`Graph.from_routes`). It is half of the derived object's fingerprint, so
# **bump it whenever a change to that pipeline would derive different edges from the
# same routes**: every store then rebuilds on its next load instead of serving edges
# computed by logic that no longer exists. Nothing else keys off it.
DERIVATION_VERSION = 1


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
    return node_priority(route, BEST_PRIORITY)


def node_priority(node, inherited):
    """The priority a tree node rides at: its own if it states one, else ``inherited``.

    Only the root is required to state a priority; a head that states one *overrides*
    it for the corridors it generates, and one that doesn't simply inherits. That is
    what keeps a head's rating local — a sibling head resolves its own priority down
    its own ancestor chain and never sees this one's.
    """
    if not isinstance(node, dict):
        return inherited
    priority = node.get("priority")
    return inherited if priority is None else priority


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

    Returns one ``{"places", "priority"}`` entry per leaf: the chain, and the
    priority it rides at — the leaf's own if it states one, otherwise the nearest
    ancestor's (see :func:`node_priority`). Priority is resolved *here*, on the way
    down, because that is the only place a leaf's ancestor chain exists: two leaves
    of the same tree can legitimately come out at different priorities, and each
    one's is decided purely by its own spine.

    A flat route (no branches) is itself the sole leaf and yields exactly one entry
    for ``route.places`` — identical to authoring it the old way. Emitted in the
    branches' pre-order; that ordering *is* the route-index space the derived
    graph, its priorities and the path labels all share.
    """
    leaves = []

    def walk(node, downstream, inherited):
        # `downstream` is the chain from this node's parent junction to the
        # destination; this node's own stops flow into its front.
        full = route_places(node) + downstream
        priority = node_priority(node, inherited)
        branches = route_branches(node)
        if branches:
            for branch in branches:
                walk(branch, full, priority)
        else:
            # A leaf head — exactly one subroute, rated by its own spine.
            leaves.append({"places": full, "priority": priority})

    walk(route, [], BEST_PRIORITY)
    return leaves


def expand_routes(routes):
    """Every authored route flattened to its subroutes, as ``{"places", "priority"}``.

    Concatenation of :func:`expand_route` over ``routes`` in order — the flat view
    the derived graph's route indices line up with.
    """
    return [subroute for route in routes for subroute in expand_route(route)]


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
        # What the derived object was built from — see :meth:`_derivation_fingerprint`.
        # Kept beside the edges rather than inside them so the derived object stays
        # exactly the record list :meth:`Graph.from_edge_routes` reads.
        self.fingerprint_key = _join_key(prefix, "edge_routes.fingerprint.json")

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

    @staticmethod
    def _clean_priority(raw, label):
        """Validate one priority value (shared by the root and every head)."""
        # bool is an int subclass, and True would silently become priority 1.
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValidationError(f"עדיפות של {label} אינה תקינה.")
        if not BEST_PRIORITY <= raw <= WORST_PRIORITY:
            raise ValidationError(
                f"עדיפות של {label} חייבת להיות בין {BEST_PRIORITY} ל-{WORST_PRIORITY}."
            )
        return raw

    @classmethod
    def _clean_branches(cls, raw_branches, label):
        """Recursively validate/normalise a node's branches (converging heads).

        Each branch is ``{"places": [≥1 stop], "priority": 0..3?, "branches": [...]}``
        — its stops flow into this node's first stop; no join index (convergence is
        always at the tail's start). Sub-branches converge into the branch's own first
        stop. ``priority`` is *optional* here, unlike on the root: absent means
        "inherit", and it is only written back when the head actually states one, so
        an inherited head stays the exact shape it had before this feature existed
        (and re-rating the route keeps carrying it along).
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
            priority = branch.get("priority")
            if priority is not None:
                entry["priority"] = cls._clean_priority(priority, blabel)
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
        ``[BEST_PRIORITY, WORST_PRIORITY]`` — required on the route (it is the
        tree-wide default), optional on each head; ``branches`` is optional (see
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

            entry = {"places": places, "priority": cls._clean_priority(raw_priority, label)}
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

    def _derivation_fingerprint(self, routes):
        """Identifies the edges ``routes`` derive *under the current derivation*.

        Two independent things can put the derived object out of step with the
        routes, so the fingerprint has two parts: a digest of the routes exactly as
        stored (catches a ``routes.json`` changed outside :meth:`save_routes` — seeded,
        restored from a backup, hand-edited) and :data:`DERIVATION_VERSION` (catches
        the routes being untouched while the logic that consumed them changed).
        ``sort_keys`` makes the digest indifferent to key order within a route but
        not to route order, which is right: the order *is* the route-index space the
        derived edges reference.
        """
        payload = json.dumps(routes, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return {
            "version": DERIVATION_VERSION,
            "routes": hashlib.sha256(payload).hexdigest(),
        }

    def _derived_is_stale(self, routes):
        """Whether the stored graph was derived from something other than ``routes``.

        A missing derived object, a missing fingerprint (a store written before
        fingerprints existed, or seeded without one), or a fingerprint that doesn't
        match what ``routes`` derive today all mean the same thing: rebuild. Erring
        toward a rebuild costs one recomputation; erring the other way serves edges
        that no route asserts — phantom adjacencies the router will happily ride,
        indefinitely and silently. That asymmetry is the whole reason this exists.
        """
        if not storage.object_exists(self.edge_routes_key):
            return True
        try:
            stored = self._read_json(self.fingerprint_key)
        except ObjectNotFound:
            return True
        return stored != self._derivation_fingerprint(routes)

    def _ensure_routes(self):
        """Guarantee ``routes.json`` exists and the derived graph matches it.

        Returns the routes *exactly as stored* (un-normalised): fetching them is the
        price of the freshness check either way, so the callers that need them
        (:meth:`load_routes`, :meth:`load_graph`) take them from here rather than
        reading the object a second time.
        """
        try:
            routes = self._read_json(self.routes_key)
        except ObjectNotFound:
            # Start empty; routes are added through the editor.
            routes = []
            self._atomic_write_json(self.routes_key, routes)
            self._rebuild_graph(routes)
            return routes
        if self._derived_is_stale(routes):
            self._rebuild_graph(routes)
        return routes

    def _ensure_compromised(self):
        """Guarantee ``compromised.json`` exists (it has nothing derived from it)."""
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

        ``routes`` must be what ``routes.json`` holds (or is about to hold), because
        it is also what gets fingerprinted: :meth:`save_routes` writes the cleaned
        routes and rebuilds from those same ones, :meth:`_ensure_routes` rebuilds
        from what it just read. Rebuilding from anything else would stamp a
        fingerprint that no later load can reproduce, so every load would rebuild.

        Branched routes are flattened by :func:`expand_routes` first, so the graph
        is built from one flat subroute per tree node. Authoring three tail-sharing
        routes flat and authoring them as one trunk + two branches therefore derive
        the *same* edges — the expansion is the single route-index space.
        """
        # Flatten each authored route to its leaf subroutes, remembering which
        # authored route (``group``) each came from. A branched route yields one
        # chain per leaf that all share the same tail, so the group id is what lets
        # the fill count a shared hop once per authored route rather than once per
        # leaf (see :meth:`fill_missing_destinations`).
        chains, priorities, groups = [], [], []
        for index, route in enumerate(routes):
            for subroute in expand_route(route):
                chains.append(subroute["places"])
                priorities.append(subroute["priority"])
                groups.append(index)
        filled = self.fill_missing_destinations(
            chains, lazy_gap, confirmed_gap, route_groups=groups
        )
        graph = Graph.from_routes(filled, priorities)
        self._atomic_write_json(self.edge_routes_key, graph.edge_routes_records)
        # Stamped last, on purpose: if this write is the one that fails, the store is
        # left with edges and no fingerprint, which reads as stale and rebuilds. The
        # other order would leave a fingerprint vouching for edges never written.
        self._atomic_write_json(self.fingerprint_key, self._derivation_fingerprint(routes))
        return graph

    @staticmethod
    def fill_missing_destinations(
        routes, lazy_gap=LAZY_GAP, confirmed_gap=CONFIRMED_GAP, route_groups=None
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

        "Several routes" means several **authored** routes. A branched route
        flattens to one chain per leaf that all share the same tail, so counting
        the direct hop once per chain would tally that single authored route once
        per leaf and wrongly "confirm" (and thus under-fill) its shared tail.
        ``route_groups[i]`` is the authored-route id of ``routes[i]`` (default:
        each chain is its own route, the pre-branch behaviour), so each authored
        route is credited a given hop at most once.

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

        # How many *authored* routes take each undirected pair as a direct hop.
        # Chains from the same authored route (a branched route's leaves) share a
        # group id, so a hop on their shared tail is counted once, not once per leaf.
        if route_groups is None:
            route_groups = range(len(routes))
        takers = {}
        for group, route in zip(route_groups, routes):
            for a, b in zip(route, route[1:]):
                if a != b:
                    takers.setdefault(frozenset((a, b)), set()).add(group)
        direct = {pair: len(groups) for pair, groups in takers.items()}

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

    @staticmethod
    def _normalised(routes):
        """Stored routes in the uniform ``{"places", "priority"[, "branches"]}`` shape."""
        return [
            {
                "places": route_places(route),
                "priority": route_priority(route),
                **({"branches": route_branches(route)} if route_branches(route) else {}),
            }
            for route in routes
        ]

    def load_routes(self):
        """The authored routes, always in the ``{"places", "priority"}`` shape.

        A routes file written before priorities existed holds bare lists; it is
        normalised here (as all-best-priority) so every caller sees one shape, and
        rewritten in the new shape on the next save.
        """
        return self._normalised(self._ensure_routes())

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
        graph's route indices — one per tree node. Both therefore describe the same
        routes: :meth:`_ensure_routes` has rebuilt the edges first if they didn't.

        The routes read for the freshness check are expanded here directly instead
        of calling :meth:`load_expanded_routes`, which would fetch ``routes.json`` a
        second time for a value already in hand.
        """
        routes = self._normalised(self._ensure_routes())
        return Graph.from_edge_routes(
            self._read_json(self.edge_routes_key),
            [route["priority"] for route in expand_routes(routes)],
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
        self._ensure_compromised()
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
