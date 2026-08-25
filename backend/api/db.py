""""Database" backed by Cloudflare R2 (S3-compatible object storage).

A :class:`Database` owns these JSON objects in an R2 bucket:

  * ``routes.json``      — the source of truth: the routes exactly as authored,
    each ``{"places": [place names], "marks": [...]}``. A route may also be
    *branched* — a shared tail (``places``) plus ``"branches"``, a converging tree of
    alternate heads whose leaves each share the downstream tail (see
    :func:`expand_route`). The tree is flattened to one flat subroute per leaf before
    the graph is built, so a branched route and the equivalent set of flat routes
    derive identical edges.

    **A ``mark`` rates a stretch, not a route**: ``{"from": i, "to": j, "priority":
    1..3}``, inclusive indices into the node's :func:`node_frame` — its own ``places``
    followed by everything downstream of it. Marks within a node are disjoint. An
    unmarked stretch rides at :data:`~.graph.BEST_PRIORITY`, and a rating only applies
    to a result that rides the marked stretch **whole** — see
    :meth:`~.graph.Graph.run_priority`.

    The frame runs past the node on purpose: a road doesn't care where the author
    split the tree, so a mark must be able to start in a head and end in the shared
    tail. It can only run *downstream*, which costs no ambiguity — heads branch
    upstream but every node has exactly one way down to the destination. Which node
    stores a mark is therefore what scopes it: one on the shared tail rates every
    corridor that rides it, one on a head rates only the corridors below that head
    (tail stops included, if it reaches them). That is what the old per-head
    ``priority`` field meant, and the field is still *read* — a rated corridor becomes
    one mark over that corridor's whole frame (:func:`upgrade_node`) — but never
    written again. Marks are *not* copied into the derived graph object; they are
    re-attached from here on every load, so this stays the one place they live.
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
  * ``places.json`` — the place registry: ``{id: {"name": base_name, "group":
    group_key}}`` (see :mod:`api.place_groups`). A place's real identity is
    this numeric id, not its name — ``routes.json``/``edge_routes.json``/
    ``compromised.json`` all reference places by id internally (compact, and
    collision-proof: two distinct display strings, e.g. "מ. גולני" and "מחלף
    גולני", always get distinct ids, since the resolve key is the *parsed*
    ``(group, base)`` pair, never the base name alone). This is entirely an
    internal storage detail — the API (``GET``/``PUT /api/routes/``,
    ``/api/places/``, ``/api/path/``, ``/api/compromised/``, ``/api/graph/``)
    keeps sending/receiving the exact display-name strings it always has;
    :meth:`Database.load_routes_display`/:meth:`Database.save_routes`/
    :meth:`Database.place_id`/:meth:`Database.translate_stops` are the
    translation boundary. No endpoint or frontend code ever sees a raw id.

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
from collections import deque

from utils.r2_storage import ObjectNotFound, storage

from .graph import BEST_PRIORITY, WORST_PRIORITY, Graph
from .place_groups import DEFAULT_GROUP, format_place, parse_prefixed_name

# Version of the *derivation* — the pipeline that turns ``routes.json`` into
# ``edge_routes.json`` (:func:`expand_route`, :meth:`Database.fill_missing_destinations`,
# :meth:`Graph.from_routes`). It is half of the derived object's fingerprint, so
# **bump it whenever a change to that pipeline would derive different edges from the
# same routes**: every store then rebuilds on its next load instead of serving edges
# computed by logic that no longer exists. Nothing else keys off it.
DERIVATION_VERSION = 2


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


# A route is stored as ``{"places": [...], "marks": [...]}``. These readers also
# accept the bare ``[...]`` list the file used before priorities existed, and the
# ``"priority": int`` field marks replaced, so an un-upgraded routes.json still
# loads (see :func:`upgrade_node`).
def route_places(route):
    """The place-name chain of a stored route (its *trunk*), whichever shape it is in."""
    return list(route["places"] if isinstance(route, dict) else route)


def route_marks(node):
    """The priority marks a tree node states (``[]`` if it states none)."""
    return node.get("marks", []) if isinstance(node, dict) else []


def node_priority(node, inherited):
    """*Legacy.* The priority a tree node rode at before marks existed.

    Its own if it stated one, else ``inherited`` — a head that stated one overrode
    it for the corridors it generated, and one that didn't simply inherited. Read
    only by :func:`upgrade_node`, which turns that whole-chain rating into an
    equivalent whole-chain mark; nothing writes the field any more.
    """
    if not isinstance(node, dict):
        return inherited
    priority = node.get("priority")
    return inherited if priority is None else priority


def route_branches(route):
    """The branches (converging heads) of a stored route (``[]`` if flat)."""
    return route.get("branches", []) if isinstance(route, dict) else []


def frame_length(places, downstream):
    """How many stops a node's marks may address: its own, plus everything downstream.

    ``downstream`` is the number of stops between this node and the destination (0
    for a flat route or a tree's root). See :func:`node_frame`.
    """
    return len(places) + downstream


def corridor_mark(places, downstream, priority):
    """One mark over a node's whole frame — the corridor it generates, end to end.

    ``[]`` when there is nothing to rate: the best priority (which is what an
    unmarked stretch already rides at), or a frame too short to hold an edge.
    """
    if priority <= BEST_PRIORITY or frame_length(places, downstream) < 2:
        return []
    return [{"from": 0, "to": frame_length(places, downstream) - 1, "priority": priority}]


def upgrade_node(node, inherited=BEST_PRIORITY, downstream=0):
    """A stored node in the current ``{"places", "marks"[, "branches"]}`` shape.

    Read-path migration, so a store written before marks existed loads as if it had
    always had them. The legacy ``priority`` field rated *the whole corridor a node
    generates* — that node, down the shared tail, to the destination — so that is
    exactly what it becomes: one mark over the node's whole frame, placed on the
    **leaves**, where a corridor is finally a single chain. Rating the leaves (rather
    than every node on the way down) is what makes the upgrade faithful: a head that
    overrode its parent keeps its own rating, a head that inherited keeps the
    inherited one, and neither is imposed on a sibling. It also lets a *one-stop*
    head carry its rating, which marks over a node's own places alone could not
    express — the head has no edge of its own, but the corridor it generates does.

    Idempotent: once upgraded there is no ``priority`` field left to resolve, and a
    node that already states marks is left exactly as it is.
    """
    places = route_places(node)
    marks = [dict(mark) for mark in route_marks(node)]
    priority = node_priority(node, inherited)
    branches = route_branches(node)
    if not marks and not branches:
        marks = corridor_mark(places, downstream, priority)
    entry = {"places": places}
    if marks:
        entry["marks"] = marks
    upgraded = [
        upgrade_node(branch, priority, frame_length(places, downstream))
        for branch in branches
    ]
    if upgraded:
        entry["branches"] = upgraded
    return entry


def node_frame(places, downstream_places):
    """The chain a node's mark indices address: its own stops, then everything
    downstream of it (its parent's, its grandparent's … to the destination).

    A node's downstream is unique — heads branch *upstream*, and they converge — so
    extending the frame past the node stays unambiguous, which is what lets one mark
    run from a head into the shared tail. A mark's ``from`` always sits in the node's
    own ``places``; it is only ``to`` that may reach past them.
    """
    return list(places) + list(downstream_places)


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

    Returns one ``{"places", "marks"}`` entry per leaf: the chain, and every mark
    that applies to it — its own spine's, gathered on the way down, so a tail mark
    lands on every leaf while a head's reaches only the leaves below it. That spine
    is the only place a leaf's ancestry exists, which is why the gathering happens
    here rather than in the caller.

    A leaf's marks come out as ``(start place, end place, priority)`` triples rather
    than the index ranges they are stored as. Indices address a node's own frame
    (:func:`node_frame`), and a leaf chain concatenates several of those — but the
    graph is built from *filled* chains (:meth:`Database.fill_missing_destinations`),
    which shift every index anyway. Names survive both, and are what
    :class:`~.graph.Graph` matches on.

    A flat route (no branches) is itself the sole leaf and yields exactly one entry
    for ``route.places`` — identical to authoring it the old way. Emitted in the
    branches' pre-order; that ordering *is* the route-index space the derived
    graph, its marks and the path labels all share.
    """
    leaves = []

    def walk(node, downstream, downstream_marks):
        # `downstream` is the chain from this node's parent junction to the
        # destination; this node's own stops flow into its front. `downstream_marks`
        # are the marks already gathered from there on — this node's are prepended,
        # so a leaf carries its whole spine's.
        places = route_places(node)
        # This node's frame *is* `full` — its own stops followed by its downstream —
        # so the walk already holds exactly what a mark's indices address.
        full = node_frame(places, downstream)
        marks = [
            (full[mark["from"]], full[mark["to"]], mark["priority"])
            for mark in route_marks(node)
            if 0 <= mark["from"] < len(full) and 0 <= mark["to"] < len(full)
        ] + downstream_marks
        branches = route_branches(node)
        if branches:
            for branch in branches:
                walk(branch, full, marks)
        else:
            # A leaf head — exactly one subroute, rated by its own spine.
            leaves.append({"places": full, "marks": marks})

    walk(route, [], [])
    return leaves


def expand_routes(routes):
    """Every authored route flattened to its subroutes, as ``{"places", "marks"}``.

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
        # {id: {"name": base_name, "group": group_key}} — the place registry. A
        # place's real identity is this numeric id, not its name: routes.json/
        # edge_routes.json/compromised.json all reference places by id internally
        # (compact, and collision-proof — two distinct display strings always get
        # distinct ids). The API boundary (views.py) is the only place ids are
        # translated to/from the full display string a place is shown/typed as
        # (base name + its group's prefix, see :mod:`api.place_groups`) — nothing
        # outside this module ever sees a raw id.
        self.places_key = _join_key(prefix, "places.json")
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
    def _clean_marks(cls, raw_marks, places, downstream, label):
        """Validate/normalise one node's priority marks against its frame.

        Each mark is ``{"from": i, "to": j, "priority": 1..3}`` with ``0 <= i < j``,
        ``i`` inside the node's own ``places`` and ``j`` anywhere in its frame
        (:func:`node_frame`, i.e. up to ``downstream`` stops past them). A mark spans
        at least one edge, since a single stop is nothing to ride, and it must
        *start* in the node that stores it — a mark beginning downstream belongs to
        the node it begins in, and storing it here would let one stretch be written
        two ways. Priority :data:`~.graph.BEST_PRIORITY` is rejected rather than
        stored: it is what an *unmarked* stretch already rides at, so a best-priority
        mark would be a rating that says nothing while still occupying a stretch the
        author can't then rate.

        Returned sorted by ``from`` and required not to share an *edge*. Two marks
        may still meet at a stop (``[0,2]`` beside ``[2,4]``): they rate different
        stretches of road, and that is exactly what re-marking the middle of a
        longer stretch leaves behind. A genuine overlap is refused rather than
        resolved, because there is no honest resolution — two ratings of one stretch
        is a contradiction, and the editor never produces it.
        """
        if raw_marks is None:
            return []
        if not isinstance(raw_marks, list):
            raise ValidationError(f"טווחי העדיפות של {label} אינם רשימה.")
        cleaned = []
        for i, mark in enumerate(raw_marks):
            mlabel = f"טווח מספר {i + 1} של {label}"
            if not isinstance(mark, dict):
                raise ValidationError(f"{mlabel} אינו תקין.")
            start, end = mark.get("from"), mark.get("to")
            for value in (start, end):
                # bool is an int subclass, and True would silently become index 1.
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValidationError(f"{mlabel} מכיל מיקום לא תקין.")
            if not 0 <= start < end <= frame_length(places, downstream) - 1:
                raise ValidationError(f"{mlabel} חורג מגבולות הציר.")
            if start >= len(places):
                raise ValidationError(f"{mlabel} חייב להתחיל בקטע שבו הוא נשמר.")
            priority = cls._clean_priority(mark.get("priority"), mlabel)
            if priority == BEST_PRIORITY:
                raise ValidationError(
                    f"{mlabel} חייב לציין עדיפות נמוכה מברירת המחדל."
                )
            cleaned.append({"from": start, "to": end, "priority": priority})
        cleaned.sort(key=lambda mark: mark["from"])
        for earlier, later in zip(cleaned, cleaned[1:]):
            if later["from"] < earlier["to"]:
                raise ValidationError(f"טווחי העדיפות של {label} חופפים זה בזה.")
        return cleaned

    @classmethod
    def _clean_node(cls, node, label, inherited=BEST_PRIORITY, downstream=0, root=False):
        """Validate/normalise one tree node and, recursively, its converging heads.

        A node is ``{"places": [...], "marks": [...], "branches": [...]}``; its
        heads' stops flow into its own first stop, and there is no join index
        (convergence is always at the tail's start). A branchless *root* is a plain
        corridor and needs both endpoints; every other node needs one stop (a
        branched root's ``places`` is only the shared tail, and the heads supply the
        origin side).

        ``downstream`` is how many stops lie between this node and the destination;
        it widens the frame its marks may address (see :meth:`_clean_marks`) and is
        accumulated on the way down, which is the only place a node's downstream is
        known.

        A bare ``[...]`` list is accepted as a node with no marks, and so is the
        legacy ``"priority"`` field, which is resolved down the spine exactly as it
        used to be and upgraded to a corridor mark on each leaf (see
        :func:`upgrade_node`) — but only where no marks are stated, since stating
        them is the newer, more specific intent. The output never carries
        ``priority``, so the file upgrades on save.
        """
        if isinstance(node, list):
            node = {"places": node}
        if not isinstance(node, dict):
            raise ValidationError(
                f"{label} אינו רשימה." if root else f"{label} אינה תקינה."
            )
        raw_branches = node.get("branches", [])
        if not isinstance(raw_branches, list):
            raise ValidationError(f"ההסתעפויות של {label} אינן רשימה.")

        places = cls._clean_places(
            node.get("places"), label, minimum=2 if root and not raw_branches else 1
        )
        raw_priority = node.get("priority")
        priority = (
            inherited
            if raw_priority is None
            else cls._clean_priority(raw_priority, label)
        )
        marks = cls._clean_marks(node.get("marks"), places, downstream, label)
        if not marks and not raw_branches:
            marks = corridor_mark(places, downstream, priority)

        entry = {"places": places}
        # Only carry `marks` / `branches` when there are any, so an unrated flat
        # route stays the bare `{"places"}` shape.
        if marks:
            entry["marks"] = marks
        branches = [
            cls._clean_node(
                branch,
                f"הסתעפות מספר {i + 1} של {label}",
                priority,
                frame_length(places, downstream),
            )
            for i, branch in enumerate(raw_branches)
        ]
        if branches:
            entry["branches"] = branches
        return entry

    @classmethod
    def validate_routes(cls, routes):
        """Validate and normalise routes. Returns cleaned routes or raises.

        ``routes`` is a list; each entry is one authored route, validated by
        :meth:`_clean_node` (which also handles the legacy shapes — a bare place
        list, and the pre-marks ``"priority"`` field). Place names are trimmed of
        surrounding whitespace.
        """
        if not isinstance(routes, list):
            raise ValidationError("הנתונים חייבים להיות רשימה של צירים.")
        return [
            cls._clean_node(route, f"ציר מספר {index + 1}", root=True)
            for index, route in enumerate(routes)
        ]

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

    def _ensure_places(self):
        """Guarantee ``places.json`` exists (it has nothing derived from it)."""
        if not storage.object_exists(self.places_key):
            self._atomic_write_json(self.places_key, {})

    # --- place registry: name (as typed/displayed) <-> internal id ---------
    #
    # A place's real identity is its numeric id; its stored ``name`` is always
    # the bare base name (no prefix), and the full display string a user types
    # or sees is reconstructed via ``format_place(name, group)``. This is what
    # lets ``routes.json``/``edge_routes.json``/``compromised.json`` store a
    # compact int instead of a repeated Hebrew string, and what makes two
    # distinct display strings (e.g. "מ. גולני" and "מחלף גולני") always get
    # distinct ids -- there is nothing to collide, since the resolve key is the
    # *parsed* ``(group, base)`` pair, never the base name alone.

    def load_place_registry(self):
        """``{id: {"name": base_name, "group": group_key}}``, ``{}`` if absent."""
        self._ensure_places()
        raw = self._read_json(self.places_key)
        return {int(place_id): entry for place_id, entry in raw.items()}

    @staticmethod
    def _by_group_base(registry):
        """``{(group, base_name): id}`` — the reverse index a resolve looks up."""
        return {(entry["group"], entry["name"]): place_id for place_id, entry in registry.items()}

    @staticmethod
    def _next_id(registry):
        return max(registry, default=0) + 1

    @staticmethod
    def display_name(entry):
        """The full display string for one registry entry (prefix + base, or
        the bare base for a prefix-less group)."""
        return format_place(entry["name"], entry["group"])

    def _resolve_or_create(self, text, registry, by_group_base, next_id_ref):
        """Resolve a typed/stored display string to its id, minting one if this
        exact ``(group, base)`` pair has never been seen before.

        Resolving by the *parsed* pair rather than the raw string means minor
        typed-formatting variance (e.g. "מ.אלפורן" vs "מ. אלפורן") still lands
        on the same id instead of minting a needless duplicate.
        """
        parsed = parse_prefixed_name(text)
        group, base = parsed if parsed else (DEFAULT_GROUP, text.strip())
        key = (group, base)
        existing = by_group_base.get(key)
        if existing is not None:
            return existing
        new_id = next_id_ref[0]
        next_id_ref[0] += 1
        registry[new_id] = {"name": base, "group": group}
        by_group_base[key] = new_id
        return new_id

    def place_id(self, text, registry=None, by_group_base=None):
        """Resolve a display string to its *existing* id, or ``None``.

        Read-only lookup — never mints. Used to translate user-supplied place
        names (path search, a compromised-destination entry) to the internal
        id the graph actually uses; an unresolvable name means "no such place"
        rather than "create one."
        """
        if by_group_base is None:
            registry = registry if registry is not None else self.load_place_registry()
            by_group_base = self._by_group_base(registry)
        parsed = parse_prefixed_name(text)
        group, base = parsed if parsed else (DEFAULT_GROUP, text.strip())
        return by_group_base.get((group, base))

    def translate_stops(self, place_ids, registry=None):
        """``[display_name(id), ...]`` for a list of ids, loading the registry once."""
        registry = registry if registry is not None else self.load_place_registry()
        return [self.display_name(registry[place_id]) for place_id in place_ids]

    def resolve_places(self, names):
        """``[place_id(name), ...]`` for several names, loading the registry once.

        Each entry is ``None`` if that name doesn't resolve to any known place —
        the caller (path search) treats that as "no such place," not an error.
        """
        registry = self.load_place_registry()
        by_group_base = self._by_group_base(registry)
        return [self.place_id(name, by_group_base=by_group_base) for name in names]

    def _tree_to_ids(self, node, registry, by_group_base, next_id_ref):
        """Recursively resolve/mint every place string in a validated route tree
        to its id, leaving ``marks`` and every other field untouched (marks are
        index-based, so the token swap never invalidates them)."""
        converted = {
            **node,
            "places": [
                self._resolve_or_create(p, registry, by_group_base, next_id_ref)
                for p in node["places"]
            ],
        }
        if "branches" in node:
            converted["branches"] = [
                self._tree_to_ids(b, registry, by_group_base, next_id_ref)
                for b in node["branches"]
            ]
        return converted

    def _tree_to_display(self, node, registry):
        """The inverse of :meth:`_tree_to_ids` — resolve every stored id back to
        its full display string."""
        converted = {
            **node,
            "places": [self.display_name(registry[p]) for p in node["places"]],
        }
        if "branches" in node:
            converted["branches"] = [self._tree_to_display(b, registry) for b in node["branches"]]
        return converted

    def _rebuild_graph(self, routes, lazy_gap=LAZY_GAP, confirmed_gap=CONFIRMED_GAP):
        """Derive and persist the graph from ``routes``.

        The routes' place chains are first passed through
        :meth:`fill_missing_destinations` so the graph is built from the *filled*
        routes, while ``routes.json`` (the caller's responsibility) keeps the
        originals. The edges are persisted with their authored-route membership;
        filled route indices match ``routes.json`` (filling preserves route order
        and endpoints).

        Only the edges are persisted — marks are *not* derived data, so they stay in
        ``routes.json`` and are re-attached at load time.

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
        chains, groups = [], []
        for index, route in enumerate(routes):
            for subroute in expand_route(route):
                chains.append(subroute["places"])
                groups.append(index)
        filled = self.fill_missing_destinations(
            chains, lazy_gap, confirmed_gap, route_groups=groups
        )
        graph = Graph.from_routes(filled)
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

        When no single route writes such a subpath, a second, narrower source
        applies: the shortest ``u..v`` chain in the *cross-route* adjacency whose
        every intermediate is **transparent** (degree 2 in the whole network). A
        transparent stop has no neighbour but the two it sits between, so it can
        belong to no road but this one — which is what makes composing across
        routes safe here and nowhere else. This is what catches a skipped stop that
        the authored routes only ever describe from two different directions.

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

        # Cross-route elaborations, for a lazy hop that no *single* route spells
        # out. The index above only sees a stretch one route writes contiguously,
        # so it misses the ordinary authoring split: one route writes
        # ``שאן, מחסום בזק, מחולה`` and another ``מחסום בזק, שלוחות, שאן``, nobody
        # ever writes ``מחולה, מחסום בזק, שלוחות`` in one go, and a third route's
        # direct ``מחולה → שלוחות`` hop is left asserting a road that bypasses the
        # checkpoint entirely. The router then rides straight through and the stop
        # becomes unreachable in practice.
        #
        # Composing adjacencies across routes is exactly what could invent a road,
        # so this is confined to intermediates that are **transparent** — degree 2
        # in the whole network. Such a stop has no neighbour but the two it sits
        # between, so it cannot belong to any road other than this one, and
        # splicing it asserts no edge that isn't already there (both halves are).
        # A hop several routes take directly is still left alone
        # (``CONFIRMED_MIN_ROUTES``): a genuine bypass running parallel to the
        # detailed road is precisely what that attestation looks like.
        #
        # Transparency is read off the *filled* routes, never the raw ones, which
        # is why this runs after a first fill rather than beside the index above: a
        # second lazy hop elsewhere inflates the very degree being tested. Raw,
        # ``מחסום בזק`` looks like a 3-way junction only because another route hops
        # ``שאן → מחסום בזק`` past ``שלוחות``; once that hop is elaborated it is the
        # 2-degree stop it really is, and the corridor it sits on becomes fillable.
        def learn_bypasses(filled):
            """Add cross-route elaborations for lazy hops; ``True`` if any were found."""
            adjacency = {}
            for route in filled:
                for a, b in zip(route, route[1:]):
                    if a != b:
                        adjacency.setdefault(a, set()).add(b)
                        adjacency.setdefault(b, set()).add(a)

            def bypassed(u, v):
                """Shortest ``u..v`` chain of transparent stops, within the gap budget.

                Breadth-first, so the first hit is the shortest; ``None`` when the
                two are joined by nothing but the direct hop, or only via a stop
                some other road also touches (which would make it a guess).
                """
                budget = gap_budget(u, v)
                frontier = deque([(u, [u])])
                while frontier:
                    node, path = frontier.popleft()
                    if len(path) - 1 > budget:
                        return None
                    for nxt in sorted(adjacency.get(node, ())):
                        if nxt == v:
                            if len(path) > 1:
                                return path + [v]
                            continue  # the direct hop itself, not an elaboration
                        if nxt == u or nxt in path or len(adjacency[nxt]) != 2:
                            continue
                        frontier.append((nxt, path + [nxt]))
                return None

            learned = False
            for pair, groups in takers.items():
                if len(groups) >= CONFIRMED_MIN_ROUTES:
                    continue
                u, v = sorted(pair)
                if (u, v) in detail or (v, u) in detail:
                    continue
                chain = bypassed(u, v)
                if chain:
                    detail[(u, v)] = chain
                    detail[(v, u)] = chain[::-1]
                    learned = True
            return learned

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
        def run_fill(pending):
            filled = []
            for route in pending:
                while True:
                    nxt = fill_pass(route)
                    if nxt == route:
                        break
                    route = nxt
                filled.append(route)
            return filled

        # Fill, then read the network back to learn the cross-route elaborations
        # only a filled adjacency reveals, and fill again with what was learned.
        # ``detail`` only ever grows and the pairs are finite, so this settles.
        filled = run_fill(routes)
        while learn_bypasses(filled):
            filled = run_fill(filled)
        return filled

    # --- public API --------------------------------------------------------

    @staticmethod
    def _normalised(routes):
        """Stored routes in the uniform ``{"places"[, "marks"][, "branches"]}`` shape."""
        return [upgrade_node(route) for route in routes]

    def _normalised_routes(self):
        """The stored route tree exactly as persisted, upgraded to the uniform
        shape (see :func:`upgrade_node`) but with places left as *whatever
        token is actually stored* — internal ids once any route has been saved
        under the id-registry scheme, plain strings for data that predates it
        (a not-yet-migrated store, or mid-migration). Internal-only: every
        caller either doesn't care about the token type (graph-building, which
        is token-agnostic) or is the migration itself (which needs the raw,
        untranslated content precisely because the registry may still be
        empty). Everything else should call :meth:`load_routes`.
        """
        return self._normalised(self._ensure_routes())

    def load_routes(self):
        """The authored routes, always in the ``{"places", "marks"}`` shape,
        with every place resolved to its full display string — this is the
        wire shape ``GET``/``PUT /api/routes/`` has always used, and what
        :meth:`save_routes` returns; id resolution is purely an internal
        storage detail (see :meth:`_normalised_routes`).
        """
        registry = self.load_place_registry()
        return [self._tree_to_display(route, registry) for route in self._normalised_routes()]

    def load_expanded_routes(self):
        """The authored routes flattened to one ``{"places", "marks"}`` per subroute.

        This is the flat view that lines up with the derived graph's route indices
        (each tree node is one graph route). Consumers that index a graph run back
        to a route — marks in :meth:`load_graph`, endpoint labels in the path view —
        read *this*, not :meth:`load_routes` (which resolves to display strings and
        loses the tree). Places here are internal ids, matching the id-keyed graph.
        """
        return expand_routes(self._normalised_routes())

    def load_graph(self):
        """Load the pre-built graph (edges + route membership) from disk.

        The edges come from the derived file; the marks come from the expanded routes
        (``routes.json`` stays their single source of truth), aligned to the graph's
        route indices — one per tree node. Both therefore describe the same routes:
        :meth:`_ensure_routes` has rebuilt the edges first if they didn't.

        The routes read for the freshness check are expanded here directly instead
        of calling :meth:`load_expanded_routes`, which would fetch ``routes.json`` a
        second time for a value already in hand.
        """
        routes = self._normalised(self._ensure_routes())
        return Graph.from_edge_routes(
            self._read_json(self.edge_routes_key),
            [route["marks"] for route in expand_routes(routes)],
        )

    def save_routes(self, routes):
        """Validate, persist routes (internally as ids), and regenerate the
        derived graph.

        ``routes`` (the incoming payload) and the return value are both the
        display-string shape the API contract has always used — the id
        conversion is entirely an internal storage detail. A place string not
        already in the registry mints a fresh id here (see
        :meth:`_resolve_or_create`); an existing one (by its parsed ``(group,
        base)`` pair) is reused.
        """
        cleaned = self.validate_routes(routes)

        registry = self.load_place_registry()
        by_group_base = self._by_group_base(registry)
        next_id_ref = [self._next_id(registry)]
        id_tree = [
            self._tree_to_ids(route, registry, by_group_base, next_id_ref)
            for route in cleaned
        ]

        self._atomic_write_json(self.routes_key, id_tree)
        self._atomic_write_json(self.places_key, {str(k): v for k, v in registry.items()})
        self._rebuild_graph(id_tree)

        return [self._tree_to_display(route, registry) for route in id_tree]

    def load_compromised(self):
        """The compromised-destination groups, as display strings (the API shape)."""
        self._ensure_compromised()
        id_groups = self._read_json(self.compromised_key)
        registry = self.load_place_registry()
        return [self.translate_stops(group, registry) for group in id_groups]

    def compromised_places(self):
        """Flattened set of every destination *id* marked unavailable, across all
        groups. Ids, not display strings — this is what feeds
        ``graph.without_places(...)``, and the graph's nodes are ids."""
        self._ensure_compromised()
        id_groups = self._read_json(self.compromised_key)
        return {place_id for group in id_groups for place_id in group}

    def save_compromised(self, groups):
        """Validate against the closed list of known destinations and persist.

        ``groups``/the return value are display strings (API shape); only an
        *already-known* place may be marked compromised — this never mints a
        new place id.
        """
        registry = self.load_place_registry()
        by_group_base = self._by_group_base(registry)
        known = {self.display_name(entry) for entry in registry.values()}
        cleaned = self.validate_compromised(groups, known)
        id_groups = [
            [self._resolve_existing(place, by_group_base) for place in group]
            for group in cleaned
        ]
        self._atomic_write_json(self.compromised_key, id_groups)
        return cleaned

    def _resolve_existing(self, text, by_group_base):
        place_id = self.place_id(text, by_group_base=by_group_base)
        if place_id is None:
            raise ValidationError(f'המקום "{text}" אינו קיים.')
        return place_id

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
