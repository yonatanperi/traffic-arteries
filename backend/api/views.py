"""DRF function views for the traffic-arteries API.

Function views with @api_view + rest_framework.response.Response, per spec.
"""

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

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

    "Best" is the route that rides one authored route as far as possible — the
    highest concentration (Herfindahl) score.

    Body: ``{"start": <place>, "end": <place>, "via": [<place>, ...]}``.
    ``via`` is optional — required intermediate stops the route must pass
    through (visited in an optimised order).
    Response: ``{"paths": [[...], ...], "meta": [{"routeCount", "match",
    "routes"}, ...]}`` — ``paths`` are the stop chains; ``meta[i]`` gives the
    match percentage (concentration) and which authored routes route ``i`` merges
    (labelled by their endpoints). Empty lists mean no route.
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

    graph = database.load_routable_graph()
    routes = database.load_routes()  # originals, for human-readable labels

    def run_endpoints(run):
        """The authored route's endpoints, oriented to the travel direction.

        A run rides authored route ``run.route_id``; its ``start``/``end`` are the
        nodes as travelled. If travel goes *backwards* along the authored route we
        flip its endpoints, so e.g. riding "אילת - מ. אלפורן" from מ. אלפורן shows
        as ``מ. אלפורן → אילת``. Falls back to the run's own endpoints when the
        route is unknown or its boundary nodes aren't on the original route.
        """
        route = routes[run.route_id] if isinstance(run.route_id, int) and 0 <= run.route_id < len(routes) else None
        if not route:
            return run.start, run.end
        order = {name: i for i, name in enumerate(route)}
        start_i, end_i = order.get(run.start), order.get(run.end)
        if start_i is not None and end_i is not None and start_i > end_i:
            return route[-1], route[0]
        return route[0], route[-1]

    def run_meta(run, total_hops):
        origin, dest = run_endpoints(run)
        return {
            "id": run.route_id if isinstance(run.route_id, int) else -1,
            "label": f"{origin} → {dest}",
            "share": round(run.hops / total_hops * 100) if total_hops else 100,
        }

    results = RouteFinder(graph).find_routes(start, end, k=3, via=via)
    paths = [r.stops for r in results]
    meta = [
        {
            "routeCount": r.route_count,
            "match": round(r.hhi * 100),
            "routes": [run_meta(run, r.total_hops) for run in r.runs],
        }
        for r in results
    ]
    return Response({"paths": paths, "meta": meta})
