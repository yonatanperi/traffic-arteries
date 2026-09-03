"""The ``/api/path/`` result metadata — one builder, two callers.

``api.views.path`` (what the home page's search form hits) and the ``find_route``
management command must report the *same* thing about a route, or the console
report stops being a way to debug what the UI shows. They had each grown their own
copy of this and already drifted — one divided a sub-route's share by ``run.length``
and the other by ``run.hops``, which under ``LengthMode.CROSSROADS_ONLY`` are
different numbers. This module is the single copy.

Everything here speaks *display names*: it takes the id-keyed place registry and the
expanded routes (the list the graph's route indices line up with, so a branched
route's nodes label correctly) and returns the JSON the API contract documents.
"""

from .db import database


def _run_endpoints(run, routes):
    """The authored route's endpoints (ids), oriented to the travel direction.

    A run rides authored route ``run.route_id``; its ``start``/``end`` are the nodes
    as travelled. If travel goes *backwards* along the authored route we flip its
    endpoints, so e.g. riding "אילת - מ. אלפורן" from מ. אלפורן shows as
    ``מ. אלפורן → אילת``. Falls back to the run's own endpoints when the route is
    unknown or its boundary nodes aren't on the original route.
    """
    places = (
        routes[run.route_id]["places"]
        if isinstance(run.route_id, int) and 0 <= run.route_id < len(routes)
        else None
    )
    if not places:
        return run.start, run.end
    order = {place_id: i for i, place_id in enumerate(places)}
    start_i, end_i = order.get(run.start), order.get(run.end)
    if start_i is not None and end_i is not None and start_i > end_i:
        return places[-1], places[0]
    return places[0], places[-1]


def _run_meta(run, registry, routes, leg_length, start_index):
    """One sub-route chip, plus its inclusive ``[startIndex, endIndex]`` stop range.

    Runs are contiguous and non-overlapping in travel order (adjacent runs share
    their boundary stop), so the caller threads a running offset of ``hops`` through
    successive runs — no need to touch ``concentration.py``. Indices are into the
    *whole* result chain, not the leg, so a chip can highlight its stops wherever
    they fall.

    ``share`` is taken from ``run.length``, **not** ``run.hops``: length is the term
    the concentration score is actually built from, so the shares shown to the user
    square back to it — within a leg, ``Σ share²`` is that leg's ``hhi``, and the
    route's is those legs' length-weighted mean. That is why the denominator is the
    *leg's* length rather than the whole route's: the score pools credit within a leg
    and never across a required stop, so shares that spanned the whole trip would
    square back to a number the ranking never computed. Under a length mode where
    hops and length diverge (``LengthMode.CROSSROADS_ONLY``) using hops here would
    print shares that contradict the score outright. The index range still counts
    hops — that's a position in ``stops``, not a weight.
    """
    origin, dest = _run_endpoints(run, routes)
    return {
        "id": run.route_id if isinstance(run.route_id, int) else -1,
        "label": (
            f"{database.display_name(registry[origin])}"
            f" - {database.display_name(registry[dest])}"
        ),
        "share": round(run.length / leg_length * 100) if leg_length else 100,
        "priority": run.priority,
        "startIndex": start_index,
        "endIndex": start_index + run.hops,
    }


def _leg_meta(route, leg, registry, routes, length_factor):
    """One leg — the stretch between two consecutive required stops.

    ``match`` is the leg's own concentration carried onto the *route's* percentage
    scale (its ``hhi`` times the route's length factor). Doing it that way is what
    makes the numbers add up on screen: the route's match is exactly the
    length-weighted mean of its legs', because that is how ``hhi`` itself is combined.
    Scoring each leg against its own ``C_min`` instead would print percentages on as
    many different scales as there are legs.
    """
    stops = route.stops
    metas, offset = [], leg.start_index
    leg_length = sum(run.length for run in leg.runs)
    for run in leg.runs:
        metas.append(_run_meta(run, registry, routes, leg_length, offset))
        offset += run.hops
    return {
        "start": database.display_name(registry[stops[leg.start_index]]),
        "end": database.display_name(registry[stops[leg.end_index]]),
        "startIndex": leg.start_index,
        "endIndex": leg.end_index,
        "match": round(leg.hhi * length_factor * 100),
        "priority": leg.priority,
        "routes": metas,
    }


def route_meta(route, registry, routes):
    """The ``meta[i]`` entry for one :class:`~api.graph.Route`.

    ``legs`` is always present and always holds at least one entry — a query with no
    ``via`` is a one-leg trip — so a caller never has to branch on whether the trip
    was split. ``routes`` stays the flat list it has always been: the legs' chips
    concatenated in travel order.
    """
    # The ranking's length factor, recovered from the two numbers the route already
    # carries (q = hhi * factor), so a leg's percentage lands on the route's scale.
    length_factor = route.q / route.hhi if route.hhi else 1.0
    legs = [_leg_meta(route, leg, registry, routes, length_factor) for leg in route.legs]
    return {
        "routeCount": route.route_count,
        "match": round(route.q * 100),
        "priority": route.priority,
        "routes": [chip for leg in legs for chip in leg["routes"]],
        "legs": legs,
    }
