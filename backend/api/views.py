"""DRF function views for the traffic-arteries API.

Function views with @api_view + rest_framework.response.Response, per spec.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import IsEditorOrAdmin

from .db import ValidationError, database
from .graph import RouteFinder


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


def _split_by_compromise(results, compromised):
    """Split ranked results (best-first) into the routes that don't touch any
    compromised destination, and which compromised destinations the natural
    top-3 (before filtering) would have used. Both are unchanged/empty when
    nothing is compromised."""
    if not compromised:
        return results, []
    detour = sorted({stop for r in results[:3] for stop in r.stops} & compromised)
    clean = [r for r in results if not (compromised & set(r.stops))]
    return clean, detour


@api_view(["POST"])
def path(request):
    """Top 3 routes between two points, optionally via required stops.

    "Best" is the route that rides one *good* authored route as far as possible:
    the best priority tier first, then the highest concentration score.

    Body: ``{"start": <place>, "end": <place>, "via": [<place>, ...]}``.
    ``via`` is optional — required intermediate stops the route must pass
    through (visited in an optimised order).
    Response: ``{"paths": [[...], ...], "meta": [{"routeCount", "match",
    "priority", "routes"}, ...], "compromisedDetour": [...]}`` — ``paths`` are the
    stop chains; ``meta[i]`` gives the match percentage (concentration), the
    route's ``priority`` *tier* (the worst priority among the sub-routes it rides,
    i.e. the max over ``routes[].priority`` below — why a longer route may outrank a
    shorter one, so the UI must surface it), and which authored routes route ``i``
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
    routes = database.load_routes()  # originals, for human-readable labels

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

    def run_meta(run, total_hops, start_index):
        """Metadata for one run, plus its inclusive [start_index, end_index]
        stop range within the result's `stops` list. Runs are contiguous and
        non-overlapping in travel order (adjacent runs share their boundary
        stop), so the caller threads a running offset of `hops` through
        successive runs — no need to touch concentration.py."""
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

    results = RouteFinder(graph).find_routes(start, end, k=None, via=via)
    clean, detour = _split_by_compromise(results, compromised)
    top = clean[:3]
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
    return Response({"paths": paths, "meta": meta, "compromisedDetour": detour if paths else []})
