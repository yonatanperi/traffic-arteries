"""DRF function views for the traffic-arteries API.

Function views with @api_view + rest_framework.response.Response, per spec.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import IsEditorOrAdmin

from .db import ValidationError, database
from .graph import RouteFinder

# Product decision: a search shows the three best routes. Named rather than a
# bare ``[:3]`` literal so the count lives in one place and never gets encoded as
# a magic ``k`` — routing is asked for the full ranked pool (the ``k=None``
# sentinel) and this is the only thing that truncates it.
TOP_N = 3


@api_view(["GET"])
def health(request):
    """Liveness probe for the frontend's startup gate.

    Deliberately touches neither the R2 store nor the database — it answers as
    soon as the process is up. The frontend polls this before rendering, so it
    can wait out Render's free-tier cold start (a spun-down service takes tens
    of seconds to wake) behind a single loader, instead of every page racing an
    unfinished request and, e.g., reporting valid places as unknown.
    """
    return Response({"status": "ok"})


@api_view(["GET"])
def places(request):
    """Known, currently-routable place names, sorted — feeds the path-finding
    autocomplete inputs. Compromised (temporarily unavailable) destinations are
    excluded, since they can't be planned through."""
    graph = database.load_routable_graph()
    return Response(graph.places())


@api_view(["GET", "PUT"])
@permission_classes([IsEditorOrAdmin])
def routes(request):
    """GET the full routes list, or PUT a replacement list.

    A successful PUT re-validates the payload and regenerates the derived graph.
    """
    if request.method == "GET":
        return Response(database.load_routes())

    try:
        saved = database.save_routes(request.data)
    except ValidationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(saved)


@api_view(["GET", "PUT"])
@permission_classes([IsEditorOrAdmin])
def compromised(request):
    """GET the compromised-destination groups, or PUT a replacement list.

    Each group is a list of destination names temporarily marked unavailable
    together. A successful PUT re-validates every destination against the
    closed list of known places.
    """
    if request.method == "GET":
        return Response(database.load_compromised())

    try:
        saved = database.save_compromised(request.data)
    except ValidationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(saved)


@api_view(["GET"])
@permission_classes([IsEditorOrAdmin])
def network(request):
    """Graph as {nodes, links} for react-force-graph-2d (read-only view).

    The full network, including compromised destinations — each node is
    annotated ``compromised`` so the frontend can flag them, rather than
    hiding them the way routing/place-picking does.
    """
    graph = database.load_graph()
    payload = graph.to_network()
    compromised_places = database.compromised_places()
    for node in payload["nodes"]:
        node["compromised"] = node["id"] in compromised_places
    return Response(payload)


@api_view(["POST"])
def path(request):
    """Top 3 routes between two points, optionally via required stops.

    "Best" is the route that rides one *good* authored route as far as possible:
    the best priority tier first, then the highest concentration score. A route's
    tier is the worst *priority mark* its ridden sub-routes complete — a mark rates
    a stretch of an authored route, and only a ride covering that stretch whole pays
    for it.

    Body: ``{"start": <place>, "end": <place>, "via": [<place>, ...]}``.
    ``via`` is optional — required intermediate stops the route must pass
    through (visited in an optimised order).
    Response: ``{"paths": [[...], ...], "meta": [{"routeCount", "match",
    "priority", "routes"}, ...], "compromisedDetour": [...]}`` — ``paths`` are the
    stop chains; ``meta[i]`` gives the match percentage (the *ranking* score
    ``Route.q`` — priority-free concentration tempered by the crossroad-distance
    term, so the number shown always agrees with the order the results are listed in
    and does not move when an artery is re-prioritised), the
    route's ``priority`` *tier* (the worst priority among the sub-routes it rides,
    each being the worst mark that sub-route completes, i.e. the max over
    ``routes[].priority`` below — why a longer route may outrank a shorter one, so
    the UI must surface it), and which authored routes route ``i``
    merges (labelled by their
    endpoints, each with its own ``priority`` and a ``startIndex``/``endIndex``
    pair — inclusive, 0-based indices into ``paths[i]`` — for the stop range it
    covers). ``compromisedDetour`` lists compromised destinations that the natural
    (unfiltered) top-3 routes would have used, had they not been temporarily
    unavailable — empty unless ``paths`` is non-empty and a detour actually
    happened. Empty ``paths`` means no route.
    """
    start = (request.data.get("start") or "").strip()
    end = (request.data.get("end") or "").strip()

    via_raw = request.data.get("via")
    via = [str(v).strip() for v in via_raw if str(v).strip()] if isinstance(via_raw, list) else []

    if not start or not end:
        return Response(
            {"detail": "יש לבחור נקודת מוצא ונקודת יעד."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    compromised = database.compromised_places()
    graph = database.load_graph()
    # Expanded subroutes (one per tree node) — this is the list the graph's route
    # indices line up with, so `run.route_id` labels resolve correctly for branched
    # routes too.
    routes = database.load_expanded_routes()

    def run_endpoints(run):
        """The authored route's endpoints, oriented to the travel direction.

        A run rides authored route ``run.route_id``; its ``start``/``end`` are the
        nodes as travelled. If travel goes *backwards* along the authored route we
        flip its endpoints, so e.g. riding "אילת - מ. אלפורן" from מ. אלפורן shows
        as ``מ. אלפורן → אילת``. Falls back to the run's own endpoints when the
        route is unknown or its boundary nodes aren't on the original route.
        """
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

    def run_meta(run, total_length, start_index):
        """Metadata for one run, plus its inclusive [start_index, end_index]
        stop range within the result's `stops` list. Runs are contiguous and
        non-overlapping in travel order (adjacent runs share their boundary
        stop), so the caller threads a running offset of `hops` through
        successive runs — no need to touch concentration.py.

        `share` is taken from `run.length`, *not* `run.hops`: length is the term
        the concentration score is actually built from, so the shares shown to the
        user square back to it: `Σ share²` is `Route.hhi`, of which the `match` %
        reported alongside is that same value scaled by the ranking length factor (so
        match sits at or just below what the shares square to). The rare exception is
        a chain where the priority-free solve behind `hhi` credits its runs
        differently from the weighted solve these shares come from. Under a length
        mode where hops and
        length diverge (`LengthMode.CROSSROADS_ONLY`) using hops here would print
        shares that contradict the score outright. The index range still counts
        hops — that's a position in `stops`, not a weight."""
        origin, dest = run_endpoints(run)
        return {
            "id": run.route_id if isinstance(run.route_id, int) else -1,
            "label": f"{origin} - {dest}",
            "share": round(run.length / total_length * 100) if total_length else 100,
            "priority": run.priority,
            "startIndex": start_index,
            "endIndex": start_index + run.hops,
        }

    def routes_meta(runs):
        total_length = sum(run.length for run in runs)
        metas = []
        offset = 0
        for run in runs:
            metas.append(run_meta(run, total_length, offset))
            offset += run.hops
        return metas

    # Rank the candidate pool once (the single sort), then select over it twice:
    # the natural best (to report what the compromise costs) and the best that
    # avoids compromised destinations (what we actually show). No re-sort, and the
    # compromised-free results are *selected* — arena and diversity budget computed
    # among showable routes — not a natural list with holes filtered out of it.
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
            "match": round(r.q * 100),
            "priority": r.priority,
            "routes": routes_meta(r.runs),
        }
        for r in top
    ]
    return Response({"paths": paths, "meta": meta, "compromisedDetour": detour if paths else []})
